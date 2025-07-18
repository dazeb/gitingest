"""Module containing functions for cloning a Git repository to a local path."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gitingest.config import DEFAULT_TIMEOUT
from gitingest.utils.git_utils import (
    check_repo_exists,
    create_git_auth_header,
    create_git_command,
    ensure_git_installed,
    is_github_host,
    run_command,
)
from gitingest.utils.os_utils import ensure_directory
from gitingest.utils.timeout_wrapper import async_timeout

if TYPE_CHECKING:
    from gitingest.schemas import CloneConfig


@async_timeout(DEFAULT_TIMEOUT)
async def clone_repo(config: CloneConfig, *, token: str | None = None) -> None:
    """Clone a repository to a local path based on the provided configuration.

    This function handles the process of cloning a Git repository to the local file system.
    It can clone a specific branch, tag, or commit if provided, and it raises exceptions if
    any errors occur during the cloning process.

    Parameters
    ----------
    config : CloneConfig
        The configuration for cloning the repository.
    token : str | None
        GitHub personal access token (PAT) for accessing private repositories.

    Raises
    ------
    ValueError
        If the repository is not found, if the provided URL is invalid, or if the token format is invalid.

    """
    # Extract and validate query parameters
    url: str = config.url
    local_path: str = config.local_path
    commit: str | None = config.commit
    branch: str | None = config.branch
    tag: str | None = config.tag
    partial_clone: bool = config.subpath != "/"

    # Create parent directory if it doesn't exist
    await ensure_directory(Path(local_path).parent)

    # Check if the repository exists
    if not await check_repo_exists(url, token=token):
        msg = "Repository not found. Make sure it is public or that you have provided a valid token."
        raise ValueError(msg)

    clone_cmd = ["git"]
    if token and is_github_host(url):
        clone_cmd += ["-c", create_git_auth_header(token, url=url)]

    clone_cmd += ["clone", "--single-branch"]

    if config.include_submodules:
        clone_cmd += ["--recurse-submodules"]

    if partial_clone:
        clone_cmd += ["--filter=blob:none", "--sparse"]

    # Shallow clone unless a specific commit is requested
    if not commit:
        clone_cmd += ["--depth=1"]

        # Prefer tag over branch when both are provided
        if tag:
            clone_cmd += ["--branch", tag]
        elif branch and branch.lower() not in ("main", "master"):
            clone_cmd += ["--branch", branch]

    clone_cmd += [url, local_path]

    # Clone the repository
    await ensure_git_installed()
    await run_command(*clone_cmd)

    # Checkout the subpath if it is a partial clone
    if partial_clone:
        await _checkout_partial_clone(config, token)

    # Checkout the commit if it is provided
    if commit:
        checkout_cmd = create_git_command(["git"], local_path, url, token)
        await run_command(*checkout_cmd, "checkout", commit)


async def _checkout_partial_clone(config: CloneConfig, token: str | None) -> None:
    """Configure sparse-checkout for a partially cloned repository.

    Parameters
    ----------
    config : CloneConfig
        The configuration for cloning the repository, including subpath and blob flag.
    token : str | None
        GitHub personal access token (PAT) for accessing private repositories.

    """
    subpath = config.subpath.lstrip("/")
    if config.blob:
        # Remove the file name from the subpath when ingesting from a file url (e.g. blob/branch/path/file.txt)
        subpath = str(Path(subpath).parent.as_posix())
    checkout_cmd = create_git_command(["git"], config.local_path, config.url, token)
    await run_command(*checkout_cmd, "sparse-checkout", "set", subpath)

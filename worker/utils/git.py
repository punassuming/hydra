import subprocess
import shutil
import os
from urllib.parse import urlparse, urlunparse


def _git_bin() -> str:
    """Return the git binary path, honouring ``HYDRA_GIT_PATH``."""
    return os.environ.get("HYDRA_GIT_PATH", "").strip() or "git"


def _inject_token_into_url(url: str, token: str) -> str:
    """Inject a personal access token into an HTTPS git URL for authentication."""
    if not token:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        # SSH or other protocol — cannot inject token into URL
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    # Use token as username with 'x-oauth-token' convention (works for GitHub, GitLab, etc.)
    netloc = f"x-oauth-token:{token}@{netloc}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _strip_credentials_from_remote(dest: str, clean_url: str) -> None:
    """Rewrite git remote URL to remove embedded credentials from .git/config."""
    git = _git_bin()
    try:
        subprocess.run([git, "remote", "set-url", "origin", clean_url],
                       cwd=dest, check=False, capture_output=True)
    except Exception:
        pass


def fetch_git_source(url: str, ref: str, dest: str, token: str = "", sparse_path: str = "") -> None:
    """
    Clones a git repository to the destination directory and checks out the reference.

    Uses a shallow clone (--depth 1) when ref looks like a branch/tag name for
    efficiency.  If token is provided it is injected into the HTTPS URL for
    private-repository authentication (personal access token / OAuth token).

    When *sparse_path* is non-empty, a sparse-checkout is used so that only
    the given sub-tree is materialized on disk.  This dramatically reduces
    bandwidth and disk usage for large mono-repos when only a small sub-
    directory is needed.
    """
    clone_url = _inject_token_into_url(url, token) if token else url

    if sparse_path:
        _sparse_clone(clone_url, ref, dest, sparse_path, clean_url=url)
    else:
        _full_clone(clone_url, ref, dest, clean_url=url)


def _full_clone(clone_url: str, ref: str, dest: str, clean_url: str = "") -> None:
    """Standard shallow-then-full clone strategy."""
    git = _git_bin()
    cmd_shallow = [git, "clone", "-q", "--depth", "1", clone_url, dest]
    result = subprocess.run(cmd_shallow, capture_output=True)
    if result.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
        cmd_clone = [git, "clone", "-q", clone_url, dest]
        subprocess.run(cmd_clone, check=True)

    if ref:
        subprocess.run([git, "checkout", ref], cwd=dest, check=True)

    if clean_url and clean_url != clone_url:
        _strip_credentials_from_remote(dest, clean_url)


def _sparse_clone(clone_url: str, ref: str, dest: str, sparse_path: str, clean_url: str = "") -> None:
    """Clone using sparse-checkout so only *sparse_path* is materialized."""
    git = _git_bin()
    os.makedirs(dest, exist_ok=True)
    subprocess.run([git, "init", "-q", dest], check=True)
    subprocess.run([git, "remote", "add", "origin", clone_url], cwd=dest, check=True)
    # Enable cone-mode sparse-checkout (fast, directory-level filtering)
    subprocess.run(
        [git, "sparse-checkout", "set", "--cone", sparse_path],
        cwd=dest, check=True,
    )
    # Attempt shallow fetch first; fall back to full fetch
    fetch_cmd = [git, "fetch", "-q", "--depth", "1", "origin", ref or "HEAD"]
    result = subprocess.run(fetch_cmd, cwd=dest, capture_output=True)
    if result.returncode != 0:
        fetch_cmd_full = [git, "fetch", "-q", "origin", ref or "HEAD"]
        subprocess.run(fetch_cmd_full, cwd=dest, check=True)
    subprocess.run([git, "checkout", ref or "FETCH_HEAD"], cwd=dest, check=True)

    if clean_url and clean_url != clone_url:
        _strip_credentials_from_remote(dest, clean_url)

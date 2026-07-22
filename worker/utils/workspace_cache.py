"""Workspace caching for Hydra workers.

Provides a persistent per-worker cache directory for source workspaces so that
successive runs of the same job avoid repeated git clones / rsync / copy
operations.  Cache entries are identified by a hash of the source configuration
and are evicted using LRU + TTL + size-limit policies.
"""

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from typing import Callable, Optional, Tuple


def _dir_size_mb(path: str) -> float:
    """Return total size of *path* in megabytes."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total / (1024 * 1024)


class WorkspaceCache:
    """Thread-safe workspace cache backed by the local filesystem."""

    def __init__(
        self,
        cache_root: Optional[str] = None,
        max_mb: int = 1024,
        ttl_seconds: int = 3600,
        persist: bool = True,
    ):
        if cache_root:
            self.root = cache_root
        else:
            self.root = os.path.join(tempfile.gettempdir(), "hydra-workspace-cache")
        self.max_mb = max_mb
        self.ttl = ttl_seconds
        self.persist = persist
        self._lock = threading.Lock()
        os.makedirs(self.root, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        domain: str,
        job_id: str,
        source_config: dict,
        fetch_fn: Callable[[str, dict], None],
    ) -> Tuple[str, Callable[[], None]]:
        """Return *(workspace_path, release_fn)*.

        *fetch_fn(dest_dir, source_config)* is called when the cache entry
        does not yet exist and needs to be populated.

        If the source has ``cache == "never"`` the caller is responsible for
        calling the returned *release_fn* which deletes the temp directory.
        """
        cache_mode = source_config.get("cache", "auto")

        if cache_mode == "never":
            # Fall back to ephemeral temp directory (current behaviour).
            tmp = tempfile.mkdtemp(prefix=f"hydra-source-{job_id}-")
            fetch_fn(tmp, source_config)
            return tmp, lambda: shutil.rmtree(tmp, ignore_errors=True)

        cache_key = self._cache_key(source_config)
        cache_path = os.path.join(self.root, domain, job_id, cache_key)

        with self._lock:
            if os.path.isdir(cache_path):
                self._touch(cache_path)
                if cache_mode == "always":
                    pass  # never re-fetch
                elif source_config.get("protocol", "git") == "git":
                    self._git_update(cache_path, source_config)
            elif cache_mode == "always":
                raise FileNotFoundError(
                    f"cache mode is 'always' but no cached workspace exists at {cache_path}"
                )
            else:
                os.makedirs(cache_path, exist_ok=True)
                fetch_fn(cache_path, source_config)
                self._touch(cache_path)
            self._evict_if_needed()

        return cache_path, lambda: None  # no cleanup for cached entries

    def cleanup_all(self) -> None:
        """Remove the entire cache tree (called on worker shutdown if persist is False)."""
        if not self.persist:
            shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(source_config: dict) -> str:
        """Deterministic hash of the source configuration."""
        parts = json.dumps(
            {
                "url": source_config.get("url", ""),
                "ref": source_config.get("ref", "main"),
                "path": source_config.get("path", ""),
                "protocol": source_config.get("protocol", "git"),
            },
            sort_keys=True,
        )
        return hashlib.sha256(parts.encode()).hexdigest()[:16]

    @staticmethod
    def _touch(path: str) -> None:
        """Update the mtime of the sentinel file inside *path*."""
        sentinel = os.path.join(path, ".hydra_cache_ts")
        with open(sentinel, "w") as f:
            f.write(str(time.time()))

    @staticmethod
    def _last_used(path: str) -> float:
        sentinel = os.path.join(path, ".hydra_cache_ts")
        try:
            with open(sentinel) as f:
                return float(f.read().strip())
        except Exception:
            return 0.0

    def _git_update(self, cache_path: str, source_config: dict) -> None:
        """Fast-update a cached git workspace."""
        import subprocess
        git = os.environ.get("HYDRA_GIT_PATH", "").strip() or "git"
        ref = source_config.get("ref", "main")
        try:
            subprocess.run(
                [git, "fetch", "-q", "origin"],
                cwd=cache_path,
                capture_output=True,
                timeout=120,
            )
            subprocess.run(
                [git, "checkout", ref],
                cwd=cache_path,
                capture_output=True,
                timeout=60,
            )
            subprocess.run(
                [git, "pull", "-q", "--ff-only"],
                cwd=cache_path,
                capture_output=True,
                timeout=120,
            )
        except Exception:
            pass  # best effort; stale cache is better than no cache

    def _evict_if_needed(self) -> None:
        """Evict oldest entries until total size is under *max_mb*."""
        total = _dir_size_mb(self.root)
        if total <= self.max_mb:
            return
        # Collect all leaf cache dirs (those containing .hydra_cache_ts).
        entries: list[Tuple[float, str]] = []
        for dirpath, _dirs, files in os.walk(self.root):
            if ".hydra_cache_ts" in files:
                entries.append((self._last_used(dirpath), dirpath))
        entries.sort()  # oldest first
        for _ts, path in entries:
            if _dir_size_mb(self.root) <= self.max_mb:
                break
            shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Module-level singleton (lazily initialised by get_workspace_cache())
# ---------------------------------------------------------------------------

_cache_instance: Optional[WorkspaceCache] = None
_cache_init_lock = threading.Lock()


def get_workspace_cache() -> WorkspaceCache:
    """Return (or create) the global WorkspaceCache singleton."""
    global _cache_instance
    if _cache_instance is None:
        with _cache_init_lock:
            if _cache_instance is None:
                _cache_instance = WorkspaceCache(
                    cache_root=os.environ.get("WORKER_WORKSPACE_CACHE_DIR") or None,
                    max_mb=int(os.environ.get("WORKER_WORKSPACE_CACHE_MAX_MB", "1024")),
                    ttl_seconds=int(os.environ.get("WORKER_WORKSPACE_CACHE_TTL", "3600")),
                    persist=os.environ.get("WORKER_WORKSPACE_CACHE_PERSIST", "true").lower()
                    in ("true", "1", "yes"),
                )
    return _cache_instance

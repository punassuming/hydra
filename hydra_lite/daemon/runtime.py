"""Daemon runtime: owns the store, trigger loop and worker pool."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path

from ..config import Config
from ..lifecycle import Lifecycle
from ..logs import LogStore
from ..loops import maintenance_loop
from ..scheduling import trigger_loop
from ..store import Store
from ..worker.inproc import WorkerPool

log = logging.getLogger("hydra_lite.daemon")


def ensure_token(path: Path) -> str:
    """Return the local API token, creating it (owner-only) on first use."""
    path = Path(path)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token


class Daemon:
    def __init__(self, config: Config):
        self.config = config
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.token = ensure_token(config.token_file)
        self.store = Store(config.db_path)
        self.logs = LogStore(config.log_dir)
        self.stop = threading.Event()
        self.lifecycle = Lifecycle(self.store, self.logs)
        self.pool = WorkerPool(self.store, self.logs, self.lifecycle, max_concurrency=config.max_concurrency)
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        lost = self.lifecycle.recover_orphans()
        if lost:
            log.warning("marked %d run(s) lost after unclean shutdown", lost)
        t = threading.Thread(target=trigger_loop, args=(self.store, self.stop, self.pool.wake), name="hydra-trigger", daemon=True)
        t.start()
        self._threads.append(t)
        m = threading.Thread(
            target=maintenance_loop,
            args=(
                self.store,
                self.lifecycle,
                self.pool,
                self.logs,
                self.stop,
                self.config.retention_days,
                self.config.retention_check_seconds,
            ),
            name="hydra-maintenance",
            daemon=True,
        )
        m.start()
        self._threads.append(m)
        self.pool.start()

    def shutdown(self) -> None:
        self.stop.set()
        self.pool.shutdown()
        for t in self._threads:
            t.join(timeout=5)
        self.store.close()

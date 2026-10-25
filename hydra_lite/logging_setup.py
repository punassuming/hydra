"""Logging for a daemon that may have no console (``pythonw.exe``, systemd, a detached process)."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5


def configure_logging(log_file: Optional[Path] = None, level: int = logging.INFO) -> None:
    """Log to a rotating file when ``log_file`` is given, else to stderr (if there is one)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)
    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    elif sys.stderr is not None:
        handler = logging.StreamHandler(sys.stderr)
    else:  # pythonw without a log file: nowhere to write, but never crash on it
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)


def rotate_if_large(path: Path, limit: int = MAX_BYTES) -> None:
    """Keep one previous generation of a log that has no handler of its own (e.g. a worker's stdout)."""
    try:
        if path.exists() and path.stat().st_size > limit:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass

"""Single-instance lock for the daemon.

Two daemons on one data directory would break the "the daemon is the only SQLite writer" rule, and a service plus
a manual ``daemon start`` makes that easy to do by accident. The lock is a real OS file lock, so it vanishes when
the process dies (no stale PID files, no PID-reuse guesswork); the PID inside is only for the error message.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Windows byte-range locks also block *reads* of the locked range, so lock a byte far beyond the PID text.
_WIN_LOCK_OFFSET = 1 << 20


class AlreadyRunning(RuntimeError):
    def __init__(self, path: Path, pid: Optional[int]):
        who = f"pid {pid}" if pid else "another process"
        super().__init__(f"a Hydra daemon is already running for this data directory ({who}; lock {path})")
        self.path, self.pid = path, pid


class DaemonLock:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._fd: Optional[int] = None

    def acquire(self) -> "DaemonLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            pid = self._read_pid(fd)
            os.close(fd)
            raise AlreadyRunning(self.path, pid) from None
        os.lseek(fd, 0, os.SEEK_SET)  # on Windows the lock call left the pointer at the lock offset
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return self

    @staticmethod
    def _read_pid(fd: int) -> Optional[int]:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            return int(os.read(fd, 32).decode().strip() or 0) or None
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(self._fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None

    def __enter__(self) -> "DaemonLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()

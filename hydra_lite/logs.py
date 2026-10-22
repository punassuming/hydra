"""Per-run log files. stdout and stderr are kept in separate append-only files so a
client can tail either with a byte offset (no database writes per output line)."""

from __future__ import annotations

import threading
from pathlib import Path

MAX_READ_BYTES = 2 * 1024 * 1024


class LogStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._open: dict[str, RunLog] = {}

    def base(self, run_id: str, month: str) -> Path:
        return self.root / month[:4] / month[5:7] / run_id

    def path(self, run_id: str, stream: str) -> Path | None:
        """Locate an existing log file for a run (searches month folders)."""
        if not self.root.is_dir():
            return None
        for candidate in self.root.glob(f"*/*/{run_id}.{stream}"):
            return candidate
        return None

    def open_writer(self, run_id: str, month: str) -> "RunLog":
        base = self.base(run_id, month)
        base.parent.mkdir(parents=True, exist_ok=True)
        return RunLog(base)

    def writer(self, run_id: str, month: str) -> "RunLog":
        """A cached append handle for ``run_id`` (used when chunks arrive over HTTP); see ``close_run``."""
        with self._lock:
            handle = self._open.get(run_id)
            if handle is None:
                handle = self._open[run_id] = self.open_writer(run_id, month)
            return handle

    def close_run(self, run_id: str) -> None:
        with self._lock:
            handle = self._open.pop(run_id, None)
        if handle:
            handle.close()

    def read(self, run_id: str, stream: str, offset: int = 0, limit: int = MAX_READ_BYTES) -> tuple[str, int]:
        """Return (text, next_offset). Offsets are byte offsets into the file."""
        path = self.path(run_id, stream)
        if path is None:
            return "", offset
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(limit)
        return data.decode("utf-8", errors="replace"), offset + len(data)

    def delete(self, run_id: str) -> None:
        for stream in ("out", "err"):
            path = self.path(run_id, stream)
            if path:
                path.unlink(missing_ok=True)


class RunLog:
    def __init__(self, base: Path):
        self.base = base
        self._files = {s: open(f"{base}.{s}", "ab", buffering=0) for s in ("out", "err")}  # noqa: SIM115
        self._lock = threading.Lock()

    def write(self, stream: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._files[stream].write(text.encode("utf-8", errors="replace"))

    def close(self) -> None:
        for handle in self._files.values():
            handle.close()

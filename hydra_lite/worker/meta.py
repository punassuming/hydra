"""Worker registration metadata, in the same shape the full edition's worker writes to its Redis hash."""

from __future__ import annotations

import getpass
import os
import platform
import socket
from datetime import datetime, timezone

from worker.protocol import WORKER_PROTOCOL_VERSION
from worker.runtime import _detect_capabilities, _detect_shells


def build_worker_meta(tags: list[str] | None = None) -> dict:
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except OSError:
        ip = ""
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    return {
        "pid": os.getpid(),
        "os": platform.system().lower(),
        "tags": ",".join(tags or []),
        "allowed_users": os.getenv("ALLOWED_USERS", ""),
        "cpu_count": os.cpu_count() or 1,
        "python_version": platform.python_version(),
        "cwd": os.getcwd(),
        "hostname": hostname,
        "ip": ip,
        "subnet": ".".join(ip.split(".")[:3]) if ip else "",
        "deployment_type": os.getenv("DEPLOYMENT_TYPE", "standalone"),
        "run_user": user,
        "shells": ",".join(_detect_shells()),
        "capabilities": ",".join(_detect_capabilities()),
        "worker_protocol_version": WORKER_PROTOCOL_VERSION,
        "started": datetime.now(timezone.utc).isoformat(),
    }

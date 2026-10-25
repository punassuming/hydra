"""Worker registration metadata, in the same shape the full edition's worker writes to its Redis hash."""

from __future__ import annotations

import getpass
import os
import platform
import socket
from datetime import datetime, timezone

from worker.protocol import WORKER_PROTOCOL_VERSION
from worker.runtime import _detect_capabilities, _detect_shells


def local_ip() -> str:
    """This host's outbound IPv4 address without a DNS lookup.

    ``socket.gethostbyname(socket.gethostname())`` can block for tens of seconds on machines whose hostname does not
    resolve (CI runners, laptops on odd networks), and it ran on every worker start. A UDP ``connect`` sends nothing; it
    only asks the OS which interface would route out.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.254.254.254", 1))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def build_worker_meta(tags: list[str] | None = None) -> dict:
    hostname = socket.gethostname()
    ip = local_ip()
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

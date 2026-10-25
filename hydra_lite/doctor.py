"""``hydra-ctl lite doctor``: read-only checks of the install, the data directory, the daemon and the service."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from scheduler.utils.affinity import normalize_affinity, passes_affinity

from .config import Config
from .store.store import MIN_SQLITE, latest_version

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
LOW_DISK_WARN, LOW_DISK_FAIL = 1_000_000_000, 100_000_000
BIG_DB_WARN, BIG_LOGS_WARN = 500_000_000, 2_000_000_000
SYNCED_NAMES = (
    "onedrive",
    "dropbox",
    "google drive",
    "googledrive",
    "icloud",
    "iclouddrive",
    "nextcloud",
    "owncloud",
    "box sync",
    "sync.com",
    "pcloud",
)
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "afs", "ceph", "glusterfs", "fuse.sshfs", "9p", "davfs", "fuse.s3fs"}


@dataclass
class Check:
    name: str
    status: str
    message: str
    hint: str = ""


def synced_or_network_reason(path: Path, mounts_file: str = "/proc/mounts") -> Optional[str]:
    """Why ``path`` is unsafe for a SQLite WAL database (network share / cloud-synced folder), or None."""
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return "it is on a network (UNC) path"
    lowered = text.lower().replace("\\", "/")
    for name in SYNCED_NAMES:
        if f"/{name}/" in lowered + "/" or lowered.endswith(f"/{name}"):
            return f"it is inside a cloud-synced folder ({name})"
    try:
        best, fstype = "", ""
        resolved = str(path.resolve())
        for line in Path(mounts_file).read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 3:
                mount = parts[1].replace("\\040", " ")
                if (resolved == mount or resolved.startswith(mount.rstrip("/") + "/")) and len(mount) > len(best):
                    best, fstype = mount, parts[2]
        if fstype in NETWORK_FS:
            return f"it is on a {fstype} network file system"
    except OSError:
        pass
    return None


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _local_checks(cfg: Config) -> list[Check]:
    out: list[Check] = []
    out.append(
        Check(
            "python",
            PASS if sys.version_info >= (3, 11) else FAIL,
            f"Python {sys.version.split()[0]}",
            "Hydra needs Python 3.11+",
        )
    )
    ok = sqlite3.sqlite_version_info >= MIN_SQLITE
    out.append(
        Check(
            "sqlite",
            PASS if ok else FAIL,
            f"SQLite {sqlite3.sqlite_version}",
            "" if ok else f"SQLite {'.'.join(map(str, MIN_SQLITE))}+ is required",
        )
    )
    data = cfg.data_dir
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / f".doctor-{os.getpid()}"
        probe.write_text("x")
        probe.unlink()
        out.append(Check("data dir writable", PASS, str(data)))
    except OSError as exc:
        out.append(Check("data dir writable", FAIL, f"{data}: {exc}", "fix permissions or set HYDRA_DATA_DIR"))
        return out
    reason = synced_or_network_reason(data)
    out.append(
        Check(
            "data dir location",
            WARN if reason else PASS,
            f"{data} - {reason}" if reason else "local disk",
            "SQLite WAL is unsafe there: move it with HYDRA_DATA_DIR to a local, unsynced folder" if reason else "",
        )
    )
    free = shutil.disk_usage(data).free
    status = FAIL if free < LOW_DISK_FAIL else WARN if free < LOW_DISK_WARN else PASS
    out.append(
        Check(
            "disk space",
            status,
            f"{free / 1e9:.1f} GB free",
            "free disk space or lower HYDRA_RUN_RETENTION_DAYS" if status != PASS else "",
        )
    )
    tok = cfg.token_file
    if tok and tok.exists() and os.name == "posix" and tok.stat().st_mode & 0o077:
        out.append(Check("token file", WARN, f"{tok} is readable by other users", f"chmod 600 {tok}"))
    else:
        out.append(
            Check(
                "token file",
                PASS if tok and tok.exists() else WARN,
                str(tok) if tok and tok.exists() else "not created yet (the daemon makes it on first start)",
            )
        )
    db = cfg.db_path
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            version = con.execute("PRAGMA user_version").fetchone()[0]
            quick = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            latest = latest_version()
            if quick != "ok":
                out.append(
                    Check("database", FAIL, f"integrity check: {quick}", "restore from a backup (`hydra-ctl lite backup`)")
                )
            elif version > latest:
                out.append(Check("database", FAIL, f"schema v{version} is newer than this Hydra (v{latest})", "upgrade Hydra"))
            else:
                out.append(
                    Check(
                        "database",
                        PASS,
                        f"schema v{version}"
                        + (f" (will upgrade to v{latest})" if version < latest else "")
                        + f", {db.stat().st_size / 1e6:.1f} MB",
                    )
                )
        except sqlite3.Error as exc:
            out.append(Check("database", FAIL, str(exc), "is another program holding it? is the file corrupt?"))
    else:
        out.append(Check("database", PASS, "none yet (created on first start)"))
    logs = _dir_size(cfg.log_dir) if cfg.log_dir.exists() else 0
    big = (db.stat().st_size if db.exists() else 0) > BIG_DB_WARN or logs > BIG_LOGS_WARN
    if cfg.retention_days == 0 and big:
        out.append(
            Check(
                "retention",
                WARN,
                f"retention is off and the database/logs are large ({logs / 1e9:.1f} GB of logs)",
                "set HYDRA_RUN_RETENTION_DAYS",
            )
        )
    else:
        out.append(
            Check(
                "retention",
                PASS,
                "off (keeps everything)" if cfg.retention_days == 0 else f"{cfg.retention_days} days; logs {logs / 1e6:.0f} MB",
            )
        )
    return out


def _service_check() -> Check:
    try:
        from .service import ServiceError, manager_for

        st = manager_for().status()
    except ServiceError as exc:
        return Check("service", WARN, str(exc))
    except Exception as exc:  # a broken service manager must not hide the other results
        return Check("service", WARN, f"could not query the service: {exc}")
    if not st.installed:
        return Check("service", WARN, f"{st.name} is not installed", "`hydra-ctl lite service install` to start Hydra at login")
    if not st.running:
        return Check("service", WARN, f"{st.name} is installed but not running", "`hydra-ctl lite service start`")
    return Check("service", PASS, f"{st.name} is running via {st.backend}")


def _api_checks(cfg: Config, client: Any, service_installed: bool) -> list[Check]:
    out: list[Check] = []
    try:
        health = client.health()
    except Exception as exc:
        severity = FAIL if service_installed else WARN
        return [
            Check(
                "daemon",
                severity,
                f"not reachable ({exc})",
                "`hydra-ctl lite daemon start` (or check daemon.log in the data dir)",
            )
        ]
    if health.get("edition") != "lite":
        return [Check("daemon", WARN, f"the API answers as edition {health.get('edition')!r}, not lite", "check HYDRA_API_URL")]
    out.append(Check("daemon", PASS, f"lite {health.get('version', '?')} on {client.base_url}"))
    try:
        workers = client.request("GET", "/workers/")
        online = [w for w in workers if w.get("connectivity_status") == "online"]
        want = cfg.default_workers if cfg.worker_mode == "subprocess" else 1
        out.append(
            Check(
                "workers",
                PASS if len(online) >= want else WARN,
                f"{len(online)} online (expected at least {want})",
                "" if len(online) >= want else "see workers/*.log in the data dir",
            )
        )
        queue = client.request("GET", "/overview/queue", query={"pending_limit": 20})
        pending = queue.get("pending", [])
        stuck: dict[str, str] = {}
        views = [
            {
                "os": w.get("os", ""),
                "tags": w.get("tags", []),
                "allowed_users": w.get("allowed_users", []),
                "hostname": w.get("hostname", ""),
                "subnet": w.get("subnet", ""),
                "deployment_type": w.get("deployment_type", ""),
                "capabilities": w.get("capabilities", []),
            }
            for w in online
        ]
        for run in pending:
            job = client.request("GET", f"/jobs/{run['job_id']}")
            norm = normalize_affinity(job)
            if not any(passes_affinity(norm, v) for v in views):
                needed = (norm.get("affinity") or {}).get("executor_types") or []
                stuck[job["name"]] = ", ".join(needed) or "affinity"
        if stuck:
            sample = "; ".join(f"{n} (needs {need})" for n, need in list(stuck.items())[:5])
            hint = (
                "no online worker can run them: spawn one with the right tags/capabilities (`hydra-ctl worker spawn --tag ...`)"
            )
            if any("sql" in need for need in stuck.values()):
                hint += "; SQL jobs need SQLAlchemy: install `hydra-jobs[sql]`"
            out.append(Check("pending runs", WARN, f"{len(stuck)} job(s) have pending runs no worker can take: {sample}", hint))
        else:
            out.append(Check("pending runs", PASS, f"{queue.get('pending_total', 0)} pending, all runnable"))
        bad_tz = []
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        for job in client.request("GET", "/jobs/"):
            sched = job.get("schedule") or {}
            if sched.get("mode") == "cron":
                try:
                    ZoneInfo(sched.get("timezone") or "UTC")
                except (ZoneInfoNotFoundError, ValueError):
                    bad_tz.append(f"{job['name']} ({sched.get('timezone')})")
        out.append(
            Check(
                "time zones",
                FAIL if bad_tz else PASS,
                ", ".join(bad_tz) if bad_tz else "all job time zones resolve",
                "install the tzdata package (Windows has no system time zone database)" if bad_tz else "",
            )
        )
    except Exception as exc:
        out.append(Check("daemon api", WARN, f"could not read workers/queue: {exc}"))
    return out


def run_checks(cfg: Config, client: Any = None, service_check: Callable[[], Check] = _service_check) -> list[Check]:
    checks = _local_checks(cfg)
    svc = service_check()
    checks.append(svc)
    if client is not None:
        checks += _api_checks(
            cfg,
            client,
            service_installed="not installed" not in svc.message and svc.status != WARN or "installed but" in svc.message,
        )
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        lines.append(f"{c.status:<4}  {c.name:<{width}}  {c.message}")
        if c.hint and c.status != PASS:
            lines.append(f"{'':<4}  {'':<{width}}  -> {c.hint}")
    counts = {s: sum(1 for c in checks if c.status == s) for s in (PASS, WARN, FAIL)}
    lines.append(f"\n{counts[PASS]} passed, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)")
    return "\n".join(lines)


def as_documents(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]


__all__ = ["Check", "run_checks", "render", "as_documents", "synced_or_network_reason"]

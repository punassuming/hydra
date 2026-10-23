"""``hydra-ctl lite ...``: local management of the lite edition (works while the daemon is down)."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from . import config as config_module
from . import paths

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def local_token(api_url: str) -> Optional[str]:
    """Token from the lite token file, only for loopback API URLs (never sent to remote hosts)."""
    host = urllib.parse.urlparse(api_url).hostname
    if host not in LOOPBACK:
        return None
    try:
        path = config_module.load().token_file
        return path.read_text(encoding="utf-8").strip() if path and path.is_file() else None
    except (OSError, ValueError):
        return None


def register(commands: Any, output_parent: argparse.ArgumentParser) -> None:
    lite = commands.add_parser("lite", help="Manage the local Hydra lite edition (daemon, config)")
    groups = lite.add_subparsers(dest="lite_command", required=True)

    daemon = groups.add_parser("daemon", help="Run or control the background scheduler")
    actions = daemon.add_subparsers(dest="daemon_command", required=True)
    for name, text in (
        ("run", "Run in the foreground"),
        ("start", "Start in the background"),
        ("stop", "Ask the daemon to exit"),
    ):
        action = actions.add_parser(name, help=text)
        if name in {"run", "start"}:
            action.add_argument("--host")
            action.add_argument("--port", type=int)
            action.add_argument("--data-dir")
    actions.add_parser("status", parents=[output_parent], help="Show daemon health")

    svc = groups.add_parser("service", help="Run the daemon as a per-user background service (no admin/root needed)")
    svc_actions = svc.add_subparsers(dest="service_command", required=True)
    install = svc_actions.add_parser("install", help="Register and start the service (idempotent; upgrades in place)")
    install.add_argument("--python", help="interpreter to register (default: the one running this command)")
    install.add_argument("--host")
    install.add_argument("--port", type=int)
    install.add_argument("--data-dir")
    install.add_argument("--no-start", action="store_true", help="register without starting")
    install.add_argument("--dry-run", action="store_true", help="print what would be registered and change nothing")
    install.add_argument(
        "--enable-linger", action="store_true", help="Linux: start at boot, not only at login (loginctl enable-linger)"
    )
    svc_actions.add_parser("remove", help="Stop and unregister the service (data is kept)")
    for name in ("start", "stop", "restart"):
        svc_actions.add_parser(name, help=f"{name.capitalize()} the registered service")
    svc_actions.add_parser("status", parents=[output_parent], help="Show whether the service is installed and running")

    doctor = groups.add_parser("doctor", parents=[output_parent], help="Check the install, data directory, daemon and service")
    doctor.add_argument("--no-api", action="store_true", help="skip checks that talk to the daemon")
    backup = groups.add_parser("backup", help="Write a consistent copy of the database (safe while the daemon runs)")
    backup.add_argument(
        "dest", nargs="?", help="destination file (default: hydra-backup-<timestamp>.db in the current directory)"
    )
    backup.add_argument("--force", action="store_true", help="overwrite an existing destination")
    backup.add_argument("--data-dir")

    cfg = groups.add_parser("config", help="Inspect configuration")
    cfg_actions = cfg.add_subparsers(dest="config_command", required=True)
    cfg_actions.add_parser("path", help="Print the config file and data locations")
    cfg_actions.add_parser("show", parents=[output_parent], help="Print the effective configuration")
    cfg_actions.add_parser("init", help="Write a commented config.toml if none exists")


def _overrides(args: argparse.Namespace) -> dict:
    return {"host": getattr(args, "host", None), "port": getattr(args, "port", None), "data_dir": getattr(args, "data_dir", None)}


def dispatch(args: argparse.Namespace, client_factory: Any) -> int:
    if args.lite_command == "daemon":
        return _daemon(args, client_factory)
    if args.lite_command == "service":
        return _service(args)
    if args.lite_command == "doctor":
        return _doctor(args, client_factory)
    if args.lite_command == "backup":
        return _backup(args)
    return _config(args)


def _daemon(args: argparse.Namespace, client_factory: Any) -> int:
    cmd = args.daemon_command
    if cmd == "run":
        from .__main__ import run

        return run({k: v for k, v in _overrides(args).items() if v is not None})
    if cmd == "start":
        return _start_background(args)
    token = args.token or local_token(args.api_url)
    client = client_factory(args.api_url, token=token, timeout=args.timeout)
    from cli._output import write_document, write_error

    try:
        if cmd == "status":
            health = client.health()
            write_document(health, args.output if args.output != "table" else "yaml")
            return 0
        client.request("POST", "/system/shutdown")
        print("shutdown requested")
        return 0
    except Exception as exc:  # APIError or OSError; unreachable server is its own exit code
        write_error(str(exc))
        return 3 if "could not reach" in str(exc) else 1  # matches hydra-ctl EXIT_UNREACHABLE


def _start_background(args: argparse.Namespace) -> int:
    overrides = {k: v for k, v in _overrides(args).items() if v is not None}
    cfg = config_module.load(overrides=overrides)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "hydra_lite", "--service"]
    for flag, key in (("--host", "host"), ("--port", "port"), ("--data-dir", "data_dir")):
        if key in overrides:
            cmd += [flag, str(overrides[key])]
    log_file = open(cfg.data_dir / "daemon.stderr.log", "ab")  # noqa: SIM115 - only start-up crashes land here; real logs rotate in daemon.log
    kwargs: dict[str, Any] = {"stdout": log_file, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603
    print(f"started hydra daemon (pid {proc.pid}); log: {cfg.data_dir / 'daemon.log'}")
    time.sleep(0.2)
    return 0


_TEMPLATE = """# Hydra (lite edition) configuration. Precedence: CLI flags > HYDRA_* env > this file.
[daemon]
host = "127.0.0.1"
port = 8000

[workers]
max_concurrency = 4

[retention]
days = 90
"""


def _config(args: argparse.Namespace) -> int:
    cmd = args.config_command
    if cmd == "path":
        cfg = config_module.load()
        print(f"config: {paths.config_file()}\ndata:   {cfg.data_dir}\nlogs:   {cfg.log_dir}\ntoken:  {cfg.token_file}")
        return 0
    if cmd == "show":
        from cli._output import write_document

        cfg = config_module.load()
        write_document(
            {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(cfg).items()}, "json" if args.output == "json" else "yaml"
        )
        return 0
    path = paths.config_file()
    if path.exists():
        print(f"{path} already exists")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def _service(args: argparse.Namespace) -> int:
    from cli._output import write_document, write_error

    from .service import ServiceError, ServiceSpec, interpreter_warnings, manager_for

    try:
        manager = manager_for()
        cmd = args.service_command
        if cmd == "install":
            if args.enable_linger and hasattr(manager, "enable_linger"):
                manager.enable_linger = True
            spec = ServiceSpec(python=args.python or sys.executable, data_dir=args.data_dir, port=args.port, host=args.host)
            for warning in interpreter_warnings(spec.python):
                print(f"warning: {warning}", file=sys.stderr)
            for line in manager.install(spec, start=not args.no_start, dry_run=args.dry_run):
                print(line)
            if args.dry_run:
                print("(dry run: nothing was changed)")
            return 0
        if cmd == "remove":
            for line in manager.uninstall():
                print(line)
            return 0
        if cmd in {"start", "stop"}:
            getattr(manager, cmd)()
            print(f"service {cmd} requested")
            return 0
        if cmd == "restart":
            manager.stop()
            manager.start()
            print("service restarted")
            return 0
        status = manager.status()
        doc = {
            "backend": status.backend,
            "name": status.name,
            "installed": status.installed,
            "running": status.running,
            "enabled": status.enabled,
            **{f"detail.{k}": v for k, v in status.detail.items()},
        }
        write_document(doc, "json" if args.output == "json" else "yaml")
        return 0 if status.running else 1
    except ServiceError as exc:
        write_error(str(exc))
        return 1


def _doctor(args: argparse.Namespace, client_factory: Any) -> int:
    from cli._output import write_document

    from . import doctor

    cfg = config_module.load()
    client = (
        None
        if args.no_api
        else client_factory(args.api_url, token=args.token or local_token(args.api_url), timeout=min(args.timeout, 5))
    )
    checks = doctor.run_checks(cfg, client)
    if args.output == "json":
        write_document(doctor.as_documents(checks), "json")
    else:
        print(doctor.render(checks))
    return 1 if any(c.status == doctor.FAIL for c in checks) else 0


def _backup(args: argparse.Namespace) -> int:
    import sqlite3
    from datetime import datetime

    from cli._output import write_error

    from .store.store import latest_version

    cfg = config_module.load({"data_dir": args.data_dir} if args.data_dir else None)
    if not cfg.db_path.exists():
        write_error(f"no database at {cfg.db_path}")
        return 4
    dest = Path(args.dest or f"hydra-backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    if dest.exists() and not args.force:
        write_error(f"{dest} already exists (use --force to overwrite)")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=30)
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")
            check = out.execute("PRAGMA integrity_check").fetchone()[0]
            version = out.execute("PRAGMA user_version").fetchone()[0]
        finally:
            out.close()
    finally:
        src.close()
    if check != "ok":
        write_error(f"the copy failed its integrity check: {check}")
        return 1
    print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB, schema v{version}, this Hydra writes v{latest_version()})")
    print("to restore: stop the daemon, replace hydra.db in the data directory with this file, start the daemon")
    return 0

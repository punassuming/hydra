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
    cmd = [sys.executable, "-m", "hydra_lite"]
    for flag, key in (("--host", "host"), ("--port", "port"), ("--data-dir", "data_dir")):
        if key in overrides:
            cmd += [flag, str(overrides[key])]
    log_file = open(cfg.data_dir / "daemon.log", "ab")  # noqa: SIM115 - inherited by the child
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

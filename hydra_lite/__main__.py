"""Run the Hydra lite daemon in the foreground: ``python -m hydra_lite``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from . import config as config_module
from .daemon.app import create_app
from .daemon.runtime import Daemon
from .logging_setup import configure_logging
from .pidlock import AlreadyRunning, DaemonLock

log = logging.getLogger("hydra_lite")


def run(overrides: dict | None = None, service: bool = False) -> int:
    cfg = config_module.load(overrides=overrides)
    log_file = os.getenv("HYDRA_LOG_FILE") or (cfg.data_dir / "daemon.log" if service else None)
    configure_logging(log_file)
    if cfg.host not in {"127.0.0.1", "localhost", "::1"}:
        log.warning("binding to non-loopback address %s; the API is token-protected but not encrypted", cfg.host)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock = DaemonLock(cfg.data_dir / "daemon.lock").acquire()
    except AlreadyRunning as exc:
        log.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 3
    try:
        app = create_app(Daemon(cfg))
        server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="info", log_config=None))
        app.state.server = server
        try:
            server.run()
        except SystemExit as exc:  # uvicorn exits (code 1) when it cannot bind the port
            log.error("the API could not start on %s:%s (is the port already in use?)", cfg.host, cfg.port)
            return int(exc.code or 1)
        return 0 if server.started else 1
    finally:
        lock.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hydra_lite", description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir")
    parser.add_argument("--service", action="store_true", help="log to <data dir>/daemon.log (rotating); for service managers")
    args = parser.parse_args(argv)
    return run({"host": args.host, "port": args.port, "data_dir": args.data_dir}, service=args.service)


if __name__ == "__main__":
    raise SystemExit(main())

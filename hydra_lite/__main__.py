"""Run the Hydra lite daemon in the foreground: ``python -m hydra_lite``."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from . import config as config_module
from .daemon.app import create_app
from .daemon.runtime import Daemon


def run(overrides: dict | None = None) -> int:
    cfg = config_module.load(overrides=overrides)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if cfg.host not in {"127.0.0.1", "localhost", "::1"}:
        logging.getLogger("hydra_lite").warning(
            "binding to non-loopback address %s; the API is token-protected but not encrypted", cfg.host
        )
    app = create_app(Daemon(cfg))
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="info"))
    app.state.server = server
    server.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hydra_lite", description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir")
    args = parser.parse_args(argv)
    return run({"host": args.host, "port": args.port, "data_dir": args.data_dir})


if __name__ == "__main__":
    raise SystemExit(main())

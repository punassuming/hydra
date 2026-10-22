"""Configuration for the Hydra lite edition.

Precedence (highest first): explicit overrides (CLI flags) > ``HYDRA_*``
environment variables > ``config.toml`` > defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Optional

from . import paths


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = field(default_factory=paths.data_dir)
    log_dir: Optional[Path] = None
    token_file: Optional[Path] = None
    default_workers: int = 1
    max_concurrency: int = 4
    worker_tags: list[str] = field(default_factory=list)
    idle_stop_seconds: int = 0
    retention_days: int = 90

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.log_dir = Path(self.log_dir) if self.log_dir else self.data_dir / "logs"
        self.token_file = Path(self.token_file) if self.token_file else self.data_dir / "token"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hydra.db"


# (config key, toml table, toml key, env var, caster)
def _int(value: Any) -> int:
    return int(value)


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return [str(t) for t in value]


_SPEC: tuple[tuple[str, str, str, str, Any], ...] = (
    ("host", "daemon", "host", "HYDRA_HOST", str),
    ("port", "daemon", "port", "HYDRA_PORT", _int),
    ("data_dir", "paths", "data_dir", "HYDRA_DATA_DIR", Path),
    ("log_dir", "paths", "log_dir", "HYDRA_LOG_DIR", Path),
    ("token_file", "auth", "token_file", "HYDRA_TOKEN_FILE", Path),
    ("default_workers", "workers", "default_count", "HYDRA_DEFAULT_WORKERS", _int),
    ("max_concurrency", "workers", "max_concurrency", "HYDRA_MAX_CONCURRENCY", _int),
    ("worker_tags", "workers", "tags", "HYDRA_WORKER_TAGS", _tags),
    ("idle_stop_seconds", "workers", "idle_stop_seconds", "HYDRA_IDLE_STOP_SECONDS", _int),
    ("retention_days", "retention", "days", "HYDRA_RETENTION_DAYS", _int),
)


def load(
    overrides: Optional[Mapping[str, Any]] = None,
    env: Optional[Mapping[str, str]] = None,
    config_path: Optional[Path] = None,
) -> Config:
    env = os.environ if env is None else env
    path = config_path or paths.config_file()
    file_data: dict[str, Any] = {}
    if path.is_file():
        with path.open("rb") as handle:
            file_data = tomllib.load(handle)

    values: dict[str, Any] = {}
    for key, table, toml_key, env_var, cast in _SPEC:
        table_data = file_data.get(table) or {}
        if toml_key in table_data:
            values[key] = cast(table_data[toml_key])
        if env_var in env and env[env_var] != "":
            values[key] = cast(env[env_var])
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key not in {f.name for f in fields(Config)}:
            raise KeyError(f"unknown config key: {key}")
        spec = next(s for s in _SPEC if s[0] == key)
        values[key] = spec[4](value)

    if values.get("port") is not None and not 0 < values["port"] < 65536:
        raise ValueError(f"port out of range: {values['port']}")
    return Config(**values)

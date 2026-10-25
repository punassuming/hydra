"""Per-OS locations for Hydra's config, data and logs.

``HYDRA_CONFIG_DIR`` / ``HYDRA_DATA_DIR`` override the defaults, which also keeps
tests hermetic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def config_dir() -> Path:
    override = os.getenv("HYDRA_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA") or _home() / "AppData" / "Roaming") / "Hydra"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Hydra"
    return Path(os.getenv("XDG_CONFIG_HOME") or _home() / ".config") / "hydra"


def data_dir() -> Path:
    override = os.getenv("HYDRA_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.getenv("LOCALAPPDATA") or _home() / "AppData" / "Local") / "Hydra"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Hydra" / "data"
    return Path(os.getenv("XDG_DATA_HOME") or _home() / ".local" / "share") / "hydra"


def config_file() -> Path:
    return config_dir() / "config.toml"

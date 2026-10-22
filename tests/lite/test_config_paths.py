import pytest

from hydra_lite import config, paths


def test_env_overrides_for_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("HYDRA_DATA_DIR", str(tmp_path / "data"))
    assert paths.config_dir() == tmp_path / "cfg"
    assert paths.data_dir() == tmp_path / "data"
    assert paths.config_file() == tmp_path / "cfg" / "config.toml"


def test_defaults_are_loopback_and_derived_paths(tmp_path):
    cfg = config.load(env={"HYDRA_DATA_DIR": str(tmp_path)}, config_path=tmp_path / "missing.toml")
    assert cfg.host == "127.0.0.1" and cfg.port == 8000
    assert cfg.db_path == tmp_path / "hydra.db"
    assert cfg.log_dir == tmp_path / "logs"
    assert cfg.token_file == tmp_path / "token"


def test_precedence_override_over_env_over_file(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[daemon]\nport = 9001\nhost = "0.0.0.0"\n[workers]\ntags = ["a", "b"]\nmax_concurrency = 2\n')
    cfg = config.load(env={"HYDRA_DATA_DIR": str(tmp_path)}, config_path=f)
    assert (cfg.port, cfg.host, cfg.worker_tags, cfg.max_concurrency) == (9001, "0.0.0.0", ["a", "b"], 2)

    cfg = config.load(env={"HYDRA_PORT": "9002", "HYDRA_DATA_DIR": str(tmp_path)}, config_path=f)
    assert cfg.port == 9002 and cfg.host == "0.0.0.0"

    cfg = config.load(overrides={"port": 9003}, env={"HYDRA_PORT": "9002", "HYDRA_DATA_DIR": str(tmp_path)}, config_path=f)
    assert cfg.port == 9003


def test_env_tags_are_comma_separated(tmp_path):
    cfg = config.load(env={"HYDRA_WORKER_TAGS": "x, y,,z", "HYDRA_DATA_DIR": str(tmp_path)}, config_path=tmp_path / "n.toml")
    assert cfg.worker_tags == ["x", "y", "z"]


def test_invalid_port_and_unknown_override(tmp_path):
    with pytest.raises(ValueError):
        config.load(overrides={"port": 70000}, env={"HYDRA_DATA_DIR": str(tmp_path)}, config_path=tmp_path / "n.toml")
    with pytest.raises(KeyError):
        config.load(overrides={"nope": 1}, env={"HYDRA_DATA_DIR": str(tmp_path)}, config_path=tmp_path / "n.toml")

# Installing Hydra lite

Hydra lite is a per-user background scheduler: one daemon, a SQLite file, and `hydra-ctl` as the command line. It
needs **Python 3.11+** and nothing else (no Redis, MongoDB or Docker).

## 1. Install

```bash
# recommended: an isolated tool environment with the lean dependency set
uv tool install git+https://github.com/punassuming/Hydra        # or: pipx install git+https://github.com/punassuming/Hydra
hydra-ctl --version

# optional extras
uv tool install "hydra-jobs[sql] @ git+https://github.com/punassuming/Hydra"   # SQL jobs (adds SQLAlchemy)
```

The default install is deliberately small (FastAPI, uvicorn, pydantic, croniter, PyYAML; `tzdata` on Windows).
`hydra-jobs[full]` is the Redis + MongoDB scheduler/worker stack and is not needed here.

From a checkout: `uv tool install .` (or `uv sync` for development; `uv sync --dev --all-extras` to run the whole
test suite).

## 2. Try it in the foreground

```bash
hydra-ctl lite doctor            # checks Python/SQLite, the data folder, the service, ...
hydra-ctl lite daemon start      # background; `lite daemon run` keeps it in this terminal
cat > hello.yaml <<'YAML'
name: hello
executor: {type: shell, script: "echo hello from hydra"}
schedule: {mode: interval, interval_seconds: 60}
YAML
hydra-ctl apply -f hello.yaml
hydra-ctl get runs
hydra-ctl lite daemon stop
```

## 3. Keep it running: install as a service

No administrator or root rights are needed; the service runs as you.

| | Windows | Linux |
|---|---|---|
| Mechanism | Task Scheduler task `\Hydra\Daemon`: starts at **your log on**, hidden, limited rights, restarted on failure | `systemd --user` unit `hydra.service` |
| Install | `hydra-ctl lite service install` | `hydra-ctl lite service install` (`--enable-linger` to start at boot instead of at login) |
| Inspect | `hydra-ctl lite service status` | `hydra-ctl lite service status`, `journalctl --user -u hydra` |
| Remove | `hydra-ctl lite service remove` (data is kept) | same |

`service install --dry-run` prints exactly what would be registered. Re-running `install` upgrades in place (use it
after upgrading Hydra, or if you moved the interpreter). Pass `--python`, `--port` or `--data-dir` to bake overrides
into the registration; everything else comes from `config.toml`.

Notes:

* Windows: the task runs while you are logged on. Starting at boot with nobody logged in needs an administrator and a
  stored password; use the NSSM recipe in [`../windows-worker-bootstrap.md`](../windows-worker-bootstrap.md) with
  `python -m hydra_lite --service` if you need that.
* Install Hydra with `uv tool install`/`pipx` first: a service that points at a throw-away `uv run` environment stops
  working when that environment is cleaned up (the installer warns when it sees one).
* Logs: `daemon.log` (rotating, 10 MB x 5) and `workers/*.log` in the data directory.
* Only one daemon can use a data directory; a second one exits with an error.

## 4. Daily operations

```bash
hydra-ctl lite doctor                 # PASS/WARN/FAIL with the fix for each problem; -o json for scripts
hydra-ctl lite backup ~/hydra.db      # consistent copy, safe while the daemon runs
hydra-ctl lite config path            # where config, data and logs live
```

**Restore:** `hydra-ctl lite service stop` (or `daemon stop`), replace `hydra.db` in the data directory with the
backup, start again. Upgrades that change the database schema copy `hydra.db` to `hydra.db.pre-vN.bak` first.

**Uninstall:** `hydra-ctl lite service remove`, then `uv tool uninstall hydra-jobs`; delete the data directory
(`hydra-ctl lite config path` shows it) if you also want the history gone.

## Troubleshooting

| Symptom | Check |
|---|---|
| `service status` says not running | `hydra-ctl lite doctor`; read `daemon.log` and `daemon.stderr.log` in the data directory |
| "a Hydra daemon is already running" | another daemon owns the data directory; `lite daemon stop` or `lite service stop` |
| port already in use | change `[daemon] port` in `config.toml` (default 8000) |
| runs stay `pending` | `doctor` lists jobs no worker can run (tags, OS, or a missing capability such as `sql`) |
| `doctor` warns about the data folder | it is on a network share or inside OneDrive/Dropbox: move it with `HYDRA_DATA_DIR` |
| cron fires at the wrong hour | set `schedule.timezone` (IANA name); on Windows `tzdata` must be installed (it is, by default) |

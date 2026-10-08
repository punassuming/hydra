# Job parameters

Run-time parameters let you pass values into a single run without editing the
job definition. They reach the job as **environment variables**.

## How to pass them

| Where | Example |
| --- | --- |
| API | `POST /jobs/{id}/run` with `{"params": {"DATE": "2026-07-22"}}` |
| CLI | `hydra-ctl run nightly-report --param DATE=2026-07-22 --param REGION=eu` |
| UI | Job detail -> **Run Now** -> "Run with Parameters", one `KEY=VALUE` per line |
| Scheduler | Backfills and artifact triggers add the `HYDRA_*` params listed below |

## Naming convention

A param `FOO=bar` becomes the environment variable `FOO=bar`, under exactly that
name, on **both** worker flavors (Python and Go). There is no prefix.

```bash
# job script
echo "report for $DATE in $REGION"
```

- **Key format:** `^[A-Za-z_][A-Za-z0-9_]*$`, at most 128 characters. The API
  rejects anything else with a `422` naming the key; the CLI and the UI modal
  check the same rule before sending.
- **Values are strings.** The CLI never JSON-coerces them (`--param retries=2`
  sends `"2"`), and structured data is just a string your script parses.
- **Case is preserved.** `date` and `DATE` are different variables.

### Precedence

Later wins:

1. the worker's own environment
2. the job's `executor.env`
3. run params
4. values the worker sets itself (for example `KRB5CCNAME` for Kerberos jobs)

So a param overrides a same-named `executor.env` entry, which is how you
override a job's default for one run.

### Which executors see them

Params are environment variables, so they reach executors that start a process:
shell, python, batch, powershell, external and sql. The `http` and `sensor`
executors do not use the process environment.

### Caution: names are not restricted beyond the format

Validation is format-only. A caller who may run a job can set any valid
variable name for that run, including `PATH`, `LD_PRELOAD` or `PYTHONPATH`.
Treat the permission to run a job with params as the permission to control its
environment.

## Names set by the scheduler

These are ordinary params whose keys happen to start with `HYDRA_`:

| Name | Set when | Value |
| --- | --- | --- |
| `HYDRA_EXECUTION_DATE` | a backfill run | `YYYY-MM-DD` being backfilled |
| `HYDRA_IS_BACKFILL` | a backfill run | `true` |
| `HYDRA_UPSTREAM_ARTIFACT_METADATA` | a job triggered by an artifact | JSON string of the artifact's metadata |

## Changed in this release

Earlier versions of the **Go** worker also exposed each param as
`HYDRA_PARAM_<KEY>` and did not document the raw name. The prefixed form is
gone: change `$HYDRA_PARAM_DATE` to `$DATE`. The Python worker never used the
prefix, so Python-only deployments are unaffected.

## For maintainers

The mapping is implemented twice and pinned by one shared fixture:
`worker/utils/params.py` (Python) and `executor.buildEnv` in
`go-worker/internal/executor/executor.go` (Go), both checked against
`tests/fixtures/param_env_contract.json`. Change the rule in both workers and
the fixture together. Params survive being re-queued after a worker failure or
detach (`scheduler/utils/requeue.py`), but a run that was already *running* when
its worker died is retried with its defaults, because params are not stored
anywhere durable.

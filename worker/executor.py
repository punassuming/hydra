import json
import os
import platform
import tempfile
import time
from typing import Callable, Dict, Optional, Tuple

from .runtime import (
    _find_python,
    _get_temp_dir,
    _resolve_shell,
)
from .utils.copy import fetch_copy_source
from .utils.git import fetch_git_source
from .utils.os_exec import _run_with_callbacks, run_external
from .utils.python_env import prepare_python_command
from .utils.rsync import fetch_rsync_source
from .utils.workspace_cache import get_workspace_cache


def _execute_powershell(
    executor: dict,
    script: str,
    args: list,
    timeout,
    merged_env,
    workdir,
    _with_impersonation,
    _run_cmd,
    log_callback_out,
    log_callback_err,
):
    """Execute a PowerShell script via pwsh or powershell."""
    shell = _resolve_shell(executor.get("shell", "pwsh"))
    cmd = _with_impersonation([shell, "-NoProfile", "-Command", script] + args)
    return _run_cmd(cmd)


def _execute_sql(executor: dict, timeout, merged_env, workdir, _run_cmd, log_callback_out, log_callback_err):
    """Execute a SQL query by writing a helper Python script that uses DB-API or pymongo."""
    dialect = executor.get("dialect", "postgres")
    query = executor.get("query", "")
    connection_uri = executor.get("connection_uri") or ""
    database = executor.get("database") or ""
    max_rows = executor.get("max_rows", 10000)
    autocommit = executor.get("autocommit", True)

    if not query.strip():
        return 1, "", "sql executor requires a non-empty query"
    if not connection_uri:
        return 1, "", "sql executor requires connection_uri or credential_ref"

    # Build a small Python driver script that connects and runs the query
    if dialect == "mongodb":
        driver_code = (
            "import json, sys\n"
            "try:\n"
            "    from pymongo import MongoClient\n"
            "except ImportError:\n"
            "    print('pymongo is not installed on this worker', file=sys.stderr); sys.exit(1)\n"
            f"client = MongoClient({connection_uri!r})\n"
            f"db = client[{database!r}] if {database!r} else client.get_default_database()\n"
            f"result = db.command({query!r})\n"
            "print(json.dumps(result, default=str))\n"
        )
    else:
        # Use sqlalchemy for relational DBs
        driver_code = (
            "import json, sys\n"
            "try:\n"
            "    from sqlalchemy import create_engine, text\n"
            "except ImportError:\n"
            "    print('sqlalchemy is not installed on this worker', file=sys.stderr); sys.exit(1)\n"
            f"engine = create_engine({connection_uri!r})\n"
            "with engine.connect() as conn:\n"
        )
        if not autocommit:
            driver_code += (
                "    trans = conn.begin()\n"
                "    try:\n"
                f"        result = conn.execute(text({query!r}))\n"
                "        try:\n"
                "            rows = [dict(r._mapping) for r in result]\n"
                f"            truncated = len(rows) > {max_rows}\n"
                f"            rows = rows[:{max_rows}]\n"
                '            print(json.dumps({"rows": rows, "row_count": len(rows), "truncated": truncated}, default=str))\n'
                "        except Exception:\n"
                '            print(json.dumps({"rows": [], "row_count": 0, "truncated": False, '
                '"message": "query executed (no result set)"}, default=str))\n'
                "        trans.commit()\n"
                "    except Exception as e:\n"
                "        trans.rollback()\n"
                "        raise\n"
            )
        else:
            driver_code += (
                f"    result = conn.execute(text({query!r}))\n"
                "    try:\n"
                "        rows = [dict(r._mapping) for r in result]\n"
                f"        truncated = len(rows) > {max_rows}\n"
                f"        rows = rows[:{max_rows}]\n"
                '        print(json.dumps({"rows": rows, "row_count": len(rows), "truncated": truncated}, default=str))\n'
                "    except Exception:\n"
                '        print(json.dumps({"rows": [], "row_count": 0, "truncated": False, '
                '"message": "query executed (no result set)"}, default=str))\n'
            )

    # Write to temp file and execute
    fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="hydra-sql-", dir=_get_temp_dir())
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(driver_code)
        interp = _find_python()
        if not interp:
            return 1, "", "No Python interpreter found to run SQL driver script"
        cmd = [interp, tmp_path]
        return _run_cmd(cmd)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _execute_http(executor: dict, timeout, log_callback_out, log_callback_err):
    """Execute an HTTP request and return the response."""
    import urllib.error
    import urllib.request

    url = executor.get("url", "")
    if not url:
        return 1, "", "http executor requires a non-empty url"

    method = executor.get("method", "GET").upper()
    headers = executor.get("headers") or {}
    body = executor.get("body")
    expected_status = executor.get("expected_status", [200])
    timeout_seconds = executor.get("timeout_seconds", 30)

    body_bytes = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout_seconds)
        status = resp.status
        resp_headers = dict(resp.getheaders())
        resp_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        resp_headers = dict(e.headers.items()) if e.headers else {}
        resp_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
    except Exception as e:
        return 1, "", f"http request failed: {e}"

    result = json.dumps(
        {
            "status": status,
            "headers": resp_headers,
            "body": resp_body,
        },
        default=str,
    )

    if log_callback_out:
        log_callback_out(result)

    if expected_status and status not in expected_status:
        return 1, result, f"unexpected status {status}, expected one of {expected_status}"

    return 0, result, ""


def _check_http_sensor(executor: dict) -> bool:
    """Return True if the HTTP sensor condition is met (expected status received)."""
    import urllib.error
    import urllib.request

    url = executor.get("target", "")
    if not url:
        return False
    method = executor.get("method", "GET").upper()
    headers = dict(executor.get("headers") or {})
    body = executor.get("body")
    expected_status = executor.get("expected_status") or [200]
    # Cap per-request timeout well below poll_interval so a slow response
    # does not delay the next interval check.
    request_timeout = min(int(executor.get("poll_interval_seconds", 30)), 25)

    body_bytes = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=request_timeout) as resp:
            return resp.status in expected_status
    except urllib.error.HTTPError as exc:
        return exc.code in expected_status
    except Exception:
        return False


def _check_sql_sensor(executor: dict) -> bool:
    """Return True if the SQL sensor condition is met (query returns ≥1 row)."""
    connection_uri = (executor.get("connection_uri") or "").strip()
    if not connection_uri:
        return False
    query = (executor.get("target") or "").strip()
    if not query:
        return False
    dialect = executor.get("dialect", "postgres")
    if dialect == "mongodb":
        try:
            from pymongo import MongoClient  # noqa: F401

            client = MongoClient(connection_uri, serverSelectionTimeoutMS=5000)
            db = client.get_default_database()
            result = db.command(query)
            return bool(result)
        except Exception:
            return False
    else:
        try:
            import sqlalchemy

            engine = sqlalchemy.create_engine(connection_uri, pool_pre_ping=True)
            with engine.connect() as conn:
                result = conn.execute(sqlalchemy.text(query))
                row = result.fetchone()
                return row is not None
        except Exception:
            return False


def _execute_sensor(
    executor: dict, kill_event: Optional[object] = None, log_callback_out: Optional[Callable[[str], None]] = None
) -> Tuple[int, str, str]:
    """Execute a sensor job: poll until condition is met or overall timeout expires.

    The sensor loops on the *worker*, keeping the scheduler free from
    direct external polling.  Polling respects ``poll_interval_seconds``
    and the overall run is bounded by ``timeout_seconds``.
    """
    sensor_type = executor.get("sensor_type", "http")
    poll_interval = max(1, int(executor.get("poll_interval_seconds", 30)))
    timeout_seconds = max(1, int(executor.get("timeout_seconds", 3600)))
    start_ts = time.time()

    while True:
        if kill_event and kill_event.is_set():
            return 1, "", "sensor run killed"

        now = time.time()
        elapsed = now - start_ts
        if elapsed >= timeout_seconds:
            return 1, "", f"sensor timed out after {elapsed:.1f}s"

        if sensor_type == "http":
            met = _check_http_sensor(executor)
        elif sensor_type == "sql":
            met = _check_sql_sensor(executor)
        else:
            return 1, "", f"unknown sensor_type '{sensor_type}'"

        if met:
            msg = f"condition_met after {time.time() - start_ts:.1f}s"
            if log_callback_out:
                log_callback_out(msg)
            return 0, msg, ""

        # Wait out the poll interval in small increments so we can react to
        # kill events and the overall timeout without excess latency.
        wait_end = time.time() + poll_interval
        while time.time() < wait_end:
            if kill_event and kill_event.is_set():
                return 1, "", "sensor run killed"
            if time.time() - start_ts >= timeout_seconds:
                break
            time.sleep(min(1.0, wait_end - time.time()))


def execute_job(
    job: dict,
    log_callback_out: Optional[Callable[[str], None]] = None,
    log_callback_err: Optional[Callable[[str], None]] = None,
    kill_event: Optional[object] = None,
    timings: Optional[Dict[str, float]] = None,
    timed_out_holder: Optional[Dict[str, bool]] = None,
) -> Tuple[int, str, str]:
    executor = job.get("executor") or {}
    timeout = job.get("timeout", 0) or None
    env = executor.get("env")
    workdir = executor.get("workdir")
    args = executor.get("args") or []
    impersonate_user = (executor.get("impersonate_user") or "").strip() or None
    kerberos = executor.get("kerberos") or {}
    exec_type = (executor.get("type") or job.get("shell") or "shell").lower()
    job_identifier = job.get("_id") or job.get("id") or "job"
    current_os = platform.system().lower()
    supports_impersonation = current_os in ("linux", "darwin")

    if (impersonate_user or kerberos) and not supports_impersonation:
        return (
            1,
            "",
            f"impersonation/kerberos executor settings are supported only on Linux/macOS workers (current: {platform.system()})",
        )

    # Sensor executor: delegate entirely to the sensor polling loop.
    # Runs on the worker — no external polling in the scheduler control plane.
    if exec_type == "sensor":
        return _execute_sensor(executor, kill_event=kill_event, log_callback_out=log_callback_out)

    effective_env = dict(env or {})
    if kerberos.get("ccache"):
        effective_env["KRB5CCNAME"] = str(kerberos.get("ccache"))
    merged_env = effective_env or None

    def _with_impersonation(cmd: list[str]) -> list[str]:
        if impersonate_user:
            return ["sudo", "-n", "-u", impersonate_user, "--"] + cmd
        return cmd

    def _run_cmd(cmd: list[str]) -> Tuple[int, str, str]:
        if log_callback_out or log_callback_err:
            return _run_with_callbacks(
                cmd,
                timeout,
                merged_env,
                workdir,
                on_stdout=log_callback_out,
                on_stderr=log_callback_err,
                kill_event=kill_event,
                timed_out_holder=timed_out_holder,
            )
        return run_external(
            binary=cmd[0], args=cmd[1:], timeout=timeout, env=merged_env, workdir=workdir, timed_out_holder=timed_out_holder
        )

    _krb_ccache = kerberos.get("ccache") if (kerberos and kerberos.get("principal") and kerberos.get("keytab")) else None
    if kerberos and kerberos.get("principal") and kerberos.get("keytab"):
        kinit_cmd = _with_impersonation(["kinit", "-kt", str(kerberos.get("keytab")), str(kerberos.get("principal"))])
        rc_k, out_k, err_k = _run_cmd(kinit_cmd)
        if rc_k != 0:
            return rc_k, out_k, f"Kerberos init failed: {err_k or out_k}"

    source = job.get("source")
    source_cleanup = None

    if source and source.get("url"):
        domain = job.get("domain", "prod")

        def _fetch_source(dest_dir: str, src_cfg: dict):
            protocol = src_cfg.get("protocol") or "git"
            if protocol == "copy":
                fetch_copy_source(src_cfg["url"], dest_dir)
            elif protocol == "rsync":
                fetch_rsync_source(src_cfg["url"], dest_dir, credential_ref_token=src_cfg.get("token") or "")
            else:
                sparse_path = src_cfg.get("path", "") if src_cfg.get("sparse") else ""
                fetch_git_source(
                    src_cfg["url"],
                    src_cfg.get("ref", "main"),
                    dest_dir,
                    token=src_cfg.get("token") or "",
                    sparse_path=sparse_path,
                )

        try:
            _source_fetch_start = time.time()
            cache = get_workspace_cache()
            source_dir, release_fn = cache.get_or_create(
                domain=domain,
                job_id=job_identifier,
                source_config=source,
                fetch_fn=_fetch_source,
            )
            if timings is not None:
                timings["source_fetch_ms"] = round((time.time() - _source_fetch_start) * 1000, 2)
            # Determine effective workdir
            base_path = source_dir
            if source.get("path"):
                base_path = os.path.join(base_path, source["path"])
            if workdir:
                # A source-relative POSIX path such as /scripts must retain
                # that meaning when the job runs on Windows.
                if os.path.isabs(workdir) or workdir.startswith(("/", "\\")):
                    workdir = os.path.join(base_path, workdir.lstrip("/\\"))
                else:
                    workdir = os.path.join(base_path, workdir)
            else:
                workdir = base_path
            source_cleanup = release_fn

        except Exception as e:
            return 1, "", f"Failed to fetch source: {str(e)}"

    try:
        if exec_type == "python":
            code = executor.get("code") or job.get("command", "")
            try:
                _env_prep_start = time.time()
                command, cleanup = prepare_python_command(executor, job_identifier)
                if timings is not None:
                    timings["env_prep_ms"] = round((time.time() - _env_prep_start) * 1000, 2)
            except Exception as prep_err:
                return 1, "", str(prep_err)
            tmp_code = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, prefix="hydra-py-", dir=_get_temp_dir())
            try:
                with tmp_code:
                    tmp_code.write(code)
                cmd_with_code = command + [tmp_code.name] + args
                return _run_cmd(_with_impersonation(cmd_with_code))
            finally:
                try:
                    os.unlink(tmp_code.name)
                except OSError:
                    pass
                if cleanup:
                    cleanup()
        if exec_type == "external":
            binary = executor.get("command") or job.get("command", "")
            cmd = _with_impersonation([binary] + args)
            return _run_cmd(cmd)
        if exec_type == "batch":
            script = executor.get("script") or job.get("command", "")
            shell = executor.get("shell", "cmd")
            suffix = ".bat" if shell == "cmd" else ".sh"
            tmp_script = tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False, prefix="hydra-batch-", dir=_get_temp_dir()
            )
            try:
                with tmp_script:
                    tmp_script.write(script)
                cmd = _with_impersonation(["cmd", "/c", tmp_script.name] if shell == "cmd" else [shell, tmp_script.name])
                return _run_cmd(cmd)
            finally:
                try:
                    os.unlink(tmp_script.name)
                except OSError:
                    pass
        if exec_type == "powershell":
            script = executor.get("script") or job.get("command", "")
            return _execute_powershell(
                executor,
                script,
                args,
                timeout,
                merged_env,
                workdir,
                _with_impersonation,
                _run_cmd,
                log_callback_out,
                log_callback_err,
            )
        if exec_type == "sql":
            return _execute_sql(
                executor,
                timeout,
                merged_env,
                workdir,
                _run_cmd,
                log_callback_out,
                log_callback_err,
            )
        if exec_type == "http":
            return _execute_http(
                executor,
                timeout,
                log_callback_out,
                log_callback_err,
            )

        # default shell executor
        script = executor.get("script") or job.get("command", "")
        shell = executor.get("shell", job.get("shell", "bash"))
        shell_name = str(shell).lower()
        suffix = ".ps1" if shell_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"} else ".sh"
        tmp_script = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, prefix="hydra-sh-", dir=_get_temp_dir())
        try:
            with tmp_script:
                tmp_script.write(script)
            resolved_shell = _resolve_shell(shell)
            if shell_name == "bash":
                shell_cmd = [resolved_shell, "-l", tmp_script.name, *args]
            elif shell_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
                shell_args = ["-NoProfile", "-NonInteractive"]
                if platform.system().lower().startswith("win"):
                    shell_args.extend(("-ExecutionPolicy", "Bypass"))
                shell_cmd = [resolved_shell, *shell_args, "-File", tmp_script.name, *args]
            elif shell_name in {"cmd", "cmd.exe"}:
                shell_cmd = [resolved_shell, "/c", tmp_script.name, *args]
            else:
                shell_cmd = [resolved_shell, tmp_script.name, *args]
            cmd = _with_impersonation(shell_cmd)
            return _run_cmd(cmd)
        finally:
            try:
                os.unlink(tmp_script.name)
            except OSError:
                pass
    finally:
        if source_cleanup:
            source_cleanup()
        if _krb_ccache:
            try:
                run_external(binary="kdestroy", args=["-c", str(_krb_ccache)], timeout=5)
            except Exception:
                pass

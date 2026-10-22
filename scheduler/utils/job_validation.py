"""Executor/schedule validation for job definitions.

Shared by the full scheduler API and the lite edition so both reject the same jobs.
Imports only pydantic models, so it is safe without Redis/MongoDB installed.
"""

from datetime import datetime, timezone

from ..models.job_definition import JobDefinition, JobValidationResult
from .schedule import initialize_schedule


def validate_job_definition(job: JobDefinition) -> JobValidationResult:
    errors = []
    next_run_at = None
    executor = job.executor
    exec_type = getattr(executor, "type", None)
    if exec_type == "python":
        code = getattr(executor, "code", "")
        if not code.strip():
            errors.append("python executor requires non-empty code")
        else:
            try:
                compile(code, "<job>", "exec")
            except SyntaxError as exc:
                errors.append(f"python code syntax error: {exc.msg} (line {exc.lineno})")
        env_cfg = getattr(executor, "environment", None)
        if env_cfg and env_cfg.type != "venv" and env_cfg.venv_path:
            errors.append("environment.venv_path can only be set when environment.type == 'venv'")
    elif exec_type in {"shell", "batch", "powershell"}:
        script = getattr(executor, "script", "")
        if not script.strip():
            errors.append(f"{exec_type} executor requires non-empty script")
    elif exec_type == "sql":
        query = getattr(executor, "query", "")
        if not query.strip():
            errors.append("sql executor requires a non-empty query")
        connection_uri = getattr(executor, "connection_uri", None) or ""
        credential_ref = getattr(executor, "credential_ref", None) or ""
        if not connection_uri.strip() and not credential_ref.strip():
            errors.append("sql executor requires connection_uri or credential_ref")
    elif exec_type == "external":
        command = getattr(executor, "command", "")
        if not command.strip():
            errors.append("external executor requires a command or binary path")
    elif exec_type == "sensor":
        target = getattr(executor, "target", "")
        if not target.strip():
            errors.append("sensor executor requires a non-empty target")
        sensor_type = getattr(executor, "sensor_type", "")
        if sensor_type == "sql":
            connection_uri = getattr(executor, "connection_uri", None) or ""
            credential_ref = getattr(executor, "credential_ref", None) or ""
            if not connection_uri.strip() and not credential_ref.strip():
                errors.append("sql sensor requires connection_uri or credential_ref")
    else:
        errors.append("executor.type must be one of python|shell|batch|powershell|sql|external|sensor")

    try:
        next_run_at = initialize_schedule(job.schedule, datetime.now(timezone.utc)).next_run_at
    except ValueError as exc:
        errors.append(str(exc))

    return JobValidationResult(valid=not errors, errors=errors, next_run_at=next_run_at)

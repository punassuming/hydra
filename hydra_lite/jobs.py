"""Job validation and (de)serialisation, reusing the main edition's pydantic models."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from scheduler.models.job_definition import JobCreate, JobDefinition
from scheduler.utils.schedule import initialize_schedule

MASKED_SECRET = "********"


class JobValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def apply_retry_count(payload: dict) -> dict:
    retry_count = payload.pop("retry_count", None)
    if retry_count is not None and not payload.get("max_retries"):
        payload["max_retries"] = retry_count
    return payload


def validate_definition(job: JobDefinition) -> list[str]:
    errors: list[str] = []
    executor = job.executor
    kind = getattr(executor, "type", None)
    if kind == "python":
        code = getattr(executor, "code", "")
        if not code.strip():
            errors.append("python executor requires non-empty code")
        else:
            try:
                compile(code, "<job>", "exec")
            except SyntaxError as exc:
                errors.append(f"python code syntax error: {exc.msg} (line {exc.lineno})")
    elif kind in {"shell", "batch", "powershell"}:
        if not getattr(executor, "script", "").strip():
            errors.append(f"{kind} executor requires non-empty script")
    elif kind == "sql":
        errors.append("sql executor is not supported by the lite edition yet")
    return errors


def build_job(payload: dict, now: Optional[datetime] = None, preserve_schedule: Optional[dict] = None) -> dict:
    """Validate a JobCreate-shaped payload and return the document to store.

    ``preserve_schedule`` keeps an existing schedule (including its ``next_run_at``) instead of
    re-initialising it, so editing an unrelated field never re-fires an interval job.
    """
    create = JobCreate.model_validate(payload)  # raises pydantic.ValidationError
    data = apply_retry_count(create.model_dump())
    data["domain"] = "prod"
    job = JobDefinition(**data)
    errors = validate_definition(job)
    if errors:
        raise JobValidationError(errors)
    try:
        if preserve_schedule is not None:
            schedule = type(job.schedule).model_validate(preserve_schedule)
        else:
            schedule = initialize_schedule(job.schedule, now or datetime.now(timezone.utc))
    except ValueError as exc:
        raise JobValidationError([str(exc)]) from exc
    job = job.model_copy(update={"schedule": schedule})
    return job.model_dump(by_alias=True, mode="json")


def validate_payload(payload: dict) -> dict:
    """Return a JobValidationResult-shaped dict (never raises for invalid jobs)."""
    try:
        doc = build_job(payload)
    except JobValidationError as exc:
        return {"valid": False, "errors": exc.errors, "next_run_at": None}
    return {"valid": True, "errors": [], "next_run_at": doc["schedule"].get("next_run_at")}


def mask_secrets(doc: dict) -> dict:
    doc = copy.deepcopy(doc)
    executor = doc.get("executor") or {}
    if executor.get("type") == "sql" and executor.get("connection_uri"):
        executor["connection_uri"] = MASKED_SECRET
    kerberos = executor.get("kerberos") or {}
    if kerberos.get("keytab"):
        kerberos["keytab"] = MASKED_SECRET
    return doc


def merge_update(existing: dict, patch: dict) -> dict:
    """Validate ``existing`` shallow-merged with ``patch``; return the new full doc."""
    merged = {**{k: v for k, v in existing.items() if k not in ("_id", "created_at", "updated_at", "enabled")}, **patch}
    return build_job(merged, preserve_schedule=None if "schedule" in patch else existing.get("schedule"))


def with_schedule_enabled(doc: dict, enabled: bool, now: Optional[datetime] = None) -> dict:
    schedule = {**(doc.get("schedule") or {}), "enabled": enabled}
    if enabled:
        schedule["next_run_at"] = None
    payload = {k: v for k, v in doc.items() if k not in ("_id", "created_at", "updated_at", "enabled")}
    payload["schedule"] = schedule
    return build_job(payload, now)


def to_api(doc: dict[str, Any]) -> dict[str, Any]:
    return mask_secrets(doc)

import os
from typing import Dict, Tuple


def _contains_all(text: str, needles: list) -> Tuple[bool, str]:
    for token in needles:
        if token not in text:
            return False, f"missing '{token}'"
    return True, "ok"


def _contains_none(text: str, needles: list) -> Tuple[bool, str]:
    for token in needles:
        if token and token in text:
            return False, f"found forbidden '{token}'"
    return True, "ok"


def evaluate_completion(job: Dict, rc: int, stdout: str, stderr: str) -> Tuple[bool, str]:
    criteria = job.get("completion") or {}
    exit_codes = criteria.get("exit_codes") or [0]
    stdout_contains = criteria.get("stdout_contains") or []
    stdout_not_contains = criteria.get("stdout_not_contains") or []
    stderr_contains = criteria.get("stderr_contains") or []
    stderr_not_contains = criteria.get("stderr_not_contains") or []

    if exit_codes and rc not in exit_codes:
        return False, f"exit code {rc} not in {exit_codes}"

    success, reason = _contains_all(stdout, stdout_contains)
    if not success:
        return False, f"stdout {reason}"

    success, reason = _contains_none(stdout, stdout_not_contains)
    if not success:
        return False, f"stdout {reason}"

    success, reason = _contains_all(stderr, stderr_contains)
    if not success:
        return False, f"stderr {reason}"

    success, reason = _contains_none(stderr, stderr_not_contains)
    if not success:
        return False, f"stderr {reason}"

    return True, "criteria satisfied"


def evaluate_file_criteria(job: Dict, run_start_time: float) -> Tuple[bool, str]:
    """Check file-based completion criteria after job execution.

    Args:
        job: The job definition dict.
        run_start_time: The job's actual start time as a UTC Unix timestamp (float).

    Returns:
        (success, reason) tuple. success is False if any file check fails.
    """
    criteria = job.get("completion") or {}
    require_exists = criteria.get("require_file_exists") or []
    require_updated = criteria.get("require_file_updated_since_start") or []

    for path in require_exists:
        if not os.path.exists(path):
            return False, f"required file does not exist: {path}"

    for path in require_updated:
        try:
            stat = os.stat(path)
        except OSError:
            return False, f"required file does not exist: {path}"
        if stat.st_mtime < run_start_time:
            return False, f"required file was not updated since job start: {path}"

    return True, "file criteria satisfied"

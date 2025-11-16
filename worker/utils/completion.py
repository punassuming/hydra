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

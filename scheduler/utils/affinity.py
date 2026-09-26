from typing import Dict, List


def user_allowed(job_user: str, allowed_users: List[str]) -> bool:
    return not allowed_users or job_user in allowed_users


def os_matches(job_oses: List[str], worker_os: str) -> bool:
    return not job_oses or worker_os.lower() in {o.lower() for o in job_oses}


def tags_match(job_tags: List[str], worker_tags: List[str]) -> bool:
    # All job tags must be present in worker tags
    if not job_tags:
        return True
    worker_set = {t.lower() for t in worker_tags}
    return all(t.lower() in worker_set for t in job_tags)


def hostnames_match(job_hosts: List[str], worker_host: str) -> bool:
    return not job_hosts or worker_host.lower() in {h.lower() for h in job_hosts}


def subnets_match(job_subnets: List[str], worker_subnet: str) -> bool:
    return not job_subnets or worker_subnet in job_subnets


def deployment_matches(job_types: List[str], worker_type: str) -> bool:
    return not job_types or worker_type.lower() in {t.lower() for t in job_types}


def executor_types_match(job_exec_types: List[str], worker_capabilities: List[str]) -> bool:
    if not job_exec_types:
        return True
    worker_set = {c.lower() for c in worker_capabilities}
    return all(t.lower() in worker_set for t in job_exec_types)


def normalize_affinity(job: Dict) -> Dict:
    """Ensure affinity.executor_types is populated from the job's executor type.

    This allows jobs to omit executor_types in their affinity and still get
    correct capability-based worker matching at dispatch time.
    """
    executor = job.get("executor") or {}
    executor_type = executor.get("type", "")
    if not executor_type:
        return job
    affinity = job.get("affinity") or {}
    if not affinity.get("executor_types"):
        executor_types = [executor_type]
        # A SQL-flavored sensor needs a worker with real SQL runtime deps
        # (sqlalchemy importable), not just any worker that can run sensors
        # at all (the HTTP sensor path needs nothing beyond stdlib) — require
        # both capabilities so dispatch doesn't land on a worker that would
        # fail the poll at runtime.
        if executor_type == "sensor" and executor.get("sensor_type") == "sql":
            executor_types.append("sql")
        return {**job, "affinity": {**affinity, "executor_types": executor_types}}
    return job


def passes_affinity(job: Dict, worker: Dict) -> bool:
    affinity = job.get("affinity", {})
    executor = job.get("executor", {})
    # If job requires impersonation, only allow Linux/macOS workers
    if executor.get("impersonate_user"):
        worker_os = worker.get("os", "").lower()
        if worker_os not in ("linux", "darwin"):
            return False
    return (
        os_matches(affinity.get("os", []), worker.get("os", ""))
        and tags_match(affinity.get("tags", []), worker.get("tags", []))
        and user_allowed(job.get("user", ""), worker.get("allowed_users", []))
        and hostnames_match(affinity.get("hostnames", []), worker.get("hostname", ""))
        and subnets_match(affinity.get("subnets", []), worker.get("subnet", ""))
        and deployment_matches(affinity.get("deployment_types", []), worker.get("deployment_type", ""))
        and executor_types_match(affinity.get("executor_types", []), worker.get("capabilities", []))
    )

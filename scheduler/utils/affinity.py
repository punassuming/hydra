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


def passes_affinity(job: Dict, worker: Dict) -> bool:
    affinity = job.get("affinity", {})
    return (
        os_matches(affinity.get("os", []), worker.get("os", ""))
        and tags_match(affinity.get("tags", []), worker.get("tags", []))
        and user_allowed(job.get("user", ""), worker.get("allowed_users", []))
    )


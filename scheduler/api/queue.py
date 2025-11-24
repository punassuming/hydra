from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter

from ..redis_client import get_redis
from ..mongo_client import get_db
from ..models.job_definition import JobDefinition, ScheduleConfig

router = APIRouter()


@router.get("/queue/overview")
def queue_overview() -> Dict[str, Any]:
    r = get_redis()
    db = get_db()

    pending_entries = r.zrevrange("job_queue:pending", 0, 99, withscores=True)
    jobs_by_id = {
        doc["_id"]: JobDefinition.model_validate(doc)
        for doc in db.job_definitions.find({"_id": {"$in": [jid for jid, _ in pending_entries]}})
    }
    pending = []
    for job_id, score in pending_entries:
        job = jobs_by_id.get(job_id)
        pending.append(
            {
                "job_id": job_id,
                "priority": score,
                "name": job.name if job else job_id,
                "queue": job.queue if job else "default",
                "user": job.user if job else "",
            }
        )

    now = datetime.utcnow()
    upcoming_cursor = db.job_definitions.find(
        {
            "schedule.enabled": True,
            "schedule.next_run_at": {"$gt": now},
        }
    ).sort("schedule.next_run_at", 1).limit(50)
    upcoming = []
    for doc in upcoming_cursor:
        job = JobDefinition.model_validate(doc)
        next_run = job.schedule.next_run_at.isoformat() if job.schedule.next_run_at else None
        upcoming.append(
            {
                "job_id": job.id,
                "name": job.name,
                "queue": job.queue,
                "priority": job.priority,
                "next_run_at": next_run,
            }
        )

    return {"pending": pending, "upcoming": upcoming}

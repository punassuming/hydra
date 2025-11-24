import asyncio
import json
from typing import Dict, Optional
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..redis_client import get_redis
from ..mongo_client import get_db
from ..models.job_run import JobRun

router = APIRouter()


def _find_run(db, run_id: str) -> Optional[Dict]:
    doc = db.job_runs.find_one({"_id": run_id})
    if doc:
        return doc
    try:
        oid = ObjectId(run_id)
        return db.job_runs.find_one({"_id": oid})
    except Exception:
        return None


@router.get("/runs/{run_id}/stream")
async def stream_run_logs(run_id: str, request: Request):
    r = get_redis()
    db = get_db()
    req_domain = getattr(request.state, "domain", None)
    is_admin = getattr(request.state, "is_admin", False)
    run_doc = _find_run(db, run_id)
    run_domain = (run_doc or {}).get("domain", None)
    if not is_admin and req_domain and run_domain and req_domain != run_domain:
        raise HTTPException(status_code=403, detail="forbidden")
    domain = run_domain or req_domain or "prod"

    history_key = f"log_stream:{domain}:{run_id}:history"
    channel = f"log_stream:{domain}:{run_id}"
    pubsub = r.pubsub()
    pubsub.subscribe(channel)

    async def event_generator():
        loop = asyncio.get_running_loop()
        try:
            # replay cached history
            history = r.lrange(history_key, -200, -1) or []
            for raw in history:
                yield {"event": "log_chunk", "data": raw}

            # live stream
            while True:
                message = await loop.run_in_executor(None, pubsub.get_message, True, 2.0)
                if not message or message.get("type") != "message":
                    continue
                data = message.get("data")
                if not data:
                    continue
                yield {"event": "log_chunk", "data": data}
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:
                pass

    return EventSourceResponse(event_generator())


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> Dict:
    db = get_db()
    doc = db.job_runs.find_one({"_id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail="run not found")
    return JobRun.model_validate(doc).model_dump()

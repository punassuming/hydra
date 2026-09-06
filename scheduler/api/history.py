import base64
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from ..mongo_client import get_db

router = APIRouter(prefix="/history", tags=["history"])


def _encode_cursor(start_ts, run_id) -> str:
    payload = json.dumps({"start_ts": start_ts.isoformat(), "run_id": str(run_id)}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["start_ts"]), str(payload["run_id"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid history cursor") from exc


@router.get("/")
def list_history(request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    if is_admin and force_domain:
        query = {"domain": force_domain}
    elif is_admin:
        query = {}
    else:
        query = {"domain": domain}
    # Keep the legacy unbounded response for API consumers that have not opted in.
    # The UI always requests the bounded, cursor-based form below.
    paged = request.query_params.get("paged", "false").lower() == "true"
    if not paged:
        items = []
        for doc in db.job_runs.find(query).sort("start_ts", -1):
            doc["_id"] = str(doc["_id"])
            items.append(doc)
        return items

    try:
        limit = max(1, min(int(request.query_params.get("limit", "50")), 200))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit must be an integer") from exc
    cursor = request.query_params.get("cursor")
    if cursor:
        start_ts, run_id = _decode_cursor(cursor)
        query = {
            "$and": [
                query,
                {"$or": [{"start_ts": {"$lt": start_ts}}, {"start_ts": start_ts, "_id": {"$lt": run_id}}]},
            ]
        }

    docs = list(db.job_runs.find(query).sort([("start_ts", -1), ("_id", -1)]).limit(limit + 1))
    has_more = len(docs) > limit
    docs = docs[:limit]
    items = []
    for doc in docs:
        doc["_id"] = str(doc["_id"])
        items.append(doc)
    next_cursor = _encode_cursor(docs[-1]["start_ts"], docs[-1]["_id"]) if has_more and docs else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

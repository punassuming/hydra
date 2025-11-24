from fastapi import APIRouter, Request

from ..mongo_client import get_db


router = APIRouter(prefix="/history", tags=["history"])


@router.get("/")
def list_history(request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    query = {} if is_admin else {"domain": domain}
    items = []
    for doc in db.job_runs.find(query).sort("start_ts", -1):
        doc["_id"] = str(doc["_id"])
        items.append(doc)
    return items

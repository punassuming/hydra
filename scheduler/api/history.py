from fastapi import APIRouter, Request

from ..mongo_client import get_db

router = APIRouter(prefix="/history", tags=["history"])


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
    items = []
    for doc in db.job_runs.find(query).sort("start_ts", -1):
        doc["_id"] = str(doc["_id"])
        items.append(doc)
    return items

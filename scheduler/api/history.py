from fastapi import APIRouter

from ..mongo_client import get_db


router = APIRouter(prefix="/history", tags=["history"])


@router.get("/")
def list_history():
    db = get_db()
    items = []
    for doc in db.job_runs.find({}).sort("start_ts", -1):
        doc["_id"] = str(doc["_id"])
        items.append(doc)
    return items

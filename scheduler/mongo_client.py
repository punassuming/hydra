import os
from typing import Any

from pymongo import MongoClient

_mongo_client: MongoClient | None = None


def get_mongo_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        # pymongo defaults to a 30s server selection timeout; on a real outage that
        # ties up a request thread for 30s per call (including /health pings). Fail
        # fast instead so healthchecks and normal requests both surface the outage quickly.
        timeout_ms = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))
        # BSON datetimes carry no timezone; pymongo returns them naive by default,
        # which crashes any arithmetic against the tz-aware datetimes used elsewhere
        # (e.g. datetime.now(timezone.utc)). tz_aware=True makes every datetime read
        # back from Mongo UTC-aware instead.
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=timeout_ms, tz_aware=True)
    return _mongo_client


def get_db() -> Any:
    db_name = os.getenv("MONGO_DB", "hydra_jobs")
    return get_mongo_client()[db_name]

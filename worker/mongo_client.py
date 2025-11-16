import os
from pymongo import MongoClient


_mongo_client: MongoClient | None = None


def get_mongo_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        _mongo_client = MongoClient(url)
    return _mongo_client


def get_db():
    db_name = os.getenv("MONGO_DB", "hydra_jobs")
    return get_mongo_client()[db_name]


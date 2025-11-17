import os
from pymongo import MongoClient


_mongo_client: MongoClient | None = None


def get_mongo_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        default_url = "mongodb://mongo:27017"
        if os.getenv("DOCKER_ENV") is None and os.getenv("MONGO_URL") is None:
            default_url = "mongodb://localhost:27017"
        url = os.getenv("MONGO_URL", default_url)
        _mongo_client = MongoClient(url)
    return _mongo_client


def get_db():
    db_name = os.getenv("MONGO_DB", "hydra_jobs")
    return get_mongo_client()[db_name]

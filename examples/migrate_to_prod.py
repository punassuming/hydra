"""
One-time helper to tag existing documents with domain='prod'.

Usage:
  MONGO_URL=mongodb://localhost:27017 MONGO_DB=hydra_jobs python examples/migrate_to_prod.py
"""

import os
from pymongo import MongoClient

mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
mongo_db = os.getenv("MONGO_DB", "hydra_jobs")

client = MongoClient(mongo_url)
db = client[mongo_db]

res1 = db.job_definitions.update_many({"domain": {"$exists": False}}, {"$set": {"domain": "prod"}})
res2 = db.job_runs.update_many({"domain": {"$exists": False}}, {"$set": {"domain": "prod"}})

print(f"Updated jobs: {res1.modified_count}, runs: {res2.modified_count}")

"""
Seed dev jobs into the dev domain using a token provided via API_TOKEN.

Usage (dev compose):
  API_BASE=http://scheduler:8000 API_TOKEN=<dev-token> python deploy/seed-dev.py
"""

import os
from examples.seed_test_jobs import main as seed_jobs

if __name__ == "__main__":
  if not os.getenv("API_TOKEN"):
    print("API_TOKEN not set; skipping dev seed")
  else:
    seed_jobs()

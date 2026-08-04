"""Regression test for the Mongo client's timezone handling.

BSON datetimes carry no timezone; pymongo decodes them as naive by default.
Scheduler code compares those values against timezone-aware datetimes
(datetime.now(timezone.utc)), which raises TypeError unless the client is
configured with tz_aware=True. See scheduler/run_events.py::_handle_run_end
and scheduler/scheduler.py::sla_monitoring_loop.
"""

from unittest.mock import patch

import scheduler.mongo_client as mongo_client


def test_get_mongo_client_is_tz_aware():
    mongo_client._mongo_client = None
    try:
        with patch("scheduler.mongo_client.MongoClient") as mock_ctor:
            mongo_client.get_mongo_client()
            _, kwargs = mock_ctor.call_args
            assert kwargs.get("tz_aware") is True
    finally:
        mongo_client._mongo_client = None

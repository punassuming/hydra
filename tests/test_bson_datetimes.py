"""pymongo's BSON layer must hand back timezone-aware datetimes.

The scheduler constructs MongoClient with tz_aware=True because naive datetimes
crash arithmetic against datetime.now(timezone.utc). tests/test_mongo_client.py
checks the constructor argument; this checks the real BSON codec honours it, so
a pymongo upgrade that changed decoding would be caught without a server.
"""

from datetime import datetime, timezone

import bson
from bson.codec_options import CodecOptions


def test_tz_aware_codec_returns_aware_utc_datetimes():
    stored = bson.encode({"ts": datetime(2026, 3, 15, 10, 2, 30, 123000, tzinfo=timezone.utc)})
    aware = bson.decode(stored, codec_options=CodecOptions(tz_aware=True))["ts"]
    assert aware == datetime(2026, 3, 15, 10, 2, 30, 123000, tzinfo=timezone.utc)
    assert aware.tzinfo is not None
    assert (aware - datetime(2026, 3, 15, tzinfo=timezone.utc)).total_seconds() > 0  # arithmetic works


def test_default_codec_returns_naive_datetimes_which_is_why_tz_aware_is_required():
    stored = bson.encode({"ts": datetime(2026, 3, 15, tzinfo=timezone.utc)})
    assert bson.decode(stored)["ts"].tzinfo is None


def test_the_scheduler_mongo_client_is_built_with_tz_aware_codec_options():
    from scheduler import mongo_client

    source = open(mongo_client.__file__, encoding="utf-8").read()
    assert "tz_aware=True" in source

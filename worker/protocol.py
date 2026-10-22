"""Worker protocol version, importable without Redis.

Identifies the registration/heartbeat/dispatch protocol every worker flavor speaks (Python, Go, and the lite
edition's HTTP worker), so version skew is visible at a glance on the workers list. Informational only.

The scheduler image does not ship the worker package, so scheduler/api/workers.py keeps its own copy
(EXPECTED_WORKER_PROTOCOL_VERSION); tests/test_worker_protocol_mismatch.py pins the two together, and the Go
worker documents the same value. Bump all of them in one change.
"""

WORKER_PROTOCOL_VERSION = "1.0"

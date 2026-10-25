"""Entry point for ``python -m worker``.

Supports two runtime modes:

1. **Worker mode** (default): runs the Hydra worker process.

   .. code-block:: sh

       python -m worker

2. **Bootstrap mode**: manages the Windows Task Scheduler watchdog task.

   .. code-block:: sh

       python -m worker bootstrap install
       python -m worker bootstrap remove
       python -m worker bootstrap run
       python -m worker bootstrap validate

"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse


def _url_has_credentials(url: str) -> bool:
    """Return True if *url* contains both a username and a password component."""
    try:
        parsed = urlparse(url)
        return bool(parsed.username and parsed.password)
    except Exception:
        return False


def _preflight_check() -> None:
    """Verify Redis connectivity and required env vars before starting the worker loop.

    Exits with a clear, actionable message rather than a raw traceback so that
    new users can quickly identify misconfiguration.
    """
    # Validate required env vars first so the error message is specific.
    api_token = (os.getenv("API_TOKEN") or "").strip()
    if not api_token:
        print("[hydra] ERROR: API_TOKEN is not set.", file=sys.stderr)
        print("[hydra]   Set API_TOKEN to the domain token for your Hydra domain.", file=sys.stderr)
        print("[hydra]   Obtain it from the Admin panel or POST /admin/domains/<domain>/token", file=sys.stderr)
        sys.exit(1)

    require_acl = (os.getenv("WORKER_REQUIRE_REDIS_ACL", "true") or "true").strip().lower()
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    if require_acl not in ("0", "false", "no", "off"):
        redis_password = (os.getenv("REDIS_PASSWORD") or "").strip()
        # Credentials can be supplied as REDIS_PASSWORD (with DOMAIN as username)
        # OR embedded directly in REDIS_URL — both are valid; mirror redis_client.py.
        if not redis_password and not _url_has_credentials(redis_url):
            print("[hydra] ERROR: REDIS_PASSWORD is not set (WORKER_REQUIRE_REDIS_ACL=true).", file=sys.stderr)
            print("[hydra]   Option A: set REDIS_PASSWORD (and DOMAIN) for ACL authentication.", file=sys.stderr)
            print("[hydra]   Option B: embed credentials in REDIS_URL (redis://user:pass@host:port/db).", file=sys.stderr)
            print("[hydra]   Option C: set WORKER_REQUIRE_REDIS_ACL=false to skip ACL enforcement.", file=sys.stderr)
            print("[hydra]   Rotate ACL credentials via POST /admin/domains/<domain>/redis_acl/rotate", file=sys.stderr)
            sys.exit(1)

    # Attempt a Redis ping to catch connection/auth issues with a clear message.
    try:
        from .redis_client import get_redis

        r = get_redis()
        r.ping()
    except Exception as exc:
        print(f"[hydra] ERROR: Cannot connect to Redis: {exc}", file=sys.stderr)
        print(f"[hydra]   REDIS_URL={redis_url}", file=sys.stderr)
        if require_acl not in ("0", "false", "no", "off"):
            domain = (os.getenv("DOMAIN") or "prod").strip()
            print(f"[hydra]   Authenticating as ACL user '{domain}' — verify REDIS_PASSWORD is correct.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    # Detect "bootstrap" sub-mode: the first positional argument (after any
    # flags) is the word "bootstrap".
    if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
        from .bootstrap import main as bootstrap_main

        sys.exit(bootstrap_main(sys.argv[2:]))
    else:
        # Run pre-flight checks before entering the worker loop.
        _preflight_check()
        from .worker import worker_main

        worker_main()


if __name__ == "__main__":
    main()

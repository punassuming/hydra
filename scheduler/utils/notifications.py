"""Failure/SLA webhook delivery shared by the full and lite editions."""

import json
import logging
import threading
import urllib.request

log = logging.getLogger("scheduler.notifications")

# Maximum length of error_message sent in webhook payloads
WEBHOOK_MAX_ERROR_LEN = 2000


def fire_webhooks(webhooks: list, job_id: str, run_id: str, error_message: str):
    """Fire HTTP POST to each webhook URL with failure details."""
    payload = json.dumps(
        {
            "job_id": job_id,
            "run_id": run_id,
            "error_message": error_message,
        }
    ).encode()
    for url in webhooks:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            log.warning("Webhook POST failed for %s: %s", url, exc)


def fire_webhooks_async(webhooks: list, job_id: str, run_id: str, error_message: str):
    if not webhooks:
        return
    t = threading.Thread(target=fire_webhooks, args=(webhooks, job_id, run_id, error_message), daemon=True)
    t.start()

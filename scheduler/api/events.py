import asyncio
import json
import queue

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..event_bus import event_bus

router = APIRouter()

# How long a worker thread waits on the subscriber queue before checking back
# in. A blocking get() with no timeout can never be woken once the client
# disconnects (unsubscribe just drops the queue), so every closed browser tab
# would leak a thread until process exit.
_POLL_SECONDS = 2.0


def _next_event(q: "queue.Queue"):
    try:
        return q.get(timeout=_POLL_SECONDS)
    except queue.Empty:
        return None


@router.get("/events/stream")
async def event_stream(request: Request):
    identifier, q = event_bus.subscribe()
    req_domain = getattr(request.state, "domain", None)
    is_admin = getattr(request.state, "is_admin", False)

    async def event_generator():
        loop = asyncio.get_running_loop()
        try:
            while True:
                event = await loop.run_in_executor(None, _next_event, q)
                if event is None:
                    continue
                ev_domain = (event.get("payload") or {}).get("domain") if isinstance(event, dict) else None
                if req_domain and not is_admin and ev_domain and ev_domain != req_domain:
                    continue
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event),
                }
        finally:
            event_bus.unsubscribe(identifier)

    return EventSourceResponse(event_generator())

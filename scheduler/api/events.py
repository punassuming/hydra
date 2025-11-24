import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from ..event_bus import event_bus


router = APIRouter()


@router.get("/events/stream")
async def event_stream(request):
    identifier, q = event_bus.subscribe()
    req_domain = getattr(request.state, "domain", None)
    is_admin = getattr(request.state, "is_admin", False)

    async def event_generator():
        loop = asyncio.get_running_loop()
        try:
            while True:
                event = await loop.run_in_executor(None, q.get)
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

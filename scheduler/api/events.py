import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from ..event_bus import event_bus


router = APIRouter()


@router.get("/events/stream")
async def event_stream():
    identifier, q = event_bus.subscribe()

    async def event_generator():
        loop = asyncio.get_running_loop()
        try:
            while True:
                event = await loop.run_in_executor(None, q.get)
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event),
                }
        finally:
            event_bus.unsubscribe(identifier)

    return EventSourceResponse(event_generator())

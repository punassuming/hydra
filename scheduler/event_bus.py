import queue
import threading
import time
from typing import Dict, List, Tuple


class SchedulerEventBus:
    def __init__(self):
        self._subscribers: Dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def subscribe(self) -> Tuple[str, queue.Queue]:
        identifier = f"sub-{time.time_ns()}"
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers[identifier] = q
        return identifier, q

    def unsubscribe(self, identifier: str):
        with self._lock:
            self._subscribers.pop(identifier, None)

    def publish(self, event_type: str, payload: Dict):
        event = {
            "type": event_type,
            "payload": payload,
            "ts": time.time(),
        }
        with self._lock:
            queues = list(self._subscribers.values())
        for q in queues:
            try:
                q.put_nowait(event)
            except queue.Full:
                # drop events for slow consumers
                continue


event_bus = SchedulerEventBus()

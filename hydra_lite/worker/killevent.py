import threading
from typing import Optional


class KillEvent(threading.Event):
    """A kill signal that remembers why it was sent ("request", "timeout", "orphaned", "shutdown")."""

    reason: Optional[str] = None

import asyncio
import threading
from collections import defaultdict


class DeviceEventHub:
    """In-process fan-out for authenticated SSE streams in the single app process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue, bool]]] = defaultdict(set)

    def subscribe(self, project_id: int, *, connection_only: bool = False) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue, bool]:
        subscriber = (asyncio.get_running_loop(), asyncio.Queue(maxsize=100), connection_only)
        with self._lock:
            self._subscribers[project_id].add(subscriber)
        return subscriber

    def unsubscribe(self, project_id: int, subscriber: tuple[asyncio.AbstractEventLoop, asyncio.Queue, bool]) -> None:
        with self._lock:
            self._subscribers[project_id].discard(subscriber)
            if not self._subscribers[project_id]:
                self._subscribers.pop(project_id, None)

    def publish(self, project_id: int, event: dict, *, heartbeat: bool = False) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(project_id, ()))
        for loop, queue, connection_only in subscribers:
            if heartbeat and connection_only:
                continue
            if not loop.is_closed():
                loop.call_soon_threadsafe(self._enqueue_latest, queue, event)

    @staticmethod
    def _enqueue_latest(queue: asyncio.Queue, event: dict) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


device_event_hub = DeviceEventHub()

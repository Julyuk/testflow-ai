"""
In-process event bus for WebSocket broadcasting.

Any module can call broadcast() to push events to all WebSocket
clients connected to a given session. Imported by pipeline routes
and orchestrator nodes.

Thread-safety: _run_pipeline runs in a threadpool worker. broadcast()
uses call_soon_threadsafe() so asyncio.Queue.put_nowait() always runs
on the event loop thread, not the caller's thread.
"""

import asyncio
import threading
from typing import Any

# session_id → list of asyncio.Queue (one per connected WS client)
_queues: dict[str, list[asyncio.Queue]] = {}
_main_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once at app startup with the running event loop."""
    global _main_loop
    with _loop_lock:
        _main_loop = loop


def broadcast(session_id: str, event: dict[str, Any]) -> None:
    """Push event to all WebSocket listeners for this session.

    Safe to call from any thread — schedules the actual put on the
    event loop thread via call_soon_threadsafe.
    """
    queues = list(_queues.get(session_id, []))
    if not queues:
        return

    def _put_all() -> None:
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    with _loop_lock:
        loop = _main_loop

    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(_put_all)
    else:
        # Startup / test context — no live event loop yet; best-effort direct put.
        _put_all()


def log_activity(session_id: str, agent: str, message: str, level: str = "info") -> None:
    """Convenience wrapper — broadcast an activity_log event."""
    broadcast(session_id, {
        "type": "activity_log",
        "agent": agent,
        "message": message,
        "level": level,   # info | success | warning | error
    })


def register_queue(session_id: str, q: asyncio.Queue) -> None:
    _queues.setdefault(session_id, []).append(q)


def unregister_queue(session_id: str, q: asyncio.Queue) -> None:
    queues = _queues.get(session_id, [])
    if q in queues:
        queues.remove(q)
    # Remove empty list to prevent memory accumulation
    if not queues and session_id in _queues:
        del _queues[session_id]

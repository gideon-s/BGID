"""In-memory per-account rate limiting for LLM `talk` (DeepSeek costs money).

Single-process only (the app runs one uvicorn worker — WorldState and these
counters live in-process), so a plain dict of timestamps is authoritative; no
Redis needed. If BGID ever scales to multiple workers this moves to Redis,
same as the `broadcast_to_room` seam.

Two sliding windows are enforced together (a burst cap and a sustained cap),
keyed by the owning account so spinning up extra characters can't multiply the
budget. Limits come from config and are read per-check so they can be tuned via
env (and monkeypatched in tests).
"""
import threading
import time
from collections import defaultdict, deque

import config


class _SlidingWindows:
    """Tracks hit timestamps per key across several (limit, window) pairs and
    allows a hit only when *every* window has room. Thread-safe (sync endpoints
    run in a threadpool; the WS handler runs on the loop thread)."""

    def __init__(self):
        self._hits: dict = defaultdict(list)  # key -> list[deque], one per window
        self._lock = threading.Lock()

    def check(self, key, windows) -> tuple[bool, float]:
        """windows: list of (limit, window_seconds). Returns (allowed,
        retry_after_seconds). Records a hit on all windows iff allowed."""
        now = time.monotonic()
        with self._lock:
            buckets = self._hits[key]
            if len(buckets) != len(windows):
                buckets = [deque() for _ in windows]
                self._hits[key] = buckets

            allowed, retry = True, 0.0
            for (limit, window), dq in zip(windows, buckets):
                cutoff = now - window
                while dq and dq[0] <= cutoff:
                    dq.popleft()
                if len(dq) >= limit:
                    allowed = False
                    retry = max(retry, (window - (now - dq[0])) if dq else float(window))

            if allowed:
                for dq in buckets:
                    dq.append(now)
            return allowed, max(0.0, retry)

    def reset(self):
        with self._lock:
            self._hits.clear()


_talk = _SlidingWindows()
_mob_chatter = _SlidingWindows()


def check_talk(user_id: int) -> tuple[bool, float]:
    """Rate-limit an account's LLM NPC conversation. Returns (allowed,
    retry_after_seconds). Shared across the WS `talk` and REST `/chat/npc`
    paths so they draw from one budget."""
    windows = [
        (config.TALK_RATE_PER_MIN, 60),
        (config.TALK_RATE_PER_HOUR, 3600),
    ]
    return _talk.check(("talk", user_id), windows)


def check_mob_chatter(room_id: int) -> tuple[bool, float]:
    """Global budget for mob smack-talk LLM lines, keyed per room. Distinct from
    the player-`talk` budget — this cost is mob-initiated. Returns (allowed,
    retry_after_seconds); over budget, callers fall back to canned barbs."""
    windows = [(config.MOB_CHATTER_RATE_PER_MIN, 60)]
    return _mob_chatter.check(("mob_chatter", room_id), windows)


def reset():
    """Clear all counters (used by the test harness between tests)."""
    _talk.reset()
    _mob_chatter.reset()

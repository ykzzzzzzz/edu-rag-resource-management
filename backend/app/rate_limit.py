"""进程内的滑动窗口频率限制。重启后清零，只适用于单进程部署。"""

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 10_000:
                # 清掉已经没有近期记录的用户，避免字典无限增长
                for stale in [k for k, v in self._events.items() if not v or now - v[-1] >= self.window]:
                    del self._events[stale]
            return True

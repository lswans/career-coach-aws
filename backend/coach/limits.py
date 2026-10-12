"""Per-user daily caps for the hosted coach, so a shared link can't run up a Bedrock bill.

Counts live in memory and reset at midnight UTC or when the service restarts, which is enough
for a workshop-sized stack with one instance.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timezone


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


class DailyLimits:
    def __init__(self, caps: dict[str, int], today: Callable[[], date] = utc_today) -> None:
        self.caps, self._today = caps, today
        self._lock = threading.Lock()
        self._day = today()
        self._used: dict[tuple[str, str], int] = {}

    def take(self, kind: str, user_id: str) -> bool:
        """Count one use; False when the user is already at today's cap (nothing is counted then)."""
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._used = day, {}
            key = (kind, user_id)
            if self._used.get(key, 0) >= self.caps[kind]:
                return False
            self._used[key] = self._used.get(key, 0) + 1
            return True

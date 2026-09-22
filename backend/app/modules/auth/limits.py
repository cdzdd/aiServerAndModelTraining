"""Single-process, bounded fixed-window login limits. Restart resets counters."""

from dataclasses import dataclass
from threading import Lock
from time import monotonic

from app.core.security import AuthError


@dataclass
class Window:
    expires: float
    attempts: int = 0
    failures: int = 0
    pending: int = 0


class LoginLimiter:
    def __init__(
        self, account_limit=5, ip_limit=30, window_seconds=300, max_entries=10000, clock=monotonic
    ):
        self.account_limit = account_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._windows = {}
        self._lock = Lock()
        self._cleanup_at = 0.0

    def reserve(self, ip: str, username: str) -> Window:
        with self._lock:
            now = self.clock()
            if now >= self._cleanup_at or len(self._windows) >= self.max_entries:
                self._windows = {k: v for k, v in self._windows.items() if v.expires > now}
                self._cleanup_at = now + self.window_seconds
            keys = [("ip", ip), ("account", ip, username)]
            for key in keys:
                if key in self._windows and self._windows[key].expires <= now:
                    del self._windows[key]
            source = self._windows.get(keys[0])
            if source is not None and source.attempts >= self.ip_limit:
                self._reject()
            missing = sum(key not in self._windows for key in keys)
            if len(self._windows) + missing > self.max_entries:
                self._reject()
            for key in keys:
                self._windows.setdefault(key, Window(now + self.window_seconds))
            source, account = (self._windows[key] for key in keys)
            source.attempts += 1
            # Pending attempts reserve failure capacity so parallel requests cannot skip the limit.
            if account.failures + account.pending >= self.account_limit:
                self._reject()
            account.pending += 1
            return account

    def finish(self, reservation: Window, *, failed: bool):
        with self._lock:
            reservation.pending -= 1
            reservation.failures += int(failed)

    @staticmethod
    def _reject():
        raise AuthError(429, "RATE_LIMITED", "登录尝试过于频繁，请稍后再试")

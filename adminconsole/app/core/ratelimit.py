"""In-memory sliding-window rate limiter for sensitive actions (password
reset, LAPS reveal — spec: "Rate-limit sensitive actions... per
user/session"). In-memory is a deliberate simplification: this app runs as
a single container with no horizontal scaling planned, so there's no
multi-instance state-sharing problem to solve with Redis. Resets on
container restart, which is acceptable for an abuse-slowdown control, not a
hard security boundary (the audit log + alerting are the hard controls).
"""

import time
from collections import defaultdict

_hits: dict[str, list[float]] = defaultdict(list)


def check(key: str, *, max_calls: int, window_seconds: int) -> bool:
    """Returns True if the call is allowed (and records it); False if the
    caller is currently over the limit (does NOT record a blocked attempt,
    so a burst of blocked retries doesn't itself extend the window)."""
    now = time.monotonic()
    cutoff = now - window_seconds
    hits = [t for t in _hits[key] if t > cutoff]
    if len(hits) >= max_calls:
        _hits[key] = hits
        return False
    hits.append(now)
    _hits[key] = hits
    return True

"""One lock per calendar account, shared by the sync worker and the events API.

A sync fetches from the server, then reconciles the local cache against what
it fetched. Anything written locally in between would be judged against that
stale copy: a new event looks "removed upstream" and is deleted, an edit is
reverted, a deleted event comes back (tests/test_sync_race.py). So a sync
holds its account's lock from fetch through reconcile, and an API write holds
it from the server call through the local commit; the two never interleave.
"""

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

_guard = threading.Lock()
_locks: dict[int, threading.Lock] = {}


class AccountBusy(RuntimeError):
    pass


def _lock_for(account_id: int) -> threading.Lock:
    with _guard:
        return _locks.setdefault(account_id, threading.Lock())


@contextmanager
def account_lock(account_id: int, timeout: Optional[float] = None) -> Iterator[None]:
    """Hold the account's lock. With a timeout, raises AccountBusy instead of
    waiting longer (the CalDAV client's own timeout bounds how long a sync can
    hold it, but a request shouldn't hang on that)."""
    lock = _lock_for(account_id)
    if not lock.acquire(timeout=-1 if timeout is None else timeout):
        raise AccountBusy(f"Calendar account {account_id} is busy syncing")
    try:
        yield
    finally:
        lock.release()

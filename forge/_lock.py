from __future__ import annotations
from typing import IO

try:
    import fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _FCNTL_AVAILABLE = False


def flock_exclusive(stream: IO) -> None:
    if _FCNTL_AVAILABLE:
        fcntl.flock(stream, fcntl.LOCK_EX)


def flock_shared(stream: IO) -> None:
    if _FCNTL_AVAILABLE:
        fcntl.flock(stream, fcntl.LOCK_SH)

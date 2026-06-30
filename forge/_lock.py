from __future__ import annotations
import warnings
from typing import IO

try:
    import portalocker
except ImportError:
    portalocker = None  # type: ignore[assignment]

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

_degraded_warned = False


def _degraded_noop() -> None:
    global _degraded_warned
    if not _degraded_warned:
        warnings.warn(
            "Forge file locking degraded (no portalocker/fcntl); "
            "cross-process safety unavailable.",
            stacklevel=3,
        )
        _degraded_warned = True


def flock_exclusive(stream: IO) -> None:
    if portalocker is not None:
        portalocker.lock(stream, portalocker.LOCK_EX)
    elif fcntl is not None:
        fcntl.flock(stream, fcntl.LOCK_EX)
    else:
        _degraded_noop()


def flock_shared(stream: IO) -> None:
    if portalocker is not None:
        try:
            portalocker.lock(stream, portalocker.LOCK_SH)
        except (NotImplementedError, ValueError, OSError):
            portalocker.lock(stream, portalocker.LOCK_EX)
    elif fcntl is not None:
        fcntl.flock(stream, fcntl.LOCK_SH)
    else:
        _degraded_noop()

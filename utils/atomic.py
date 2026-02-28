"""Atomic file write with fcntl file locking."""

import fcntl
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str, lock_path: Path, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically using a lock file.

    Acquires an exclusive ``fcntl.flock`` on *lock_path*, writes to a
    temporary file in the same directory, then ``os.replace``s onto the
    target.  The lock is released in a ``finally`` block regardless of
    outcome.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lf = open(lock_path, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tmp", dir=str(path.parent),
            delete=False, encoding=encoding,
        ) as f:
            f.write(content)
            tmp = f.name
        os.replace(tmp, str(path))
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()


def locked_read(path: Path, lock_path: Path, *, encoding: str = "utf-8") -> str:
    """Read *path* under a shared flock on *lock_path*."""
    lf = open(lock_path, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_SH)
        return path.read_text(encoding=encoding)
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()

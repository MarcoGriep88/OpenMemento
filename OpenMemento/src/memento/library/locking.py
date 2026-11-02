"""An OS-owned lock, released even when the desktop process crashes."""
from __future__ import annotations

import errno
import os
from pathlib import Path


class LibraryAlreadyOpen(RuntimeError):
    pass


class LibraryLock:
    def __init__(self, database_path: Path):
        self.path = Path(database_path).with_suffix(".lock")
        self._stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise LibraryAlreadyOpen("Diese Medienbibliothek ist bereits in einer anderen Memento-Instanz geöffnet.") from None
            raise
        self._stream = stream
        return self

    def close(self):
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    @property
    def is_held(self):
        return self._stream is not None and not self._stream.closed

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.close()

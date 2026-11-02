from __future__ import annotations

import os
import subprocess
import sys

import pytest

from memento.library.locking import LibraryAlreadyOpen, LibraryLock


def test_live_process_lock_prevents_second_instance_and_recovers_after_exit(tmp_path):
    database = tmp_path / "library.sqlite3"
    code = "from pathlib import Path; from memento.library.locking import LibraryLock; import sys; lock=LibraryLock(Path(sys.argv[1])).acquire(); print('locked', flush=True); sys.stdin.readline(); lock.close()"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")
    process = subprocess.Popen([sys.executable, "-u", "-c", code, str(database)], env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert process.stdout.readline().strip() == "locked"
        assert process.poll() is None
        with pytest.raises(LibraryAlreadyOpen):
            LibraryLock(database).acquire()
        # A process crash must release the OS lock; a remaining lock file is harmless.
        process.kill()
        process.wait(timeout=5)
        with LibraryLock(database):
            assert database.with_suffix(".lock").is_file()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_distinct_libraries_have_independent_locks(tmp_path):
    with LibraryLock(tmp_path / "first.sqlite3"), LibraryLock(tmp_path / "second.sqlite3"):
        pass

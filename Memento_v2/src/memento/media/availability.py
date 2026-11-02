"""Small subprocess entry point: filesystem calls may block on offline shares."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def check_folder(path: Path) -> dict:
    try:
        # Opening the directory checks access, rather than merely its existence.
        with os.scandir(path):
            pass
    except OSError as exc:
        return {"available": False, "detail": str(exc)}
    return {"available": True, "detail": "Medienordner ist erreichbar."}


if __name__ == "__main__":
    print(json.dumps(check_folder(Path(sys.argv[1]))))

#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    echo 'Bitte zuerst die Linux-Umgebung einrichten (siehe README.md):' >&2
    echo 'python3.12 -m venv .venv' >&2
    echo '.venv/bin/python -m pip install -e ".[dev]"' >&2
    exit 1
fi
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m memento.app "$@"

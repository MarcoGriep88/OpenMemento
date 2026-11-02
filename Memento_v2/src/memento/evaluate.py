"""Command-line, network-free evaluation of saved movie plans."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from memento.application.evaluation import evaluate_movie
from memento.library.movies import load_movie


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Doppelte JSON-Felder in der Referenzdatei.")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Filmplan lokal mit menschlich markierten Referenzmomenten vergleichen.")
    parser.add_argument("movie", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path, help="Neue JSON-Berichtsdatei; bestehende Dateien werden nicht überschrieben.")
    parser.add_argument("--retained-fraction", type=float, default=0.8)
    args = parser.parse_args(argv)
    try:
        reference = json.loads(args.reference.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        report = evaluate_movie(load_movie(args.movie), reference, retained_fraction=args.retained_fraction)
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            # Exclusive creation protects reference, project, media and old reports.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        else:
            print(text, end="")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Auswertung fehlgeschlagen: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Durable empty projects, independent of paid analysis and editable movie plans."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from memento.ai.contracts import ANALYSIS_PROFILE
from memento.domain.editing import EditingStyle


@dataclass
class FilmProject:
    project_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    target_seconds: int = 720
    prompt: str = ""
    roots: list[str] = field(default_factory=list)
    date_from: str = "1900-01-01"
    date_to: str = "2100-12-31"
    template: str = "random"
    transition_seconds: float = 0.6
    music_path: str = ""
    music_enabled: bool = False
    suno_prompt: str = ""
    output: str = ""
    step: int = 1
    updated_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())

    @property
    def analysis_profile(self):
        text = self.prompt.strip()
        return ANALYSIS_PROFILE if not text else ANALYSIS_PROFILE + ":" + hashlib.sha256(text.encode()).hexdigest()[:20]

    def validate(self):
        from datetime import date
        from uuid import UUID
        if (not all(isinstance(value, str) for value in (self.project_id, self.title, self.prompt,
                self.date_from, self.date_to, self.template, self.music_path, self.suno_prompt, self.output, self.updated_at))
                or not isinstance(self.roots, list) or any(not isinstance(root, str) for root in self.roots)
                or type(self.music_enabled) is not bool or type(self.step) is not int):
            raise ValueError("Ungültige Projektdaten.")
        UUID(self.project_id)
        datetime.fromisoformat(self.updated_at)
        if not self.title.strip() or len(self.title) > 200:
            raise ValueError("Bitte einen Filmtitel mit höchstens 200 Zeichen eingeben.")
        if type(self.target_seconds) is not int or not 2 <= self.target_seconds <= 10800:
            raise ValueError("Die Zielzeit muss zwischen 2 Sekunden und 180 Minuten liegen.")
        if len(self.prompt) > 4000 or not 1 <= self.step <= 5:
            raise ValueError("Ungültige Projektvorgaben.")
        if date.fromisoformat(self.date_to) < date.fromisoformat(self.date_from):
            raise ValueError("Das Enddatum muss nach dem Startdatum liegen.")
        if any(not Path(root).is_absolute() for root in self.roots):
            raise ValueError("Medienordner müssen absolute Pfade sein.")
        EditingStyle(self.template, self.transition_seconds).validate()


class ProjectStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, project_id):
        from uuid import UUID
        UUID(project_id)
        return self.root / f"{project_id}.project.json"

    def movie_path(self, project):
        self.path(project.project_id)  # Validate the identity before building a path.
        return self.root / f"{project.project_id}.memento.json"

    def save(self, project):
        project.validate()
        project.updated_at = datetime.now().astimezone().isoformat()
        target = self.path(project.project_id)
        fd, name = tempfile.mkstemp(prefix=".project-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "project": asdict(project)}, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)

    def load(self, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload["version"] != 1:
            raise ValueError("Unbekannte Projektversion.")
        project = FilmProject(**payload["project"])
        project.validate()
        return project

    def list(self):
        projects, errors = [], []
        for path in self.root.glob("*.project.json"):
            try:
                projects.append(self.load(path))
            except (ValueError, KeyError, TypeError, OSError):
                errors.append(path.name)
        return sorted(projects, key=lambda project: project.updated_at, reverse=True), errors


def project_asset_ids(library, roots):
    """Include verified aliases in selected folders, even if the preferred copy is elsewhere."""
    normalized = [os.path.normcase(os.path.abspath(root)) for root in roots]
    result = set()
    with library._connection() as db:
        for row in db.execute("SELECT asset_id, path FROM locations"):
            path = os.path.normcase(os.path.abspath(row["path"]))
            for root in normalized:
                try:
                    if os.path.commonpath((path, root)) == root:
                        result.add(row["asset_id"])
                        break
                except ValueError:
                    continue
    return result

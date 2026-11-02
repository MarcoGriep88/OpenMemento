"""Offline project isolation and actual soundtrack export for the guided workflow."""
from copy import deepcopy
from datetime import date
import os
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from memento.application.music import SoundtrackRenderService
from memento.application.rendering import RenderSettings
from memento.library.movies import load_movie
from memento.library.projects import FilmProject, ProjectStore
from memento.library.semantic import SemanticRepository
from memento.media.metadata import _run_command
from memento.ui.workflow_window import WorkflowWindow
from test_movie_rendering import make_plan
from test_ui_movie import wait_until


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("memento.ui.main_window.QSettings", lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    # Metadata checks run in other tests; avoid spawning folder probes here.
    monkeypatch.setattr(WorkflowWindow, "_check_folders", lambda self: None)
    make_plan(tmp_path)
    from memento.library.database import MediaLibrary
    window = WorkflowWindow(MediaLibrary(tmp_path / "library.sqlite3"))
    window.settings.setValue("ai/model", "test-model")
    window.show()
    yield app, window
    window.close()
    app.processEvents()


def test_empty_projects_reset_and_reopen_without_cross_project_music(workflow, tmp_path):
    app, window = workflow
    window.new_project()
    window.project_title.setText("Urlaub")
    window.project_duration.setValue(7)
    window.create_or_update_project()
    assert window.pages.currentIndex() == 2
    first_id = window.project.project_id
    assert window.project.roots == []
    assert window.project.template == "random"
    assert not window.store.movie_path(window.project).exists()
    window.settings.setValue("library/folders", [str(tmp_path)])
    window.project.music_path = str(tmp_path / "song.wav")
    window.use_music.setChecked(True)
    window.suno_text.setPlainText("Sonnenuntergang am Strand")
    window.cut_style.setCurrentIndex(window.cut_style.findData("cut"))
    window.save_project()
    window.new_project()
    window.project_title.setText("Geburtstag")
    window.create_or_update_project()
    second = deepcopy(window.project)
    assert second.project_id != first_id
    assert second.roots == [] and second.template == "random"
    assert not second.music_enabled and not second.music_path and not second.suno_prompt
    window.show_step(0)
    assert window.projects_table.rowCount() == 2
    first = window.store.load(window.store.path(first_id))
    window.load_project(first)
    assert window.project_title.text() == "Urlaub"
    assert window.project_duration.value() == 7
    assert window.use_music.isChecked()
    assert window.suno_text.toPlainText() == "Sonnenuntergang am Strand"
    window.load_project(second)
    assert not window.use_music.isChecked() and not window.suno_text.toPlainText()


def test_project_scope_prompt_copy_plan_edit_and_export_tracking(workflow, tmp_path):
    app, window = workflow
    window.new_project()
    window.project_title.setText("Unser Ausflug")
    window.project_duration.setValue(0.1)
    window.create_or_update_project()
    # A folder from a different project must never contribute candidates.
    window.settings.setValue("library/folders", [str(tmp_path / "other")])
    window.save_project()
    day = date(2026, 7, 12)
    assert not window.planner().candidates(day, day, "gemini", "test-model")[0]
    window.settings.setValue("library/folders", [str(tmp_path)])
    window.save_project()
    window.create_music_prompt()
    assert "Familienausflug" in window.suno_text.toPlainText()
    window.copy_music_prompt()
    assert QApplication.clipboard().text() == window.suno_text.toPlainText()
    window.open_movie()
    editor = window.movie_editor
    assert editor.style_combo.currentData() == "random"
    assert editor.project_path == window.store.movie_path(window.project)
    editor.generate()
    assert wait_until(app, lambda: editor.thread is None)
    assert editor.plan is not None, editor.status.text()
    assert editor.plan.title == "Unser Ausflug"
    assert editor.plan.editing_style.template == "random"
    editor.title.setText("Unsere Erinnerungen")
    editor.persist()
    editor.duration.setValue(9)
    window.show_step(4)
    assert window.project.title == "Unsere Erinnerungen"
    assert window.project.target_seconds == 9
    assert load_movie(editor.project_path).target_seconds == 9
    # The real renderer is checked separately below. Here exercise its UI callback.
    export = tmp_path / "export.mp4"
    export.write_bytes(b"export-fixture")
    editor.rendered((export, editor.plan))
    assert window.store.load(window.store.path(window.project.project_id)).output == str(export)
    window.show_step(0)
    assert window.projects_table.item(0, 2).text() == "Exportiert"
    window.project_prompt.setPlainText("Jetzt Landschaften bevorzugen.")
    window.save_project()
    assert editor.plan is None
    assert not editor.history.can_undo and not editor.history.can_redo
    assert not editor.candidates


def test_prompt_profiles_preserve_paid_cache_and_scope_resumable_jobs(workflow, tmp_path):
    _, window = workflow
    window.new_project()
    window.project_title.setText("Familie")
    window.create_or_update_project()
    window.settings.setValue("library/folders", [str(tmp_path)])
    window.save_project()
    assets = window.selected_assets(False)
    default_profile = window.project.analysis_profile
    window.project_prompt.setPlainText("Achte besonders auf gemeinsames Lachen.")
    window.save_project()
    assert window.project.analysis_profile != default_profile
    day = date(2026, 7, 12)
    assert not window.planner().candidates(day, day, "gemini", "test-model")[0]
    window.project_prompt.clear()
    window.save_project()
    assert window.project.analysis_profile == default_profile
    assert len(window.planner().candidates(day, day, "gemini", "test-model")[0]) == 2
    job = window.analysis_service.create_job({assets[0].asset_id})
    assert len(window.library.list_media_analysis_job_items(job.job_id)) == 1
    window._refresh_analysis_choices()
    assert window.analysis_job_selector.findData(job.job_id) >= 0
    window.new_project()
    assert window.analysis_job_selector.count() == 0


def test_real_music_mix_keeps_video_duration_and_source_files(tmp_path):
    plan = make_plan(tmp_path)
    music = tmp_path / "soundtrack.wav"
    renderer = SoundtrackRenderService(tmp_path / "renders", str(music))
    assert _run_command([renderer.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                         "sine=frequency=880:duration=1", str(music)], 20, None).returncode == 0
    original = music.read_bytes()
    video_sources = {item.source.path: Path(item.source.path).read_bytes() for item in plan.segments}
    output = tmp_path / "with-music.mp4"
    renderer.render(plan, output, Event(), settings=RenderSettings(160, 90, 24))
    from memento.media.metadata import probe_media
    metadata = probe_media(output)
    assert metadata.duration_seconds == pytest.approx(4, abs=0.15)
    assert metadata.has_audio
    import subprocess
    result = subprocess.run([renderer.ffmpeg, "-v", "error", "-i", str(output),
                             "-f", "f32le", "-ac", "1", "-ar", "8000", "pipe:1"],
                            capture_output=True, check=True, timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    # The silent second source now contains the looped soundtrack.
    assert np.mean(np.abs(audio[18000:24000])) > 0.004
    assert music.read_bytes() == original
    assert all(Path(path).read_bytes() == data for path, data in video_sources.items())
    with pytest.raises(ValueError):
        renderer.render(plan, music, Event())


def test_project_store_skips_corrupt_records_and_preserves_previous_save(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path / "projects")
    project = FilmProject(title="Sommer")
    store.save(project)
    original = store.path(project.project_id).read_bytes()
    def fail_replace(*_):
        raise OSError("Datenträger voll")
    monkeypatch.setattr("memento.library.projects.os.replace", fail_replace)
    project.title = "Geändert"
    with pytest.raises(OSError):
        store.save(project)
    assert store.path(project.project_id).read_bytes() == original
    (store.root / "broken.project.json").write_text("{}")
    projects, errors = store.list()
    assert [item.title for item in projects] == ["Sommer"]
    assert errors == ["broken.project.json"]


def test_custom_analysis_profile_resumes_without_repeating_provider_calls(tmp_path):
    from test_semantic_analysis import setup_library, FakeProvider, fake_proxy
    from memento.application.semantic_analysis import SemanticAnalysisService
    library, assets, _ = setup_library(tmp_path, duration=10)
    project = FilmProject(title="Lachen", prompt="Achte besonders auf Reaktionen.")
    repo = SemanticRepository(library, project.analysis_profile)
    provider = FakeProvider()
    job = repo.create_job(assets, provider.name, provider.model)
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(job, Event()) == "complete"
    reopened = SemanticRepository(library, project.analysis_profile)
    resumed = reopened.create_job(assets, provider.name, provider.model)
    assert reopened.estimate(resumed)["pending"] == 0
    assert SemanticAnalysisService(reopened, provider, fake_proxy).run(resumed, Event()) == "complete"
    assert len(provider.calls) == 1
    project.prompt = "Achte auf die Landschaft."
    different = SemanticRepository(library, project.analysis_profile)
    assert different.estimate(different.create_job(assets, provider.name, provider.model))["pending"] == 1


def test_editorial_prompt_reaches_gemini_request_without_secret_in_body(tmp_path):
    import json
    from test_semantic_analysis import Opener
    from memento.ai.gemini import GeminiProvider
    opener = Opener({"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": json.dumps({"moments": []})}]}}]})
    source = tmp_path / "proxy.mp4"
    source.write_bytes(b"test-proxy")
    prompt = "Bitte achte besonders auf gemeinsames Lachen."
    GeminiProvider("test-secret", "test-model", opener, user_prompt=prompt).analyze(source, 10, Event())
    request = opener.requests[0]
    body = json.loads(request.data)
    assert prompt in body["contents"][0]["parts"][1]["text"]
    assert b"test-secret" not in request.data
    assert request.get_header("X-goog-api-key") == "test-secret"

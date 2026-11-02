from __future__ import annotations

import os
from datetime import datetime
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from memento.ai.contracts import SemanticResult
from memento.domain.media import MediaAsset
from memento.library.database import MediaLibrary
from memento.ui import semantic_dialog


def test_dialog_does_not_send_before_start_and_background_job_shows_cached_results(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    source = tmp_path / "family.mp4"
    source.write_bytes(b"video")
    asset = library.save_asset(MediaAsset("family", source, source.stat().st_size,
        datetime.fromtimestamp(source.stat().st_mtime).astimezone(), duration_seconds=4))
    calls = []

    class Provider:
        name = "gemini"

        def __init__(self, key, model):
            assert key == "mock-vault-key"
            self.model = model

        def analyze(self, path, duration, cancel_token):
            calls.append(path)
            return SemanticResult((), 10, 3)

    original_service = semantic_dialog.SemanticAnalysisService

    def proxy(source, start, end, target, cancel_token):
        target.write_bytes(b"mp4")
        return target

    monkeypatch.setattr(semantic_dialog, "GeminiProvider", Provider)
    monkeypatch.setattr(semantic_dialog, "get_gemini_key", lambda: "mock-vault-key")
    monkeypatch.setattr(semantic_dialog, "SemanticAnalysisService",
                        lambda repo, provider: original_service(repo, provider, proxy))
    dialog = semantic_dialog.SemanticDialog(library, [asset], "test-model")
    dialog.show()
    app.processEvents()
    assert calls == []
    assert "1 neuer Bereich" in dialog.notice.text()
    assert str(source) == dialog.table.item(0, 0).text()
    dialog.start_button.click()
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if dialog.thread is None else None)
    poll.start(10)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    poll.stop()
    app.processEvents()
    assert dialog.thread is None
    assert len(calls) == 1
    assert dialog.table.item(0, 2).text() == "Gespeichert"
    assert "10 Eingabe- und 3 Ausgabetokens" in dialog.notice.text()
    assert dialog.start_button.isEnabled()
    dialog.reject()


def test_worker_without_key_never_constructs_provider(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(semantic_dialog, "get_gemini_key", lambda: None)
    monkeypatch.setattr(semantic_dialog, "GeminiProvider", lambda *args: (_ for _ in ()).throw(AssertionError("No network allowed")))
    messages = []
    worker = semantic_dialog.SemanticWorker(
        type("Repository", (), {"get_job": lambda self, job_id: {"model": "test"}})(), "job", Event())
    worker.finished.connect(messages.append)
    worker.run()
    assert messages == ["Kein Gemini-Schlüssel gespeichert. Bitte Einstellungen öffnen."]


def test_dialog_request_cap_stops_and_explicit_resume_uses_paid_cache(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    source = tmp_path / "family.mp4"
    source.write_bytes(b"video")
    asset = library.save_asset(MediaAsset("family", source, source.stat().st_size,
        datetime.fromtimestamp(source.stat().st_mtime).astimezone(), duration_seconds=90))
    calls = []

    class Provider:
        name = "gemini"

        def __init__(self, key, model):
            self.model = model

        def analyze(self, path, duration, token):
            calls.append(path)
            return SemanticResult((), 10, 3)

    original_service = semantic_dialog.SemanticAnalysisService

    def proxy(source, start, end, target, token):
        target.write_bytes(b"proxy")
        return target

    monkeypatch.setattr(semantic_dialog, "GeminiProvider", Provider)
    monkeypatch.setattr(semantic_dialog, "get_gemini_key", lambda: "mock-key")
    monkeypatch.setattr(semantic_dialog, "SemanticAnalysisService", lambda repo, provider: original_service(repo, provider, proxy))
    dialog = semantic_dialog.SemanticDialog(library, [asset], "test-model")
    dialog.show()
    dialog.request_limit.setValue(1)
    assert "höchstens 1 Anbieteraufruf" in dialog.notice.text()
    assert "maximal 8 MiB" in dialog.notice.text()
    assert not calls

    def finish():
        loop, poll = QEventLoop(), QTimer()
        poll.timeout.connect(lambda: loop.quit() if dialog.thread is None else None)
        poll.start(10)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        poll.stop()
        app.processEvents()
        assert dialog.thread is None

    dialog.start()
    assert not dialog.request_limit.isEnabled()
    finish()
    assert len(calls) == 1
    assert "Anfragelimit" in dialog.status.text()
    assert dialog.repository.get_job(dialog.jobs.currentData())["status"] == "request_limit"
    assert "Bisher 1 versuchter Aufruf" in dialog.notice.text()
    assert dialog.request_limit.isEnabled()
    dialog.start()
    finish()
    assert len(calls) == 2
    assert dialog.status.text() == "Analyse abgeschlossen."
    assert "Bisher 2 versuchte Aufrufe" in dialog.notice.text()
    assert all(dialog.table.item(row, 2).text() == "Gespeichert" for row in range(2))
    dialog.reject()


def test_twenty_thousand_ranges_show_bounded_pages_without_per_row_database_reads(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    source = tmp_path / "long-recording.mp4"
    source.write_bytes(b"video")
    asset = library.save_asset(MediaAsset("long", source, 5,
        datetime.fromtimestamp(source.stat().st_mtime).astimezone(), duration_seconds=45 * 20_000))
    reads = []
    original = library._connect

    def connect():
        reads.append(True)
        return original()

    monkeypatch.setattr(library, "_connect", connect)
    monkeypatch.setattr(library, "get_asset", lambda *args: (_ for _ in ()).throw(AssertionError("No per-row reads")))
    monkeypatch.setattr(semantic_dialog.SemanticRepository, "cached", lambda *args: (_ for _ in ()).throw(AssertionError("No per-row reads")))
    monkeypatch.setattr(semantic_dialog, "get_gemini_key", lambda: (_ for _ in ()).throw(AssertionError("No credentials needed for viewing")))
    dialog = semantic_dialog.SemanticDialog(library, [asset], "test-model")
    assert len(reads) <= 7  # Fixed number of connections, independent of row count.
    assert dialog.table.rowCount() == 100
    assert dialog.page_label.text() == "Bereiche 1–100 von 20000"
    assert not dialog.previous_page.isEnabled() and dialog.next_page.isEnabled()
    reads.clear()
    dialog.next_page.click()
    assert len(reads) == 1
    assert dialog.table.rowCount() == 100
    assert dialog.table.item(0, 1).text() == "4500.0–4545.0"
    assert dialog.page_label.text() == "Bereiche 101–200 von 20000"
    dialog.page_offset = 19_900
    dialog.refresh_page()
    assert dialog.table.item(99, 1).text() == "899955.0–900000.0"
    assert not dialog.next_page.isEnabled()
    # Switching to another saved job resets navigation, not the job's contents.
    small_asset = library.save_asset(MediaAsset("small", source, 5, asset.modified_at, duration_seconds=4))
    small_job = dialog.repository.create_job([small_asset], "gemini", "test-model")
    dialog.jobs.addItem("Kleiner Auftrag", small_job)
    dialog.jobs.setCurrentIndex(1)
    assert dialog.page_offset == 0 and dialog.table.rowCount() == 1
    assert dialog.page_label.text() == "Bereiche 1–1 von 1"
    dialog.reject()

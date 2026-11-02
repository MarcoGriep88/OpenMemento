"""Offline installed-app check using generated media and a fixture AI answer."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import Event
from uuid import uuid4
from copy import deepcopy
from dataclasses import replace


def check_installed_app(library, parent):
    import imageio_ffmpeg
    from memento.security.credentials import _secure_keyring
    from PySide6.QtCore import QDate, QEventLoop, QTimer
    from memento.ai.contracts import Moment, SemanticResult
    from memento.application.indexing import MediaIndexService
    from memento.application.movie_planning import PLANNER_VERSION, MoviePlanningService
    from memento.application.rendering import RENDER_VERSION, MovieRenderService, RenderSettings
    from memento.application.shot_analysis import LOCAL_ANALYSIS_VERSION, ShotAnalysisService
    from memento.library.movies import load_movie, save_movie
    from memento.library.semantic import SemanticRepository
    from memento.media.metadata import _run_command, probe_media
    from memento.ui.movie_dialog import MovieDialog
    from memento.domain.editing import EditingStyle
    from memento.ui.recovery_dialog import RecoveryDialog
    from memento.ui.capture_time_dialog import CaptureTimeDialog
    from memento.ui.date_range_dialog import DateRangeDialog
    from memento.library.recovery import create_backup, restore_backup

    icon = parent.windowIcon()
    icon_sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
    if not {(16, 16), (256, 256)} <= icon_sizes or icon.pixmap(32, 32).isNull():
        raise RuntimeError("Das gebündelte Anwendungsicon fehlt oder ist nicht lesbar.")

    root = library.path.parent
    media = root / "smoke-media"
    media.mkdir()
    source = media / "source.mov"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, "-nostdin", "-n", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=96x64:r=12:d=2",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
               "-metadata", "creation_time=2026-07-12T10:00:00Z", str(source)]
    if _run_command(command, 30, None).returncode:
        raise RuntimeError("Das gebündelte FFmpeg konnte keine Testdatei erstellen.")
    indexing = MediaIndexService(library)
    indexing.run(indexing.create_job([media]).job_id)
    assets = library.list_assets()
    if len(assets) != 1 or not assets[0].capture_time or assets[0].capture_time.value.date() != date(2026, 7, 12):
        raise RuntimeError("Medienimport oder Aufnahmezeitprüfung fehlgeschlagen.")
    local = ShotAnalysisService(library)
    local.run(local.create_job().job_id)
    assets = library.list_assets()
    windows = library.local_features_for_assets(assets, LOCAL_ANALYSIS_VERSION)
    if not windows.get(assets[0].asset_id):
        raise RuntimeError("Lokale Analyse fehlgeschlagen.")
    repository = SemanticRepository(library)
    job = repository.create_job(assets, "gemini", "smoke-fixture")
    moment = Moment(0, 2, "Synthetische Testaufnahme", "Lokaler Funktionstest", (), (), 0.8, 0.8, 0.8, 1, 1, ("Testfixture",))
    repository.save_result(repository.get_job(job), repository.items(job)[0], SemanticResult((moment,)))
    planner = MoviePlanningService(repository)
    day = date(2026, 7, 12)
    plan = planner.build(day, day, 2, "gemini", "smoke-fixture")
    project = root / "smoke.memento.json"
    save_movie(project, plan)
    if load_movie(project) != plan:
        raise RuntimeError("Projektrundlauf fehlgeschlagen.")
    capture_dialog = CaptureTimeDialog(library, parent)
    capture_dialog.show()
    capture_dialog.table.selectRow(0)
    capture_dialog.day.setDate(QDate(2026, 8, 3))
    capture_dialog.save_button.click()
    capture_dialog.accept()
    corrected = library.get_asset(assets[0].asset_id)
    new_day = date(2026, 8, 3)
    corrected_plan = planner.build(new_day, new_day, 2, "gemini", "smoke-fixture")
    if (not capture_dialog.changed or corrected.capture_time.value.date() != new_day
            or corrected_plan.segments[0].candidate_id != plan.segments[0].candidate_id
            or load_movie(project) != plan):
        raise RuntimeError("Die Aufnahmezeitkorrektur hat den Cache oder den gespeicherten Filmplan verändert.")
    page = library.capture_date_page(new_day, new_day, limit=DateRangeDialog.PAGE_SIZE)
    range_dialog = DateRangeDialog(library, new_day, new_day, parent, initial_page=page)
    range_dialog.show()
    if (page.total != 1 or page.unknown != 0 or range_dialog.model.rowCount() != 1
            or range_dialog.model.data(range_dialog.model.index(0, 3)) != source.name
            or range_dialog.previous_button.isEnabled() or range_dialog.next_button.isEnabled()):
        raise RuntimeError("Die gebündelte Zeitraumprüfung liefert nicht die erwartete Seite.")
    range_dialog.accept()
    output = root / "smoke.mp4"
    renderer = MovieRenderService(root / "cache" / "renders")
    renderer.render(plan, output, Event(), settings=RenderSettings(160, 90, 12))
    rendered_frames = renderer._validate_video(output, 24, Event())
    result = probe_media(output)
    if result.duration_seconds is None or abs(result.duration_seconds - 2) > 0.2 or not result.has_audio:
        raise RuntimeError("Renderprüfung fehlgeschlagen.")
    dialog = MovieDialog(library, new_day, new_day, 2, "smoke-fixture", parent)
    dialog.planned((corrected_plan, planner.candidates(new_day, new_day, "gemini", "smoke-fixture")[0]))
    dialog.show()
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData("crossfade"))
    dialog.transition_duration.setValue(0.5)
    dialog.apply_style_button.click()
    if load_movie(dialog.project_path).editing_style != EditingStyle("crossfade", 0.5):
        raise RuntimeError("Die gebündelte Schnittvorlage wurde nicht gespeichert.")
    style_plan = deepcopy(plan)
    first = style_plan.segments[0]
    style_plan.segments = [replace(first, end_seconds=1),
                           replace(first, candidate_id="smoke-second", start_seconds=1)]
    style_plan.events = [replace(style_plan.events[0], candidate_ids=(first.candidate_id, "smoke-second"))]
    style_plan.editing_style = dialog.plan.editing_style
    style_output = root / "smoke-crossfade.mp4"
    renderer.render(style_plan, style_output, Event(), settings=RenderSettings(160, 90, 12))
    style_frames = renderer._validate_video(style_output, 18, Event(), tolerance=1)
    loop = QEventLoop()
    frames = []

    def frame_ready(frame):
        if frame.isValid():
            frames.append(True)
            loop.quit()

    dialog.video.videoSink().videoFrameChanged.connect(frame_ready)
    QTimer.singleShot(20000, loop.quit)
    dialog.table.selectRow(0)
    dialog.preview()
    loop.exec()
    dialog.reject()
    if not frames:
        raise RuntimeError("Die gebündelte Qt-Videovorschau lieferte kein Bild.")
    backup = root / "smoke-backup.sqlite3"
    create_backup(library.path, backup, active_lock=parent._library_lock)
    with library._connection() as db:
        db.execute("UPDATE assets SET video_codec='smoke-temporary-change'")
    recovery = RecoveryDialog(library.path, parent, parent._library_lock)
    recovery.show()
    recovery_loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: recovery_loop.quit() if recovery.thread is None else None)
    timer.start(10)
    QTimer.singleShot(20000, recovery_loop.quit)
    recovery.run_operation("restore", lambda token, progress: restore_backup(backup, library.path, token, progress, parent._library_lock))
    recovery_loop.exec()
    timer.stop()
    if recovery.thread is not None or not recovery.restored:
        raise RuntimeError("Der Wiederherstellungsdialog konnte den Teststand nicht übernehmen.")
    recovery.reject()
    if library.list_assets()[0].video_codec == "smoke-temporary-change":
        raise RuntimeError("Die Wiederherstellung hat den gesicherten Stand nicht übernommen.")
    store = _secure_keyring()
    backend = type(store)
    test_service = "Memento-smoke-" + uuid4().hex
    test_account = "disposable-vault-test"
    written = False
    try:
        store.set_password(test_service, test_account, "local-smoke-test-value")
        written = True
        if store.get_password(test_service, test_account) != "local-smoke-test-value":
            raise RuntimeError("Betriebssystem-Schlüsselspeicher-Rundlauf fehlgeschlagen.")
    finally:
        if written:
            store.delete_password(test_service, test_account)
    return {"window_created": parent.isVisible(), "indexed_assets": len(assets), "local_windows": len(windows[assets[0].asset_id]),
            "project_roundtrip": True, "rendered_seconds": result.duration_seconds, "audio": result.has_audio,
            "preview_frame": True, "credential_backend": f"{backend.__module__}.{backend.__name__}",
            "credential_roundtrip": True, "recovery_roundtrip": True, "capture_time_correction": True, "ffmpeg": Path(ffmpeg).name,
            "date_range_page": True, "rendered_frames": rendered_frames,
            "application_icon": True,
            "editing_template": "crossfade", "editing_template_frames": style_frames,
            "planner_profile": PLANNER_VERSION, "local_analysis_profile": LOCAL_ANALYSIS_VERSION, "render_profile": RENDER_VERSION,
            "semantic_response": "fixture; no network or Gemini credential access"}

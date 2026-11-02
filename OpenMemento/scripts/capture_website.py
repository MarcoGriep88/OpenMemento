"""Render real Qt views with isolated sample projects, without media or AI access.

Run with the development environment: python scripts/capture_website.py
Screenshots are generated in website/static/images for both website languages.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QLocale, QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from memento.i18n import set_language
from memento.library.database import MediaLibrary
from memento.library.projects import FilmProject
from memento.ui.theme import APP_STYLE, light_palette
from memento.ui.workflow_window import WorkflowWindow


def main():
    output = Path(__file__).resolve().parents[2] / "website" / "static" / "images"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    # Qt's offscreen plugin does not discover Windows fonts automatically.
    font_root = Path("C:/Windows/Fonts")
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        if (font_root / name).is_file():
            QFontDatabase.addApplicationFont(str(font_root / name))
    app.setFont(QFont("Segoe UI", 10))
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    app.setStyleSheet(APP_STYLE)
    with tempfile.TemporaryDirectory(prefix="memento-website-") as temp:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, temp)
        app.setOrganizationName("MementoWebsitePreview")
        for lang in ("de", "en"):
            app.setApplicationName(f"Sample-{lang}")
            set_language(lang)
            QLocale.setDefault(QLocale("de_DE" if lang == "de" else "en_US"))
            library = MediaLibrary(Path(temp) / lang / "library.sqlite3")
            window = WorkflowWindow(library)
            window.resize(1360, 860)
            titles = (("Unser Sommer am Meer", "Ein Geburtstag", "Ein Wochenende bei Oma")
                      if lang == "de" else ("Our summer by the sea", "A birthday", "A weekend at grandma's"))
            for title, duration in zip(titles, (720, 300, 420)):
                window.store.save(FilmProject(title=title, target_seconds=duration, template="cut"))
            window.refresh_dashboard()
            window.show()
            app.processEvents()
            assert window.grab().save(str(output / f"app-dashboard-{lang}.png"))
            window.load_project(window.dashboard_projects[-1])
            window.show_step(1)
            app.processEvents()
            assert window.grab().save(str(output / f"app-project-{lang}.png"))
            window.close()
            app.processEvents()
    print(f"Rendered four application screenshots: {output}")


if __name__ == "__main__":
    main()

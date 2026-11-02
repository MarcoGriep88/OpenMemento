"""Shared, resolution-independent application wordmark."""
from pathlib import Path

from PySide6.QtSvgWidgets import QSvgWidget


def brand_widget() -> QSvgWidget:
    widget = QSvgWidget(str(Path(__file__).resolve().parents[1] / "resources" / "logo-wordmark.svg"))
    widget.setObjectName("brand")
    widget.setAccessibleName("OpenMemento")
    widget.setFixedSize(190, 35)
    return widget

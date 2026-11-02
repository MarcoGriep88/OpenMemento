"""Render the editable SVG into a PNG preview and a multiresolution Windows ICO."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "memento" / "resources"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(RESOURCES / "memento.svg"))
    if not renderer.isValid():
        raise RuntimeError("Ungültige Icon-Vektorgrafik.")
    frames = []
    for size in (*SIZES, 512):
        canvas = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(0)
        painter = QPainter(canvas)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not canvas.save(buffer, "PNG"):
            raise RuntimeError("Icon konnte nicht gerendert werden.")
        buffer.close()
        if size == 512:
            (RESOURCES / "memento.png").write_bytes(bytes(data))
        else:
            frames.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, data in frames:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (RESOURCES / "memento.ico").write_bytes(header + b"".join(entries) + b"".join(data for _, data in frames))
    # NSIS Modern UI expects 24-bit BMPs, not transparent PNGs.
    for name, width, height, source, bounds in (
        ("installer-welcome.bmp", 164, 314, "logo-mark.svg", (14, 105, 136, 80)),
        ("installer-header.bmp", 150, 57, "logo-wordmark.svg", (5, 14, 140, 29)),
    ):
        image = QImage(width, height, QImage.Format.Format_RGB888)
        image.fill(QColor("#fffaf2" if height == 314 else "#ffffff"))
        branding = QSvgRenderer(str(RESOURCES / source))
        if not branding.isValid():
            raise RuntimeError(f"Invalid branding SVG: {source}")
        painter = QPainter(image)
        branding.render(painter, QRectF(*bounds))
        painter.end()
        if not image.save(str(RESOURCES / name), "BMP"):
            raise RuntimeError(f"Could not generate {name}")
    preview = QImage(1200, 720, QImage.Format.Format_RGB888)
    preview.fill(QColor("#f5f3ed"))
    painter = QPainter(preview)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#ffffff"))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(QRectF(40, 40, 1120, 390), 24, 24)
    QSvgRenderer(str(RESOURCES / "logo-wordmark.svg")).render(painter, QRectF(180, 160, 840, 160))
    for x, color, source in ((40, "#ffffff", "logo-mark.svg"), (424, "#e5f5ee", "memento.svg"), (808, "#193e32", "memento.svg")):
        painter.setPen(QColor(color))
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(x, 454, 352, 226), 20, 20)
        bounds = QRectF(x + 70, 504, 212, 125) if source == "logo-mark.svg" else QRectF(x + 112, 492, 128, 128)
        QSvgRenderer(str(RESOURCES / source)).render(painter, bounds)
    painter.end()
    preview_dir = ROOT / "docs" / "branding"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview.save(str(preview_dir / "logo-preview.png"))
    website = ROOT.parent / "website" / "static"
    if website.is_dir():
        for name in ("logo-mark.svg", "logo-wordmark.svg"):
            shutil.copyfile(RESOURCES / name, website / "images" / name)
        shutil.copyfile(RESOURCES / "memento.svg", website / "favicon.svg")
        shutil.copyfile(RESOURCES / "memento.png", website / "images" / "app-icon.png")
    print(f"Icon erzeugt: {RESOURCES / 'memento.ico'} ({len(frames)} Auflösungen)")


if __name__ == "__main__":
    main()

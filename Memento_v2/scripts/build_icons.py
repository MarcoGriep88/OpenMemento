"""Render the editable SVG into a PNG preview and a multiresolution Windows ICO."""
from __future__ import annotations

import os
from pathlib import Path
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
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
    print(f"Icon erzeugt: {RESOURCES / 'memento.ico'} ({len(frames)} Auflösungen)")


if __name__ == "__main__":
    main()

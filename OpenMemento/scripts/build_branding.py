"""Build the approved memory-ribbon identity as editable SVG and outlined type.

Run manually when changing the identity, then run build_icons.py. Runtime and
installer builds use the checked-in SVGs and never need a particular font.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QPainterPath

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "memento" / "resources"
RIBBON = (
    "M20 276C38 239 59 122 82 91C98 69 152 54 192 41C208 36 219 38 229 46C207 50 198 77 189 116L157 227C149 255 129 271 102 273Z",
    "M229 46C257 68 258 119 269 165L282 230C280 253 266 275 252 275C225 275 208 210 196 152L183 104C196 62 202 38 225 42Z",
    "M252 275C282 275 298 232 315 188C337 143 350 116 376 108C391 104 397 120 402 144L422 227C432 268 456 290 488 274L523 247C482 261 469 231 457 190L434 108C425 73 406 75 379 84C337 96 300 119 278 169C264 197 260 232 252 275Z",
)


def ribbon(colors):
    return "".join(f'<path fill="{color}" d="{path}"/>' for color, path in zip(colors, RIBBON))


def svg(body, width, height):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>OpenMemento</title>{body}</svg>\n'


def outline(text, font, x, y):
    path = QPainterPath()
    path.addText(x, y, font, text)
    commands, i = [], 0
    while i < path.elementCount():
        e = path.elementAt(i)
        if e.isMoveTo():
            commands.append(f"M{e.x:.3f} {e.y:.3f}")
        elif e.isLineTo():
            commands.append(f"L{e.x:.3f} {e.y:.3f}")
        elif e.type == QPainterPath.ElementType.CurveToElement:
            b, c = path.elementAt(i + 1), path.elementAt(i + 2)
            commands.append(f"C{e.x:.3f} {e.y:.3f} {b.x:.3f} {b.y:.3f} {c.x:.3f} {c.y:.3f}")
            i += 2
        i += 1
    return f'<path fill="#204e40" d="{"".join(commands)}"/>', path.boundingRect().right()


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    # Load explicitly: the offscreen Windows platform may have no font database.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("segoeuil.ttf", "segoeuib.ttf"):
        if (fonts / name).is_file():
            QFontDatabase.addApplicationFont(str(fonts / name))
    if "Segoe UI" not in QFontDatabase.families():
        raise RuntimeError("Install Segoe UI to regenerate the outlined wordmark; existing assets remain usable without it.")
    mark = ribbon(("#204e40", "#eda77f", "#285b49"))
    (RESOURCES / "logo-mark.svg").write_text(svg(mark, 544, 320), encoding="utf-8")
    icon = '<rect width="512" height="512" rx="112" fill="#193e32"/>'
    icon += '<g transform="translate(50 128) scale(.76)">' + ribbon(("#fff7e7", "#eda77f", "#dcebd5")) + '</g>'
    (RESOURCES / "memento.svg").write_text(svg(icon, 512, 512), encoding="utf-8")
    light = QFont("Segoe UI", -1, QFont.Weight.Light)
    light.setPixelSize(64)
    light.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -2)
    bold = QFont(light)
    bold.setWeight(QFont.Weight.Bold)
    first, right = outline("Open", light, 147, 80)
    second, right = outline("Memento", bold, right + 3, 80)
    wordmark = '<g transform="translate(0 22) scale(.24)">' + mark + '</g>' + first + second
    (RESOURCES / "logo-wordmark.svg").write_text(svg(wordmark, round(right + 8), 120), encoding="utf-8")
    print("Memory ribbon SVGs and outlined wordmark generated.")


if __name__ == "__main__":
    main()

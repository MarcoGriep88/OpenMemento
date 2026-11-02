"""Presentation-only localization; never translate persisted identifiers or AI data.

German is the source language. Configure before constructing UI widgets at startup.
Changing the saved preference takes effect at the next application start.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from string import Formatter

LANGUAGES = {"en": "English", "de": "Deutsch"}
LANGUAGE_KEY = "ui/language"
_language = "de"


@lru_cache(maxsize=1)
def english_catalog() -> dict[str, str]:
    resources = Path(__file__).parent / "resources"
    catalog = json.loads((resources / "i18n_en.json").read_text(encoding="utf-8"))
    catalog.update(json.loads((resources / "i18n_diagnostics_en.json").read_text(encoding="utf-8")))
    return catalog


@lru_cache(maxsize=1)
def german_diagnostics() -> dict[str, str]:
    path = Path(__file__).parent / "resources" / "i18n_diagnostics_de.json"
    return json.loads(path.read_text(encoding="utf-8"))


def language() -> str:
    return _language


def set_language(value: str) -> None:
    global _language
    if value not in LANGUAGES:
        raise ValueError(f"Unsupported interface language: {value}")
    _language = value


def resolve_language(saved: str | None, system: str) -> str:
    """Honor an explicit choice; use English for unsupported system languages."""
    if saved in LANGUAGES:
        return saved
    return "de" if system.lower().replace("-", "_").split("_")[0] == "de" else "en"


def tr(source: str, *args) -> str:
    text = english_catalog().get(source, source) if _language == "en" else source
    return text.format(*args) if args else text


def date_pattern(*, qt: bool = False, with_time: bool = False) -> str:
    pattern = ("dd.MM.yyyy" if _language == "de" else "yyyy-MM-dd") if qt else (
        "%d.%m.%Y" if _language == "de" else "%Y-%m-%d")
    return pattern + ((" HH:mm:ss" if qt else " %H:%M:%S") if with_time else "")


def format_date(value: date | datetime, *, with_time: bool = False) -> str:
    # Deliberately preserve the recorded wall time; localization is not conversion.
    return value.strftime(date_pattern(with_time=with_time))


def format_number(value: float, decimals: int = 2) -> str:
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if _language == "de" else text


@lru_cache(maxsize=2)
def _message_patterns(code):
    """Match complete application messages, never replace words in user content."""
    patterns = []
    catalog = english_catalog() if code == "en" else german_diagnostics()
    for source, target in catalog.items():
        parts, groups = [], []
        for literal, field, spec, conversion in Formatter().parse(source):
            parts.append(re.escape(literal))
            if field is not None:
                if field in groups:
                    parts.append(f"(?P=v{field})")
                else:
                    parts.append(f"(?P<v{field}>.+?)")
                    groups.append(field)
        if groups:
            patterns.append((re.compile("".join(parts), re.DOTALL), target))
    return patterns


def display_message(message: str) -> str:
    """Translate known service diagnostics at the UI boundary, without changing storage."""
    if not message:
        return message
    catalog = english_catalog() if _language == "en" else german_diagnostics()
    if message in catalog:
        return catalog[message]
    for pattern, target in _message_patterns(_language):
        match = pattern.fullmatch(message)
        if match:
            fields = {int(key[1:]): value for key, value in match.groupdict().items()}
            return target.format(*(fields.get(i, "") for i in range(max(fields) + 1)))
    return message


def configure(settings, app, override: str | None = None) -> str:
    """Initialize locale and Qt's own standard controls, retaining translator ownership."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    selected = resolve_language(override or settings.value(LANGUAGE_KEY, "", type=str), QLocale.system().name())
    set_language(selected)
    QLocale.setDefault(QLocale("de_DE" if selected == "de" else "en_GB"))
    previous = getattr(app, "_memento_translator", None)
    if previous is not None:
        app.removeTranslator(previous)
    translator = QTranslator(app)
    if selected == "de" and translator.load("qtbase_de", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    app._memento_translator = translator
    return selected

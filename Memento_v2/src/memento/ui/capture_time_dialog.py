"""Paged local recording-time review; editing never opens or writes source media."""
from __future__ import annotations

from memento.i18n import tr, display_message, date_pattern

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDate, QTime, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QHeaderView, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTimeEdit, QVBoxLayout,
)


def parse_offset(text):
    text = text.strip()
    if not text:
        return None
    if text.upper() in {"Z", "UTC"}:
        return timezone.utc
    if not re.fullmatch(r"[+-](?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", text):
        raise ValueError(tr("Zeitzone als UTC-Abstand eingeben, zum Beispiel +02:00, oder für unbekannt leer lassen."))
    seconds = int(text[1:3]) * 3600 + int(text[4:6]) * 60 + (int(text[7:9]) if len(text) == 9 else 0)
    return timezone(timedelta(seconds=seconds if text[0] == "+" else -seconds))


class CaptureTimeDialog(QDialog):
    PAGE_SIZE = 200

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library, self.offset, self.assets, self.changed = library, 0, [], False
        self.setWindowTitle(tr("Aufnahmezeiten prüfen"))
        self.resize(920, 600)
        layout = QVBoxLayout(self)
        note = QLabel(tr("Korrigierte Aufnahmezeiten bestimmen den Zeitraum und die Chronologie neuer Filmpläne. Die Korrektur gilt für alle identischen Kopien in der Bibliothek. Bereits gespeicherte Filmpläne behalten ihre Reihenfolge."))
        note.setWordWrap(True)
        layout.addWidget(note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Dateiname oder Ordner suchen …"))
        self.mode = QComboBox()
        for title, value in ((tr("Alle Aufnahmen"), "all"), (tr("Unsichere oder fehlende Zeiten"), "uncertain"),
                             (tr("Ohne Aufnahmezeit"), "missing")):
            self.mode.addItem(title, value)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.mode)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("AUFNAHMEZEIT"), tr("QUELLE"), tr("SICHERHEIT"), tr("DATEI")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        for column in range(3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        pages = QHBoxLayout()
        self.previous_button, self.next_button = QPushButton(tr("Zurück")), QPushButton(tr("Weiter"))
        self.count_label = QLabel()
        pages.addWidget(self.previous_button)
        pages.addWidget(self.count_label, 1)
        pages.addWidget(self.next_button)
        layout.addLayout(pages)
        self.selected_label = QLabel(tr("Eine Aufnahme auswählen."))
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)
        editor = QHBoxLayout()
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat(date_pattern(qt=True))
        self.day.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
        self.clock = QTimeEdit()
        self.clock.setDisplayFormat("HH:mm:ss")
        self.zone = QLineEdit()
        self.zone.setPlaceholderText(tr("Unbekannt"))
        self.zone.setMaximumWidth(130)
        self.zone.setToolTip(tr("UTC-Abstand am Aufnahmeort, z. B. +02:00. Leer = unbekannt. Keine automatische Ortszeitumrechnung."))
        self.save_button = QPushButton(tr("Aufnahmezeit speichern"))
        editor.addWidget(QLabel(tr("Datum")))
        editor.addWidget(self.day)
        editor.addWidget(self.clock)
        editor.addWidget(QLabel(tr("UTC-Abstand")))
        editor.addWidget(self.zone)
        editor.addWidget(self.save_button)
        layout.addLayout(editor)
        self.status = QLabel(tr("Originaldateien werden nicht verändert. Unbekannte Zeitzonen werden nicht ergänzt."))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.reset_page)
        self.search.textChanged.connect(lambda: self.timer.start())
        self.mode.currentIndexChanged.connect(self.reset_page)
        self.previous_button.clicked.connect(lambda: self.turn_page(-1))
        self.next_button.clicked.connect(lambda: self.turn_page(1))
        self.table.itemSelectionChanged.connect(self.select_asset)
        self.save_button.clicked.connect(self.save_time)
        self.refresh()

    def reset_page(self, *_):
        self.offset = 0
        self.refresh()

    def turn_page(self, direction):
        self.offset = max(0, self.offset + direction * self.PAGE_SIZE)
        self.refresh()

    def refresh(self):
        self.assets, total = self.library.review_capture_times(
            self.search.text(), self.mode.currentData(), self.offset, self.PAGE_SIZE)
        if self.offset and not self.assets:
            self.offset = max(0, ((total - 1) // self.PAGE_SIZE) * self.PAGE_SIZE)
            self.assets, total = self.library.review_capture_times(
                self.search.text(), self.mode.currentData(), self.offset, self.PAGE_SIZE)
        self.table.clearSelection()
        self.table.setRowCount(len(self.assets))
        for row, asset in enumerate(self.assets):
            capture = asset.capture_time
            values = (capture.value.isoformat(sep=" ") if capture else tr("Unbekannt"),
                      capture.source.value if capture else "–",
                      (tr("Manuell bestätigt") if capture.source.value == "manual" else f"{capture.confidence:.0%}") if capture else "–",
                      asset.path.name)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(asset.path) if column == 3 else value)
                self.table.setItem(row, column, item)
        self.count_label.setText(tr("{0}–{1} von {2} Aufnahmen", self.offset + 1 if total else 0, self.offset + len(self.assets), total))
        self.previous_button.setEnabled(self.offset > 0)
        self.next_button.setEnabled(self.offset + len(self.assets) < total)
        self.select_asset()

    def select_asset(self):
        row = self.table.currentRow() if self.table.selectedItems() else -1
        enabled = 0 <= row < len(self.assets)
        for widget in (self.day, self.clock, self.zone, self.save_button):
            widget.setEnabled(enabled)
        if not enabled:
            self.selected_label.setText(tr("Eine Aufnahme auswählen."))
            return
        asset = self.assets[row]
        self.selected_label.setText(str(asset.path))
        # No implicit conversion through the workstation's local timezone.
        value = asset.capture_time.value if asset.capture_time else datetime.now().replace(microsecond=0)
        self.day.setDate(QDate(value.year, value.month, value.day))
        self.clock.setTime(QTime(value.hour, value.minute, value.second))
        offset = value.utcoffset()
        if offset is None:
            self.zone.clear()
        else:
            seconds = int(offset.total_seconds())
            if seconds % 60:
                # Preserve unusual historical offsets until explicitly edited.
                self.zone.setText(value.isoformat()[-9:])
            else:
                minutes = abs(seconds) // 60
                self.zone.setText(f"{'+' if seconds >= 0 else '-'}{minutes // 60:02d}:{minutes % 60:02d}")

    def save_time(self):
        row = self.table.currentRow()
        if not self.table.selectedItems() or not 0 <= row < len(self.assets):
            return
        try:
            value = datetime.combine(self.day.date().toPython(), self.clock.time().toPython(), parse_offset(self.zone.text()))
            previous = self.assets[row].capture_time
            if previous and value.time().replace(microsecond=0) == previous.value.time().replace(microsecond=0):
                value = value.replace(microsecond=previous.value.microsecond)
            self.library.set_manual_capture_time(self.assets[row].asset_id, value)
        except (ValueError, KeyError, sqlite3.Error) as exc:
            QMessageBox.warning(self, tr("Aufnahmezeit nicht gespeichert"), display_message(str(exc)))
            return
        self.changed = True
        self.status.setText(tr("Aufnahmezeit lokal gespeichert. Für einen vorhandenen Film bitte die Auswahl neu planen, um die neue Chronologie zu verwenden."))
        self.refresh()

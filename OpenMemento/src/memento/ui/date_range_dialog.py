"""Inspect a bounded page of recordings without reading media or semantic data."""
from __future__ import annotations

from memento.i18n import tr, format_date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHeaderView, QHBoxLayout, QLabel, QPushButton,
    QTableView, QVBoxLayout,
)


class RecordingTableModel(QAbstractTableModel):
    HEADERS = ("AUFNAHMEZEIT", "DATUMSQUELLE", "SICHERHEIT", "DATEI")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets = ()

    def set_assets(self, assets):
        self.beginResetModel()
        self.assets = assets
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.assets)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal
                and 0 <= section < len(self.HEADERS)):
            return tr(self.HEADERS[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.assets) or not 0 <= index.column() < 4:
            return None
        asset = self.assets[index.row()]
        capture = asset.capture_time
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(asset.path) if index.column() == 3 else capture.value.isoformat(sep=" ")
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.column() == 0:
            return format_date(capture.value, with_time=True)
        if index.column() == 1:
            return capture.source.value
        if index.column() == 2:
            return f"{capture.confidence:.0%}" + (tr(" · ohne Zeitzone") if capture.value.utcoffset() is None else "")
        return asset.path.name


class DateRangeDialog(QDialog):
    PAGE_SIZE = 200

    def __init__(self, library, start, end, parent=None, *, initial_page=None):
        super().__init__(parent)
        self.library, self.start, self.end = library, start, end
        self.setWindowTitle(tr("Aufnahmen im Zeitraum"))
        self.resize(860, 480)
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.model = RecordingTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.previous_button.clicked.connect(lambda: self.refresh(self.page.offset - self.PAGE_SIZE))
        self.next_button.clicked.connect(lambda: self.refresh(self.page.offset + self.PAGE_SIZE))
        self.show_page(initial_page if initial_page is not None else
                       library.capture_date_page(start, end, limit=self.PAGE_SIZE))

    def refresh(self, offset=0):
        self.show_page(self.library.capture_date_page(self.start, self.end, offset=max(0, offset), limit=self.PAGE_SIZE))

    def show_page(self, page):
        self.page = page
        self.model.set_assets(page.assets)
        self.note.setText(tr("{0} Aufnahmen · {1} bis {2} · {3} Videos ohne bekanntes Aufnahmedatum", page.total, format_date(self.start), format_date(self.end), page.unknown))
        self.count_label.setText(tr("{0}–{1} von {2} Aufnahmen", page.offset + 1 if page.total else 0, page.offset + len(page.assets), page.total))
        self.previous_button.setEnabled(page.offset > 0)
        self.next_button.setEnabled(page.offset + len(page.assets) < page.total)

"""Inspect cached moments and edit constraints without regenerating a timeline."""
from __future__ import annotations

from memento.i18n import tr, display_message, format_date

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QPushButton,
    QTableView, QVBoxLayout,
)


class CandidateTableModel(QAbstractTableModel):
    """Read rows on demand; large libraries need no item widget per cell."""

    HEADERS = ("MOMENT", "QUELLE / BEREICH", "AUSSCHLIESSEN", "ERZWINGEN", "ENTSCHEIDUNG")

    def __init__(self, plan, candidates, parent=None):
        super().__init__(parent)
        self.preferences = deepcopy(plan.preferences)
        self.candidates = {item.candidate_id: item for item in candidates}
        known = set(plan.decisions) | {key for event in plan.events for key in event.candidate_ids}
        known |= self.preferences.forced | self.preferences.excluded | self.preferences.trims.keys()
        self.keys = list(self.candidates) + sorted(known - self.candidates.keys())
        self.segments = {item.candidate_id: item for item in plan.segments}
        self.decisions = dict(plan.decisions)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.keys)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def _decision_text(self, key):
        original = self.decisions.get(key)
        if original is None:
            return tr("Noch keine Auswahlentscheidung für diesen Moment.")
        segment = self.segments.get(key)
        if segment and original.startswith("Ausgewählt: "):
            return tr("Ausgewählt: {0}", "; ".join(display_message(reason) for reason in segment.reasons))
        return display_message(original)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(self.HEADERS[section]) if 0 <= section < len(self.HEADERS) else None
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.keys):
            return None
        key = self.keys[index.row()]
        candidate = self.candidates.get(key)
        segment = self.segments.get(key)
        if role == Qt.ItemDataRole.CheckStateRole and index.column() in (2, 3):
            values = self.preferences.excluded if index.column() == 2 else self.preferences.forced
            return Qt.CheckState.Checked if key in values else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            trim = self.preferences.trims.get(key)
            return "\n".join(filter(None, (
                key, candidate.source.path if candidate else segment.source.path if segment else None,
                tr("Manueller Schnitt: {0}–{1} s", format(trim[0], f'.3f'), format(trim[1], f'.3f')) if trim else None,
                tr("Nicht im aktuellen Analysebestand. Gespeicherte Vorgaben können entfernt werden.") if not candidate else None,
                self._decision_text(key) if key in self.decisions else None,
            )))
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.column() == 0:
            if candidate:
                return f"{format_date(candidate.recorded_at, with_time=True)} · {candidate.description}"
            return tr("Nicht im aktuellen Analysebestand · {0}", segment.description if segment else key)
        if index.column() == 1:
            item = candidate or segment
            if item:
                bounds = self.preferences.trims.get(key, (item.start_seconds, item.end_seconds))
                return f"{Path(item.source.path).name} · {bounds[0]:.3f}–{bounds[1]:.3f} s"
            return ""
        if index.column() == 4:
            return self._decision_text(key)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in (2, 3):
            key = self.keys[index.row()]
            # A missing forced range may be cleared, but cannot be newly forced.
            if index.column() == 2 or key in self.candidates or key in self.preferences.forced:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (not index.isValid() or role != Qt.ItemDataRole.CheckStateRole
                or not self.flags(index) & Qt.ItemFlag.ItemIsUserCheckable):
            return False
        key = self.keys[index.row()]
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        values, other = ((self.preferences.excluded, self.preferences.forced) if index.column() == 2
                         else (self.preferences.forced, self.preferences.excluded))
        if checked:
            values.add(key)
            other.discard(key)
        else:
            values.discard(key)
        self.dataChanged.emit(self.index(index.row(), 2), self.index(index.row(), 3), [Qt.ItemDataRole.CheckStateRole])
        return True

    def clear_trim(self, row):
        if 0 <= row < len(self.keys):
            self.preferences.trims.pop(self.keys[row], None)
            self.dataChanged.emit(self.index(row, 0), self.index(row, 4))


class CandidateDialog(QDialog):
    def __init__(self, plan, candidates, warnings=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Momente und Auswahlentscheidungen"))
        self.resize(1100, 600)
        layout = QVBoxLayout(self)
        explanation = QLabel(tr("Vorgaben ändern die Segmentauswahl erst beim Neuplanen. Die angezeigten Auswahlgründe stammen aus der letzten Planung."))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.model = CandidateTableModel(plan, candidates, self)
        missing = len(self.model.keys) - len(self.model.candidates)
        notes = list(warnings)
        if missing:
            missing_text = (tr("Ein gespeicherter Moment fehlt") if missing == 1 else tr("{0} gespeicherte Momente fehlen", missing))
            notes.insert(0, tr("{0} im aktuellen Analysebestand. Vorhandene Schnittbereiche im Film bleiben erhalten; fehlende erzwungene Vorgaben vor dem Neuplanen entfernen.", missing_text))
        note = QLabel("\n".join(display_message(message) for message in notes))
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(note)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(2, 145)
        self.table.setColumnWidth(3, 115)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        reset = QPushButton(tr("Manuelle Schnittvorgabe des gewählten Moments zurücksetzen"))
        reset.clicked.connect(lambda: self.model.clear_trim(self.table.currentIndex().row()))
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Vorgaben übernehmen"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Abbrechen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

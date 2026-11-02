"""Inspect actual event allocation before changing the automatic first cut."""
from __future__ import annotations

from memento.i18n import tr, format_number

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QTableView, QVBoxLayout

from memento.domain.movie_review import review_events


class EventReviewModel(QAbstractTableModel):
    HEADERS = ("EREIGNIS", "DAUER (s)", "FILMANTEIL", "AUSGEWÄHLT / BEKANNT", "AUSGESCHLOSSEN", "ERZWUNGEN", "GEWICHT", "VORGABEN PRÜFEN")

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.reviews = review_events(plan)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.reviews)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(self.HEADERS[section]) if 0 <= section < len(self.HEADERS) else None
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.reviews[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            seconds = format_number(item.duration_seconds, 3)
            return (tr("{0}\n{1} Sekunden im aktuellen Film.\nErzwungen, aber nicht enthalten: {2}\nAusgeschlossen, aber noch enthalten: {3}\nAbweichende manuelle Schnittvorgaben: {4}\nGewichte gelten bei der nächsten Neuplanung. Bekannte Momente können inzwischen fehlen oder überlappen.", item.title, seconds, item.pending_forced, item.pending_excluded, item.pending_trims))
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return (item.title, format_number(item.duration_seconds, 1), format_number(item.share * 100, 1) + " %",
                f"{item.selected_moments} / {item.known_moments}", str(item.excluded_moments),
                str(item.forced_moments), format_number(item.weight, 2),
                f"{item.pending} {tr("Abweichung") if item.pending == 1 else tr("Abweichungen")}" if item.pending
                else tr("Keine"))[index.column()]


class EventReviewDialog(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Ereignisse und Zeitverteilung"))
        self.resize(1200, 580)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            tr("Die Übersicht misst die aktiven Segmente des aktuellen Films. Bekannte Momente stammen aus dem gespeicherten Plan; sie sind keine Zusage, dass alle Bereiche noch verfügbar oder miteinander kombinierbar sind. Gewichte und Ein-/Ausschlüsse wirken bei der nächsten Neuplanung. Die Gewichte sind keine festen Zeitbudgets.")
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        known = {key for event in plan.events for key in event.candidate_ids}
        unassigned = (plan.preferences.forced | plan.preferences.excluded | plan.preferences.trims.keys()) - known
        self.unassigned_notice = QLabel()
        self.unassigned_notice.setWordWrap(True)
        if unassigned:
            subject = tr("Eine Momentvorgabe ist") if len(unassigned) == 1 else tr("{0} Momentvorgaben sind", len(unassigned))
            self.unassigned_notice.setText(tr("{0} keinem gespeicherten Ereignis zugeordnet. Im Dialog „Momente ein-/ausschließen“ prüfen und gegebenenfalls entfernen.", subject))
        self.unassigned_notice.setVisible(bool(unassigned))
        layout.addWidget(self.unassigned_notice)
        self.model = EventReviewModel(plan, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 200)
        for column, width in ((1, 100), (2, 110), (3, 200), (4, 160), (5, 125), (6, 100)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.details = QLabel(tr("Ein Ereignis auswählen, um offene Vorgaben zu prüfen."))
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.details)
        self.table.selectionModel().currentRowChanged.connect(self.selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("Schließen"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self, current, previous):
        if current.isValid():
            self.details.setText(self.model.data(current, Qt.ItemDataRole.ToolTipRole))

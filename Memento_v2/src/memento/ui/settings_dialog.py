from __future__ import annotations

from memento.i18n import LANGUAGES, LANGUAGE_KEY, language, tr, display_message

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from memento.security.credentials import (
    CredentialStoreError,
    delete_gemini_key,
    has_gemini_key,
    save_gemini_key,
)


DEFAULT_MODEL = "gemini-3.8-flash"


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Einstellungen"))
        self.setMinimumWidth(540)
        self.settings = QSettings()
        self._build_ui()
        self._refresh_key_status()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        language_form = QFormLayout()
        self.language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(
            self.settings.value(LANGUAGE_KEY, language(), type=str)))
        if self.language_combo.currentIndex() < 0:
            self.language_combo.setCurrentIndex(self.language_combo.findData(language()))
        language_form.addRow(tr("Sprache / Language"), self.language_combo)
        layout.addLayout(language_form)
        restart_note = QLabel(tr("Die Sprache wird beim nächsten Start übernommen. Laufende Aufträge werden nicht unterbrochen."))
        restart_note.setWordWrap(True)
        restart_note.setObjectName("mutedLabel")
        layout.addWidget(restart_note)
        heading = QLabel(tr("KI-Analyse"))
        heading.setObjectName("dialogHeading")
        layout.addWidget(heading)

        form = QFormLayout()
        self.provider = QLabel("Google Gemini")
        form.addRow(tr("Anbieter"), self.provider)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems([DEFAULT_MODEL, "gemini-3.5-flash"])
        self.model.setCurrentText(
            self.settings.value("ai/model", DEFAULT_MODEL, type=str)
        )
        form.addRow(tr("Modell"), self.model)

        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(tr("Neuen Schlüssel hier einfügen"))
        self.api_key.setClearButtonEnabled(True)
        key_row.addWidget(self.api_key, 1)
        self.delete_key_button = QPushButton(tr("Schlüssel löschen"))
        self.delete_key_button.clicked.connect(self._delete_key)
        key_row.addWidget(self.delete_key_button)
        form.addRow(tr("API-Schlüssel"), key_row)
        layout.addLayout(form)

        self.key_status = QLabel()
        self.key_status.setObjectName("mutedLabel")
        layout.addWidget(self.key_status)

        privacy = QLabel(
            tr("Der Schlüssel wird im sicheren Betriebssystem-Schlüsselspeicher abgelegt (unter Linux Secret Service oder KDE Wallet). Erst mit „An Google senden“ im Analysedialog überträgt Memento ausgewählte, lokal verkleinerte Videoabschnitte mit Ton direkt an Google Gemini. Das kann Kosten in deinem Google-Konto verursachen.")
        )
        privacy.setObjectName("noticeCard")
        privacy.setWordWrap(True)
        privacy.setTextFormat(Qt.TextFormat.PlainText)
        # Leave room for the longer German notice at the minimum dialog width.
        privacy.setMinimumHeight(privacy.fontMetrics().lineSpacing() * 8 + 24)
        layout.addWidget(privacy)

        help_link = QLabel(
            tr("<a style=\"color:#8ee0cf\" href=\"https://aistudio.google.com/app/apikey\">Gemini-Schlüssel in Google AI Studio erstellen</a>")
        )
        help_link.setObjectName("helpLink")
        help_link.setOpenExternalLinks(True)
        layout.addWidget(help_link)

        self.status_message = QLabel()
        self.status_message.setWordWrap(True)
        self.status_message.setObjectName("mutedLabel")
        layout.addWidget(self.status_message)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Speichern"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Abbrechen"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_key_status(self):
        try:
            saved = has_gemini_key()
        except CredentialStoreError as exc:
            self.key_status.setText(display_message(str(exc)))
            self.api_key.setEnabled(False)
            self.delete_key_button.setEnabled(False)
            return
        self.key_status.setText(
            tr("Ein Gemini-Schlüssel ist sicher gespeichert.")
            if saved
            else tr("Noch kein Gemini-Schlüssel gespeichert.")
        )
        self.delete_key_button.setEnabled(saved)

    def _save(self):
        secret = self.api_key.text()
        model = self.model.currentText().strip()
        if not model:
            QMessageBox.warning(self, tr("Modell fehlt"), tr("Bitte ein Modell angeben."))
            return
        if secret:
            try:
                save_gemini_key(secret)
            except (CredentialStoreError, ValueError) as exc:
                QMessageBox.warning(self, tr("Schlüssel nicht gespeichert"), display_message(str(exc)))
                return
        self.settings.setValue("ai/model", model)
        self.settings.setValue(LANGUAGE_KEY, self.language_combo.currentData())
        self.api_key.clear()
        self.accept()

    def _delete_key(self):
        box = QMessageBox(self)
        box.setWindowTitle(tr("Gemini-Schlüssel löschen"))
        box.setText(
            tr("Soll der gespeicherte Gemini-Schlüssel aus dem Betriebssystem-Schlüsselspeicher gelöscht werden?")
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.button(QMessageBox.StandardButton.Yes).setText(tr("Löschen"))
        box.button(QMessageBox.StandardButton.No).setText(tr("Abbrechen"))
        answer = box.exec()
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_gemini_key()
        except CredentialStoreError as exc:
            QMessageBox.warning(self, tr("Schlüssel nicht gelöscht"), display_message(str(exc)))
            return
        self._refresh_key_status()
        self.status_message.setText(tr("Der gespeicherte Schlüssel wurde gelöscht."))

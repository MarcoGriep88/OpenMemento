"""White and mint presentation shared by the desktop shell and its dialogs."""
from PySide6.QtGui import QColor, QPalette


TEXT = "#263b46"
WARNING = "#8a5318"


def light_palette() -> QPalette:
    """Set native controls too, independently of the operating system theme."""
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f7faf9",
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f2f7f6",
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: "#ccefe5",
        QPalette.ColorRole.HighlightedText: "#174e43",
        QPalette.ColorRole.Link: "#256b5d",
        QPalette.ColorRole.LinkVisited: "#256b5d",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: "#637780",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#edf4f1",
        QPalette.ColorRole.Mid: "#c9d9d3",
        QPalette.ColorRole.Dark: "#7c9188",
        QPalette.ColorRole.Shadow: "#c9d9d3",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#718079"))
    return palette


APP_STYLE = """
QMainWindow, QDialog, QWidget#workflowPage { background: #f7faf9; }
QWidget { color: #263b46; font-family: "Segoe UI"; font-size: 10pt; }
QFrame#sidebar { background: #f0f7f4; border-right: 1px solid #d9e5df; }
QLabel#brand { color: #256b5d; font-size: 17pt; font-weight: 700; }
QLabel#eyebrow { color: #546d75; font-size: 9pt; font-weight: 600; letter-spacing: 1px; }
QLabel#pageTitle { color: #263b46; font-size: 25pt; font-weight: 650; }
QLabel#mutedLabel { color: #576e77; }
QLabel#statValue { color: #263b46; font-size: 18pt; font-weight: 650; }
QFrame#card, QFrame#heroCard, QFrame#noticeCard {
    background: #ffffff; border: 1px solid #d9e5df; border-radius: 12px;
}
QFrame#heroCard { background: #e5f5ee; border-color: #b8ded0; }
QPushButton {
    background: #ffffff; color: #263b46; border: 1px solid #c9d9d3;
    border-radius: 8px; padding: 9px 13px;
}
QPushButton:hover { background: #edf7f2; border-color: #83b9a5; }
QPushButton:pressed { background: #d7eee3; }
QPushButton:focus { border: 2px solid #256b5d; padding: 8px 12px; }
QPushButton#primaryButton {
    background: #256b5d; color: #ffffff; border: 1px solid #256b5d;
    font-weight: 700; padding: 11px 16px;
}
QPushButton#primaryButton:hover { background: #1d594d; }
QPushButton#primaryButton:pressed { background: #164b40; }
QPushButton#primaryButton:focus { border: 2px solid #83ddca; padding: 10px 15px; }
QPushButton#navButton {
    text-align: left; background: transparent; border: 1px solid transparent;
    padding: 11px 12px; color: #425e66;
}
QPushButton#navButton:hover { background: #e3f1e9; }
QPushButton#navButton:checked { background: #d7f0e7; color: #175746; font-weight: 650; }
QPushButton#navButton:focus { border-color: #256b5d; }
QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit, QPlainTextEdit {
    background: #ffffff; color: #263b46; border: 1px solid #c9d9d3;
    border-radius: 6px; padding: 7px; selection-background-color: #ccefe5;
    selection-color: #174e43;
}
QDateEdit:focus, QTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus { border-color: #256b5d; }
QComboBox QAbstractItemView { background: #ffffff; color: #263b46; selection-background-color: #ccefe5; selection-color: #174e43; }
QProgressBar { background: #edf4f1; border: 1px solid #c9d9d3; border-radius: 6px; text-align: center; padding: 2px; }
QProgressBar::chunk { background: #83ddca; border-radius: 4px; }
QTableWidget, QTableView {
    background: #ffffff; alternate-background-color: #f2f7f6;
    border: 1px solid #d9e5df; border-radius: 9px; gridline-color: #e5ede9;
    selection-background-color: #ccefe5; selection-color: #174e43;
}
QHeaderView::section { background: #edf5f1; color: #4e6871; border: 0; border-bottom: 1px solid #d9e5df; padding: 9px; }
QTableCornerButton::section { background: #edf5f1; border: 0; }
QTableView::item { padding: 4px 8px; }
QStatusBar { background: #edf5f1; color: #576e77; }
QLabel#dialogHeading { font-size: 17pt; font-weight: 650; }
QLabel#noticeCard { padding: 12px; background: #e8f5ef; color: #345e52; border-radius: 10px; }
QToolTip { background: #ffffff; color: #263b46; border: 1px solid #c9d9d3; padding: 5px; }
QPushButton:disabled, QPushButton#primaryButton:disabled {
    color: #718079; background: #edf2ef; border: 1px solid #d9e5df;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled { color: #718079; background: #f0f4f2; }
"""

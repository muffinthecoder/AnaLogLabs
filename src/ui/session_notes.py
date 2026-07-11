from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QFileDialog


class SessionNotesWidget(QWidget):
    # Emitted with the saved file path on a successful export — MainWindow
    # uses this to surface a toast, without SessionNotesWidget needing to
    # know anything about toasts itself.
    notes_exported = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.notes_area = QTextEdit()
        self.notes_area.setPlaceholderText("Enter key findings...")
        self.notes_area.setStyleSheet("""
            QTextEdit {
                background-color: #101a30;
                color: #c8d3ea;
                border: 1px solid #1c2740;
                border-radius: 7px;
                padding: 8px;
                font-size: 11px;
            }
            QTextEdit:focus {
                border-color: #2e8fff;
            }
        """)
        layout.addWidget(self.notes_area)

        self.export_btn = QPushButton("Export Session Notes")
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #101a30;
                color: #2e8fff;
                border: 1px solid #2e8fff;
                border-radius: 7px;
                padding: 7px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #2e8fff; color: #04101f; }
        """)
        self.export_btn.clicked.connect(self._export_notes)
        layout.addWidget(self.export_btn)
        self.notes_area.setAcceptDrops(True)

    def _export_notes(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Notes", "session_notes.txt", "Text Files (*.txt)")
        if filename:
            with open(filename, "w") as f:
                f.write(self.notes_area.toPlainText())
            self.notes_exported.emit(filename)
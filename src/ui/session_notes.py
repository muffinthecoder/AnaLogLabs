'''

Owned by: Hiba

'''


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

        # Themeable — this widget had hardcoded dark-blue colors (#101a30 /
        # #2e8fff) that bypassed the theme system entirely, which is exactly
        # what showed up as "random blue" in a light theme. Defaults match
        # what shipped before theming existed.
        self._bg_input = "#101a30"
        self._text_primary = "#c8d3ea"
        self._border = "#1c2740"
        self._accent = "#2e8fff"
        self._accent_contrast_text = "#04101f"

        self.notes_area = QTextEdit()
        self.notes_area.setPlaceholderText("Enter key findings...")
        layout.addWidget(self.notes_area)

        self.export_btn = QPushButton("Export Session Notes")
        self.export_btn.clicked.connect(self._export_notes)
        layout.addWidget(self.export_btn)
        self.notes_area.setAcceptDrops(True)

        self._apply_style()

    def _apply_style(self) -> None:
        self.notes_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {self._bg_input};
                color: {self._text_primary};
                border: 1px solid {self._border};
                border-radius: 7px;
                padding: 8px;
                font-size: 12px;
            }}
            QTextEdit:focus {{
                border-color: {self._accent};
            }}
        """)
        self.export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._bg_input};
                color: {self._accent};
                border: 1px solid {self._accent};
                border-radius: 7px;
                padding: 7px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {self._accent}; color: {self._accent_contrast_text}; }}
        """)

    def set_theme(self, theme: dict) -> None:
        self._bg_input = theme["bg_input"]
        self._text_primary = theme["text_primary"]
        self._border = theme["border"]
        self._accent = theme["accent"]
        self._accent_contrast_text = theme["accent_contrast_text"]
        self._apply_style()

    def _export_notes(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Notes", "session_notes.txt", "Text Files (*.txt)")
        if filename:
            with open(filename, "w") as f:
                f.write(self.notes_area.toPlainText())
            self.notes_exported.emit(filename)
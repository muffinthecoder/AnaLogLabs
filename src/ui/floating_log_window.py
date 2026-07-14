"""
floating_log_window.py — R1 free-floating log window.

Hosts a LogWindowWidget as a genuine top-level desktop window so the
investigator can drag it anywhere on screen, including onto a second monitor,
fully independent of the AnaLog Labs main window (unlike the MDI sub-windows,
which are clipped to the workspace area).

MainWindow owns the reparenting: it pulls a panel out of its QMdiSubWindow,
wraps it here, and can later dock it back. This class only provides the
floating chrome (a slim toolbar with a "Dock back" button) and reports two
events:
    redock_requested — the user asked to snap this panel back into the app.
    closed           — the floating window's own X was clicked; MainWindow
                       treats this like closing the panel entirely.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)


class FloatingLogWindow(QMainWindow):
    """A top-level window wrapping one LogWindowWidget (R1)."""

    redock_requested = Signal(str)  # source_label
    closed = Signal(str)            # source_label

    def __init__(self, panel, source_label: str, theme: dict | None = None, parent=None):
        # parent=None makes this a real independent OS window rather than a
        # child clipped to the main window. WA_DeleteOnClose keeps us from
        # leaking hidden windows as panels are popped out and closed.
        super().__init__(parent)
        self.source_label = source_label
        self.panel = panel
        self._redocking = False

        # Themeable — being a genuine top-level window (not a child of
        # MainWindow), this never inherited MainWindow's stylesheet even
        # before hardcoded colors were the problem; it always needed its own
        # explicit theming, which it never got. set_theme() below is called
        # both here at construction and again by MainWindow on a live switch.
        self._theme_text = "#000000"
        self._theme_bg = "#102120"
        self._theme_text_on_bg = "#ffffff"
        self._theme_accent = "#00c4e8"

        self.setWindowTitle(f"AnaLog Labs — {source_label}")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(680, 500)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        toolbar.setObjectName("FloatingToolbar")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 4, 8, 4)

        self._title_label = QLabel(f"⧉ {source_label} (floating)")
        tb.addWidget(self._title_label)
        tb.addStretch()

        self._dock_button = QPushButton("Dock back into app")
        self._dock_button.clicked.connect(lambda: self.redock_requested.emit(self.source_label))
        tb.addWidget(self._dock_button)

        layout.addWidget(toolbar)
        layout.addWidget(panel, stretch=1)
        self.setCentralWidget(central)

        self.set_theme(theme) if theme is not None else self._apply_style()

    def _apply_style(self) -> None:
        self._title_label.setStyleSheet(f"font-size: 12px; color: {self._theme_text};")
        self._dock_button.setStyleSheet(
            f"background-color: {self._theme_bg}; color: {self._theme_text_on_bg}; "
            f"border: 1px solid {self._theme_accent}; font-size: 11px; "
            "border-radius: 3px; padding: 2px 8px;"
        )

    def set_theme(self, theme: dict) -> None:
        self._theme_text = theme["text_primary"]
        self._theme_bg = theme["bg_input"]
        self._theme_text_on_bg = theme["text_primary"]
        self._theme_accent = theme["accent"]
        self._apply_style()

    def prepare_redock(self) -> None:
        """Call before pulling the panel back out, so the subsequent close()
        does NOT fire `closed` (which MainWindow treats as "remove the log").
        """
        self._redocking = True

    def closeEvent(self, event) -> None:
        # A plain top-level window does not propagate closeEvent to child
        # widgets the way a QMdiSubWindow does, so we surface it explicitly.
        if not self._redocking:
            self.closed.emit(self.source_label)
        super().closeEvent(event)
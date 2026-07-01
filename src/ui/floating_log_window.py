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

    def __init__(self, panel, source_label: str, parent=None):
        # parent=None makes this a real independent OS window rather than a
        # child clipped to the main window. WA_DeleteOnClose keeps us from
        # leaking hidden windows as panels are popped out and closed.
        super().__init__(parent)
        self.source_label = source_label
        self.panel = panel
        self._redocking = False

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

        title = QLabel(f"⧉ {source_label} (floating)")
        title.setStyleSheet("font-size: 11px; color: #8090b0;")
        tb.addWidget(title)
        tb.addStretch()

        dock_button = QPushButton("Dock back into app")
        dock_button.setStyleSheet(
            "background-color: transparent; color: #00c4e8; "
            "border: 1px solid #00c4e8; font-size: 10px; "
            "border-radius: 3px; padding: 2px 8px;"
        )
        dock_button.clicked.connect(lambda: self.redock_requested.emit(self.source_label))
        tb.addWidget(dock_button)

        layout.addWidget(toolbar)
        layout.addWidget(panel, stretch=1)
        self.setCentralWidget(central)

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

"""
locked_workspace.py — the "Sync Scroll" locked line.

When Sync Scroll is enabled (a valid time range must already be set), every open
log panel is snapped side-by-side into this one container ("locked in a straight
line") and can no longer be dragged/moved. Unlike the earlier unified view, this
is deliberately NOT a single shared scrollbar: each panel keeps its OWN vertical
scrollbar and can be scrolled independently — the panels are kept in step by
ScrollSyncManager (MainWindow wires each panel's `scrolled` signal to it), which
aligns every other panel to the nearest timestamp of whichever one the
investigator scrolls. Turning Sync Scroll off returns the panels to the normal
movable MDI workspace.

This widget is purely the side-by-side CONTAINER; all the timestamp-sync logic
lives in ScrollSyncManager.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


class LockedWorkspace(QWidget):
    """Side-by-side ("straight line") container of all panels while sync is on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: dict[str, object] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self._layout = root

        self._placeholder = QLabel("No log panels to lock.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #ffffff; font-size: 12px;")
        self._layout.addWidget(self._placeholder)

    def set_panels(self, panels: dict) -> None:
        """Reparent every panel into this container, side by side. Each keeps
        its OWN vertical scrollbar (ScrollSyncManager keeps them in step).
        """
        self._panels = dict(panels)
        if self._placeholder.parent() is not None:
            self._placeholder.setParent(None)
        for panel in self._panels.values():
            # Individual scrollbars stay VISIBLE — panels scroll separately and
            # are re-aligned by timestamp via ScrollSyncManager.
            panel.table_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._layout.addWidget(panel, stretch=1)
            panel.show()

    def release_panels(self) -> dict:
        """Detach the panels and return them so MainWindow can put them back
        into movable MDI sub-windows.
        """
        released = dict(self._panels)
        for panel in self._panels.values():
            panel.setParent(None)
        self._panels = {}
        self._layout.addWidget(self._placeholder)
        return released

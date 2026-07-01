"""
locked_workspace.py — R7 "lock windows" unified view.

When the investigator clicks "Lock windows", every open log panel is snapped
side-by-side into this single container ("like a puzzle piece"), their
individual vertical scrollbars are hidden, and ONE master scrollbar on the
right drives them all together. Movement stays timestamp-aligned (reusing
ScrollSyncManager), so logs with very different event densities still line up
by the moment in time rather than by row count.

MainWindow hands the actual LogWindowWidget objects in via set_panels() and
takes them back with release_panels() when lock mode is switched off — the
panels themselves are never recreated, only reparented.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QScrollBar, QLabel

from src.correlator.scroll_sync_manager import ScrollSyncManager


class LockedWorkspace(QWidget):
    """Side-by-side, single-scrollbar locked view of all log panels (R7)."""

    def __init__(self, scroll_sync_manager: ScrollSyncManager, parent=None):
        super().__init__(parent)
        self._sync = scroll_sync_manager
        self._panels: dict[str, object] = {}
        self._anchor_source: str | None = None
        self._syncing = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # Holds the panels laid out left-to-right.
        self._panels_container = QWidget()
        self._panels_layout = QHBoxLayout(self._panels_container)
        self._panels_layout.setContentsMargins(0, 0, 0, 0)
        self._panels_layout.setSpacing(2)
        root.addWidget(self._panels_container, stretch=1)

        # The single unified scrollbar on the far right.
        self._master = QScrollBar(Qt.Vertical)
        self._master.setSingleStep(1)
        self._master.valueChanged.connect(self._on_master_scroll)
        root.addWidget(self._master)

        self._placeholder = QLabel("Lock windows requires at least 2 log panels.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #4a5a7a; font-size: 12px;")
        self._panels_layout.addWidget(self._placeholder)

    # -- Lifecycle -------------------------------------------------------------

    def set_panels(self, panels: dict) -> None:
        """Reparents every panel into this container and rewires scrolling.

        panels: source_label -> LogWindowWidget (insertion order preserved).
        """
        self._panels = dict(panels)

        # Drop the placeholder if it's showing.
        if self._placeholder.parent() is not None:
            self._placeholder.setParent(None)

        for source_label, panel in self._panels.items():
            # Hide the panel's own vertical scrollbar — the master owns
            # vertical movement in lock mode.
            panel.table_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            # Register with the shared sync manager so timestamp alignment
            # works, and mirror wheel scrolls back onto the master bar.
            self._sync.register_window(source_label, panel)
            panel.scrolled.connect(self._on_child_scrolled)
            self._panels_layout.addWidget(panel, stretch=1)
            panel.show()

        self._pick_anchor()
        self._configure_master()

    def release_panels(self) -> dict:
        """Undoes set_panels(): restores each panel's own scrollbar, detaches
        it from this container, and returns the panels so MainWindow can put
        them back into MDI sub-windows. The sync manager is left as MainWindow
        configures it afterward.
        """
        released = dict(self._panels)
        for source_label, panel in self._panels.items():
            try:
                panel.scrolled.disconnect(self._on_child_scrolled)
            except (TypeError, RuntimeError):
                pass  # already disconnected
            panel.table_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            panel.setParent(None)
        self._panels = {}
        self._anchor_source = None

        # Restore the placeholder for the next time lock mode is (re)entered.
        self._panels_layout.addWidget(self._placeholder)
        return released

    # -- Internal --------------------------------------------------------------

    def _pick_anchor(self) -> None:
        """The anchor is the panel with the most rows — it gives the master
        scrollbar its finest resolution, and every other panel aligns to its
        currently-visible timestamp.
        """
        best_source, best_rows = None, -1
        for source_label, panel in self._panels.items():
            rows = panel.table_model.rowCount()
            if rows > best_rows:
                best_source, best_rows = source_label, rows
        self._anchor_source = best_source

    def _configure_master(self) -> None:
        if not self._anchor_source:
            self._master.setRange(0, 0)
            return
        anchor = self._panels[self._anchor_source]
        rows = anchor.table_model.rowCount()
        self._master.setRange(0, max(0, rows - 1))
        # Page step roughly tracks a screenful so the handle is a sensible
        # size; exact visible-row count isn't critical for alignment.
        self._master.setPageStep(max(1, rows // 20))
        self._master.setValue(0)

    def _on_master_scroll(self, value: int) -> None:
        """The unified scrollbar moved — drive the anchor there, then let the
        sync manager align every other panel by timestamp.
        """
        if self._syncing or not self._anchor_source:
            return
        self._syncing = True
        try:
            anchor = self._panels[self._anchor_source]
            anchor.receive_sync_scroll(value)      # move anchor (no re-emit)
            self._sync.sync_scroll(anchor, value)  # align the rest by time
        finally:
            self._syncing = False

    def _on_child_scrolled(self, source_label: str, row: int) -> None:
        """A panel was scrolled directly (mouse wheel) — reflect it on the
        master bar and re-align the others.
        """
        if self._syncing or source_label not in self._panels:
            return
        self._syncing = True
        try:
            child = self._panels[source_label]
            # Translate the child's top row into the equivalent anchor row so
            # the master handle tracks it.
            anchor_row = self._anchor_row_for(source_label, row)
            self._master.blockSignals(True)
            self._master.setValue(anchor_row)
            self._master.blockSignals(False)
            self._sync.sync_scroll(child, row)
        finally:
            self._syncing = False

    def _anchor_row_for(self, source_label: str, row: int) -> int:
        """Row in the anchor panel whose timestamp is closest to `row` in the
        given source panel — so the master handle position stays meaningful
        regardless of which panel the investigator scrolled.
        """
        if source_label == self._anchor_source or not self._anchor_source:
            return row
        child = self._panels[source_label]
        entries = child.table_model.get_entries()
        if not (0 <= row < len(entries)):
            return row
        ts = entries[row].normalized_timestamp
        if ts is None:
            return row
        anchor_entries = self._panels[self._anchor_source].table_model.get_entries()
        return ScrollSyncManager._find_closest_index(anchor_entries, ts.utc_datetime)

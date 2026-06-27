"""
LogWindowWidget — displays raw log entries from a single log source in a
scrollable, read-only table (Section 5.2, Presentation Layer).

Per the design doc's class diagram (Section 4.6):
    source_label: str
    entries: list[RawLogEntry]       (no truncation allowed)
    matched_indices: list[int]       (may be empty)
    scroll_position: int             (>= 0)

Multiple LogWindowWidgets are opened simultaneously and arranged side-by-side
inside the MainWindow's central workspace (Zone 3).
"""

from PySide6.QtCore import Qt, Signal
from src.models.data_classes import RawLogEntry
from src.models.log_table_model import LogTableModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QFrame, QSlider,
    QHeaderView, QAbstractItemView,
)


class LogWindowWidget(QWidget):
    """One independent, movable/resizable log panel (Zone 3)."""

    # Emitted when the investigator clicks a row — MainWindow connects this
    # to EventDetailPanel.show_event().
    row_selected = Signal(object)  # RawLogEntry

    # Emitted on scroll — ScrollSyncManager connects to this to propagate
    # scroll position to other open LogWindowWidgets (Section 4.7.3).
    scrolled = Signal(str, int)  # (source_label, scroll_position)

    def __init__(self, source_label: str, color_hex: str, columns: list[str], parent=None):
        super().__init__(parent)
        self.source_label = source_label
        self.color_hex = color_hex
        self.scroll_position = 0
        self.matched_indices: list[int] = []

        self._build_ui(columns)

    def _build_ui(self, columns: list[str]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- Panel header --------------------------------------------------
        header = QFrame()
        header.setObjectName("LogPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background-color: {self.color_hex}; border-radius: 4px;")
        header_layout.addWidget(dot)

        self.filename_label = QLabel(f"{self.source_label}.csv")
        self.filename_label.setStyleSheet("font-weight: 500; font-size: 11px;")
        header_layout.addWidget(self.filename_label)

        self.timezone_badge = QLabel("UTC+4")
        self.timezone_badge.setStyleSheet(
            "background-color: #1e2a4a; color: #4a5a7a; font-size: 10px; "
            "padding: 1px 5px; border-radius: 10px;"
        )
        header_layout.addWidget(self.timezone_badge)

        header_layout.addStretch()

        self.row_count_label = QLabel("0 rows")
        self.row_count_label.setStyleSheet("font-size: 10px; color: #4a5a7a;")
        header_layout.addWidget(self.row_count_label)

        layout.addWidget(header)

        # ---- Table -----------------------------------------------------------
        self.table_model = LogTableModel(columns=columns)
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setShowGrid(False)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.horizontalHeader().setMinimumSectionSize(60)
        self.table_view.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        self.table_view.setWordWrap(False)
        self.table_view.verticalHeader().setDefaultSectionSize(22)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.clicked.connect(self._on_row_clicked)

        # TODO (Section 4.7.3 SyncScroll):
        #   Connect verticalScrollBar().valueChanged to _on_scroll() so
        #   ScrollSyncManager can detect when this panel scrolls. Placeholder
        #   wired below — real binary-search-by-timestamp logic belongs in
        #   ScrollSyncManager, not here.
        self.table_view.verticalScrollBar().valueChanged.connect(self._on_scroll)

        layout.addWidget(self.table_view)

        # ---- Scroll position indicator bar -----------------------------------
        sync_bar = QFrame()
        sync_bar.setObjectName("ScrollSyncBar")
        sync_layout = QHBoxLayout(sync_bar)
        sync_layout.setContentsMargins(10, 4, 10, 4)

        sync_label = QLabel("Scroll position")
        sync_label.setStyleSheet("font-size: 10px; color: #4a5a7a;")
        sync_layout.addWidget(sync_label)

        self.scroll_indicator = QSlider(Qt.Orientation.Horizontal)
        self.scroll_indicator.setEnabled(False)  # display-only, driven programmatically
        sync_layout.addWidget(self.scroll_indicator)

        self.scroll_timestamp_label = QLabel("--:--")
        self.scroll_timestamp_label.setStyleSheet(f"font-size: 10px; color: {self.color_hex};")
        sync_layout.addWidget(self.scroll_timestamp_label)

        layout.addWidget(sync_bar)

    def _resize_columns_to_content(self) -> None:
        """Set sensible column widths after data loads.
        Uses the first 200 rows as a sample rather than measuring all rows,
        keeping it fast on large files.
        """
        header = self.table_view.horizontalHeader()
        # Sample-based resize: measure only visible/first rows for speed
        self.table_view.resizeColumnsToContents()

        # Apply per-column minimum widths for known fields
        col_min_widths = {
            "timestamp": 160,
            "date": 160,
            "username": 130,
            "ip_address": 120,
            "status": 70,
            "action_type": 140,
            "hostname": 130,
        }
        for col_index in range(self.table_model.columnCount()):
            col_key = self.table_model.column_key_at(col_index)
            min_w = col_min_widths.get(col_key, 80)
            if header.sectionSize(col_index) < min_w:
                header.resizeSection(col_index, min_w)
    # -- Public API --------------------------------------------------------------

    def load_rows(self, entries: list[RawLogEntry]) -> None:
        """Load entries filtered to this source_label (Section 4.7.1 step 6)."""
        self.table_model.load_entries(entries)
        self.row_count_label.setText(f"{len(entries):,} rows")
        self._resize_columns_to_content()

    def highlight_matched(self, matched_row_indices: list[int]) -> None:
        """Called by LogFilter results (Section 4.7.2 step 4)."""
        self.matched_indices = matched_row_indices
        self.table_model.highlight_matched(matched_row_indices)

    def receive_sync_scroll(self, row_index: int) -> None:
        """Called by ScrollSyncManager — scrolls this panel to row_index
        WITHOUT emitting the scrolled signal, preventing recursive sync loops
        (Section 4.7.3 step 4).
        """
        if not self.table_model.rowCount():
            return

        # Clamp to valid range
        row_index = max(0, min(row_index, self.table_model.rowCount() - 1))

        # Block the scroll signal so ScrollSyncManager doesn't pick this up
        # as a new user-initiated scroll and trigger another sync round.
        scrollbar = self.table_view.verticalScrollBar()
        scrollbar.blockSignals(True)
        try:
            index = self.table_model.index(row_index, 0)
            self.table_view.scrollTo(
                index,
                QAbstractItemView.ScrollHint.PositionAtTop,
            )
            self.scroll_position = scrollbar.value()
        finally:
            scrollbar.blockSignals(False)

    def set_timezone_label(self, tz_label: str) -> None:
        self.timezone_badge.setText(tz_label)

    # -- Internal handlers ---------------------------------------------------------

    def _on_row_clicked(self, index) -> None:
        entry = self.table_model.entry_at(index.row())
        if entry is not None:
            self.table_model.set_selected_row(index.row())
            self.row_selected.emit(entry)

    def _on_scroll(self, value: int) -> None:
        # TODO (Section 4.7.3 SyncScroll):
        #   Translate scrollbar `value` into a top-visible row index, store
        #   in self.scroll_position, then emit self.scrolled so
        #   ScrollSyncManager can propagate to other panels.
        self.scroll_position = value
        self.scrolled.emit(self.source_label, value)

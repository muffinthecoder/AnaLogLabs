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

owned by: fatima
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QFrame, QSlider,
    QHeaderView, QPushButton,
)

from src.models.data_classes import RawLogEntry
from src.models.log_table_model import LogTableModel


class LogWindowWidget(QWidget):
    """One independent, movable/resizable log panel (Zone 3)."""

    # Emitted when the investigator clicks a row — MainWindow connects this
    # to EventDetailPanel.show_event().
    row_selected = Signal(object)  # RawLogEntry

    # Emitted on scroll — ScrollSyncManager connects to this to propagate
    # scroll position to other open LogWindowWidgets (Section 4.7.3).
    scrolled = Signal(str, int)  # (source_label, scroll_position)

    # Emitted when this panel is closed (via the sub-window's X button or
    # programmatically) — MainWindow connects this to remove the panel from
    # self.log_panels, drop its tab, and unregister it from sync scroll.
    panel_closed = Signal(str)  # source_label

    # Emitted when the header's restore-size button is clicked. Exists
    # because QMdiArea's native maximize/restore title-bar button has shown
    # unreliable behavior on some platforms during testing — clicking it a
    # second time sometimes doesn't restore the window or re-enable
    # resizing (reported during manual testing; not reproducible through
    # showNormal() called in code, only through the actual title-bar
    # button click, which points at a QMdiArea/platform-level quirk rather
    # than anything in this codebase). This button is a guaranteed-working
    # alternative path that MainWindow wires directly to the containing
    # QMdiSubWindow's showNormal(), bypassing whatever the native button
    # is doing.
    restore_size_requested = Signal(str)  # source_label

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

        # Guaranteed-working restore/resize toggle — see restore_size_
        # requested's docstring above for why this exists alongside (not
        # instead of) the native QMdiSubWindow title-bar button. Shows a
        # restore-style glyph since its only real job is "get me out of
        # maximized and back to a resizable window" — MainWindow decides
        # exactly what that means (showNormal() + a sane default size).
        self.restore_button = QPushButton("Restore window size")
        self.restore_button.setObjectName("RestoreSizeButton")
        self.restore_button.setFixedHeight(20)
        self.restore_button.setToolTip("Click if a maximized window won't resize back down")
        self.restore_button.setStyleSheet(
            "QPushButton#RestoreSizeButton { "
            "background-color: transparent; color: #00c4e8; border: 1px solid #00c4e8; "
            "font-size: 10px; border-radius: 3px; padding: 0 8px; } "
            "QPushButton#RestoreSizeButton:hover { "
            "background-color: #00c4e8; color: #0a0e1a; }"
        )
        self.restore_button.clicked.connect(
            lambda: self.restore_size_requested.emit(self.source_label)
        )
        header_layout.addWidget(self.restore_button)

        self.row_count_label = QLabel("0 rows")
        self.row_count_label.setStyleSheet("font-size: 10px; color: #4a5a7a;")
        header_layout.addWidget(self.row_count_label)

        layout.addWidget(header)

        # ---- Table -----------------------------------------------------------
        self.table_model = LogTableModel(columns=columns)
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setShowGrid(False)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.verticalHeader().setVisible(False)

        # QHeaderView.Stretch forces every column into an equal share of the
        # available width regardless of how much content it actually holds
        # — fine for 4-5 columns, but real forensic log sources can have
        # 15-20+ fields (process_command_line, initiating_process_command_
        # line, sha256, etc. — see log_parser.py's _FIELD_NAME_ALIASES), and
        # Stretch squeezes every one of them into an unreadable sliver no
        # matter how wide the panel is resized. Interactive mode sizes each
        # column to its content on load, then lets the investigator drag
        # column borders afterward (e.g. widen a command-line field, narrow
        # a short status field) — exactly the kind of per-column control a
        # forensic table needs that Stretch can't offer.
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)

        # Horizontal scrolling picks up wherever total column width exceeds
        # the panel's width — this is what actually prevents columns from
        # being invisible/hidden once there are too many to fit, regardless
        # of how the panel itself is resized.
        self.table_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table_view.setHorizontalScrollMode(QTableView.ScrollPerPixel)

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

        self.scroll_indicator = QSlider(Qt.Horizontal)
        self.scroll_indicator.setEnabled(False)  # display-only, driven programmatically
        sync_layout.addWidget(self.scroll_indicator)

        self.scroll_timestamp_label = QLabel("--:--")
        self.scroll_timestamp_label.setStyleSheet(f"font-size: 10px; color: {self.color_hex};")
        sync_layout.addWidget(self.scroll_timestamp_label)

        layout.addWidget(sync_bar)

    # -- Public API --------------------------------------------------------------

    def load_rows(self, entries: list[RawLogEntry]) -> None:
        """Load entries filtered to this source_label (Section 4.7.1 step 6)."""
        self.table_model.load_entries(entries)
        self.row_count_label.setText(f"{len(entries):,} rows")

        # Interactive resize mode (set in _build_ui) starts every column at
        # a generic default width, not one based on its actual content —
        # this sizing pass is what makes columns readable on first load.
        # Investigators can still drag any column narrower/wider afterward;
        # this only sets sensible starting widths.
        self.table_view.resizeColumnsToContents()

        # A single very long value (e.g. a full process_command_line or a
        # raw syslog line) would otherwise blow that one column out to
        # hundreds of pixels and push every column after it off-screen.
        # Capping keeps the row scannable; the investigator can still widen
        # a specific column by hand via EventDetailPanel's full raw-JSON
        # view, or by dragging the header, if they need to see more.
        header = self.table_view.horizontalHeader()
        max_column_width = 220
        for col in range(self.table_model.columnCount()):
            if header.sectionSize(col) > max_column_width:
                header.resizeSection(col, max_column_width)

        self._update_scroll_indicator(0)

    def highlight_matched(self, matched_row_indices: list[int]) -> None:
        """Called by LogFilter results (Section 4.7.2 step 4)."""
        self.matched_indices = matched_row_indices
        self.table_model.highlight_matched(matched_row_indices)

    def receive_sync_scroll(self, row_index: int) -> None:
        """Called by ScrollSyncManager — sets scroll position WITHOUT emitting
        the `scrolled` signal again, to avoid recursive sync loops
        (Section 4.7.3 step 4).

        TODO (Fatima — Section 4.7.3):
            self.table_view.scrollTo(...) using row_index, blocking signals
            on verticalScrollBar() for the duration of the call.
        """
        pass

    def set_timezone_label(self, tz_label: str) -> None:
        self.timezone_badge.setText(tz_label)

    # -- Internal handlers ---------------------------------------------------------

    def _on_row_clicked(self, index) -> None:
        entry = self.table_model.entry_at(index.row())
        if entry is not None:
            self.table_model.set_selected_row(index.row())
            self.row_selected.emit(entry)

    def _on_scroll(self, value: int) -> None:
        """Fires on every vertical scrollbar movement (mouse wheel, drag,
        or programmatic). `value` here is the scrollbar's own internal
        unit (roughly "pixels scrolled", not a row index), so it has to be
        converted via rowAt() before it means anything to LogTableModel or
        ScrollSyncManager.
        """
        top_row = self.table_view.rowAt(0)
        if top_row == -1:
            # rowAt(0) returns -1 if no row currently occupies the very top
            # pixel of the viewport (e.g. the table is empty, or — on some
            # platforms — briefly during a resize/layout pass). Falling
            # back to the last known good scroll_position avoids feeding a
            # bogus -1 row index into ScrollSyncManager or the indicator
            # below.
            top_row = self.scroll_position

        self.scroll_position = top_row
        self._update_scroll_indicator(top_row)
        self.scrolled.emit(self.source_label, top_row)

    def _update_scroll_indicator(self, row: int) -> None:
        """Keeps the bottom "Scroll position" slider and timestamp label in
        sync with the table's actual scroll position. The slider stays
        disabled/non-interactive by design (Section 4.6 class diagram:
        scroll_position is read from the table, not written by dragging
        this control) — this is what makes it move at all, since nothing
        previously called it after construction.
        """
        row_count = self.table_model.rowCount()
        if row_count <= 1:
            self.scroll_indicator.setValue(0)
            self.scroll_timestamp_label.setText("--:--")
            return

        # QSlider's range defaults to 0-99; map the row index onto that
        # range rather than resizing the slider's range to row_count every
        # load, since the slider's job here is purely a proportional
        # position indicator, not a row picker.
        position_pct = int((row / (row_count - 1)) * 99)
        self.scroll_indicator.setValue(position_pct)

        entry = self.table_model.entry_at(row)
        if entry is not None and entry.normalized_timestamp is not None:
            self.scroll_timestamp_label.setText(
                entry.normalized_timestamp.utc_datetime.strftime("%H:%M:%S")
            )
        elif entry is not None:
            # Falls back to the raw display string for rows Hiba's
            # normalizer couldn't parse (normalized_timestamp is None) —
            # still better than leaving the label stuck at "--:--" for
            # every unparsed row.
            self.scroll_timestamp_label.setText(str(entry.fields.get("timestamp", "--:--")))

    def closeEvent(self, event) -> None:
        """Fired when this panel's containing QMdiSubWindow is closed via
        its title-bar X button, or when .close() is called directly.

        Emits panel_closed so MainWindow can drop this source from
        self.log_panels, remove its TabManager entry, and unregister it
        from ScrollSyncManager — otherwise those would keep stale
        references to a widget that no longer exists.
        """
        self.panel_closed.emit(self.source_label)
        super().closeEvent(event)
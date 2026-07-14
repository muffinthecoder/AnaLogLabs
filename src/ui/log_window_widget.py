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

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QColor, QAction, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QFrame, QSlider,
    QHeaderView, QPushButton, QAbstractItemView, QMenu, QApplication,
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

    # R1 — emitted when the header "Pop out" button is clicked. MainWindow
    # detaches this panel from the MDI area into a free-floating top-level
    # window that can be moved anywhere on the desktop.
    detach_requested = Signal(str)  # source_label

    # Section 4.2 — emitted when the investigator flags/unflags a row. Carries
    # the RawLogEntry so MainWindow can add/remove a shared ±30s flag anchor.
    flag_toggle_requested = Signal(object)  # RawLogEntry

    def __init__(self, source_label: str, color_hex: str, columns: list[str], parent=None):
        super().__init__(parent)
        self.source_label = source_label
        self.color_hex = color_hex
        self.scroll_position = 0
        self.matched_indices: list[int] = []

        # Guard flag used to skip OUR OWN _on_scroll() handler during a
        # code-driven scroll (receive_sync_scroll), WITHOUT scrollbar.
        # blockSignals(True) — that would also block Qt's own internal wiring
        # that moves the visible rows to match the scrollbar, so the handle
        # would jump while the rows on screen never did.
        self._suppress_scroll_signal = False

        self._build_ui(columns)

    def _build_ui(self, columns: list[str]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- Panel header --------------------------------------------------
        header = QFrame()
        header.setObjectName("LogPanelHeader")
        # Section 5.3 — a coloured top accent tied to the file's palette colour,
        # so a window (docked or popped out) is visually correlatable to its
        # heatmap row / spike series / legend swatch.
        header.setStyleSheet(
            f"QFrame#LogPanelHeader {{ border-top: 2px solid {self.color_hex}; }}"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background-color: {self.color_hex}; border-radius: 4px;")
        header_layout.addWidget(dot)

        self.filename_label = QLabel(f"{self.source_label}.csv")
        # self.filename_label.setStyleSheet("QLabel { color: #ffffff; font-weight: bold; font-size: 12px; }")
        self.filename_label.setObjectName("FilenameLabel")  # <-- 1. Assign a unique ID
        header_layout.addWidget(self.filename_label)

        self.timezone_badge = QLabel("UTC+8")
        self.timezone_badge.setStyleSheet(
            "background-color: #D1EFF0; color: #000000; font-size: 10px; "
            "padding: 1px 5px; border-radius: 10px;"
        )
        header_layout.addWidget(self.timezone_badge)

        header_layout.addStretch()

        # Guaranteed-working restore/resize toggle — see restore_size_
        # requested's docstring above for why this exists alongside (not
        # instead of) the native QMdiSubWindow title-bar button. Uses a
        # text label with a visible border (rather than a muted icon-only
        # glyph) because the icon version blended into the dark background
        # and was effectively invisible — found during testing when it was
        # only ever located by accident.
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

        # R1 — pop this panel out into a free-floating desktop window. Styled
        # like the restore button so the two header actions read as a pair.
        self.detach_button = QPushButton("Pop out")
        self.detach_button.setObjectName("DetachButton")
        self.detach_button.setFixedHeight(20)
        self.detach_button.setToolTip("Detach this log into a movable floating window")
        self.detach_button.setStyleSheet(
            "QPushButton#DetachButton { "
            "background-color: transparent; color: #00c4e8; border: 1px solid #00c4e8; "
            "font-size: 10px; border-radius: 3px; padding: 0 8px; } "
            "QPushButton#DetachButton:hover { "
            "background-color: #00c4e8; color: #0a0e1a; }"
        )
        self.detach_button.clicked.connect(
            lambda: self.detach_requested.emit(self.source_label)
        )
        header_layout.addWidget(self.detach_button)

        self.row_count_label = QLabel("0 rows")
        self.row_count_label.setStyleSheet("font-size: 10px; color: #ffffff;")
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

        # Floor on how narrow a dragged column can get — without this, an
        # investigator (or the auto-sizing pass in load_rows()) could drag
        # a column down to near-zero width and lose track of which column
        # is which.
        header.setMinimumSectionSize(60)

        # Long values (command lines, raw syslog text) wrapping to multiple
        # lines would make every row a different height, which breaks the
        # visual rhythm of a forensic table where row N and row N+1 should
        # be directly comparable at a glance. Horizontal scrolling (set
        # below) is the intended way to see more of a long value instead.
        self.table_view.setWordWrap(False)
        self.table_view.verticalHeader().setDefaultSectionSize(22)

        # Alternating row shading makes it easier to track a row across a
        # wide, horizontally-scrolled table — useful here specifically
        # because Interactive mode (above) means rows are often wider than
        # the visible panel.
        #
        # setAlternatingRowColors(True) alone only toggles WHETHER rows
        # alternate — it does not set what the alternate color actually is.
        # That comes from QPalette.AlternateBase, which defaults to Qt's
        # light-theme grey (~#f7f7f7) and was never set here, so every
        # other row was rendering near-white against this dark theme,
        # which looked like a rendering bug rather than a subtle stripe.
        # Setting it to a shade close to the existing dark background
        # fixes that without losing the row-tracking benefit.
        self.table_view.setAlternatingRowColors(True)
        table_palette = self.table_view.palette()
        table_palette.setColor(table_palette.ColorRole.Base, QColor("#0e1320"))
        table_palette.setColor(table_palette.ColorRole.AlternateBase, QColor("#131a2e"))
        self.table_view.setPalette(table_palette)

        # Horizontal scrolling picks up wherever total column width exceeds
        # the panel's width — this is what actually prevents columns from
        # being invisible/hidden once there are too many to fit, regardless
        # of how the panel itself is resized.
        self.table_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table_view.setHorizontalScrollMode(QTableView.ScrollPerPixel)

        self.table_view.clicked.connect(self._on_row_clicked)

        # R5 — right-click a row to flag/unflag it. A flagged event is marked
        # here and mirrored at the corresponding time in every other panel.
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_context_menu)

        # Copy support (reliable): Ctrl+C is caught via an event filter on the
        # table view — a QShortcut with no explicit context can fail to fire in
        # an MDI/reparented panel, which is why the earlier copy didn't work.
        # The event filter only reacts when THIS table actually has focus.
        self.table_view.installEventFilter(self)

        # Sync scroll: a scrollbar move emits `scrolled`, which the unified
        # LockedWorkspace listens to (reading this panel's CENTER timestamp and
        # aligning every other panel by nearest timestamp). Programmatic moves
        # via center_on_row()/receive_sync_scroll() block this signal to avoid
        # recursive sync.
        self.table_view.verticalScrollBar().valueChanged.connect(self._on_scroll)

        layout.addWidget(self.table_view)

        # ---- Scroll position indicator bar -----------------------------------
        sync_bar = QFrame()
        sync_bar.setObjectName("ScrollSyncBar")
        sync_layout = QHBoxLayout(sync_bar)
        sync_layout.setContentsMargins(10, 4, 10, 4)

        sync_label = QLabel("Scroll position")
        sync_label.setStyleSheet("font-size: 10px; color: #ffffff;")
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

        # Known fields get a sensible floor even when their actual content
        # is short — e.g. a "status" column full of "OK" would otherwise
        # auto-size to a few px, which looks cramped and invites accidental
        # mis-clicks right next to it. Unknown fields fall back to a small
        # generic floor (80px) since log_parser.py's _FIELD_NAME_ALIASES
        # covers many but not all possible source columns.
        column_min_widths = {
            "original_log_time": 175,
            "timestamp": 130,
            "date": 160,
            "username": 130,
            "ip_address": 120,
            "status": 70,
            "action_type": 140,
            "hostname": 130,
        }
        for col in range(self.table_model.columnCount()):
            width = header.sectionSize(col)
            if width > max_column_width:
                header.resizeSection(col, max_column_width)
                continue
            column_key = self.table_model.column_key_at(col)
            min_width = column_min_widths.get(column_key, 80)
            if width < min_width:
                header.resizeSection(col, min_width)

        self._update_scroll_indicator(0)

    def highlight_matched(self, matched_row_indices: list[int]) -> None:
        """Called by LogFilter results (Section 4.7.2 step 4)."""
        self.matched_indices = matched_row_indices
        self.table_model.highlight_matched(matched_row_indices)

    def receive_sync_scroll(self, row_index: int) -> None:
        """Called by ScrollSyncManager — scrolls this panel to row_index
        WITHOUT re-triggering sync (Section 4.7.3 step 4).

        Uses the `_suppress_scroll_signal` guard rather than
        scrollbar.blockSignals(True): blockSignals silences EVERY slot on the
        scrollbar's valueChanged — including Qt's own internal wiring that
        moves the visible rows to match the scrollbar value — so the handle
        jumped while the content on screen never did. The guard flag only
        short-circuits our own _on_scroll(), leaving Qt's scroll-the-viewport
        connection intact.
        """
        if not self.table_model.rowCount():
            return

        # Clamp to valid range — ScrollSyncManager's binary search always
        # returns a valid index for ITS OWN entries list, but that list can
        # have a different length than this panel's, so the clamp here is
        # what actually guards against an out-of-range row_index.
        row_index = max(0, min(row_index, self.table_model.rowCount() - 1))

        self._suppress_scroll_signal = True
        try:
            index = self.table_model.index(row_index, 0)
            # Center-aligned, matching _on_scroll's center anchor: the row a
            # sync moves TO should land at the same center point it was read
            # from, not the top edge.
            self.table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.scroll_position = row_index
            self._update_scroll_indicator(row_index)
        finally:
            self._suppress_scroll_signal = False

    def set_flag_anchors(self, anchors: list) -> None:
        """Section 4.2 — apply the shared ±30s flag anchors to this window's
        model so every correlated event renders flagged consistently.
        """
        self.table_model.set_flag_anchors(anchors)

    def scroll_to_time(self, utc_dt) -> None:
        """Scroll so the first row at/after utc_dt is at the top (Sections 3 &
        4.1 — jump to range start / a file's first entry). Uses the sync path
        so it does not re-emit a scroll and cause feedback.
        """
        entries = self.table_model.get_entries()
        if not entries:
            return
        target = 0
        found = False
        for i, e in enumerate(entries):
            nts = e.normalized_timestamp
            if nts is not None and nts.utc_datetime >= utc_dt:
                target = i
                found = True
                break
        if not found:
            target = len(entries) - 1
        self.receive_sync_scroll(target)

    def select_and_scroll_to_time(self, utc_dt) -> RawLogEntry | None:
        """Programmatic navigation entry point for chart-click interactions —
        scrolls to (and selects/highlights) the entry CLOSEST to utc_dt, then
        emits row_selected the same way a manual row click would, so the
        Event Detail panel updates to match. Distinct from scroll_to_time()
        above, which finds the first entry AT/AFTER a timestamp rather than
        the nearest one — that distinction matters less for a chart click,
        where "closest" is the more intuitive landing point.
        """
        entries = self.table_model.get_entries()
        if not entries:
            return None
        best_index = 0
        best_delta = None
        for i, e in enumerate(entries):
            nts = e.normalized_timestamp
            if nts is None:
                continue
            delta = abs((nts.utc_datetime - utc_dt).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_index = i
        self.receive_sync_scroll(best_index)
        entry = self.table_model.entry_at(best_index)
        if entry is not None:
            self.table_model.set_selected_row(best_index)
            self.row_selected.emit(entry)
        return entry

    def first_entry_time(self):
        """UTC datetime of this file's earliest event, or None."""
        for e in self.table_model.get_entries():
            if e.normalized_timestamp is not None:
                return e.normalized_timestamp.utc_datetime
        return None

    def set_timezone_label(self, tz_label: str) -> None:
        self.timezone_badge.setText(tz_label)

    def set_display_timezone(self, iana_tz: str) -> None:
        """Converts and re-renders the TIMESTAMP column in iana_tz (e.g.
        "Asia/Dubai") — separate from set_timezone_label() above, which
        only updates the small badge text and never touched the actual
        table data. Without this call, the badge would correctly show
        "UTC+8" after switching to Perth while every row still displayed
        the same raw, unconverted timestamp string underneath it.
        """
        self.table_model.set_display_timezone(iana_tz)
        self._update_scroll_indicator(self.scroll_position)

    # -- Internal handlers ---------------------------------------------------------

    def _on_row_clicked(self, index) -> None:
        entry = self.table_model.entry_at(index.row())
        if entry is not None:
            self.table_model.set_selected_row(index.row())
            self.row_selected.emit(entry)

    def _on_context_menu(self, pos) -> None:
        """Right-click menu for the row under the cursor. Shows TWO actions:
        Copy timestamp and Flag (Section 4.2). Right-clicking selects the row
        first so both actions operate on the row that was actually clicked.
        """
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return
        self.table_view.selectRow(index.row())
        entry = self.table_model.entry_at(index.row())
        if entry is None:
            return

        menu = QMenu(self)
        copy_action = QAction("Copy timestamp", self)
        menu.addAction(copy_action)

        already = self.table_model._is_flagged_row(index.row())
        flag_label = "⚑ Remove flag (±30s)" if already else "⚑ Flag event (+ correlate ±30s)"
        flag_action = QAction(flag_label, self)
        menu.addAction(flag_action)

        chosen = menu.exec(self.table_view.viewport().mapToGlobal(pos))
        if chosen is copy_action:
            self._copy_timestamp(entry)
        elif chosen is flag_action:
            self.flag_toggle_requested.emit(entry)

    def eventFilter(self, obj, event) -> bool:
        """Catches Ctrl+C (the platform copy shortcut) while the table view has
        focus and copies the selected row's timestamp. Every other event is
        passed through so normal table navigation still works.
        """
        if obj is self.table_view and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Copy):
                self._copy_current_row_timestamp()
                return True
        return super().eventFilter(obj, event)

    def _copy_current_row_timestamp(self) -> None:
        """Ctrl+C path — copy the currently selected/current row's timestamp."""
        selected = self.table_view.selectionModel().selectedRows()
        row = selected[0].row() if selected else self.table_view.currentIndex().row()
        entry = self.table_model.entry_at(row) if row >= 0 else None
        if entry is not None:
            self._copy_timestamp(entry)

    def _copy_timestamp(self, entry: RawLogEntry) -> None:
        """Copies the row's CONVERTED timestamp as a full, paste-ready
        "YYYY-MM-DD HH:MM:SS.mmm" (display timezone) to the clipboard, so it
        drops straight into the time-range Start/End boxes. Read-only — never
        touches highlight/flag state.
        """
        QApplication.clipboard().setText(self.table_model.full_display_datetime(entry))

    def _on_scroll(self, value: int) -> None:
        """Fires on every vertical scrollbar movement (mouse wheel, drag, or
        programmatic). The sync anchor is the row visible at the CENTER of the
        viewport, not the topmost row — different sources pack very different
        row counts into the same time span, so anchoring on what's centered on
        screen keeps what the investigator is actually looking at aligned
        across panels.
        """
        if self._suppress_scroll_signal:
            # A code-driven scroll (receive_sync_scroll) already updates
            # scroll_position/the indicator itself and must not re-emit.
            return

        center_point = self.table_view.viewport().rect().center()
        center_row = self.table_view.indexAt(center_point).row()
        if center_row == -1:
            center_row = self.table_view.rowAt(0)
        if center_row == -1:
            center_row = self.scroll_position

        self.scroll_position = center_row
        self._update_scroll_indicator(center_row)
        self.scrolled.emit(self.source_label, center_row)

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
        if entry is not None:
            # Reuses LogTableModel._format_timestamp() rather than
            # duplicating the UTC-to-display-timezone conversion here —
            # this label had the exact same bug as the TIMESTAMP column
            # (showed raw utc_datetime regardless of the selected display
            # timezone) until both were fixed to go through one shared
            # conversion path.
            self.scroll_timestamp_label.setText(self.table_model.format_timestamp(entry))

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
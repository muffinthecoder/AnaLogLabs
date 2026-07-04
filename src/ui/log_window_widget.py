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

from PySide6.QtCore import Qt, Signal, QEvent, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QFrame, QSlider,
    QHeaderView, QPushButton, QAbstractItemView, QMenu,
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

        # Guard used by _do_scroll_to_first_match() (and could be reused
        # anywhere else that scrolls this panel programmatically) to skip
        # OUR OWN _on_scroll() handler during a code-driven scroll, without
        # calling scrollbar.blockSignals(True). blockSignals(True) blocks
        # every slot connected to valueChanged — not just _on_scroll — and
        # Qt's own QAbstractItemView/QAbstractScrollArea internals are ALSO
        # connected to that same signal to actually move the viewport's
        # visible rows to match the scrollbar's value. Blocking it meant
        # the scrollbar handle moved (it repaints itself from its own
        # internal value regardless) while the rows on screen never did.
        # A plain guard flag only short-circuits _on_scroll, leaving Qt's
        # own scroll-the-viewport wiring untouched.
        self._suppress_scroll_signal = False

        self._build_ui(columns)

    @staticmethod
    def _prepend_original_ts_column(columns: list[str]) -> list[str]:
        """Inserts "original_timestamp" as the first column so investigators
        always see the raw, un-converted timestamp from the source file
        alongside the display-timezone-converted "timestamp" column.

        Skipped if it is already present (idempotent) so this helper is safe
        to call during both initial construction and any later column rebuild.
        """
        if "original_timestamp" in columns:
            return columns
        return ["original_timestamp"] + list(columns)

    def _build_ui(self, columns: list[str]) -> None:
        # Inject the "Original Log Time" column before any source columns.
        columns = self._prepend_original_ts_column(columns)
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

        # Phase 2 — copy/paste timestamps. Ctrl+C is caught via an event
        # filter (QTableView has no built-in copy action, and subclassing
        # QTableView just for this would touch more than needed) rather
        # than a QShortcut, since a QShortcut with no explicit context can
        # fire even when this panel/table isn't the one focused — an event
        # filter on the table_view itself only reacts when the table
        # actually has focus, which is the correct scope for a per-panel
        # row copy action.
        self.table_view.installEventFilter(self)

        # Right-click copy — same action, reachable without keyboard focus.
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_table_context_menu)

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

        # Known fields get a sensible floor even when their actual content
        # is short — e.g. a "status" column full of "OK" would otherwise
        # auto-size to a few px, which looks cramped and invites accidental
        # mis-clicks right next to it. Unknown fields fall back to a small
        # generic floor (80px) since log_parser.py's _FIELD_NAME_ALIASES
        # covers many but not all possible source columns.
        column_min_widths = {
            # Widened from 160 — format_timestamp() now renders a full
            # "YYYY-MM-DD HH:MM:SS.mmm" date+time (Phase 2), not just
            # "HH:MM:SS.mmm", so the old width clipped the date portion.
            "timestamp": 210,
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

    def highlight_matched(self, matched_entries: list[RawLogEntry]) -> None:
        """Called by LogFilter results (Section 4.7.2 step 4).

        Phase 5 — takes the matched RawLogEntry objects directly rather
        than a list of row indices. `self.matched_indices` is kept as the
        Section 4.6 class-diagram field (each entry's original file
        row_index, for anything that wants to inspect "what's matched"
        without caring about display order), but it is no longer what
        LogTableModel uses to decide what to paint — that's tracked by
        entry identity instead (see LogTableModel.highlight_matched), so
        the highlight stays correct no matter what order the table is
        currently sorted into.
        """
        self.matched_indices = [e.row_index for e in matched_entries]
        self.table_model.highlight_matched(matched_entries)

    def scroll_to_first_match(self) -> None:
        """Auto-jumps this panel to its first (topmost, in current display
        order) matched/highlighted row, if any — so an investigator doesn't
        have to manually scroll and hunt after applying a filter. No-op if
        nothing in this panel matched.

        Called by MainWindow._on_filter_applied() right after
        highlight_matched(), once every panel's matched state is already
        up to date.

        The actual scroll is deferred one event-loop tick via
        QTimer.singleShot(0, ...) rather than run immediately. highlight_
        matched() just called beginResetModel()/endResetModel(), and Qt
        does NOT recompute a QTableView's row-position layout synchronously
        on reset — it schedules that for the next paint pass. Calling
        scrollTo() in the same call stack as the reset was asking it to
        jump to a row position calculated from geometry that hadn't been
        refreshed yet, so the jump either silently no-op'd or landed on the
        wrong offset. Scheduling with singleShot(0, ...) runs this after
        Qt's own pending layout pass has already happened.
        """
        QTimer.singleShot(0, self._do_scroll_to_first_match)

    def _do_scroll_to_first_match(self) -> None:
        """The actual scroll logic behind scroll_to_first_match(), run one
        event-loop tick later — see that method's docstring for why.

        Uses the _suppress_scroll_signal guard (see __init__) rather than
        scrollbar.blockSignals(True) around scrollTo() — blockSignals was
        also silencing Qt's own internal wiring that scrolls the
        viewport's visible rows to match the scrollbar's new value, so the
        scrollbar handle jumped but the table content on screen never did.
        """
        row = self.table_model.first_matched_row()
        if row is None:
            return

        self._suppress_scroll_signal = True
        try:
            index = self.table_model.index(row, 0)
            self.table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
        finally:
            self._suppress_scroll_signal = False

        self.scroll_position = self.table_view.verticalScrollBar().value()
        self._update_scroll_indicator(row)

    def eventFilter(self, obj, event) -> bool:
        """Catches Ctrl+C (or the platform's native copy shortcut) while
        the table view has focus and routes it to _copy_selected_
        timestamp() (Phase 2). Only intercepts the Copy key sequence —
        every other key event is passed through untouched so normal
        table navigation (arrows, Home/End, etc.) keeps working.
        """
        if obj is self.table_view and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Copy):
                self._copy_selected_timestamp()
                return True
        return super().eventFilter(obj, event)

    def _on_table_context_menu(self, pos) -> None:
        """Right-click copy — the same action as Ctrl+C, but reachable
        without keyboard focus or an existing selection. Right-clicking a
        row selects it first (SingleSelection mode means this can't
        conflict with a different existing selection) so "Copy timestamp"
        always operates on the row that was actually right-clicked, not
        whatever was selected beforehand.
        """
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return
        self.table_view.selectRow(index.row())

        menu = QMenu(self.table_view)
        copy_action = menu.addAction("Copy timestamp")
        copy_action.triggered.connect(self._copy_selected_timestamp)
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _copy_selected_timestamp(self) -> None:
        """Copies the currently selected row's display-timezone-converted
        TIMESTAMP value (not the raw "original_timestamp" column, and not
        the whole row) to the system clipboard, so it can be pasted
        straight into TimeFrameSelector's Start/End fields.

        Only the timestamp column is copied — locked-in decision, since
        copying the entire row (tab-separated across columns) wouldn't
        paste cleanly into a single-line time field anyway, and all open
        panels already share one display timezone so no per-row timezone
        ambiguity exists to resolve.

        Never touches matched/flagged state — copy/paste is a read-only
        action with no side effects on highlighting or flagging.
        """
        selected_rows = self.table_view.selectionModel().selectedRows()
        row = selected_rows[0].row() if selected_rows else self.table_view.currentIndex().row()
        if row < 0:
            return

        entry = self.table_model.entry_at(row)
        if entry is None:
            return

        QGuiApplication.clipboard().setText(self.table_model.format_timestamp(entry))

    def receive_sync_scroll(self, row_index: int) -> None:
        """Called by ScrollSyncManager — scrolls this panel to row_index
        WITHOUT emitting the scrolled signal, preventing recursive sync
        loops (Section 4.7.3 step 4).

        Phase 8 fix: this used to guard against re-triggering sync with
        `scrollbar.blockSignals(True)`. That blocks EVERY slot connected to
        the scrollbar's valueChanged — including Qt's own internal
        QAbstractItemView/QAbstractScrollArea wiring that actually moves
        the visible rows to match the scrollbar's new value — so the
        scrollbar handle jumped to the right place while the table content
        on screen never did (the same bug already fixed in
        _do_scroll_to_first_match). Now uses the same
        `_suppress_scroll_signal` guard flag instead, which only
        short-circuits our own `_on_scroll()` handler and leaves Qt's
        internal scroll-the-viewport connection untouched.
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
            # Center-aligned rather than PositionAtTop — Phase 8 syncs
            # panels off the timestamp visible at the CENTER of each
            # viewport (see _on_scroll), so the row a sync moves TO should
            # land at that same center point, not the top edge.
            self.table_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
            # _on_scroll() is what normally updates scroll_position/the
            # indicator, but it's skipped here (via the guard flag above)
            # since this is a programmatic, not user-driven, scroll. Store
            # the actual row index landed on rather than the scrollbar's
            # raw pixel value — every other place in this class treats
            # scroll_position as a row index, and reading scrollbar.value()
            # here was a latent inconsistency.
            self.scroll_position = row_index
            self._update_scroll_indicator(row_index)
        finally:
            self._suppress_scroll_signal = False

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

    def _on_scroll(self, value: int) -> None:
        """Fires on every vertical scrollbar movement (mouse wheel, drag,
        or programmatic).

        Phase 8: the anchor row used for Sync Scroll is the row visible at
        the CENTER of this panel's viewport, not the topmost row. Different
        log sources have very different row heights-per-timestamp (one
        source might have 40px of rows covering the same second another
        covers in 2px), so anchoring on whichever entry happens to be
        centered on screen keeps what the investigator is actually LOOKING
        AT aligned across panels, rather than an edge row that may already
        be scrolled past in a denser panel.
        """
        if self._suppress_scroll_signal:
            # A code-driven scroll (e.g. _do_scroll_to_first_match or
            # receive_sync_scroll) is already updating scroll_position/the
            # indicator itself and deliberately doesn't want scrolled()
            # emitted for this move — see the guard's docstring in __init__.
            return

        center_point = self.table_view.viewport().rect().center()
        center_row = self.table_view.indexAt(center_point).row()
        if center_row == -1:
            # indexAt() returns an invalid index if no row currently
            # occupies that pixel (e.g. the table is empty, fewer rows
            # than fit a full viewport, or — on some platforms — briefly
            # during a resize/layout pass). Fall back to the top row, then
            # to the last known good scroll_position, rather than feeding
            # a bogus -1 row index into ScrollSyncManager or the indicator
            # below.
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
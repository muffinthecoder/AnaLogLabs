"""
MainWindow — application shell that hosts and manages all other components
(Section 5.2, Presentation Layer).

Per the design doc: "MainWindow is the sole orchestrator, it holds references
to all other modules but contains no business logic itself." All filtering,
correlation, normalisation, and parsing logic belongs in the Application and
Data layers (src/normaliser, src/filter, src/correlator, src/parser) — NOT
here. This file only wires signals between UI components.

Organised into three main areas per Section 5.2:
    - Top navigation bar
    - Central log viewing workspace (with two side bars)
"""

import sys
import copy
from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFileDialog,
    QMdiArea, QMdiSubWindow, QMessageBox, QComboBox, QLabel
)

from src.ui.styles import MAIN_STYLESHEET
from src.ui.top_nav_bar import TopNavBar
from src.ui.tab_manager import TabManager
from src.ui.timeframe_selector import TimeFrameSelector
from src.ui.log_window_widget import LogWindowWidget
from src.ui.event_detail_panel import EventDetailPanel
from src.ui.investigation_dashboard import InvestigationDashboard
from src.ui.timezone_import_dialog import TimezoneImportDialog

from src import mock_data
from src.models.data_classes import FilterConfig, RawLogEntry
from src.filter.log_filter import LogFilter, FilterValidationError
from src.parser.log_parser import LogParser
from src.normaliser.timezone_map import set_timezone_for_source, display_label_for_timezone
from src.correlator.scroll_sync_manager import ScrollSyncManager

# TODO (Fatima — styles.py):
#   Move this to styles.py once that file is shared/consolidated, so the
#   QMdiArea background and the rest of the dark theme stay in one place
#   instead of main_window.py hardcoding its own color. Match this to
#   whatever the outer app background is in MAIN_STYLESHEET.
BACKGROUND_COLOR = "#0a0e1a"


class MainWindow(QMainWindow):
    """Application shell — Section 5.2 Presentation Layer."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AnaLog Labs")
        self.resize(1400, 900)
        self.setStyleSheet(MAIN_STYLESHEET)

        # source_label -> LogWindowWidget, mirrors ScrollSyncManager.windows
        self.log_panels: dict[str, LogWindowWidget] = {}

        # source_label -> QMdiSubWindow — the movable/resizable/closable
        # container each LogWindowWidget lives inside. Tracked separately
        # from self.log_panels since MainWindow needs the sub-window (not
        # the inner widget) to control geometry, tiling, and closing.
        self.log_subwindows: dict[str, QMdiSubWindow] = {}

        # Hiba's real Section 4.7.3 SyncScroll implementation — registers
        # LogWindowWidget instances by source_label and keeps their scroll
        # positions aligned by UTC timestamp rather than row index.
        self._scroll_sync = ScrollSyncManager()
        self._sync_scroll_enabled: bool = False

        # Phase 3 — Sync Scroll requires a valid, currently-applied time
        # range. Holds the last FilterConfig successfully emitted by
        # TimeFrameSelector.filter_applied, and is cleared back to None
        # whenever filter_cleared fires — so this doubles as "is there a
        # valid time range right now" without re-deriving that from the
        # sidebar's raw text fields (which TimeFrameSelector already
        # validated once at apply-time; re-validating here would just
        # duplicate that logic).
        self._active_filter_config: FilterConfig | None = None

        # Phase 4 — one global sort direction applying to every open panel
        # at once (TopNavBar's single dropdown, not per-panel). Stored here
        # so a newly-imported panel (add_log_panel / _on_import_logs) can be
        # brought into line with whatever order is already selected, rather
        # than always defaulting to file/merge order until the investigator
        # happens to re-touch the dropdown.
        self._sort_ascending: bool = True

        self._build_ui()
        self._connect_signals()

        # TODO (Pooja — testing):
        #   Remove this call once LogParser (R1) is implemented and wired to
        #   the real Import logs button flow. This currently loads
        #   mock_data so the interface can be reviewed end-to-end.
        # self._load_mock_session()

    # -- UI construction ------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- Zone 1: Top navigation bar -----------------------------------------
        self.top_nav = TopNavBar()
        root_layout.addWidget(self.top_nav)

        # ---- Body: sidebar + centre workspace + dashboard ------------------------
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Zone 2: Left sidebar
        self.left_sidebar = QWidget()
        self.left_sidebar.setObjectName("LeftSidebar")
        self.left_sidebar.setFixedWidth(190)
        sidebar_layout = QVBoxLayout(self.left_sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(14)

        self.tab_manager = TabManager()
        sidebar_layout.addWidget(self.tab_manager)

        # Phase 4 — single global sort control, placed here in the left
        # sidebar (under Log sources, above the time range) per request,
        # rather than in TopNavBar. Still applies to every open panel at
        # once, not per-panel — placement changed, scope didn't.
        sort_row = QWidget()
        sort_row_layout = QHBoxLayout(sort_row)
        sort_row_layout.setContentsMargins(0, 0, 0, 0)
        sort_row_layout.setSpacing(6)

        sort_label = QLabel("Sort")
        sort_label.setStyleSheet("font-size: 11px; color: #5a6a8a;")
        sort_row_layout.addWidget(sort_label)

        self.sort_dropdown = QComboBox()
        # userData carries the bool the rest of the app actually cares
        # about (ascending?) rather than making the handler parse
        # "Oldest -> Newest" back into a direction.
        self.sort_dropdown.addItem("Oldest \u2192 Newest", userData=True)
        self.sort_dropdown.addItem("Newest \u2192 Oldest", userData=False)
        self.sort_dropdown.currentIndexChanged.connect(self._on_sort_index_changed)
        sort_row_layout.addWidget(self.sort_dropdown, stretch=1)

        sidebar_layout.addWidget(sort_row)

        # Range padding note — sits directly above TimeFrameSelector.
        # Not literally inside that widget above its own Apply button
        # (would need timeframe_selector.py's own layout code for that),
        # but placed right above the whole Start/End/Apply block here in
        # the sidebar so it's the last thing the investigator reads before
        # applying. Empty until a filter is actually applied.
        self.filter_range_label = QLabel("")
        self.filter_range_label.setWordWrap(True)
        self.filter_range_label.setStyleSheet("font-size: 10px; color: #5a6a8a;")
        sidebar_layout.addWidget(self.filter_range_label)

        self.timeframe_selector = TimeFrameSelector(timezone="Asia/Dubai")
        sidebar_layout.addWidget(self.timeframe_selector)

        sidebar_layout.addStretch()
        body_layout.addWidget(self.left_sidebar)

        # Zone 3 + 4: Central workspace (log panels + detail panel)
        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(0)

        # Zone 3: log panel workspace — QMdiArea gives each LogWindowWidget
        # an independently movable, resizable, and closable sub-window
        # (drag the title bar to move, drag edges/corners to resize, click
        # the X to close), which a plain QHBoxLayout cannot provide since
        # layout-managed widgets have their geometry fixed by the layout.
        self.panels_area = QMdiArea()
        self.panels_area.setObjectName("PanelsArea")
        self.panels_area.setViewMode(QMdiArea.SubWindowView)
        self.panels_area.setOption(QMdiArea.DontMaximizeSubWindowOnActivation, True)
        self.panels_area.setTabsClosable(False)

        # QMdiArea paints its own background via QPalette.Window rather than
        # respecting a plain stylesheet `background-color` on #PanelsArea —
        # that's why it shows up grey by default. Setting the palette
        # directly (in addition to the stylesheet rule in styles.py) is
        # what actually overrides it.
        panels_palette = self.panels_area.palette()
        panels_palette.setColor(QPalette.Window, QColor(BACKGROUND_COLOR))
        self.panels_area.setPalette(panels_palette)
        self.panels_area.setBackground(QColor(BACKGROUND_COLOR))

        centre_layout.addWidget(self.panels_area, stretch=1)

        self.event_detail_panel = EventDetailPanel()
        centre_layout.addWidget(self.event_detail_panel)

        body_layout.addWidget(centre, stretch=1)

        # Zone 5: Right investigation dashboard
        self.dashboard = InvestigationDashboard()
        body_layout.addWidget(self.dashboard)

        root_layout.addWidget(body, stretch=1)

    def _connect_signals(self) -> None:
        self.top_nav.import_logs_clicked.connect(self._on_import_logs)
        self.top_nav.timezone_changed.connect(self._on_timezone_changed)
        self.top_nav.sync_scroll_toggled.connect(self._on_sync_scroll_toggled)

        self.tab_manager.tab_selected.connect(self._on_tab_selected)

        self.timeframe_selector.filter_applied.connect(self._on_filter_applied)
        self.timeframe_selector.filter_cleared.connect(self._on_filter_cleared)

        self.dashboard.correlated_event_clicked.connect(self._on_correlated_event_clicked)

    # -- Log panel management -----------------------------------------------------

    def add_log_panel(self, source_label: str, color_hex: str, columns: list[str]) -> LogWindowWidget:
        panel = LogWindowWidget(source_label=source_label, color_hex=color_hex, columns=columns)
        panel.row_selected.connect(self._on_row_selected)
        panel.scrolled.connect(self._on_panel_scrolled)
        panel.panel_closed.connect(self._on_panel_closed)
        panel.restore_size_requested.connect(self._on_restore_size_requested)

        # Wrap in a QMdiSubWindow so the investigator can drag to move,
        # drag edges/corners to resize, and click the native X button to
        # close — none of which a plain layout-managed widget supports.
        sub_window = QMdiSubWindow()
        sub_window.setWidget(panel)
        sub_window.setWindowTitle(source_label)
        sub_window.setAttribute(Qt.WA_DeleteOnClose, True)
        # LogWindowWidget.closeEvent() already emits panel_closed when the
        # sub-window's X button is clicked, since closing a QMdiSubWindow
        # propagates closeEvent to its inner widget first.

        self.panels_area.addSubWindow(sub_window)
        sub_window.resize(480, 420)
        sub_window.show()

        self.log_panels[source_label] = panel
        self.log_subwindows[source_label] = sub_window
        self.tab_manager.add_tab(source_label, color_hex)

        # Side-by-side default layout for newly-opened panels — re-tile
        # existing windows so they reflow rather than stacking on top of
        # each other. Investigators can still freely drag/resize afterwards;
        # this only sets the initial arrangement.
        #
        # IMPORTANT: tileSubWindows() silently un-maximizes any currently
        # maximized sub-window without updating its title-bar button state
        # to match — this was the cause of a "maximize gets stuck" bug
        # found during testing. Skipping the auto-tile whenever any panel
        # is already maximized avoids triggering that mismatch.
        any_maximized = any(
            sw.windowState() & Qt.WindowMaximized
            for sw in self.log_subwindows.values()
        )
        if not any_maximized:
            self.panels_area.tileSubWindows()

        self.top_nav.set_loaded_count(len(self.log_panels))
        self.top_nav.set_sync_scroll_enabled(len(self.log_panels) >= 2)

        # If sync scroll was already toggled on before this panel was
        # added, register it immediately — otherwise a log imported after
        # enabling sync would silently sit outside the synced group until
        # the investigator toggled sync off and back on.
        if self._sync_scroll_enabled:
            self._scroll_sync.register_window(source_label, panel)

        return panel

    @staticmethod
    def _badge_label_for_panel(iana_tz: str, panel: LogWindowWidget) -> str:
        """Returns the full "Country (City), UTC+X" badge text for one panel,
        with the UTC offset computed against that panel's OWN loaded data
        (its earliest entry) rather than "now" — see timezone_map.py's
        get_utc_offset_label() docstring for why this matters for the
        DST-observing zones (Adelaide, Melbourne, Sydney): the same zone can
        legitimately show a different offset for different panels if their
        data falls in different DST periods.

        Falls back to "now" (via display_label_for_timezone's default) if
        the panel has no valid normalized entries yet to anchor to.
        """
        reference_dt = None
        entries = panel.table_model.get_entries()
        for entry in entries:
            if entry.normalized_timestamp is not None:
                reference_dt = entry.normalized_timestamp.utc_datetime
                break
        return display_label_for_timezone(iana_tz, reference_dt)

    # -- Signal handlers -----------------------------------------------------------

    def _on_import_logs(self) -> None:
        """R1 — Section 4.7.1 ImportAndParse.

        Flow:
            1. File picker — one or more log files.
            2. Single timezone dialog — asks what timezone the investigator
               wants to VIEW times in (not per-file source timezones).
            3. Parse files via LogParser.
            4. For each result, create a panel and load entries.
            5. Apply the chosen display timezone to all new panels immediately.

        Timestamp rules (handled in TimestampNormalizer, not here):
            - Timestamps ending in Z are already UTC — converted straight to
              display tz.
            - Timestamps without Z are assumed Perth (AWST, UTC+8) — converted
              to UTC first, then to display tz.
        """
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Import log files", "", "Log files (*.csv *.xlsx *.txt)"
        )
        if not file_paths:
            return

        # Single dialog — asks for display timezone only, not per-file source tz.
        dialog = TimezoneImportDialog(file_paths, parent=self)
        if dialog.exec() != TimezoneImportDialog.Accepted:
            return  # investigator cancelled; do not import

        display_tz = dialog.display_timezone  # IANA string, e.g. "Asia/Dubai"

        results = LogParser.parse_files(file_paths)

        _PANEL_COLOURS = [
            "#4A90D9", "#7c3aed", "#22c55e", "#f59e0b",
            "#ef4444", "#38bdf8", "#ec4899", "#00c4e8",
        ]
        existing_count = len(self.log_panels)

        for i, result in enumerate(results):
            if result.failed:
                print(f"File error [{result.source_label}]: {result.file_error}")
                continue

            if not result.valid_entries:
                print(f"No valid entries in {result.source_label}")
                continue

            color = _PANEL_COLOURS[(existing_count + i) % len(_PANEL_COLOURS)]
            columns = list(result.valid_entries[0].fields.keys())
            panel = self.add_log_panel(result.source_label, color, columns)
            panel.load_rows(result.valid_entries)
            self.dashboard.load_entries(result.source_label, result.valid_entries, color)

        # Apply display timezone to every panel (including ones just added).
        # Each panel's badge is computed from ITS OWN loaded entries (below)
        # rather than a single shared string, since DST-observing zones can
        # legitimately show a different UTC offset per panel depending on
        # what dates that panel's data actually falls on.
        for panel in self.log_panels.values():
            panel.set_timezone_label(self._badge_label_for_panel(display_tz, panel))
            panel.set_display_timezone(display_tz)

        self.dashboard.set_display_timezone(display_tz)
        self.timeframe_selector.set_timezone(display_tz)

        # Phase 4 — newly imported panels should land in whatever sort
        # order is already active, not raw file/merge order.
        self._apply_sort_to_all_panels()


    def _on_timezone_changed(self, iana_tz: str) -> None:
        """Phase 1: TopNavBar.timezone_changed now emits the IANA timezone
        string directly (e.g. "Australia/Sydney") rather than a display
        label — the old approach of parsing "UTC+X" back out of a label
        string breaks for the DST-observing zones (Adelaide, Melbourne,
        Sydney), which don't have one single fixed offset to embed in a
        static label at all. See TopNavBar's module docstring.

        TODO (R3 — Section 4.7.5 NormalizeTimestamp):
            set_timezone_for_source() below updates SOURCE_TIMEZONE_
            ASSIGNMENTS, which TimestampNormalizer.normalize_for_source()
            reads — but only the NEXT time a file is parsed. Entries already
            loaded keep whatever UTC value they were normalized to at
            import time; this does NOT re-run normalization on already-
            loaded entries or re-render the dashboard/timeline against the
            new source timezone. That gap is real: changing the dropdown
            after import currently only updates display badges, not the
            underlying data. A correct full implementation needs to either
            re-parse loaded files or re-localize each entry's stored
            milliseconds, which doesn't exist yet.

        NOTE: SOURCE_TIMEZONE_ASSIGNMENTS represents the ORIGINAL authoring
        timezone TimestampNormalizer assumes when parsing a source's raw
        timestamps — it is not really a "display" timezone in the sense of
        reformatting already-UTC values for viewing. This dropdown
        currently conflates the two; calling set_timezone_for_source() here
        is what makes the dropdown affect parsing at all (its absence was
        the actual cause of "timezone conversion isn't working" — every
        source was silently parsed as Dubai-authored regardless of the
        dropdown, since SOURCE_TIMEZONE_ASSIGNMENTS started empty and
        DEFAULT_TIMEZONE is Dubai). A future iteration should likely
        separate "what timezone was this log written in" from "what
        timezone do I want to view times in" as two distinct controls.
        """
        self.timeframe_selector.set_timezone(iana_tz)
        self.dashboard.set_display_timezone(iana_tz)

        for source_label in self.log_panels:
            set_timezone_for_source(source_label, iana_tz)

        for panel in self.log_panels.values():
            # Badge text is computed per-panel from that panel's own loaded
            # entries (DST-aware — see _badge_label_for_panel's docstring),
            # not parsed from the dropdown's display label.
            panel.set_timezone_label(self._badge_label_for_panel(iana_tz, panel))

            # The actual fix (pre-Phase-1): set_timezone_label() above only
            # updates the small badge text. Without this call, every row's
            # TIMESTAMP column kept showing the raw, unconverted source
            # string regardless of which timezone was selected — confirmed
            # by importing the same WLC log under Dubai then Perth and
            # seeing identical timestamps in both windows. The backend
            # conversion (TimestampNormalizer) was already correct; only
            # the display layer never read normalized_timestamp at all.
            panel.set_display_timezone(iana_tz)

    def _on_sync_scroll_toggled(self, enabled: bool) -> None:
        """Register or unregister all open log panels with ScrollSyncManager
        (Section 4.7.3 SyncScroll) — Hiba's real implementation, replacing
        the earlier `pass` stub.

        Phase 3 gate: Sync Scroll can only be switched ON once the sidebar's
        Start/End time range (TimeFrameSelector) has been successfully
        applied — reuses that existing filter state as the gate rather than
        adding a second/separate validity dialog (locked-in decision). If
        the investigator tries to enable it before that, the toggle button
        is reverted back to unchecked and a message box explains why.

        Note this only gates the moment of turning Sync Scroll ON. It does
        not retroactively turn Sync Scroll back OFF if the time range is
        cleared afterward while sync is already active — that's outside
        what Phase 3 asked for, and would need its own decision (e.g.
        whether clearing the filter mid-sync should silently disable sync,
        or just leave it running against the last-applied range).
        """
        if enabled and self._active_filter_config is None:
            # The button has already flipped to "checked" by the time this
            # handler runs (that's how QPushButton.toggled fires) — revert
            # it rather than leaving it showing "on" for a sync that never
            # actually started.
            self.top_nav.set_sync_scroll_checked(False)
            QMessageBox.warning(
                self, "Sync Scroll", "Please enter a valid time range first."
            )
            return

        self._sync_scroll_enabled = enabled
        self._scroll_sync.clear()
        if enabled:
            for source_label, panel in self.log_panels.items():
                self._scroll_sync.register_window(source_label, panel)

            # Phase 8 — the moment sync is switched on, jump every panel
            # to the START of the already-applied (and padded) highlighted
            # range, so the investigator doesn't have to manually re-align
            # them by hand first. That start timestamp becomes the
            # reference/datum panels stay aligned around as the
            # investigator scrolls from here. self._active_filter_config
            # is guaranteed non-None at this point — the guard clause
            # above already returned early otherwise.
            self._scroll_sync.move_all_to_timestamp(self._active_filter_config.start_time)

    def _on_sort_index_changed(self, index: int) -> None:
        """Handles the sidebar sort dropdown directly (it's built inline in
        _build_ui rather than as its own widget class, so MainWindow reads
        userData itself instead of a child widget emitting a signal).
        """
        ascending = self.sort_dropdown.itemData(index)
        self._on_sort_order_changed(bool(ascending))

    def _on_sort_order_changed(self, ascending: bool) -> None:
        """Phase 4 — the sidebar's single global sort dropdown. Applies to
        every currently-open panel at once (not per-panel), and the chosen
        direction is remembered on self._sort_ascending so any panel
        imported afterwards (_on_import_logs / _load_mock_session) is
        brought into the same order via _apply_sort_to_all_panels() rather
        than sitting in raw file/merge order until re-touched.

        LogTableModel.sort_by_timestamp() itself preserves each panel's
        highlighted rows and current selection across the re-sort, so
        nothing further needs to happen here for that.
        """
        self._sort_ascending = ascending
        self._apply_sort_to_all_panels()

    def _apply_sort_to_all_panels(self) -> None:
        """Re-applies the current global sort direction to every open
        panel's table model. Called both when the dropdown changes and
        whenever new panels are added, so newly imported logs land in the
        same order as everything already on screen instead of only sorting
        on the next explicit dropdown change.
        """
        for panel in self.log_panels.values():
            panel.table_model.sort_by_timestamp(self._sort_ascending)

    def _on_tab_selected(self, source_label: str) -> None:
        self.tab_manager.set_focused_tab(source_label)
        # TODO: bring the corresponding LogWindowWidget into focus / scroll
        # the panels_area so it is visible if off-screen.

    def _pad_filter_config(self, config: FilterConfig) -> FilterConfig:
        """Widens whatever start/end the investigator typed by 1 minute on
        each side — subtracted from start_time, added to end_time — before
        anything downstream ever sees the range: LogFilter matching, row
        highlighting, the new auto-jump-to-first-match, Sync Scroll's
        Phase 3 gate, and the dashboard's investigation-window shading all
        read self._active_filter_config, so padding it exactly once, here,
        means every one of those stays consistent automatically — none of
        them need to know padding happened or re-derive it themselves.

        Returns a shallow copy rather than mutating the FilterConfig
        TimeFrameSelector handed us — that instance may still be read
        elsewhere (e.g. by the sidebar for its own Start/End field display),
        so mutating it in place would risk the padded values silently
        leaking back into what the investigator sees typed in the boxes.
        """
        padded = copy.copy(config)
        padded.start_time = config.start_time - timedelta(minutes=1)
        padded.end_time = config.end_time + timedelta(minutes=1)
        return padded

    def _on_filter_applied(self, config: FilterConfig) -> None:
        """Section 4.7.2 ApplyFilter (R4, R5, R6) — fully wired to the real
        LogFilter implementation.
        """
        # Widen the investigator-entered range by ±1 minute before it's
        # used for anything — see _pad_filter_config's docstring for why
        # this happens exactly once, up front.
        config = self._pad_filter_config(config)
        self.filter_range_label.setText(
            "Search window padded by 1 min before the start and 1 min after the end."
        )

        # Phase 3 — a successfully applied filter is what unlocks Sync
        # Scroll (see _on_sync_scroll_toggled). Recorded here rather than
        # in TimeFrameSelector itself, since MainWindow — not the sidebar
        # widget — is what owns cross-component gating decisions per the
        # module docstring's "sole orchestrator" rule.
        self._active_filter_config = config

        all_entries = {
            source_label: panel.table_model.get_entries()
            for source_label, panel in self.log_panels.items()
        }

        try:
            matched = LogFilter.apply_filter(config, all_entries)
        except FilterValidationError:
            # TimeFrameSelector already validates before emitting
            # filter_applied, so this should not normally trigger. Guarded
            # here in case apply_filter is ever called from elsewhere.
            return

        # Step 4 — highlight matched rows in each panel.
        #
        # Phase 5 — pass the matched RawLogEntry objects straight through
        # rather than going via LogFilter.get_matched_row_indices() first.
        # That helper returns each entry's row_index (Section 4.7.1's
        # ORIGINAL file/import order), which was previously fed into
        # highlight_matched() and treated as a current row POSITION —
        # correct only by coincidence right after a fresh load, and wrong
        # the moment the table has been sorted (Phase 4) into a different
        # order than the file. LogWindowWidget/LogTableModel now track
        # matched state by entry identity instead, so they need the
        # entries themselves, not a position snapshot.
        #
        # Auto-jump: once a panel's matched state is up to date, scroll it
        # straight to its own first (topmost, current-sort-order) matched
        # row, so the investigator lands on the highlighted range
        # immediately instead of having to scroll and hunt for it. Each
        # panel jumps independently to ITS OWN first match — a source with
        # no matches simply doesn't move.
        for source_label, panel in self.log_panels.items():
            panel.highlight_matched(matched.get(source_label, []))
            panel.scroll_to_first_match()

        # Steps 5-6 — update tab states.
        active_sources, inactive_sources = LogFilter.get_active_inactive_sources(matched)
        self.tab_manager.highlight_active_tabs(active_sources, inactive_sources)
        for source_label, entries in matched.items():
            self.tab_manager.set_match_count(source_label, len(entries))

        # Step 7 — refresh dashboard summary.
        summary = LogFilter.build_dashboard_summary(matched)
        self.dashboard.refresh(summary, active_sources, inactive_sources)

        # Drives the activity chart's dimmed-vs-full-opacity bar split.
        self.dashboard.set_investigation_window(config.start_time, config.end_time)

        total_matched = sum(len(v) for v in matched.values())
        self.dashboard.matched_card.set_value(str(total_matched))

    def _on_filter_cleared(self) -> None:
        # Phase 3 — clearing the filter revokes the Sync Scroll gate for
        # any FUTURE attempt to turn sync on; see _on_sync_scroll_toggled's
        # docstring for why this deliberately does not also turn off an
        # already-active sync.
        self._active_filter_config = None
        self.filter_range_label.setText("")

        for panel in self.log_panels.values():
            panel.highlight_matched([])
        self.dashboard.set_investigation_window(None, None)

    def _on_row_selected(self, entry: RawLogEntry) -> None:
        # TODO (R13 — Section 4.7.4 Correlate):
        #   Replace correlation_count=0 with the real count from
        #   EventCorrelator once src/correlator/event_correlator.py exists.
        self.event_detail_panel.show_event(entry, correlation_count=0)

    def _on_panel_scrolled(self, source_label: str, scroll_position: int) -> None:
        """Forwards a scroll event to ScrollSyncManager when sync scroll is
        enabled — Hiba's real Section 4.7.3 SyncScroll implementation,
        replacing the earlier `pass` stub. ScrollSyncManager.sync_scroll()
        itself handles the binary search and the is_syncing recursion
        guard; this handler only needs to look up the source panel and
        forward to it.
        """
        if not self._sync_scroll_enabled:
            return
        source_panel = self.log_panels.get(source_label)
        if source_panel is not None:
            self._scroll_sync.sync_scroll(source_panel, scroll_position)

    def _on_panel_closed(self, source_label: str) -> None:
        """Cleans up state when a log panel is closed via its sub-window's
        X button (or programmatically). Without this, self.log_panels and
        self.log_subwindows would keep stale references to a destroyed
        widget, and the tab would keep pointing at nothing.
        """
        self.log_panels.pop(source_label, None)
        self.log_subwindows.pop(source_label, None)
        self.tab_manager.remove_tab(source_label)
        self.dashboard.remove_source(source_label)

        # Now that ScrollSyncManager is wired in (_on_sync_scroll_toggled),
        # a closed panel must be dropped from it too — otherwise sync_scroll
        # would keep calling receive_sync_scroll() on a LogWindowWidget that
        # no longer exists the next time another panel scrolls.
        self._scroll_sync.unregister_window(source_label)

        if f"\u00b7 {source_label}" in self.event_detail_panel.header_label.text():
            self.event_detail_panel.clear()

        self.top_nav.set_loaded_count(len(self.log_panels))
        self.top_nav.set_sync_scroll_enabled(len(self.log_panels) >= 2)

    def _on_restore_size_requested(self, source_label: str) -> None:
        """Handles LogWindowWidget's restore-size button — a deliberate
        bypass of QMdiArea's native title-bar maximize/restore button,
        which testing showed can get visually or functionally stuck on
        some platforms. This handler calls showNormal() directly on the
        real QMdiSubWindow, then forces a sane default size.
        """
        sub_window = self.log_subwindows.get(source_label)
        if sub_window is None:
            return

        sub_window.showNormal()
        sub_window.resize(480, 420)

    def _on_correlated_event_clicked(self, timestamp: str) -> None:
        """TODO: scroll all open log panels to the given timestamp."""
        pass

    # -- Development-only mock session loader ----------------------------------------

    def _load_mock_session(self) -> None:
        """Loads mock_data.py content so the interface is reviewable before
        LogParser exists. DELETE this method once real import is wired up.
        """
        log_files = mock_data.get_mock_log_files()
        entries_by_source = {
            "Interactive_signin": mock_data.get_mock_entries_interactive_signin(),
            "MUPC_events": mock_data.get_mock_entries_mupc_events(),
            "WLC_events": mock_data.get_mock_entries_wlc_events(),
        }

        for log_file in log_files:
            columns = mock_data.SOURCE_COLUMNS[log_file.source_label]
            color = mock_data.SOURCE_COLORS[log_file.source_label]
            panel = self.add_log_panel(log_file.source_label, color, columns)
            panel.load_rows(entries_by_source[log_file.source_label])
            self.dashboard.load_entries(log_file.source_label, entries_by_source[log_file.source_label], color)

        stats = mock_data.MOCK_SESSION_STATS
        self.dashboard.set_session_stats(
            total=stats["total_events"], matched=stats["matched"],
            failures=stats["failures"], correlated=stats["correlated"],
        )
        self.dashboard.set_correlated_events(mock_data.MOCK_CORRELATED_EVENTS)

        # Phase 4 — keep the mock loader consistent with the real import
        # path above.
        self._apply_sort_to_all_panels()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
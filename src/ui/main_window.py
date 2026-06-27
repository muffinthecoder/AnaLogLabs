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

owned by: fatima
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFileDialog,
    QMdiArea, QMdiSubWindow
)

from src.ui.styles import MAIN_STYLESHEET
from src.ui.top_nav_bar import TopNavBar
from src.ui.tab_manager import TabManager
from src.ui.timeframe_selector import TimeFrameSelector
from src.ui.log_window_widget import LogWindowWidget
from src.ui.event_detail_panel import EventDetailPanel
from src.ui.investigation_dashboard import InvestigationDashboard

from src import mock_data
from src.models.data_classes import FilterConfig, RawLogEntry
from src.filter.log_filter import LogFilter, FilterValidationError
from src.parser.log_parser import LogParser

# TODO (Fatima — styles.py):
#   Move this to styles.py once that file is shared/consolidated, so the
#   QMdiArea background and the rest of the dark theme stay in one place
#   instead of main_window.py hardcoding its own color. Match this to
#   whatever the outer app background is in MAIN_STYLESHEET (looked like
#   #0a0e1a from the screenshot — confirm against the real value).
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
        # that's why it showed up grey once there were no sub-windows to
        # cover it. Setting the palette directly (in addition to the
        # stylesheet rule in styles.py) is what actually overrides it.
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
        # to match — this was the cause of the "maximize gets stuck" bug
        # reported during testing (the window's actual geometry and Qt's
        # internal windowState end up disagreeing, and from that point on
        # neither the maximize nor restore button behaves correctly until
        # the panel is closed). Skipping the auto-tile whenever any panel
        # is already maximized avoids triggering that mismatch in the first
        # place, at the cost of not auto-arranging new panels in that case
        # — an acceptable trade since an investigator who has deliberately
        # maximized a panel almost certainly doesn't want it silently
        # resized anyway.
        any_maximized = any(
            sw.windowState() & Qt.WindowMaximized
            for sw in self.log_subwindows.values()
        )
        if not any_maximized:
            self.panels_area.tileSubWindows()

        self.top_nav.set_loaded_count(len(self.log_panels))
        self.top_nav.set_sync_scroll_enabled(len(self.log_panels) >= 2)
        return panel

    # -- Signal handlers -----------------------------------------------------------

    def _on_import_logs(self) -> None:
        """R1 — Section 4.7.1 ImportAndParse: Wire LogParser to UI."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Import log files", "", "Log files (*.csv *.xlsx *.txt)"
        )
        if not file_paths:
            return

        results = LogParser.parse_files(file_paths)
        for result in results:
            if result.failed:
                # TODO: show error dialog with result.file_error
                print(f"File error: {result.file_error}")
                continue

            if not result.valid_entries:
                # TODO: show warning dialog — file parsed but had 0 valid rows
                print(f"No valid entries in {result.source_label}")
                continue

            columns = list(result.valid_entries[0].fields.keys())
            color = "#4A90D9"  # default blue
            panel = self.add_log_panel(result.source_label, color, columns)
            panel.load_rows(result.valid_entries)

            # Feeds the activity frequency chart and timeline (Minal's
            # visualisations) — they need the FULL entry set, not just
            # LogFilter's matched subset, so they can be wired here rather
            # than only inside _on_filter_applied.
            self.dashboard.load_entries(result.source_label, result.valid_entries, color)

    def _on_timezone_changed(self, timezone_label: str) -> None:
        """TODO (R3 — Section 4.7.5 NormalizeTimestamp):
            For a full implementation, this should also trigger
            re-normalisation of all loaded timestamps via
            TimestampNormalizer for sources whose ORIGINAL source timezone
            assignment changes (not just the display timezone), then
            re-render affected visualisations.
        """
        label_to_iana = {
            "Dubai (GST, UTC+4)": "Asia/Dubai",
            "Singapore (SGT, UTC+8)": "Asia/Singapore",
            "Perth (AWST, UTC+8)": "Australia/Perth",
        }
        iana_tz = label_to_iana.get(timezone_label, "Asia/Dubai")
        self.timeframe_selector.set_timezone(iana_tz)
        self.dashboard.set_display_timezone(iana_tz)

        for panel in self.log_panels.values():
            tz_short = timezone_label.split("(")[1].split(",")[1].strip(") ")
            panel.set_timezone_label(tz_short)

    def _on_sync_scroll_toggled(self, enabled: bool) -> None:
        """TODO (Section 4.7.3 SyncScroll):
            Wire to ScrollSyncManager — when enabled, register all open
            LogWindowWidgets; when disabled, unregister them.
        """
        pass

    def _on_tab_selected(self, source_label: str) -> None:
        self.tab_manager.set_focused_tab(source_label)
        # TODO: bring the corresponding LogWindowWidget into focus / scroll
        # the panels_area so it is visible if off-screen.

    def _on_filter_applied(self, config: FilterConfig) -> None:
        """Section 4.7.2 ApplyFilter (R4, R5, R6) — fully wired to the real
        LogFilter implementation.
        """
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
        for source_label, panel in self.log_panels.items():
            matched_indices = LogFilter.get_matched_row_indices(matched.get(source_label, []))
            panel.highlight_matched(matched_indices)

        # Steps 5-6 — update tab states.
        active_sources, inactive_sources = LogFilter.get_active_inactive_sources(matched)
        self.tab_manager.highlight_active_tabs(active_sources, inactive_sources)
        for source_label, entries in matched.items():
            self.tab_manager.set_match_count(source_label, len(entries))

        # Step 7 — refresh dashboard summary.
        summary = LogFilter.build_dashboard_summary(matched)
        self.dashboard.refresh(summary, active_sources, inactive_sources)

        # Drives the activity chart's dimmed-vs-full-opacity bar split
        # (Section 6.3.4 Zone 5 subsection 1). See the TODO on
        # InvestigationDashboard.refresh() for why this is a direct call
        # rather than threaded through the summary dict.
        self.dashboard.set_investigation_window(config.start_time, config.end_time)

        total_matched = sum(len(v) for v in matched.values())
        self.dashboard.matched_card.set_value(str(total_matched))

    def _on_filter_cleared(self) -> None:
        for panel in self.log_panels.values():
            panel.highlight_matched([])
        self.dashboard.set_investigation_window(None, None)

    def _on_row_selected(self, entry: RawLogEntry) -> None:
        # TODO (R13 — Section 4.7.4 Correlate):
        #   Replace correlation_count=0 with the real count from
        #   EventCorrelator once src/correlator/event_correlator.py exists.
        self.event_detail_panel.show_event(entry, correlation_count=0)

    def _on_panel_scrolled(self, source_label: str, scroll_position: int) -> None:
        """TODO (Section 4.7.3 SyncScroll):
            If sync scroll is enabled, find the anchor timestamp at
            scroll_position in this panel, binary-search the closest row in
            every other open panel, then call their receive_sync_scroll().
            Must guard against recursive loops (ScrollSyncManager.is_syncing).
        """
        pass

    def _on_panel_closed(self, source_label: str) -> None:
        """Cleans up state when a log panel is closed via its sub-window's
        X button (or programmatically). Without this, self.log_panels and
        self.log_subwindows would keep stale references to a destroyed
        widget, and the tab would keep pointing at nothing.

        TODO (Section 4.7.3 SyncScroll):
            Once ScrollSyncManager is wired in (_on_sync_scroll_toggled),
            also call ScrollSyncManager.unregister_window(source_label)
            here so a closed panel isn't still targeted by sync scroll.
        """
        self.log_panels.pop(source_label, None)
        self.log_subwindows.pop(source_label, None)
        self.tab_manager.remove_tab(source_label)
        self.dashboard.remove_source(source_label)

        if f"\u00b7 {source_label}" in self.event_detail_panel.header_label.text():
            self.event_detail_panel.clear()

        self.top_nav.set_loaded_count(len(self.log_panels))
        self.top_nav.set_sync_scroll_enabled(len(self.log_panels) >= 2)

    def _on_restore_size_requested(self, source_label: str) -> None:
        """Handles LogWindowWidget's restore-size button — a deliberate
        bypass of QMdiArea's native title-bar maximize/restore button,
        which testing showed can get visually or functionally stuck on
        some platforms (clicking it a second time doesn't always call
        showNormal() or re-enable dragging/resizing — a QMdiArea/platform
        quirk, not something reproducible by calling showNormal() directly
        in code). This handler calls that same showNormal() directly on
        the real QMdiSubWindow, then forces a sane default size — so even
        if the window's internal state was somehow left inconsistent by
        the native button, this always produces a normal, resizable,
        sensibly-sized window the investigator can immediately drag again.
        """
        sub_window = self.log_subwindows.get(source_label)
        if sub_window is None:
            return

        sub_window.showNormal()
        # Re-applying a concrete size (rather than relying solely on
        # showNormal() to restore whatever geometry was cached before
        # maximizing) is the actual fix for "doesn't become resizable
        # again" — if the cached pre-maximize geometry was ever left in an
        # inconsistent state, showNormal() alone can return a window that
        # LOOKS normal but whose resize handles don't respond until some
        # other geometry change occurs. Explicitly resizing guarantees a
        # clean, working state every time this button is clicked.
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


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
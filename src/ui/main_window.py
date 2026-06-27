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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFileDialog
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


class MainWindow(QMainWindow):
    """Application shell — Section 5.2 Presentation Layer."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AnaLog Labs")
        self.resize(1400, 900)
        self.setStyleSheet(MAIN_STYLESHEET)

        # source_label -> LogWindowWidget, mirrors ScrollSyncManager.windows
        self.log_panels: dict[str, LogWindowWidget] = {}

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

        self.panels_area = QWidget()
        self.panels_layout = QHBoxLayout(self.panels_area)
        self.panels_layout.setContentsMargins(0, 0, 0, 0)
        self.panels_layout.setSpacing(0)
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

        self.log_panels[source_label] = panel
        self.panels_layout.addWidget(panel)
        self.tab_manager.add_tab(source_label, color_hex)

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

        total_matched = sum(len(v) for v in matched.values())
        self.dashboard.matched_card.set_value(str(total_matched))

    def _on_filter_cleared(self) -> None:
        for panel in self.log_panels.values():
            panel.highlight_matched([])

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

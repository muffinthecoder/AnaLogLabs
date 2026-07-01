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

MVP additions wired here:
    R1 — pop log panels out into free-floating desktop windows
    R3 — display-timezone switching across Australian cities + Dubai/Singapore
    R5 — cross-file flag/pin markers
    R7 — "lock windows" unified single-scrollbar view
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFileDialog,
    QMdiArea, QMdiSubWindow, QStackedWidget,
)

from src.ui.styles import MAIN_STYLESHEET
from src.ui.top_nav_bar import TopNavBar
from src.ui.tab_manager import TabManager
from src.ui.timeframe_selector import TimeFrameSelector
from src.ui.log_window_widget import LogWindowWidget
from src.ui.event_detail_panel import EventDetailPanel
from src.ui.investigation_dashboard import InvestigationDashboard
from src.ui.floating_log_window import FloatingLogWindow
from src.ui.locked_workspace import LockedWorkspace

from src import mock_data
from src.models.data_classes import FilterConfig, RawLogEntry
from src.filter.log_filter import LogFilter, FilterValidationError
from src.parser.log_parser import LogParser
from src.normaliser.timezone_map import utc_offset_label, DEFAULT_TIMEZONE
from src.correlator.scroll_sync_manager import ScrollSyncManager

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
        # container each docked LogWindowWidget lives inside. A panel that has
        # been popped out (R1) or locked (R7) is NOT in this dict.
        self.log_subwindows: dict[str, QMdiSubWindow] = {}

        # source_label -> FloatingLogWindow for panels popped out of the app
        # into free-floating desktop windows (R1).
        self.floating_windows: dict[str, FloatingLogWindow] = {}

        # Hiba's Section 4.7.3 SyncScroll implementation — aligns panels by
        # UTC timestamp rather than row index.
        self._scroll_sync = ScrollSyncManager()
        self._sync_scroll_enabled: bool = False

        # R7 lock-mode state.
        self._locked: bool = False
        self._sync_before_lock: bool = False

        # The display timezone every panel/label renders times in (R3). Starts
        # at the default (Perth) and follows TopNavBar's dropdown thereafter.
        self._display_tz: str = DEFAULT_TIMEZONE

        self._build_ui()
        self._connect_signals()

        # TODO (Pooja — testing): remove once real import flow is signed off.
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

        self.timeframe_selector = TimeFrameSelector(timezone=self._display_tz)
        sidebar_layout.addWidget(self.timeframe_selector)

        sidebar_layout.addStretch()
        body_layout.addWidget(self.left_sidebar)

        # Zone 3 + 4: Central workspace (log panels + detail panel)
        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(0)

        # Zone 3: log panel workspace. A QStackedWidget lets us swap between
        # the normal MDI workspace (freely movable sub-windows) and the R7
        # locked workspace (all panels snapped together under one scrollbar)
        # without tearing down either.
        self.panels_area = QMdiArea()
        self.panels_area.setObjectName("PanelsArea")
        self.panels_area.setViewMode(QMdiArea.SubWindowView)
        self.panels_area.setOption(QMdiArea.DontMaximizeSubWindowOnActivation, True)
        self.panels_area.setTabsClosable(False)

        panels_palette = self.panels_area.palette()
        panels_palette.setColor(QPalette.Window, QColor(BACKGROUND_COLOR))
        self.panels_area.setPalette(panels_palette)
        self.panels_area.setBackground(QColor(BACKGROUND_COLOR))

        self._locked_workspace = LockedWorkspace(self._scroll_sync)

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self.panels_area)       # index 0
        self.workspace_stack.addWidget(self._locked_workspace)  # index 1
        centre_layout.addWidget(self.workspace_stack, stretch=1)

        self.event_detail_panel = EventDetailPanel()
        centre_layout.addWidget(self.event_detail_panel)

        body_layout.addWidget(centre, stretch=1)

        # Zone 5: Right investigation dashboard
        self.dashboard = InvestigationDashboard()
        self.dashboard.set_display_timezone(self._display_tz)
        body_layout.addWidget(self.dashboard)

        root_layout.addWidget(body, stretch=1)

    def _connect_signals(self) -> None:
        self.top_nav.import_logs_clicked.connect(self._on_import_logs)
        self.top_nav.timezone_changed.connect(self._on_timezone_changed)
        self.top_nav.sync_scroll_toggled.connect(self._on_sync_scroll_toggled)
        self.top_nav.lock_windows_toggled.connect(self._on_lock_windows_toggled)

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
        panel.detach_requested.connect(self._on_detach_requested)      # R1
        panel.flags_changed.connect(self._on_flags_changed)            # R5

        # Render the new panel in the current display timezone from the start
        # (R3) so a log imported after the dropdown was changed doesn't show
        # stale times/badge.
        panel.set_display_timezone(self._display_tz)
        panel.set_timezone_label(utc_offset_label(self._display_tz))

        self.log_panels[source_label] = panel
        self.tab_manager.add_tab(source_label, color_hex)

        if self._locked:
            # Fold the newcomer straight into the locked view.
            self._rebuild_locked_workspace()
        else:
            self._mount_in_mdi(panel, source_label)
            self._auto_tile()

        self.top_nav.set_loaded_count(len(self.log_panels))
        self._update_multi_panel_controls()

        if self._sync_scroll_enabled:
            self._scroll_sync.register_window(source_label, panel)

        return panel

    def _mount_in_mdi(self, panel: LogWindowWidget, source_label: str) -> QMdiSubWindow:
        """Wraps a panel in a movable/resizable/closable MDI sub-window and
        adds it to the workspace. Used on import and when docking a panel back
        from a floating or locked state.
        """
        sub_window = QMdiSubWindow()
        sub_window.setWidget(panel)
        sub_window.setWindowTitle(source_label)
        sub_window.setAttribute(Qt.WA_DeleteOnClose, True)
        # Closing the sub-window propagates closeEvent to the inner panel,
        # which emits panel_closed -> _on_panel_closed.
        self.panels_area.addSubWindow(sub_window)
        sub_window.resize(480, 420)
        sub_window.show()
        self.log_subwindows[source_label] = sub_window
        return sub_window

    def _auto_tile(self) -> None:
        """Side-by-side default layout for docked panels. Skipped while any
        panel is maximized (tileSubWindows() silently un-maximizes without
        fixing the title-bar button state — the old "maximize gets stuck" bug).
        """
        any_maximized = any(
            sw.windowState() & Qt.WindowMaximized
            for sw in self.log_subwindows.values()
        )
        if not any_maximized:
            self.panels_area.tileSubWindows()

    def _update_multi_panel_controls(self) -> None:
        """Sync/lock only make sense with 2+ panels, and lock can't run while
        any panel is floating (it snaps everything into one container).
        """
        multi = len(self.log_panels) >= 2
        self.top_nav.set_sync_scroll_enabled(multi)
        self.top_nav.set_lock_windows_enabled(multi and not self.floating_windows)

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
                print(f"File error: {result.file_error}")
                continue

            if not result.valid_entries:
                print(f"No valid entries in {result.source_label}")
                continue

            columns = list(result.valid_entries[0].fields.keys())
            color = "#4A90D9"  # default blue
            panel = self.add_log_panel(result.source_label, color, columns)
            panel.load_rows(result.valid_entries)

            self.dashboard.load_entries(result.source_label, result.valid_entries, color)

    def _on_timezone_changed(self, iana_tz: str) -> None:
        """R3 — change the DISPLAY timezone for every open panel and the
        dashboard. This never re-parses logs (imported logs are always
        assumed Perth-authored per R2 unless their raw timestamp carries an
        explicit offset); it only re-renders the stored UTC values in the
        chosen zone, which is exactly what the investigator wants when
        switching between office locations.
        """
        self._display_tz = iana_tz
        self.timeframe_selector.set_timezone(iana_tz)
        self.dashboard.set_display_timezone(iana_tz)
        self.event_detail_panel.set_display_timezone(iana_tz)

        badge = utc_offset_label(iana_tz)
        for panel in self.log_panels.values():
            panel.set_timezone_label(badge)
            panel.set_display_timezone(iana_tz)

    def _on_sync_scroll_toggled(self, enabled: bool) -> None:
        """Register/unregister all open panels with ScrollSyncManager
        (Section 4.7.3). Ignored while locked, since the locked workspace owns
        scrolling entirely.
        """
        if self._locked:
            return
        self._sync_scroll_enabled = enabled
        self._scroll_sync.clear()
        if enabled:
            for source_label, panel in self.log_panels.items():
                self._scroll_sync.register_window(source_label, panel)

    def _on_tab_selected(self, source_label: str) -> None:
        self.tab_manager.set_focused_tab(source_label)
        # If the panel is floating, raise its window; otherwise activate its
        # MDI sub-window so it's brought to the front.
        floating = self.floating_windows.get(source_label)
        if floating is not None:
            floating.raise_()
            floating.activateWindow()
            return
        sub_window = self.log_subwindows.get(source_label)
        if sub_window is not None:
            self.panels_area.setActiveSubWindow(sub_window)

    def _on_filter_applied(self, config: FilterConfig) -> None:
        """Section 4.7.2 ApplyFilter (R4, R5, R6) — wired to LogFilter. The
        ±1 minute boundary offset (R4) is already baked into config's
        start/end by TimeFrameSelector, so nothing extra is needed here.
        """
        all_entries = {
            source_label: panel.table_model.get_entries()
            for source_label, panel in self.log_panels.items()
        }

        try:
            matched = LogFilter.apply_filter(config, all_entries)
        except FilterValidationError:
            return

        for source_label, panel in self.log_panels.items():
            matched_indices = LogFilter.get_matched_row_indices(matched.get(source_label, []))
            panel.highlight_matched(matched_indices)

        active_sources, inactive_sources = LogFilter.get_active_inactive_sources(matched)
        self.tab_manager.highlight_active_tabs(active_sources, inactive_sources)
        for source_label, entries in matched.items():
            self.tab_manager.set_match_count(source_label, len(entries))

        summary = LogFilter.build_dashboard_summary(matched)
        self.dashboard.refresh(summary, active_sources, inactive_sources)
        self.dashboard.set_investigation_window(config.start_time, config.end_time)

        total_matched = sum(len(v) for v in matched.values())
        self.dashboard.matched_card.set_value(str(total_matched))

    def _on_filter_cleared(self) -> None:
        for panel in self.log_panels.values():
            panel.highlight_matched([])
        self.dashboard.set_investigation_window(None, None)

    def _on_row_selected(self, entry: RawLogEntry) -> None:
        self.event_detail_panel.show_event(entry, correlation_count=0)

    def _on_panel_scrolled(self, source_label: str, scroll_position: int) -> None:
        """Forwards a scroll to ScrollSyncManager when sync scroll is on and
        we're not locked (the locked workspace handles its own scrolling).
        """
        if self._locked or not self._sync_scroll_enabled:
            return
        source_panel = self.log_panels.get(source_label)
        if source_panel is not None:
            self._scroll_sync.sync_scroll(source_panel, scroll_position)

    def _on_panel_closed(self, source_label: str) -> None:
        """Cleans up all state when a panel is closed — via an MDI sub-window
        X, a floating window X, or programmatically.
        """
        self.log_panels.pop(source_label, None)
        self.log_subwindows.pop(source_label, None)
        self.floating_windows.pop(source_label, None)
        self.tab_manager.remove_tab(source_label)
        self.dashboard.remove_source(source_label)
        self._scroll_sync.unregister_window(source_label)

        if f"· {source_label}" in self.event_detail_panel.header_label.text():
            self.event_detail_panel.clear()

        self.top_nav.set_loaded_count(len(self.log_panels))
        self._update_multi_panel_controls()

        # A closed source's flags disappear, so refresh cross-file markers.
        self._recompute_cross_markers()

    def _on_restore_size_requested(self, source_label: str) -> None:
        """Restore-size button — bypasses QMdiArea's flaky native maximize
        button. No-op for floating/locked panels (they have no sub-window).
        """
        sub_window = self.log_subwindows.get(source_label)
        if sub_window is None:
            return
        sub_window.showNormal()
        sub_window.resize(480, 420)

    def _on_correlated_event_clicked(self, timestamp: str) -> None:
        """TODO: scroll all open log panels to the given timestamp."""
        pass

    # -- R1: pop-out / dock-back ---------------------------------------------------

    def _on_detach_requested(self, source_label: str) -> None:
        """Pop a panel out of the app into a free-floating desktop window."""
        # Floating panels and lock mode are mutually exclusive — lock snaps
        # everything into one container, so leave lock first.
        if self._locked:
            self.top_nav.lock_windows_button.setChecked(False)  # exits lock

        panel = self.log_panels.get(source_label)
        if panel is None or source_label in self.floating_windows:
            return

        sub_window = self.log_subwindows.pop(source_label, None)
        panel.setParent(None)  # detach before removing the empty sub-window
        if sub_window is not None:
            self.panels_area.removeSubWindow(sub_window)
            sub_window.deleteLater()

        floating = FloatingLogWindow(panel, source_label, parent=None)
        floating.redock_requested.connect(self._on_redock_requested)
        floating.closed.connect(self._on_floating_closed)
        self.floating_windows[source_label] = floating
        floating.show()

        self._update_multi_panel_controls()

    def _on_redock_requested(self, source_label: str) -> None:
        """Snap a floating panel back into the MDI workspace."""
        floating = self.floating_windows.pop(source_label, None)
        if floating is None:
            return
        panel = floating.panel
        floating.prepare_redock()   # so close() doesn't fire `closed`
        panel.setParent(None)
        floating.close()

        self._mount_in_mdi(panel, source_label)
        self._auto_tile()
        self._update_multi_panel_controls()

    def _on_floating_closed(self, source_label: str) -> None:
        """A floating window's own X was clicked — treat as closing the log.
        The panel is deleted with the window, so run the shared cleanup
        directly (a top-level close doesn't propagate to the child panel the
        way an MDI sub-window close does).
        """
        self._on_panel_closed(source_label)

    # -- R5: flags / cross-file markers -------------------------------------------

    def _on_flags_changed(self, _source_label: str) -> None:
        self._recompute_cross_markers()

    def _recompute_cross_markers(self) -> None:
        """R5 — for each panel, place a marker on the row whose timestamp is
        closest to every flag set in ANY OTHER file, coloured by the origin
        file. This is what makes a flagged event visible "at the corresponding
        point in time across all other open files".
        """
        flags = {s: p.flagged_timestamps() for s, p in self.log_panels.items()}
        colors = {s: p.color_hex for s, p in self.log_panels.items()}

        for target_source, target_panel in self.log_panels.items():
            entries = target_panel.table_model.get_entries()
            markers: dict[int, str] = {}
            if entries:
                for origin_source, stamps in flags.items():
                    if origin_source == target_source or not stamps:
                        continue
                    origin_color = colors.get(origin_source, "#ffd60a")
                    for ts in stamps:
                        idx = ScrollSyncManager._find_closest_index(entries, ts)
                        if 0 <= idx < len(entries):
                            markers[idx] = origin_color
            target_panel.set_cross_markers(markers)

    # -- R7: lock windows ----------------------------------------------------------

    def _on_lock_windows_toggled(self, enabled: bool) -> None:
        if enabled:
            if len(self.log_panels) < 2 or self.floating_windows:
                # Shouldn't happen (button is disabled), but guard anyway.
                self.top_nav.lock_windows_button.setChecked(False)
                return
            self._enter_lock_mode()
        else:
            if self._locked:
                self._exit_lock_mode()

    def _enter_lock_mode(self) -> None:
        self._locked = True
        # Locked workspace owns all scrolling; remember prior sync state so we
        # can restore it on unlock.
        self._sync_before_lock = self._sync_scroll_enabled
        self._sync_scroll_enabled = False

        # Pull every panel out of its MDI sub-window (panels are reparented by
        # LockedWorkspace.set_panels).
        for source_label, sub_window in list(self.log_subwindows.items()):
            panel = self.log_panels[source_label]
            panel.setParent(None)
            self.panels_area.removeSubWindow(sub_window)
            sub_window.deleteLater()
        self.log_subwindows.clear()

        self._scroll_sync.clear()
        self._locked_workspace.set_panels(self.log_panels)
        self.workspace_stack.setCurrentWidget(self._locked_workspace)

    def _exit_lock_mode(self) -> None:
        self._locked = False
        panels = self._locked_workspace.release_panels()
        self.workspace_stack.setCurrentWidget(self.panels_area)

        for source_label, panel in panels.items():
            self._mount_in_mdi(panel, source_label)
        self._auto_tile()

        # Restore the pre-lock sync state.
        self._scroll_sync.clear()
        self._sync_scroll_enabled = self._sync_before_lock
        if self._sync_scroll_enabled:
            for source_label, panel in self.log_panels.items():
                self._scroll_sync.register_window(source_label, panel)

    def _rebuild_locked_workspace(self) -> None:
        """Re-fold all current panels into the locked view — used when a log
        is imported while lock mode is already active.
        """
        self._locked_workspace.release_panels()
        self._scroll_sync.clear()
        self._locked_workspace.set_panels(self.log_panels)

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

"""
MainWindow — application shell.

Layout:

    ┌───────────────────────────── TOP BAR ─────────────────────────────┐
    │  import · sync scroll · convert-to timezone · stats                │
    ├────────────┬──────────────────────────────────────────────────────┤
    │            │  VISUALIZATION ROW  (heatmap | spike) + legend        │  ~1/3
    │  LEFT      ├──────────────────────────────────────────────────────┤
    │  PANEL     │  LOG VIEWING SPACE  (up to 8 windows) + event detail  │  ~2/3
    └────────────┴──────────────────────────────────────────────────────┘

MainWindow only wires signals; parsing/filtering/normalisation live in the
data/application layers.
"""

import sys
from datetime import timedelta

from PySide6.QtCore import Qt, QSettings, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
    QMdiArea, QMdiSubWindow, QStackedWidget, QSplitter, QMessageBox, QDialog, QLabel,
)

from src.ui.theme import THEMES, THEME_LABELS, DEFAULT_THEME, build_stylesheet
from src.ui.top_nav_bar import TopNavBar
from src.ui.left_panel import LeftPanel, SORT_TIME_ASC, SORT_TIME_DESC
from src.ui.log_window_widget import LogWindowWidget
from src.ui.event_detail_panel import EventDetailPanel
from src.ui.visualization_row import VisualizationRow
from src.ui.floating_log_window import FloatingLogWindow
from src.ui.locked_workspace import LockedWorkspace
from src.ui.color_map import SourceColorMap
from src.ui.timezone_import_dialog import TimezoneImportDialog
from src.ui.session_notes import SessionNotesWidget
from src.ui.toast_notification import ToastNotification
from src.models.data_classes import FilterConfig, RawLogEntry
from src.filter.log_filter import LogFilter, FilterValidationError
from src.parser.log_parser import LogParser
from src.normaliser.timezone_map import utc_offset_label, DEFAULT_TIMEZONE
from src.correlator.scroll_sync_manager import ScrollSyncManager

BACKGROUND_COLOR = "#0a0e1a"
MAX_WINDOWS = 8  # window cap


class MainWindow(QMainWindow):
    """Application shell."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AnaLog Labs")
        self.resize(1500, 950)

        self._settings = QSettings("PentalogTech", "AnaLogLabs")

        # Theme (Section: switchable color themes) — restored from last
        # session if present, otherwise the original palette by default.
        self._current_theme = self._settings.value("theme", DEFAULT_THEME)
        if self._current_theme not in THEMES:
            self._current_theme = DEFAULT_THEME
        self.setStyleSheet(build_stylesheet(THEMES[self._current_theme]))

        # -- shared state ------------------------------------------------------
        self.color_map = SourceColorMap(palette=THEMES[self._current_theme]["accent_palette"])
        self._scroll_sync = ScrollSyncManager()
        # True while the unified single-scrollbar lock is active.
        self._locked = False

        # Default display/convert-to timezone = Perth (the client's primary
        # zone; matches the "+8" converted times in the reference screenshot).
        # Overridden per-import once the investigator confirms a choice in
        # TimezoneImportDialog (see _on_import_logs).
        self._display_tz = DEFAULT_TIMEZONE

        self.log_panels: dict[str, LogWindowWidget] = {}
        self.log_subwindows: dict[str, QMdiSubWindow] = {}
        self.floating_windows: dict[str, FloatingLogWindow] = {}

        # source_label -> full entry list (post-normalisation), for the charts.
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}

        # Shared ±30s flag anchors (absolute UTC datetimes) — set MANUALLY by
        # the investigator only; the time-range filter never flags anything.
        self._flag_anchors: list = []

        # Active filter state.
        self._last_config: FilterConfig | None = None
        self._highlighted_count = 0
        self._malformed_count = 0

        self._build_ui()
        self._connect_signals()
        self._restore_layout()

    # -- UI construction ------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_nav = TopNavBar()
        self.top_nav.set_current_theme(self._current_theme)
        root.addWidget(self.top_nav)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self.left_panel = LeftPanel(timezone=self._display_tz)
        self.left_panel.tab_manager.set_theme(THEMES[self._current_theme])
        self.left_panel.timeframe_selector.set_theme(THEMES[self._current_theme])
        self.left_panel.session_notes.set_theme(THEMES[self._current_theme])
        self.left_panel.setMinimumWidth(170)
        self.main_splitter.addWidget(self.left_panel)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.setChildrenCollapsible(False)

        self.visualization_row = VisualizationRow()
        self.visualization_row.set_display_timezone(self._display_tz)
        self.visualization_row.set_theme(THEMES[self._current_theme])
        self.right_splitter.addWidget(self.visualization_row)

        # Log space: MDI workspace (or the locked view) + event detail.
        self.log_splitter = QSplitter(Qt.Vertical)
        self.log_splitter.setChildrenCollapsible(False)

        self.panels_area = QMdiArea()
        self.panels_area.setObjectName("PanelsArea")
        self.panels_area.setViewMode(QMdiArea.SubWindowView)
        self.panels_area.setOption(QMdiArea.DontMaximizeSubWindowOnActivation, True)
        pal = self.panels_area.palette()
        pal.setColor(QPalette.Window, QColor(BACKGROUND_COLOR))
        self.panels_area.setPalette(pal)
        self.panels_area.setBackground(QColor(BACKGROUND_COLOR))

        # Shown only while no log file is open — otherwise this whole area is
        # just an unexplained empty void, which is what prompted this.
        self._empty_workspace_label = QLabel(
            "No logs loaded yet\nImport a log file to see it here.", self.panels_area
        )
        self._empty_workspace_label.setAlignment(Qt.AlignCenter)
        self._empty_workspace_label.setWordWrap(True)
        self._empty_workspace_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.panels_area.installEventFilter(self)
        self._apply_workspace_theme(THEMES[self._current_theme])
        self._update_empty_workspace_geometry()
        self._update_workspace_empty_state()

        # A stacked widget swaps between the movable MDI workspace and the
        # unified single-scrollbar locked view (Sync Scroll on).
        self._locked_workspace = LockedWorkspace()
        self._locked_workspace.set_theme(THEMES[self._current_theme])
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self.panels_area)  # index 0
        self.workspace_stack.addWidget(self._locked_workspace)  # index 1
        self.log_splitter.addWidget(self.workspace_stack)

        self.event_detail_panel = EventDetailPanel()
        self.event_detail_panel.set_theme(THEMES[self._current_theme])
        self.event_detail_panel.set_display_timezone(self._display_tz)
        self.log_splitter.addWidget(self.event_detail_panel)

        # Set default proportions so the log area takes up most of the space
        self.log_splitter.setStretchFactor(0, 1)
        self.log_splitter.setStretchFactor(1, 0)
        self.log_splitter.setSizes([700, 200])

        self.right_splitter.addWidget(self.log_splitter)
        # # Log space: MDI workspace (or the locked view) + event detail.
        # log_area = QWidget()
        # log_layout = QVBoxLayout(log_area)
        # log_layout.setContentsMargins(0, 0, 0, 0)
        # log_layout.setSpacing(0)

        # self.panels_area = QMdiArea()
        # self.panels_area.setObjectName("PanelsArea")
        # self.panels_area.setViewMode(QMdiArea.SubWindowView)
        # self.panels_area.setOption(QMdiArea.DontMaximizeSubWindowOnActivation, True)
        # pal = self.panels_area.palette()
        # pal.setColor(QPalette.Window, QColor(BACKGROUND_COLOR))
        # self.panels_area.setPalette(pal)
        # self.panels_area.setBackground(QColor(BACKGROUND_COLOR))

        # # A stacked widget swaps between the movable MDI workspace and the
        # # unified single-scrollbar locked view (Sync Scroll on).
        # self._locked_workspace = LockedWorkspace()
        # self.workspace_stack = QStackedWidget()
        # self.workspace_stack.addWidget(self.panels_area)        # index 0
        # self.workspace_stack.addWidget(self._locked_workspace)  # index 1
        # log_layout.addWidget(self.workspace_stack, stretch=1)

        # self.event_detail_panel = EventDetailPanel()
        # self.event_detail_panel.set_display_timezone(self._display_tz)
        # log_layout.addWidget(self.event_detail_panel)

        # self.right_splitter.addWidget(log_area)

        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 2)
        self.right_splitter.setSizes([300, 600])

        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([210, 1290])

        root.addWidget(self.main_splitter, stretch=1)

        # Non-blocking action feedback (apply/clear filter, import results,
        # sync scroll, flags, session notes export, pop-out/redock/close,
        # timezone changes) — see toast_notification.py. Parented directly to
        # the QMainWindow (not the central widget) and raised on every show()
        # so it always floats above whatever panel/log window is underneath.
        self.toast = ToastNotification(self, theme=THEMES[self._current_theme])

    def _connect_signals(self) -> None:
        self.top_nav.import_logs_clicked.connect(self._on_import_logs)
        self.top_nav.display_timezone_changed.connect(self._on_display_tz_changed)
        self.top_nav.sync_scroll_toggled.connect(self._on_sync_scroll_toggled)
        self.top_nav.theme_changed.connect(self._on_theme_changed)
        self.top_nav.clear_flags_clicked.connect(self._on_clear_all_flags)

        self.left_panel.tab_manager.tab_selected.connect(self._on_tab_selected)
        self.visualization_row.element_clicked.connect(self._on_chart_navigate)
        self.visualization_row.flag_requested.connect(self._on_chart_flag_toggle)
        self.visualization_row.chart_popped_out.connect(self._on_chart_popped_out)
        self.visualization_row.chart_docked_back.connect(self._on_chart_docked_back)
        self.left_panel.sort_changed.connect(self._on_sort_changed)
        self.left_panel.timeframe_selector.filter_applied.connect(self._on_filter_applied)
        self.left_panel.timeframe_selector.filter_cleared.connect(self._on_filter_cleared)
        self.left_panel.session_notes.notes_exported.connect(self._on_notes_exported)

    # -- Layout persistence --------------------------------------------------------

    def _restore_layout(self) -> None:
        geo = self._settings.value("window_geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        for key, splitter in (("main_splitter", self.main_splitter),
                              ("right_splitter", self.right_splitter),
                              ):
            state = self._settings.value(key)
            if state is not None:
                splitter.restoreState(state)

    def closeEvent(self, event) -> None:
        self._settings.setValue("window_geometry", self.saveGeometry())
        self._settings.setValue("main_splitter", self.main_splitter.saveState())
        self._settings.setValue("right_splitter", self.right_splitter.saveState())
        self._settings.setValue("charts_splitter", self.visualization_row.charts_splitter.saveState())
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast.reposition()
        if hasattr(self, "_empty_workspace_label"):
            self._update_empty_workspace_geometry()

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "panels_area", None) and event.type() == QEvent.Resize:
            self._update_empty_workspace_geometry()
        return super().eventFilter(obj, event)

    def _update_empty_workspace_geometry(self) -> None:
        self._empty_workspace_label.setGeometry(self.panels_area.viewport().rect())

    def _update_workspace_empty_state(self) -> None:
        self._empty_workspace_label.setVisible(len(self.log_panels) == 0)

    def _apply_workspace_theme(self, theme: dict) -> None:
        """Re-colors the MDI workspace background and its empty-state message
        — this used a fixed BACKGROUND_COLOR constant entirely outside the
        theme system, which (like several other spots found this session)
        would have stayed dark regardless of theme otherwise.
        """
        bg = QColor(theme["bg_app"])
        pal = self.panels_area.palette()
        pal.setColor(QPalette.Window, bg)
        self.panels_area.setPalette(pal)
        self.panels_area.setBackground(bg)
        self._empty_workspace_label.setStyleSheet(
            f"color: {theme['text_secondary']}; font-size: 13px; background: transparent;"
        )

    # -- Import --------------------------------------------------------------------

    def _on_import_logs(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Import log files", "", "Log files (*.csv *.xlsx *.txt)"
        )
        if not file_paths:
            return

        # Ask which timezone the investigator wants to VIEW timestamps in for
        # this import. This was previously missing from the import flow
        # entirely — files were parsed straight away and the app silently
        # kept whatever display timezone happened to already be selected
        # (Perth, by default). The dialog itself doesn't change how raw
        # timestamps are PARSED (that rule — "Z" suffix = UTC, no "Z" =
        # Perth — is fixed in TimestampNormalizer and applies regardless of
        # this choice); it only sets how already-normalised UTC values are
        # rendered afterward.
        dialog = TimezoneImportDialog(file_paths, theme=THEMES[self._current_theme], parent=self)
        if dialog.exec() != QDialog.Accepted:
            return  # investigator cancelled; do not import

        chosen_tz = dialog.display_timezone

        results = LogParser.parse_files(file_paths)
        skipped_total = 0
        duplicates = []
        imported_count = 0
        failed_count = 0
        for result in results:
            if result.failed:
                print(f"File error: {result.file_error}")
                failed_count += 1
                continue

            # Prevent importing the same file twice (keyed on source label).
            if result.source_label in self.log_panels:
                duplicates.append(result.source_label)
                continue

            skipped_total += result.skipped_count
            if not result.valid_entries:
                print(f"No valid entries in {result.source_label}")
                continue
            if len(self.log_panels) >= MAX_WINDOWS:
                QMessageBox.information(
                    self, "Window limit reached",
                    f"AnaLog Labs shows up to {MAX_WINDOWS} log windows at once. "
                    f"'{result.source_label}' was not opened."
                )
                break

            # Column layout: ORIGINAL LOG TIME (raw) first, then the CONVERTED
            # TIMESTAMP, then every other field from the source.
            columns = ["original_log_time"] + list(result.valid_entries[0].fields.keys())
            color = self.color_map.color_for(result.source_label)
            panel = self.add_log_panel(result.source_label, color, columns)
            panel.load_rows(result.valid_entries)
            self._entries_by_source[result.source_label] = result.valid_entries
            imported_count += 1

        if duplicates:
            QMessageBox.information(
                self, "Already imported",
                "These files are already open and were skipped:\n  "
                + "\n  ".join(duplicates)
            )

        if skipped_total:
            self._malformed_count += skipped_total
            print(f"[ingestion] {skipped_total} row(s) skipped this import "
                  f"(unparseable/missing timestamp).")

        # Apply the investigator's chosen display timezone to everything —
        # existing panels, charts, event detail, AND the newly-added panels
        # above (add_log_panel() already reads self._display_tz for those,
        # so it must be set BEFORE _apply_sort()/_refresh_visualization()
        # run below, not just at the very end of this method).
        if chosen_tz != self._display_tz:
            self._on_display_tz_changed(chosen_tz)
        # Reflect the choice back on the "Convert to" dropdown so it never
        # silently disagrees with what was just confirmed in the dialog.
        self.top_nav.set_display_timezone(chosen_tz)

        # Newest-first (or the current sort) is applied to every panel.
        self._apply_sort()
        # DST-aware timezone badges (computed from each panel's own data date)
        # — panels now have rows loaded, so the offset is accurate.
        for panel in self.log_panels.values():
            panel.set_timezone_label(self._badge_label_for_panel(self._display_tz, panel))
        self._apply_flag_anchors()
        self._refresh_visualization()
        if self._last_config is not None:
            self._apply_filter_highlighting(self._last_config)
            for panel in self.log_panels.values():
                panel.scroll_to_time(self._last_config.start_time)
        self._recompute_stats()

        # Summary toast — placed last so it's the final (and therefore
        # visible, single-slot) feedback for this action, overriding any
        # earlier "Timezone changed" toast fired above in this same import.
        if imported_count:
            noun = "file" if imported_count == 1 else "files"
            self.toast.show_toast("Logs imported", f"{imported_count} {noun} added", kind="success",
                                  anchor=self.top_nav.import_button)
        elif failed_count and not duplicates:
            self.toast.show_toast("Import failed", "No valid log files found", kind="warning",
                                  anchor=self.top_nav.import_button)
        elif duplicates and not failed_count:
            self.toast.show_toast("Already imported", "No new files were added", kind="neutral",
                                  anchor=self.top_nav.import_button)

    def add_log_panel(self, source_label: str, color_hex: str, columns: list[str]) -> LogWindowWidget:
        panel = LogWindowWidget(source_label=source_label, color_hex=color_hex, columns=columns)
        panel.row_selected.connect(self._on_row_selected)
        panel.panel_closed.connect(self._on_panel_closed)
        panel.restore_size_requested.connect(self._on_restore_size_requested)
        panel.detach_requested.connect(self._on_detach_requested)
        panel.flag_toggle_requested.connect(self._on_flag_toggle)
        # Feature 3 — a scroll on any panel drives ScrollSyncManager (only acts
        # while Sync Scroll is on).
        panel.scrolled.connect(self._on_panel_scrolled)

        panel.set_display_timezone(self._display_tz)
        panel.set_timezone_label(utc_offset_label(self._display_tz))
        panel.set_flag_anchors(self._flag_anchors)
        panel.set_theme(THEMES[self._current_theme])

        self.log_panels[source_label] = panel
        self.left_panel.tab_manager.add_tab(source_label, color_hex)
        self._update_workspace_empty_state()

        if self._locked:
            self._rebuild_locked_workspace()
        else:
            self._mount_in_mdi(panel, source_label)
            self._auto_tile()
        return panel

    def _mount_in_mdi(self, panel: LogWindowWidget, source_label: str) -> QMdiSubWindow:
        sub = QMdiSubWindow()
        sub.setWidget(panel)
        sub.setWindowTitle(source_label)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        self.panels_area.addSubWindow(sub)
        sub.resize(480, 380)
        sub.show()
        self.log_subwindows[source_label] = sub
        return sub

    def _auto_tile(self) -> None:
        any_max = any(sw.windowState() & Qt.WindowMaximized for sw in self.log_subwindows.values())
        if not any_max:
            self.panels_area.tileSubWindows()

    # -- Timezone (single "convert to" dropdown) ----------------------------------

    def _on_display_tz_changed(self, iana_tz: str) -> None:
        """Change only how times are RENDERED (the CONVERTED TIMESTAMP column,
        charts, event detail, and the time-range interpretation)."""
        self._display_tz = iana_tz
        self.left_panel.timeframe_selector.set_timezone(iana_tz)
        self.visualization_row.set_display_timezone(iana_tz)
        self.event_detail_panel.set_display_timezone(iana_tz)
        for panel in self.log_panels.values():
            # DST-aware badge computed from each panel's own data date.
            panel.set_timezone_label(self._badge_label_for_panel(iana_tz, panel))
            panel.set_display_timezone(iana_tz)
        # The investigation window is an ABSOLUTE (UTC) window, so switching the
        # display timezone only changes how times are shown — the same events
        # stay highlighted. Nothing to re-filter here.
        self.toast.show_toast("Timezone changed", f"Now displaying times in {iana_tz}", kind="info",
                              anchor=self.top_nav.display_tz_dropdown)

    def _on_theme_changed(self, theme_key: str) -> None:
        """Switches the active color theme (Section: switchable themes).
        Re-applies the app-wide QSS, pushes the new colors into the three
        charts (QPainter/pyqtgraph don't pick up QSS changes on their own),
        remaps the source-color palette so existing sources keep their slot
        but get the new theme's hue, recolors already-open log panel headers
        to match, and persists the choice for next launch.
        """
        if theme_key not in THEMES:
            return
        self._current_theme = theme_key
        theme = THEMES[theme_key]

        self.setStyleSheet(build_stylesheet(theme))
        self.visualization_row.set_theme(theme)
        self.event_detail_panel.set_theme(theme)
        self.left_panel.tab_manager.set_theme(theme)
        self.left_panel.timeframe_selector.set_theme(theme)
        self._locked_workspace.set_theme(theme)
        self.left_panel.session_notes.set_theme(theme)
        self._apply_workspace_theme(theme)
        self.toast.set_theme(theme)
        # Floating log windows are genuine top-level OS windows, not children
        # of MainWindow, so they never inherited setStyleSheet() above —
        # each currently-open one needs its own explicit update.
        for floating in self.floating_windows.values():
            floating.set_theme(theme)

        self.color_map.set_palette(theme["accent_palette"])
        for source_label, panel in self.log_panels.items():
            panel.set_color(self.color_map.color_for(source_label))
            panel.set_theme(theme)
        self._refresh_visualization()
        self._apply_flag_anchors()  # flag glow color is theme-dependent too

        self._settings.setValue("theme", theme_key)
        self.toast.show_toast("Theme changed", THEME_LABELS.get(theme_key, theme_key), kind="info",
                              anchor=self.top_nav.theme_dropdown)

    def _badge_label_for_panel(self, iana_tz: str, panel: LogWindowWidget) -> str:
        """Feature 2 — the "UTC+X" badge for one panel, computed against that
        panel's OWN earliest entry rather than "now", so DST-observing zones
        (Sydney/Melbourne/Adelaide) show the offset that actually applied to
        that log's dates. Falls back to "now" if the panel has no entries yet.
        """
        reference_dt = None
        for entry in panel.table_model.get_entries():
            if entry.normalized_timestamp is not None:
                reference_dt = entry.normalized_timestamp.utc_datetime
                break
        return utc_offset_label(iana_tz, reference_dt)

    # -- Sort ----------------------------------------------------------------------

    def _on_sort_changed(self, _code: str) -> None:
        self._apply_sort()
        if self._last_config is not None:
            self._apply_filter_highlighting(self._last_config)
        self._apply_flag_anchors()

    def _apply_sort(self) -> None:
        code = self.left_panel.current_sort()
        if code in (SORT_TIME_ASC, SORT_TIME_DESC):
            descending = code == SORT_TIME_DESC
            for panel in self.log_panels.values():
                panel.table_model.sort_by_time(descending=descending)

    # -- Filter / time range -------------------------------------------------------

    def _on_filter_applied(self, config: FilterConfig) -> None:
        self._last_config = config
        self._apply_filter_highlighting(config)
        # Jump every open window to the start of the range.
        for panel in self.log_panels.values():
            panel.scroll_to_time(config.start_time)
        self.toast.show_toast(
            "Filter applied",
            f"{self._highlighted_count:,} row{'s' if self._highlighted_count != 1 else ''} matched",
            kind="success",
            anchor=self.left_panel.timeframe_selector.apply_button,
        )

    def _apply_filter_highlighting(self, config: FilterConfig) -> None:
        """Highlight (ONLY highlight — never flag) rows whose converted time
        falls in the investigation window."""
        all_entries = {s: p.table_model.get_entries() for s, p in self.log_panels.items()}
        try:
            matched = LogFilter.apply_filter(config, all_entries)
        except FilterValidationError:
            return

        # Map matched entries to their CURRENT positions in each panel's model
        # (entries are displayed in sorted order, so entry.row_index — the
        # original file position — cannot be used as a display index; that was
        # the bug where "9:30–10:30" highlighted unrelated rows like 11:24).
        for source_label, panel in self.log_panels.items():
            entries = all_entries[source_label]
            matched_ids = {id(e) for e in matched.get(source_label, [])}
            positions = [i for i, e in enumerate(entries) if id(e) in matched_ids]
            panel.highlight_matched(positions)

        active, inactive = LogFilter.get_active_inactive_sources(matched)
        self.left_panel.tab_manager.highlight_active_tabs(active, inactive)

        self._highlighted_count = sum(len(v) for v in matched.values())
        self.visualization_row.set_investigation_range(config.start_time, config.end_time)
        self._recompute_stats()

    def _on_filter_cleared(self) -> None:
        for panel in self.log_panels.values():
            panel.highlight_matched([])
        self.left_panel.tab_manager.highlight_active_tabs([], list(self.log_panels.keys()))
        self._last_config = None
        self._highlighted_count = 0
        self.visualization_row.set_investigation_range(None, None)
        self._recompute_stats()
        self.toast.show_toast("Filter cleared", "Showing the full imported range again", kind="neutral",
                              anchor=self.left_panel.timeframe_selector.clear_button)

    def _on_notes_exported(self, filepath: str) -> None:
        import os
        self.toast.show_toast("Session notes exported", os.path.basename(filepath), kind="success",
                              anchor=self.left_panel.session_notes.export_btn)

    # -- Flags (manual only) -------------------------------------------------------

    def _on_flag_toggle(self, entry: RawLogEntry) -> None:
        nts = entry.normalized_timestamp
        if nts is None:
            return
        t = nts.utc_datetime + timedelta(milliseconds=nts.milliseconds)
        for i, anchor in enumerate(self._flag_anchors):
            if abs((t - anchor).total_seconds()) <= 30:
                del self._flag_anchors[i]
                was_added = False
                break
        else:
            self._flag_anchors.append(t)
            was_added = True
        self._apply_flag_anchors()
        self._recompute_stats()
        flag_anchor_widget = self.sender()  # the LogWindowWidget whose row was flagged
        if was_added:
            self.toast.show_toast("Flag added", entry.source_label, kind="success", anchor=flag_anchor_widget)
        else:
            self.toast.show_toast("Flag removed", entry.source_label, kind="neutral", anchor=flag_anchor_widget)

    def _on_chart_flag_toggle(self, source_label: str, utc_dt) -> None:
        """Same anchor-toggle logic as _on_flag_toggle, driven from a chart's
        right-click 'Flag this event' action instead of a log-row checkbox.

        Charts only resolve to an aggregated bucket's representative
        (source_label, utc_dt) — heatmap/spike buckets can span many log
        rows, and even a single bubble represents one (entity, bucket) pair,
        not necessarily one RawLogEntry — so this works directly off that
        pair rather than requiring an actual entry object like
        _on_flag_toggle does.
        """
        for i, anchor in enumerate(self._flag_anchors):
            if abs((utc_dt - anchor).total_seconds()) <= 30:
                del self._flag_anchors[i]
                was_added = False
                break
        else:
            self._flag_anchors.append(utc_dt)
            was_added = True
        self._apply_flag_anchors()
        self._recompute_stats()
        if was_added:
            self.toast.show_toast("Flag added", source_label, kind="success", anchor=self.visualization_row)
        else:
            self.toast.show_toast("Flag removed", source_label, kind="neutral", anchor=self.visualization_row)

    def _apply_flag_anchors(self) -> None:
        for panel in self.log_panels.values():
            panel.set_flag_anchors(self._flag_anchors)
        self.visualization_row.set_flag_anchors(self._flag_anchors)

    def _on_clear_all_flags(self) -> None:
        """Removes every flag in the session at once — same underlying state
        (_flag_anchors) and same apply/recompute path as toggling a single
        flag, just emptying the list instead of adding/removing one entry.
        """
        if not self._flag_anchors:
            self.toast.show_toast("No flags to clear", kind="neutral", anchor=self.top_nav.clear_flags_button)
            return
        count = len(self._flag_anchors)
        self._flag_anchors = []
        self._apply_flag_anchors()
        self._recompute_stats()
        noun = "flag" if count == 1 else "flags"
        self.toast.show_toast("Flags cleared", f"{count} {noun} removed", kind="success",
                              anchor=self.top_nav.clear_flags_button)

    # -- Sync scroll → unified time-based lock ------------------------------------

    def _on_sync_scroll_toggled(self, enabled: bool) -> None:
        """CASE 1 (no valid time range) → prompt, do not enable.
        CASE 2 (valid range) → enter the unified single-scrollbar lock.
        """
        if enabled:
            if self._last_config is None:
                QMessageBox.information(
                    self, "Sync Scroll",
                    "Please select a valid time range before enabling Sync Scroll."
                )
                self.top_nav.force_sync_off()
                return
            self._enter_lock_mode()
            self.toast.show_toast("Sync scroll on", "Every open window now scrolls together", kind="success",
                                  anchor=self.top_nav.sync_scroll_button)
        else:
            if self._locked:
                self._exit_lock_mode()
                self.toast.show_toast("Sync scroll off", kind="neutral", anchor=self.top_nav.sync_scroll_button)

    def _enter_lock_mode(self) -> None:
        self._locked = True
        # Any popped-out windows rejoin so ALL panels lock together.
        for source_label in list(self.floating_windows.keys()):
            self._on_redock_requested(source_label)
        # Pull every panel out of its MDI sub-window; the locked view reparents
        # them side-by-side ("straight line") and they can no longer be dragged
        # until sync scroll is turned off.
        for source_label, sub in list(self.log_subwindows.items()):
            panel = self.log_panels[source_label]
            panel.setParent(None)
            self.panels_area.removeSubWindow(sub)
            sub.deleteLater()
        self.log_subwindows.clear()

        self._locked_workspace.set_panels(self.log_panels)
        self.workspace_stack.setCurrentWidget(self._locked_workspace)
        self._register_all_for_sync()

    def _exit_lock_mode(self) -> None:
        self._locked = False
        self._scroll_sync.clear()
        panels = self._locked_workspace.release_panels()
        self.workspace_stack.setCurrentWidget(self.panels_area)
        for source_label, panel in panels.items():
            self._mount_in_mdi(panel, source_label)
        self._auto_tile()

    def _rebuild_locked_workspace(self) -> None:
        self._locked_workspace.release_panels()
        self._locked_workspace.set_panels(self.log_panels)
        self._register_all_for_sync()

    def _register_all_for_sync(self) -> None:
        """Register every open panel with ScrollSyncManager and snap them all
        to the highlighted range START. Deferred one event-loop tick so the
        just-reparented panels have a laid-out viewport before scrollTo runs.
        """
        self._scroll_sync.clear()
        for source_label, panel in self.log_panels.items():
            self._scroll_sync.register_window(source_label, panel)
        if self._last_config is not None:
            start = self._last_config.start_time
            QTimer.singleShot(0, lambda: self._scroll_sync.move_all_to_timestamp(start))

    def _on_panel_scrolled(self, source_label: str, center_row: int) -> None:
        """A panel was scrolled — while locked, drive the others to the same
        timestamp via ScrollSyncManager (Feature 3). No-op when not locked.
        """
        if not self._locked:
            return
        panel = self.log_panels.get(source_label)
        if panel is not None:
            self._scroll_sync.sync_scroll(panel, center_row)

    # -- Row / tab interaction -----------------------------------------------------

    def _on_row_selected(self, entry: RawLogEntry) -> None:
        self.event_detail_panel.show_event(entry, correlation_count=0)

    def _on_chart_navigate(self, source_label: str, utc_dt) -> None:
        """Chart click-to-navigate (Section 5.1/5.2 UI interaction) — a click
        on a heatmap cell, spike-chart segment, or bubble jumps the matching
        log window to the nearest entry at utc_dt, selects it (which also
        populates the Event Detail panel via the usual row_selected path),
        and — if Sync Scroll has windows registered — carries every other
        open window along to the same timestamp too.
        """
        panel = self.log_panels.get(source_label)
        if panel is not None:
            panel.select_and_scroll_to_time(utc_dt)
        elif source_label in self.floating_windows:
            fw = self.floating_windows[source_label]
            inner = getattr(fw, "panel", None) or getattr(fw, "chart_widget", None)
            if inner is not None and hasattr(inner, "select_and_scroll_to_time"):
                inner.select_and_scroll_to_time(utc_dt)

        if self._scroll_sync.registered_windows:
            self._scroll_sync.move_all_to_timestamp(utc_dt)

    def _on_chart_popped_out(self, chart_title: str) -> None:
        """Mirrors _on_detach_requested's toast for log windows — charts
        previously popped out silently, the one action in that family that
        didn't confirm itself.
        """
        self.toast.show_toast("Chart popped out", chart_title, kind="info")

    def _on_chart_docked_back(self, chart_title: str) -> None:
        """Mirrors _on_redock_requested's toast for log windows."""
        self.toast.show_toast("Chart docked back", chart_title, kind="info")

    def _on_tab_selected(self, source_label: str) -> None:
        """The file list is display-only: a click does NOT leave a persistent
        highlight (that stuck-highlight was a reported annoyance). It simply
        scrolls all windows to that file's first event as a convenience.
        """
        panel = self.log_panels.get(source_label)
        if panel is None:
            return
        t = panel.first_entry_time()
        if t is None:
            return
        for other in self.log_panels.values():
            other.scroll_to_time(t)

    # -- Panel lifecycle -----------------------------------------------------------

    def _on_panel_closed(self, source_label: str) -> None:
        self.log_panels.pop(source_label, None)
        self.log_subwindows.pop(source_label, None)
        self.floating_windows.pop(source_label, None)
        self._entries_by_source.pop(source_label, None)
        self.color_map.remove(source_label)
        self.left_panel.tab_manager.remove_tab(source_label)
        self._scroll_sync.unregister_window(source_label)
        self._update_workspace_empty_state()

        if f"· {source_label}" in self.event_detail_panel.header_label.text():
            self.event_detail_panel.clear()

        self._refresh_visualization()
        self._recompute_stats()
        # No anchor: whatever triggered this (the panel's close button) no
        # longer exists by this point, so this one intentionally falls back
        # to the corner rather than anchoring to something already gone.
        self.toast.show_toast("Log window closed", source_label, kind="neutral")

    def _on_restore_size_requested(self, source_label: str) -> None:
        sub = self.log_subwindows.get(source_label)
        if sub is None:
            return
        sub.showNormal()
        sub.resize(480, 380)
        self.toast.show_toast("Window restored", source_label, kind="info", anchor=self.sender())

    # -- Pop-out / dock-back -------------------------------------------------------

    def _on_detach_requested(self, source_label: str) -> None:
        # Pop-out and the unified lock are mutually exclusive — leave lock first.
        if self._locked:
            self.top_nav.force_sync_off()
            self._exit_lock_mode()

        panel = self.log_panels.get(source_label)
        if panel is None or source_label in self.floating_windows:
            return
        sub = self.log_subwindows.pop(source_label, None)
        panel.setParent(None)
        if sub is not None:
            self.panels_area.removeSubWindow(sub)
            sub.deleteLater()

        floating = FloatingLogWindow(panel, source_label, theme=THEMES[self._current_theme], parent=None)
        floating.redock_requested.connect(self._on_redock_requested)
        floating.closed.connect(self._on_floating_closed)
        self.floating_windows[source_label] = floating
        floating.show()
        self.toast.show_toast("Popped out", source_label, kind="info", anchor=self.sender())

    def _on_redock_requested(self, source_label: str) -> None:
        floating = self.floating_windows.pop(source_label, None)
        if floating is None:
            return
        panel = floating.panel
        floating.prepare_redock()
        panel.setParent(None)
        floating.close()
        self._mount_in_mdi(panel, source_label)
        self._auto_tile()
        self.toast.show_toast("Docked back", source_label, kind="info", anchor=panel)

    def _on_floating_closed(self, source_label: str) -> None:
        self._on_panel_closed(source_label)

    # -- Charts + stats ------------------------------------------------------------

    def _refresh_visualization(self) -> None:
        if self._entries_by_source:
            self.visualization_row.set_entries(self._entries_by_source, self.color_map.as_dict())
        else:
            self.visualization_row.clear()

    def _recompute_stats(self) -> None:
        total = sum(p.table_model.rowCount() for p in self.log_panels.values())
        flagged = sum(p.table_model.flagged_count() for p in self.log_panels.values())
        self.top_nav.set_stats(total, self._highlighted_count, flagged)
        if self._malformed_count:
            self.top_nav.total_label.setToolTip(
                f"{self._malformed_count} row(s) failed to parse and were skipped."
            )


def main() -> None:
    app = QApplication(sys.argv)
    # Without an explicit icon, Qt falls back to its own default logo on
    # every top-level window this app creates (MainWindow AND each
    # popped-out FloatingChartWindow, since those are standalone windows
    # too) — most visible on Windows' title bar. Setting a blank one here,
    # at the QApplication level, clears it everywhere in one place rather
    # than needing it set on each window individually.
    app.setWindowIcon(QIcon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
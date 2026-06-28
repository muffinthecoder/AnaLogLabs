"""
InvestigationDashboard — right panel summarising loaded logs, activity, and
correlations (Section 5.2, Presentation Layer / Section 6.3.4 Zone 5).

Per the design doc's class diagram (Section 4.6):
    summary: dict        {source_label: event_count}
    filter_ref: LogFilter (cannot be None)

Four subsections (Section 6.3.4 Zone 5):
    1. Activity Frequency Chart (PyQtGraph bar chart)
    2. Timeline (multi-row horizontal timeline)
    3. Session Statistics (2x2 metric card grid)
    4. Correlated Events List (scrollable)

Owned by: Fatima
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QGridLayout
)

# TODO (Fatima — Section 5.5 Additional Software Components):
#   The activity frequency chart should be implemented using PyQtGraph's
#   BarGraphItem / PlotWidget per the design doc, not a placeholder QLabel.
#   from pyqtgraph import PlotWidget, BarGraphItem

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QGridLayout
)

from src.models.data_classes import RawLogEntry
from src.visualiser.activity_frequency_chart import ActivityFrequencyChart
from src.visualiser.timeline_widget import TimelineWidget


class StatCard(QFrame):
    """One metric card in the Session Statistics 2x2 grid."""

    def __init__(self, label: str, value: str, value_color: str = "#c0cce8", parent=None):
        super().__init__(parent)
        self.setProperty("class", "StatCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(2)

        label_widget = QLabel(label)
        label_widget.setStyleSheet("font-size: 9px; color: #4a5a7a;")
        layout.addWidget(label_widget)

        self.value_label = QLabel(value)
        self.value_label.setProperty("class", "StatValue")
        self.value_label.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {value_color};")
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class CorrelatedEventItem(QFrame):
    """One entry in the scrollable Correlated Events List."""

    clicked = Signal(str)  # timestamp string, used to sync all panels

    def __init__(self, description: str, timestamp: str, severity: str, parent=None):
        super().__init__(parent)
        self.timestamp = timestamp
        icon_color = "#e06060" if severity == "attribute" else "#ffd60a"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        icon = QLabel("\u2022")  # link indicator placeholder
        icon.setStyleSheet(f"color: {icon_color}; font-size: 12px;")
        layout.addWidget(icon)

        text = QLabel(description)
        text.setWordWrap(True)
        text.setStyleSheet("font-size: 10px; color: #8090b0;")
        layout.addWidget(text, stretch=1)

        time_label = QLabel(timestamp)
        time_label.setStyleSheet("font-size: 9px; color: #4a5a7a;")
        layout.addWidget(time_label)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.timestamp)
        super().mousePressEvent(event)


class InvestigationDashboard(QWidget):
    """Section 6.3.4 Zone 5 — right investigation dashboard."""

    # Emitted when a correlated event item is clicked — MainWindow connects
    # this to scroll all open LogWindowWidgets to the relevant timestamp.
    correlated_event_clicked = Signal(str)  # timestamp string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RightDashboard")
        self.setFixedWidth(220)

        # source_label -> list[RawLogEntry] (the FULL set, not just matched
        # entries) — kept here so refresh() can re-dim the activity chart
        # against the investigation window without needing MainWindow to
        # pass the complete entry set on every single filter application.
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}

        # source_label -> "#rrggbb", kept in sync via load_entries() so
        # both PyQtGraph widgets always draw each source in the same color
        # as its LogTab dot and LogWindowWidget header dot.
        self._colors: dict[str, str] = {}

        self._display_tz = "Asia/Dubai"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)

        layout.addWidget(self._build_activity_chart_section())
        layout.addWidget(self._build_timeline_section())
        layout.addWidget(self._build_stats_section())
        layout.addWidget(self._build_correlated_events_section())
        layout.addStretch()

    # -- Subsection builders ---------------------------------------------------

    def _build_activity_chart_section(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("ACTIVITY FREQUENCY")
        title.setProperty("class", "SectionTitle")
        v.addWidget(title)

        self.activity_chart = ActivityFrequencyChart()
        v.addWidget(self.activity_chart)
        return container

    def _build_timeline_section(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("TIMELINE")
        title.setProperty("class", "SectionTitle")
        v.addWidget(title)

        self.timeline_widget = TimelineWidget()
        # Clicking any point on the timeline behaves like clicking a
        # CorrelatedEventItem — both funnel through correlated_event_clicked
        # so MainWindow only needs the one existing connection (see
        # MainWindow._connect_signals -> _on_correlated_event_clicked).
        self.timeline_widget.point_clicked.connect(self.correlated_event_clicked.emit)
        v.addWidget(self.timeline_widget)
        return container

    def _build_stats_section(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("SESSION STATS")
        title.setProperty("class", "SectionTitle")
        v.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(6)

        self.total_events_card = StatCard("Total events", "0", value_color="#00c4e8")
        self.matched_card = StatCard("Matched", "0", value_color="#ffd60a")
        self.failures_card = StatCard("Failures", "0", value_color="#e06060")
        self.correlated_card = StatCard("Correlated", "0", value_color="#57cc99")

        grid.addWidget(self.total_events_card, 0, 0)
        grid.addWidget(self.matched_card, 0, 1)
        grid.addWidget(self.failures_card, 1, 0)
        grid.addWidget(self.correlated_card, 1, 1)

        v.addLayout(grid)
        return container

    def _build_correlated_events_section(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("CORRELATED EVENTS")
        title.setProperty("class", "SectionTitle")
        v.addWidget(title)

        self.correlated_list_container = QVBoxLayout()
        self.correlated_list_container.setSpacing(4)
        v.addLayout(self.correlated_list_container)
        return container

    # -- Public API ----------------------------------------------------------------

    def load_entries(self, source_label: str, entries: list[RawLogEntry], color_hex: str) -> None:
        """Registers (or replaces) one source's full entry list and color.

        Called by MainWindow.add_log_panel() right after LogWindowWidget
        is created — separate from refresh() because refresh() only ever
        receives LogFilter's MATCHED entries (Section 4.7.2 step 7's
        `summary` dict doesn't carry timestamps at all), while the activity
        chart and timeline both need the FULL entry set so they can show
        what's outside the investigation window too, not just what's
        inside it.
        """
        self._entries_by_source[source_label] = entries
        self._colors[source_label] = color_hex
        self.activity_chart.set_entries(self._entries_by_source, self._colors)
        self.timeline_widget.set_entries(self._entries_by_source, self._colors)

    def remove_source(self, source_label: str) -> None:
        """Called by MainWindow._on_panel_closed() so a closed log panel's
        data drops out of both PyQtGraph widgets immediately, rather than
        leaving a stale row/bar series for a source that no longer exists.
        """
        self._entries_by_source.pop(source_label, None)
        self._colors.pop(source_label, None)

        if not self._entries_by_source:
            self.activity_chart.clear_chart()
            self.timeline_widget.clear_timeline()
        else:
            self.activity_chart.set_entries(self._entries_by_source, self._colors)
            self.timeline_widget.set_entries(self._entries_by_source, self._colors)

    def set_display_timezone(self, tz_name: str) -> None:
        """Called by MainWindow._on_timezone_changed() — keeps the
        timeline's x-axis labels in the same timezone as every other
        display element (LogWindowWidget's badge, EventDetailPanel, etc).
        The activity chart's axis is unaffected since its three labeled
        ticks (start/mid/end) are formatted from the same datetime objects
        regardless of display_tz — only the timeline's continuous
        DateAxisItem needs the offset.
        """
        self._display_tz = tz_name
        self.timeline_widget.set_display_timezone(tz_name)

    def refresh(self, summary: dict, active_sources: list[str], inactive_sources: list[str]) -> None:
        """Section 4.7.2 step 7 — InvestigationDashboard.refresh().

        Note: `summary` (source_label -> matched_count) and
        active_sources/inactive_sources aren't actually needed by either
        PyQtGraph widget directly — they already recompute matched-vs-not
        themselves from the investigation window bounds, since "matched"
        here means "falls within the window" and both widgets need that
        per-bucket/per-point, not just a per-source total. The parameters
        are kept (rather than dropped) so this still satisfies the
        Section 4.7.2 step 7 call signature MainWindow._on_filter_applied
        already invokes.

        TODO (Pooja/Fatima — TimeFrameSelector):
            This currently has no access to the active FilterConfig's
            start_time/end_time directly — MainWindow holds that, not
            InvestigationDashboard. Until FilterConfig (or just its two
            datetimes) is passed through here, call
            set_investigation_window() directly from
            MainWindow._on_filter_applied / _on_filter_cleared instead of
            relying on refresh() to do it. See the two new calls added in
            MainWindow for the current wiring.
        """
        pass

    def set_investigation_window(self, start, end) -> None:
        """Updates which bars render dimmed vs full-opacity on the activity
        chart. start/end should be the same UTC-aware datetimes (or both
        None, to clear) that LogFilter.apply_filter() received — see the
        TODO on refresh() for why MainWindow calls this directly rather
        than through refresh()'s summary dict.
        """
        self.activity_chart.set_investigation_window(start, end)

    def set_session_stats(self, total: int, matched: int, failures: int, correlated: int) -> None:
        self.total_events_card.set_value(f"{total:,}")
        self.matched_card.set_value(str(matched))
        self.failures_card.set_value(str(failures))
        self.correlated_card.set_value(str(correlated))

    def set_correlated_events(self, events: list[dict]) -> None:
        """events: list of {"description": str, "time": str, "severity": str}"""
        # Clear existing items
        while self.correlated_list_container.count():
            item = self.correlated_list_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for event in events:
            item = CorrelatedEventItem(
                description=event["description"],
                timestamp=event["time"],
                severity=event.get("severity", "timestamp"),
            )
            item.clicked.connect(self.correlated_event_clicked.emit)
            self.correlated_list_container.addWidget(item)

        # Event-linking visualization concept — same correlated_events list
        # drives both the scrollable list above AND the connecting lines
        # drawn across timeline rows, so the two views always agree with
        # each other rather than needing separate update calls from
        # MainWindow.
        self.timeline_widget.set_links(events, display_tz=self._display_tz)
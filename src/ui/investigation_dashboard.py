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
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QGridLayout
)

# TODO (Fatima — Section 5.5 Additional Software Components):
#   The activity frequency chart should be implemented using PyQtGraph's
#   BarGraphItem / PlotWidget per the design doc, not a placeholder QLabel.
#   from pyqtgraph import PlotWidget, BarGraphItem


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

        # TODO (Fatima — Section 6.3.4 Zone 5 subsection 1):
        #   Replace this placeholder with a PyQtGraph BarGraphItem bound to
        #   InvestigationDashboard.summary. Bars within the investigation
        #   window render at full opacity in source color; bars outside are
        #   dimmed. X-axis shows start, midpoint, end of investigation window.
        self.activity_chart_placeholder = QLabel("[ PyQtGraph bar chart placeholder ]")
        self.activity_chart_placeholder.setStyleSheet(
            "color: #4a5a7a; font-size: 10px; background-color: #1a2035; "
            "border-radius: 4px; padding: 18px 0; qproperty-alignment: AlignCenter;"
        )
        v.addWidget(self.activity_chart_placeholder)
        return container

    def _build_timeline_section(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("TIMELINE")
        title.setProperty("class", "SectionTitle")
        v.addWidget(title)

        # TODO (Fatima — Section 6.3.4 Zone 5 subsection 2):
        #   Replace with a PyQtGraph multi-row horizontal timeline. One row
        #   per log source, each event a small colored block at its
        #   timestamp position. self.timeline_rows keyed by source_label so
        #   rows can be added/removed as logs are imported/closed.
        self.timeline_placeholder = QLabel("[ Multi-row timeline placeholder ]")
        self.timeline_placeholder.setStyleSheet(
            "color: #4a5a7a; font-size: 10px; background-color: #1a2035; "
            "border-radius: 4px; padding: 18px 0; qproperty-alignment: AlignCenter;"
        )
        v.addWidget(self.timeline_placeholder)
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

    def refresh(self, summary: dict, active_sources: list[str], inactive_sources: list[str]) -> None:
        """Section 4.7.2 step 7 — InvestigationDashboard.refresh().

        TODO (Fatima):
            Wire summary dict into the activity chart and timeline once
            PyQtGraph components replace the placeholders above.
        """
        pass

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

"""
visualization_row.py — the top ~1/3 visualization area (Sections 1 & 5).

Composition:
    ┌───────────────────────┬──────────────────────┬──────────────────────┐
    │  Heatmap (full range) │  Spike chart (range) │ Bubble Chart (range) │  ← resizable H-splitter
    ├───────────────────────┴──────────────────────┴──────────────────────┤
    │  Shared legend: file → colour swatch                                │
    └─────────────────────────────────────────────────────────────────────┘
"""

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QFrame, QStackedWidget,
                               QPushButton, QFileDialog)

from PySide6.QtCore import QTimer  # <-- Add this import
from src.visualiser.activity_heatmap import ActivityHeatmap
from src.visualiser.spike_chart import SpikeChart
from src.visualiser.bubble_chart import BubbleChart

from PySide6.QtWidgets import QFileDialog
from PySide6.QtGui import QPixmap, QPainter


def _export_widget(widget: QWidget, title: str):
    """Takes a snapshot of the widget after ensuring it has painted."""
    filename, _ = QFileDialog.getSaveFileName(widget, "Export Visualization", f"{title.replace(' ', '_')}.png",
                                              "PNG Files (*.png)")
    if filename:
        # Force a synchronous repaint before capturing
        widget.repaint()

        pixmap = QPixmap(widget.size())
        widget.render(pixmap)
        pixmap.save(filename)


class FloatingChartWindow(QWidget):
    """A resizable floating window that temporarily holds a popped-out chart."""

    def __init__(self, chart_widget: QWidget, stack: QStackedWidget, title: str = "Detached Chart", parent=None):
        super().__init__(parent)
        self.chart_widget = chart_widget
        self.stack = stack

        self.setWindowTitle(title)
        self.resize(1000, 600)  # Open nice and large for the ISOO
        # Header for the floating window
        layout = QVBoxLayout(self)
        header_layout = QHBoxLayout()

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-weight: bold; color: #2e8fff;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        # The Export Button is now here, clearly visible
        btn = QPushButton("Export")
        btn.setFixedSize(80, 24)
        btn.setStyleSheet("background-color: #101a30; color: #c8d3ea; border: 1px solid #2e8fff; border-radius: 6px;")
        btn.clicked.connect(lambda: _export_widget(self.chart_widget, title))
        header_layout.addWidget(btn)

        layout.addLayout(header_layout)
        layout.addWidget(self.chart_widget)

        self.chart_widget.show()
        self.stack.setCurrentIndex(1)

    def closeEvent(self, event) -> None:
        """When the investigator closes the floating window, snap the chart back."""
        self.stack.insertWidget(0, self.chart_widget)
        self.stack.setCurrentIndex(0)
        super().closeEvent(event)


class _LegendChip(QWidget):
    """One clickable file -> colour swatch entry (Section 5.3). Click toggles
    that source's visibility across all three charts.
    """

    toggled = Signal(str)  # source_label

    def __init__(self, source_label: str, color: str, parent=None):
        super().__init__(parent)
        self.source_label = source_label
        self._color = color
        self._active = True
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to hide/show this source in all three charts")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)

        self.swatch = QFrame()
        self.swatch.setFixedSize(10, 10)
        row.addWidget(self.swatch)

        self.name = QLabel(source_label)
        row.addWidget(self.name)

        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            self.swatch.setStyleSheet(f"background-color: {self._color}; border-radius: 3px;")
            self.name.setStyleSheet("font-size: 10px; color: #c8d3ea;")
        else:
            self.swatch.setStyleSheet(
                f"background-color: transparent; border: 1px solid {self._color}; border-radius: 3px;"
            )
            self.name.setStyleSheet("font-size: 10px; color: #4a5a7a; text-decoration: line-through;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._active = not self._active
            self._apply_style()
            self.toggled.emit(self.source_label)
        super().mousePressEvent(event)


class _LegendStrip(QWidget):
    """Horizontal file → colour key shown under both charts (Section 5.3)."""

    source_toggled = Signal(str)  # source_label — click-to-toggle visibility

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 2, 10, 2)
        self._layout.setSpacing(14)
        self._title = QLabel("KEY:")
        self._title.setStyleSheet("font-size: 11px; color: #c8d3ea; font-weight: bold;")
        self._layout.addWidget(self._title)
        self._layout.addStretch()
        self._chips: dict[str, _LegendChip] = {}

    def set_items(self, colors: dict[str, str]) -> None:
        while self._layout.count() > 2:
            item = self._layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self._chips.clear()

        for source_label, color in colors.items():
            chip = _LegendChip(source_label, color)
            chip.toggled.connect(self.source_toggled)
            self._chips[source_label] = chip
            self._layout.insertWidget(self._layout.count() - 1, chip)


class VisualizationRow(QWidget):
    """Heatmap + spike chart + bubble chart + shared legend."""

    # Relayed from whichever chart was clicked — (source_label, utc_datetime).
    element_clicked = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        self.heatmap = ActivityHeatmap()
        self.spike = SpikeChart()
        self.bubble = BubbleChart()

        # Relay each chart's click-to-navigate signal straight through.
        self.heatmap.element_clicked.connect(self.element_clicked)
        self.spike.element_clicked.connect(self.element_clicked)
        self.bubble.element_clicked.connect(self.element_clicked)

        # 1. Install Event Filters to listen for double-clicks on the charts
        self.heatmap.installEventFilter(self)
        self.spike.installEventFilter(self)
        self.bubble.installEventFilter(self)

        # Keep references to floating windows so they aren't garbage collected
        self._floating_windows = []

        # Full (unfiltered) data + colors, and which sources are currently
        # hidden via legend click — re-applied whenever either changes.
        self._all_entries: dict[str, list] = {}
        self._all_colors: dict[str, str] = {}
        self._hidden_sources: set[str] = set()

        self.charts_splitter = QSplitter(Qt.Horizontal)

        self.charts_splitter.addWidget(self._titled("ACTIVITY HEATMAP  ·  time of day", self.heatmap))
        self.charts_splitter.addWidget(self._titled("SPIKE CHART  ·  investigation range", self.spike))
        self.charts_splitter.addWidget(self._titled("ENTITY BUBBLE CHART  ·  anomalies", self.bubble))

        self.charts_splitter.setStretchFactor(0, 1)
        self.charts_splitter.setStretchFactor(1, 1)
        self.charts_splitter.setStretchFactor(2, 1)
        self.charts_splitter.setSizes([400, 400, 400])

        layout.addWidget(self.charts_splitter, stretch=1)

        self.legend = _LegendStrip()
        self.legend.source_toggled.connect(self._on_source_toggled)
        layout.addWidget(self.legend)

    @staticmethod
    def _titled(title: str, widget: QWidget) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 0, 4, 0)
        v.setSpacing(2)

        # Now just holds the title
        label = QLabel(title)
        label.setStyleSheet("font-size: 10px; font-weight: bold; color: #2e8fff; text-transform: uppercase;")
        v.addWidget(label)

        stack = QStackedWidget()
        stack.addWidget(widget)
        placeholder = QLabel("Chart detached.\nClose floating window to restore.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #7284a8; font-style: italic; font-size: 11px;")
        stack.addWidget(placeholder)
        v.addWidget(stack, stretch=1)

        widget._parent_stack = stack
        widget._chart_title = title
        return container

    def eventFilter(self, obj, event) -> bool:
        """Catches double-clicks on the charts and pops them out."""
        if event.type() == QEvent.MouseButtonDblClick:
            if obj in (self.heatmap, self.spike, self.bubble):
                # Ensure we only pop it out if it is currently inside the dashboard stack
                if obj.parentWidget() == getattr(obj, '_parent_stack', None):
                    # Create and show the floating window
                    fw = FloatingChartWindow(obj, obj._parent_stack, obj._chart_title)
                    self._floating_windows.append(fw)
                    fw.show()

                    return True  # Consume the double-click event

        return super().eventFilter(obj, event)

    # -- Public API (driven by MainWindow) -------------------------------------

    def set_entries(self, entries_by_source: dict, colors: dict) -> None:
        self._all_entries = entries_by_source
        self._all_colors = colors
        # A fresh data load starts every source visible again.
        self._hidden_sources &= set(entries_by_source.keys())
        self.legend.set_items(colors)
        self._apply_visibility()

    def set_display_timezone(self, tz_name: str) -> None:
        self.heatmap.set_display_timezone(tz_name)
        self.spike.set_display_timezone(tz_name)
        self.bubble.set_display_timezone(tz_name)

    def set_investigation_range(self, start_utc, end_utc) -> None:
        self.spike.set_range(start_utc, end_utc)
        self.bubble.set_investigation_range(start_utc, end_utc)

    def set_flag_anchors(self, anchors: list) -> None:
        """Relays the shared manual-flag anchors (Section 4.2) to all three
        charts so flagged entries glow there too, in sync with log windows.
        """
        self.heatmap.set_flag_anchors(anchors)
        self.spike.set_flag_anchors(anchors)
        self.bubble.set_flag_anchors(anchors)

    def clear(self) -> None:
        self._all_entries = {}
        self._all_colors = {}
        self._hidden_sources = set()
        self.heatmap.clear_chart()
        self.spike.clear_chart()
        self.bubble.set_entries({}, {})
        self.legend.set_items({})

    # -- Internal ----------------------------------------------------------------

    def _on_source_toggled(self, source_label: str) -> None:
        """Legend click — show/hide one source across all three charts without
        touching the underlying data (a re-import or filter change still starts
        fresh with everything visible).
        """
        if source_label in self._hidden_sources:
            self._hidden_sources.discard(source_label)
        else:
            self._hidden_sources.add(source_label)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        visible_entries = {
            label: entries for label, entries in self._all_entries.items()
            if label not in self._hidden_sources
        }
        self.heatmap.set_entries(visible_entries, self._all_colors)
        self.spike.set_entries(visible_entries, self._all_colors)
        self.bubble.set_entries(visible_entries, self._all_colors)
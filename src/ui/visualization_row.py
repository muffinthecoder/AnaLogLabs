"""
visualization_row.py — the top ~1/3 visualization area (Sections 1 & 5).

Composition:
    ┌───────────────────────┬──────────────────────┐
    │  Heatmap (full range)  │  Spike chart (range) │   ← resizable H-splitter
    ├───────────────────────┴──────────────────────┤
    │  Shared legend: file → colour swatch          │
    └───────────────────────────────────────────────┘

The heatmap and spike chart split the width via a draggable QSplitter (5.4).
A single legend strip below both maps each file to its shared base colour
(5.3), so both charts and the log windows can be read against one key.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QFrame,
)

from src.visualiser.activity_heatmap import ActivityHeatmap
from src.visualiser.spike_chart import SpikeChart


class _LegendStrip(QWidget):
    """Horizontal file → colour key shown under both charts (Section 5.3)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 2, 10, 2)
        self._layout.setSpacing(14)
        self._title = QLabel("KEY:")
        self._title.setStyleSheet("font-size: 9px; color: #4a5a7a;")
        self._layout.addWidget(self._title)
        self._layout.addStretch()

    def set_items(self, colors: dict[str, str]) -> None:
        # Clear existing swatches (keep the title at index 0 and stretch at end).
        while self._layout.count() > 2:
            item = self._layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        for source_label, color in colors.items():
            chip = QWidget()
            row = QHBoxLayout(chip)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(5)

            swatch = QFrame()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
            row.addWidget(swatch)

            name = QLabel(source_label)
            name.setStyleSheet("font-size: 10px; color: #8090b0;")
            row.addWidget(name)

            self._layout.insertWidget(self._layout.count() - 1, chip)


class VisualizationRow(QWidget):
    """Heatmap + spike chart + shared legend (Sections 1, 5)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        # Titled panes side by side.
        self.heatmap = ActivityHeatmap()
        self.spike = SpikeChart()

        self.charts_splitter = QSplitter(Qt.Horizontal)
        self.charts_splitter.addWidget(self._titled("ACTIVITY HEATMAP  ·  time of day", self.heatmap))
        self.charts_splitter.addWidget(self._titled("SPIKE CHART  ·  investigation range", self.spike))
        self.charts_splitter.setSizes([500, 500])
        layout.addWidget(self.charts_splitter, stretch=1)

        self.legend = _LegendStrip()
        layout.addWidget(self.legend)

    @staticmethod
    def _titled(title: str, widget: QWidget) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 0, 4, 0)
        v.setSpacing(2)
        label = QLabel(title)
        label.setProperty("class", "SectionTitle")
        v.addWidget(label)
        v.addWidget(widget, stretch=1)
        return container

    # -- Public API (driven by MainWindow) -------------------------------------

    def set_entries(self, entries_by_source: dict, colors: dict) -> None:
        self.heatmap.set_entries(entries_by_source, colors)
        self.spike.set_entries(entries_by_source, colors)
        self.legend.set_items(colors)

    def set_display_timezone(self, tz_name: str) -> None:
        self.heatmap.set_display_timezone(tz_name)
        self.spike.set_display_timezone(tz_name)

    def set_investigation_range(self, start_utc, end_utc) -> None:
        # Only the spike chart is range-filtered; the heatmap always shows full.
        self.spike.set_range(start_utc, end_utc)

    def clear(self) -> None:
        self.heatmap.clear_chart()
        self.spike.clear_chart()
        self.legend.set_items({})

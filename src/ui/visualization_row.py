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

from src.ui.theme import THEMES, DEFAULT_THEME

_FALLBACK_THEME = THEMES[DEFAULT_THEME]

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
    """A resizable floating window that temporarily holds a popped-out chart.

    Being reparented OUT of MainWindow (a real, independent top-level window)
    means the chart stops inheriting MainWindow's stylesheet entirely — that
    was the actual cause of a popped-out chart reverting to a grayish Qt
    default background instead of its themed color, and never picking up
    later theme switches. Fixed by giving this window its own explicit
    stylesheet (re-applied by set_theme()) covering the exact chart-panel
    rule the chart widget needs, plus tracking so MainWindow's theme switch
    can reach any currently-open one of these.
    """

    closed = Signal(object)  # self — lets VisualizationRow prune its tracking list

    def __init__(self, chart_widget: QWidget, stack: QStackedWidget, title: str = "Detached Chart",
                 theme: dict | None = None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.chart_widget = chart_widget
        self.stack = stack
        self._title = title

        self.setWindowTitle(title)
        self.resize(1000, 600)  # Open nice and large for the ISOO
        # Header for the floating window
        layout = QVBoxLayout(self)
        header_layout = QHBoxLayout()

        self._title_lbl = QLabel(title)
        header_layout.addWidget(self._title_lbl)
        header_layout.addStretch()

        # The Export Button is now here, clearly visible
        self._export_btn = QPushButton("Export")
        self._export_btn.setFixedSize(80, 24)
        self._export_btn.clicked.connect(lambda: _export_widget(self.chart_widget, title))
        header_layout.addWidget(self._export_btn)

        layout.addLayout(header_layout)
        layout.addWidget(self.chart_widget)

        self.chart_widget.show()
        self.stack.setCurrentIndex(1)

        self.set_theme(theme or _FALLBACK_THEME)

    def set_theme(self, theme: dict) -> None:
        """Re-styles this window's own chrome AND re-establishes the chart
        panel background the reparented chart widget lost — both need doing
        here since this window's stylesheet is the closest ancestor once
        popped out of MainWindow.
        """
        accent = theme["accent"]
        bg_input = theme["bg_input"]
        text_primary = theme["text_primary"]
        bg_app = theme["bg_app"]

        self._title_lbl.setStyleSheet(f"font-weight: bold; color: {accent};")
        self._export_btn.setStyleSheet(
            f"background-color: {bg_input}; color: {text_primary}; border: 1px solid {accent}; border-radius: 6px;"
        )

        heat_bg, heat_border = theme["chart_heat_bg"], theme["chart_heat_border"]
        spike_bg, spike_border = theme["chart_spike_bg"], theme["chart_spike_border"]
        bubble_bg, bubble_border = theme["chart_bubble_bg"], theme["chart_bubble_border"]
        self.setStyleSheet(f"""
            FloatingChartWindow {{ background-color: {bg_app}; }}
            ActivityHeatmap {{ background-color: {heat_bg}; border: 1px solid {heat_border}; border-radius: 10px; }}
            SpikeChart {{ background-color: {spike_bg}; border: 1px solid {spike_border}; border-radius: 10px; }}
            BubbleChart {{ background-color: {bubble_bg}; border: 1px solid {bubble_border}; border-radius: 10px; }}
        """)

    def closeEvent(self, event) -> None:
        """When the investigator closes the floating window, snap the chart back."""
        self.stack.insertWidget(0, self.chart_widget)
        self.stack.setCurrentIndex(0)
        self.closed.emit(self)
        super().closeEvent(event)


class _LegendChip(QWidget):
    """One clickable file -> colour swatch entry (Section 5.3). Click toggles
    that source's visibility across all three charts.
    """

    toggled = Signal(str)  # source_label

    def __init__(self, source_label: str, color: str, active_text: str = "#c8d3ea",
                 inactive_text: str = "#4a5a7a", parent=None):
        super().__init__(parent)
        self.source_label = source_label
        self._color = color
        self._active = True
        self._active_text = active_text
        self._inactive_text = inactive_text
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

    def set_theme_colors(self, active_text: str, inactive_text: str) -> None:
        self._active_text = active_text
        self._inactive_text = inactive_text
        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            self.swatch.setStyleSheet(f"background-color: {self._color}; border-radius: 3px;")
            self.name.setStyleSheet(f"font-size: 11px; color: {self._active_text};")
        else:
            self.swatch.setStyleSheet(
                f"background-color: transparent; border: 1px solid {self._color}; border-radius: 3px;"
            )
            self.name.setStyleSheet(f"font-size: 11px; color: {self._inactive_text}; text-decoration: line-through;")

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
        self._active_text = "#c8d3ea"
        self._inactive_text = "#4a5a7a"
        self._title.setStyleSheet(f"font-size: 12px; color: {self._active_text}; font-weight: bold;")
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
            chip = _LegendChip(source_label, color, self._active_text, self._inactive_text)
            chip.toggled.connect(self.source_toggled)
            self._chips[source_label] = chip
            self._layout.insertWidget(self._layout.count() - 1, chip)

    def set_theme(self, active_text: str, inactive_text: str) -> None:
        self._active_text = active_text
        self._inactive_text = inactive_text
        self._title.setStyleSheet(f"font-size: 12px; color: {active_text}; font-weight: bold;")
        for chip in self._chips.values():
            chip.set_theme_colors(active_text, inactive_text)


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

        # Current theme colors — read when creating NEW widgets (section
        # titles, floating-window chrome) so they're correct from the start
        # rather than needing a separate pass. set_theme() below handles
        # already-existing widgets.
        self._theme = _FALLBACK_THEME
        self._theme_accent = "#2e8fff"
        self._theme_bg_input = "#101a30"
        self._theme_text = "#c8d3ea"
        self._theme_dim = "#7284a8"
        self._section_labels: list[QLabel] = []
        self._section_placeholders: list[QLabel] = []

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

    def _titled(self, title: str, widget: QWidget) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(4, 0, 4, 0)
        v.setSpacing(2)

        # Now just holds the title
        label = QLabel(title)
        label.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {self._theme_accent}; text-transform: uppercase;")
        v.addWidget(label)
        self._section_labels.append(label)

        stack = QStackedWidget()
        stack.addWidget(widget)
        placeholder = QLabel("Chart detached.\nClose floating window to restore.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(f"color: {self._theme_dim}; font-style: italic; font-size: 12px;")
        stack.addWidget(placeholder)
        self._section_placeholders.append(placeholder)
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
                    fw = FloatingChartWindow(
                        obj, obj._parent_stack, obj._chart_title, theme=self._theme,
                    )
                    fw.closed.connect(self._on_floating_chart_closed)
                    self._floating_windows.append(fw)
                    fw.show()

                    return True  # Consume the double-click event

        return super().eventFilter(obj, event)

    def _on_floating_chart_closed(self, fw) -> None:
        """Stops tracking a floating chart window once closed, so a later
        theme switch doesn't try to restyle (or hold a dangling reference
        to) a window that no longer exists.
        """
        if fw in self._floating_windows:
            self._floating_windows.remove(fw)

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

    def set_theme(self, theme: dict) -> None:
        """Applies a theme switch to everything this widget owns directly —
        section titles, placeholders, the legend, forwards to the three
        charts (whose QPainter/pyqtgraph internals need their own explicit
        set_theme, since QSS re-application alone doesn't reach them), and
        any currently-open floating (popped-out) chart windows — those are
        genuine top-level windows outside MainWindow's widget tree, so they
        need their own explicit re-theming rather than inheriting it.
        """
        self._theme = theme
        self._theme_accent = theme["accent"]
        self._theme_bg_input = theme["bg_input"]
        self._theme_text = theme["text_primary"]
        self._theme_dim = theme["text_secondary"]

        for label in self._section_labels:
            label.setStyleSheet(
                f"font-size: 11px; font-weight: bold; color: {self._theme_accent}; text-transform: uppercase;")
        for placeholder in self._section_placeholders:
            placeholder.setStyleSheet(f"color: {self._theme_dim}; font-style: italic; font-size: 12px;")

        self.legend.set_theme(self._theme_text, self._theme_dim)

        for fw in self._floating_windows:
            fw.set_theme(theme)

        self.heatmap.set_theme(theme)
        self.spike.set_theme(theme)
        self.bubble.set_theme(theme)

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
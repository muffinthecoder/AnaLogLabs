"""
spike_chart.py — Section 5.2 master timeline / spike chart.

X-axis = time (the active investigation range only), Y-axis = total event
volume per time bucket, STACKED by source using the shared per-file colours so
a spike's contributing sources are identifiable at a glance.

Unlike the heatmap (which always shows the full range), the spike chart renders
ONLY after a time range has been entered, and only for that filtered range
(Section 5.2 / user journey step 4). Before a range is set it shows a prompt.

Pure QPainter, so it always renders and shares the exact colour system.
"""

from datetime import datetime

import pytz
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget

from src.models.data_classes import RawLogEntry

BUCKETS = 40
AXIS_HEIGHT = 16
LEFT_GUTTER = 28   # room for a small Y scale
TOP_PAD = 6


class SpikeChart(QWidget):
    """Filtered-range stacked-volume timeline (Section 5.2)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}
        self._colors: dict[str, str] = {}
        self._display_tz = "Australia/Perth"
        self._range_start: datetime | None = None  # UTC
        self._range_end: datetime | None = None    # UTC
        self.setMinimumHeight(80)
        self.setToolTip("Event volume over the investigation range, stacked by file")

    # -- Public API ------------------------------------------------------------

    def set_entries(self, entries_by_source: dict[str, list[RawLogEntry]], colors: dict[str, str]) -> None:
        self._entries_by_source = entries_by_source
        self._colors = colors
        self.update()

    def set_range(self, start_utc: datetime | None, end_utc: datetime | None) -> None:
        """Section 5.2 — set (or clear) the filtered range this chart draws."""
        self._range_start = start_utc
        self._range_end = end_utc
        self.update()

    def set_display_timezone(self, tz_name: str) -> None:
        self._display_tz = tz_name
        self.update()

    def clear_chart(self) -> None:
        self._entries_by_source = {}
        self._colors = {}
        self._range_start = self._range_end = None
        self.update()

    # -- Internal --------------------------------------------------------------

    def _tz(self):
        try:
            return pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone("Australia/Perth")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setFont(self._small_font())

        # Section 5.2 — nothing until a range is chosen.
        if self._range_start is None or self._range_end is None or self._range_end <= self._range_start:
            painter.setPen(QColor("#4a5a7a"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Enter a time range to see the spike chart")
            painter.end()
            return

        sources = sorted(
            label for label, entries in self._entries_by_source.items()
            if any(e.normalized_timestamp is not None for e in entries)
        )

        span = (self._range_end - self._range_start).total_seconds()
        bucket_seconds = span / BUCKETS

        # Stacked counts: stacks[bucket] = list of (color, count) bottom->top.
        stacks: list[list[tuple[str, int]]] = [[] for _ in range(BUCKETS)]
        totals = [0] * BUCKETS
        for label in sources:
            color = self._colors.get(label, "#4A90D9")
            per_bucket = [0] * BUCKETS
            for entry in self._entries_by_source[label]:
                nts = entry.normalized_timestamp
                if nts is None:
                    continue
                t = nts.utc_datetime
                if not (self._range_start <= t <= self._range_end):
                    continue
                idx = int((t - self._range_start).total_seconds() // bucket_seconds)
                idx = min(max(idx, 0), BUCKETS - 1)
                per_bucket[idx] += 1
            for b in range(BUCKETS):
                if per_bucket[b]:
                    stacks[b].append((color, per_bucket[b]))
                    totals[b] += per_bucket[b]

        plot_left = LEFT_GUTTER
        plot_width = max(self.width() - plot_left - 4, 1)
        plot_bottom = self.height() - AXIS_HEIGHT
        plot_top = TOP_PAD
        plot_height = max(plot_bottom - plot_top, 1)
        max_total = max(totals) if any(totals) else 1
        bar_width = plot_width / BUCKETS

        # Y scale ticks (0 and max).
        painter.setPen(QColor("#4a5a7a"))
        painter.drawText(QRectF(0, plot_top - 6, LEFT_GUTTER - 4, 12), Qt.AlignRight | Qt.AlignVCenter, str(max_total))
        painter.drawText(QRectF(0, plot_bottom - 12, LEFT_GUTTER - 4, 12), Qt.AlignRight | Qt.AlignVCenter, "0")

        # Draw stacked bars.
        for b in range(BUCKETS):
            x = plot_left + b * bar_width
            y = plot_bottom
            for color, count in stacks[b]:
                seg_h = (count / max_total) * plot_height
                rect = QRectF(x, y - seg_h, max(bar_width - 0.5, 1), seg_h)
                fill = QColor(color)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawRect(rect)
                y -= seg_h

        # X axis: start / mid / end in display tz.
        tz = self._tz()
        mid = self._range_start + (self._range_end - self._range_start) / 2
        painter.setPen(QColor("#4a5a7a"))
        painter.drawText(QRectF(plot_left, plot_bottom, 60, AXIS_HEIGHT),
                         Qt.AlignLeft | Qt.AlignVCenter, self._range_start.astimezone(tz).strftime("%H:%M:%S"))
        painter.drawText(QRectF(plot_left + plot_width / 2 - 30, plot_bottom, 60, AXIS_HEIGHT),
                         Qt.AlignHCenter | Qt.AlignVCenter, mid.astimezone(tz).strftime("%H:%M:%S"))
        painter.drawText(QRectF(plot_left + plot_width - 60, plot_bottom, 60, AXIS_HEIGHT),
                         Qt.AlignRight | Qt.AlignVCenter, self._range_end.astimezone(tz).strftime("%H:%M:%S"))
        painter.end()

    @staticmethod
    def _small_font() -> QFont:
        f = QFont()
        f.setPixelSize(9)
        return f

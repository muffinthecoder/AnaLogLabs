"""
activity_heatmap.py — R6 activity/frequency HEAT MAP.

Complements the existing ActivityFrequencyChart (grouped bars) with a compact
heat map that makes "busy periods across files" pop at a glance: one row per
log source, one column per time bucket, cell colour intensity proportional to
how many events that source logged in that bucket. The busiest cell in the
whole session anchors full intensity, so a genuine spike in any file stands out
against quiet periods.

Implemented with a plain QPainter (rather than PyQtGraph) so it has no extra
dependency and always renders inside the fixed-width right dashboard.

Data flow mirrors ActivityFrequencyChart so InvestigationDashboard can drive
both from the same call sites:
    InvestigationDashboard.load_entries() -> set_entries()
    MainWindow._on_timezone_changed()     -> set_display_timezone()
"""

from datetime import datetime, timedelta

import pytz
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget

from src.models.data_classes import RawLogEntry

# Number of time buckets across the loaded range — matches the bar chart's
# default so the two visualisations line up conceptually.
DEFAULT_BUCKET_COUNT = 24

# Cell intensity floor/ceiling (alpha). Even a single event shows faintly so an
# occupied bucket is never invisible; the busiest bucket hits full alpha.
MIN_ALPHA = 45
MAX_ALPHA = 235

ROW_HEIGHT = 16          # px per source row
LABEL_GUTTER = 8         # left px reserved for the source colour dot
AXIS_HEIGHT = 14         # bottom px reserved for time labels
TOP_PAD = 2


class ActivityHeatmap(QWidget):
    """R6 — per-source time-bucketed activity heat map."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}
        self._colors: dict[str, str] = {}
        self._display_tz = "Australia/Perth"
        self.setMinimumHeight(ROW_HEIGHT + AXIS_HEIGHT + TOP_PAD)
        self.setToolTip("Activity heat map — darker cells = busier periods")

    # -- Public API (mirrors ActivityFrequencyChart) ---------------------------

    def set_entries(self, entries_by_source: dict[str, list[RawLogEntry]], colors: dict[str, str]) -> None:
        self._entries_by_source = entries_by_source
        self._colors = colors
        self._resize_for_sources()
        self.update()

    def clear_chart(self) -> None:
        self._entries_by_source = {}
        self._colors = {}
        self._resize_for_sources()
        self.update()

    def set_display_timezone(self, tz_name: str) -> None:
        self._display_tz = tz_name
        self.update()

    # -- Internal --------------------------------------------------------------

    def _valid_sources(self) -> list[str]:
        return [
            label for label, entries in self._entries_by_source.items()
            if any(e.normalized_timestamp is not None for e in entries)
        ]

    def _resize_for_sources(self) -> None:
        rows = max(len(self._valid_sources()), 1)
        self.setFixedHeight(TOP_PAD + rows * ROW_HEIGHT + AXIS_HEIGHT)

    def _time_range(self, sources: list[str]) -> tuple[datetime, datetime]:
        all_ts = [
            e.normalized_timestamp.utc_datetime
            for label in sources
            for e in self._entries_by_source[label]
            if e.normalized_timestamp is not None
        ]
        start, end = min(all_ts), max(all_ts)
        if end <= start:
            end = start + timedelta(seconds=1)
        return start, end

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        sources = self._valid_sources()
        if not sources:
            painter.setPen(QColor("#4a5a7a"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No log data loaded")
            painter.end()
            return

        sources = sorted(sources)
        range_start, range_end = self._time_range(sources)
        span_seconds = (range_end - range_start).total_seconds()
        bucket_seconds = span_seconds / DEFAULT_BUCKET_COUNT

        # First pass — bucket every source and find the global max so intensity
        # is comparable across files ("busiest bucket anywhere" = full alpha).
        counts_by_source: dict[str, list[int]] = {}
        global_max = 1
        for label in sources:
            buckets = [0] * DEFAULT_BUCKET_COUNT
            for entry in self._entries_by_source[label]:
                if entry.normalized_timestamp is None:
                    continue
                ts = entry.normalized_timestamp.utc_datetime
                idx = int((ts - range_start).total_seconds() // bucket_seconds)
                idx = min(idx, DEFAULT_BUCKET_COUNT - 1)
                buckets[idx] += 1
            counts_by_source[label] = buckets
            global_max = max(global_max, max(buckets))

        # Geometry.
        grid_left = LABEL_GUTTER
        grid_width = max(self.width() - grid_left - 2, 1)
        cell_width = grid_width / DEFAULT_BUCKET_COUNT

        # Second pass — draw the colour dot + cells for each source row.
        for row, label in enumerate(sources):
            y = TOP_PAD + row * ROW_HEIGHT
            base = QColor(self._colors.get(label, "#4A90D9"))

            # Source colour dot in the left gutter.
            painter.setPen(Qt.NoPen)
            painter.setBrush(base)
            painter.drawEllipse(QRectF(0, y + ROW_HEIGHT / 2 - 3, 6, 6))

            for b, count in enumerate(counts_by_source[label]):
                cell = QRectF(
                    grid_left + b * cell_width, y + 1,
                    cell_width - 1, ROW_HEIGHT - 2,
                )
                if count == 0:
                    painter.setBrush(QColor("#12182a"))  # faint empty cell
                else:
                    alpha = MIN_ALPHA + int((MAX_ALPHA - MIN_ALPHA) * (count / global_max))
                    fill = QColor(base)
                    fill.setAlpha(alpha)
                    painter.setBrush(fill)
                painter.drawRect(cell)

        # Bottom axis — start / midpoint / end in the display timezone.
        try:
            tz = pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("Australia/Perth")
        mid = range_start + (range_end - range_start) / 2
        axis_y = self.height() - AXIS_HEIGHT + 2
        painter.setPen(QColor("#4a5a7a"))
        font = QFont()
        font.setPixelSize(8)
        painter.setFont(font)
        painter.drawText(
            QRectF(grid_left, axis_y, grid_width / 3, AXIS_HEIGHT),
            Qt.AlignLeft | Qt.AlignVCenter,
            range_start.astimezone(tz).strftime("%H:%M"),
        )
        painter.drawText(
            QRectF(grid_left + grid_width / 3, axis_y, grid_width / 3, AXIS_HEIGHT),
            Qt.AlignCenter,
            mid.astimezone(tz).strftime("%H:%M"),
        )
        painter.drawText(
            QRectF(grid_left + 2 * grid_width / 3, axis_y, grid_width / 3, AXIS_HEIGHT),
            Qt.AlignRight | Qt.AlignVCenter,
            range_end.astimezone(tz).strftime("%H:%M"),
        )
        painter.end()

"""
activity_heatmap.py — R6 / Section 5.1 activity heat map.

Grid: X-axis = time of day (0:00 → 24:00), Y-axis = log source (one row per
imported file). Every event is bucketed by its time-of-day (in the current
DISPLAY timezone), aggregated across the FULL imported range — this view is
deliberately independent of any investigation-window filter (Section 5.1).

Each file has ONE fixed hue (from the shared SourceColorMap). Within a file's
row, cell intensity encodes frequency — busier buckets render at full hue,
quiet buckets fade toward the background — normalised PER FILE so each source's
own busy periods are visible regardless of how its volume compares to others.
Hue never changes with frequency, only intensity (Section 5.1).

Pure QPainter (no PyQtGraph dependency) so it always renders.
"""

from datetime import datetime

import pytz
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget

from src.models.data_classes import RawLogEntry

# 48 half-hour buckets across the day give a readable "busy period" resolution.
BUCKETS_PER_DAY = 48
MINUTES_PER_BUCKET = 24 * 60 // BUCKETS_PER_DAY  # 30

MIN_ALPHA = 30
MAX_ALPHA = 245

ROW_HEIGHT = 22
LABEL_GUTTER = 96   # left area: colour dot + file name
AXIS_HEIGHT = 16
TOP_PAD = 4


class ActivityHeatmap(QWidget):
    """Time-of-day × file activity heat map (Section 5.1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}
        self._colors: dict[str, str] = {}
        self._display_tz = "Australia/Perth"
        self.setMinimumHeight(ROW_HEIGHT + AXIS_HEIGHT + TOP_PAD)
        self.setToolTip("Activity by time of day — brighter = busier (per file)")

    # -- Public API ------------------------------------------------------------

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
        self.setMinimumHeight(TOP_PAD + rows * ROW_HEIGHT + AXIS_HEIGHT)

    def _tz(self):
        try:
            return pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone("Australia/Perth")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        sources = sorted(self._valid_sources())
        if not sources:
            painter.setPen(QColor("#4a5a7a"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No log data loaded")
            painter.end()
            return

        tz = self._tz()

        # Bucket each source by time-of-day, tracking each row's own max.
        counts_by_source: dict[str, list[int]] = {}
        row_max: dict[str, int] = {}
        for label in sources:
            buckets = [0] * BUCKETS_PER_DAY
            for entry in self._entries_by_source[label]:
                if entry.normalized_timestamp is None:
                    continue
                local = entry.normalized_timestamp.utc_datetime.astimezone(tz)
                minute_of_day = local.hour * 60 + local.minute
                idx = min(minute_of_day // MINUTES_PER_BUCKET, BUCKETS_PER_DAY - 1)
                buckets[idx] += 1
            counts_by_source[label] = buckets
            row_max[label] = max(1, max(buckets))

        grid_left = LABEL_GUTTER
        grid_width = max(self.width() - grid_left - 4, 1)
        cell_width = grid_width / BUCKETS_PER_DAY

        painter.setFont(self._small_font())
        for row, label in enumerate(sources):
            y = TOP_PAD + row * ROW_HEIGHT
            base = QColor(self._colors.get(label, "#4A90D9"))

            # Left gutter — colour dot + (truncated) file name.
            painter.setPen(Qt.NoPen)
            painter.setBrush(base)
            painter.drawEllipse(QRectF(4, y + ROW_HEIGHT / 2 - 3, 6, 6))
            painter.setPen(QColor("#8090b0"))
            painter.drawText(
                QRectF(16, y, grid_left - 18, ROW_HEIGHT),
                Qt.AlignVCenter | Qt.AlignLeft,
                self._elide(label, 12),
            )

            rmax = row_max[label]
            for b, count in enumerate(counts_by_source[label]):
                cell = QRectF(grid_left + b * cell_width, y + 1, cell_width - 0.5, ROW_HEIGHT - 2)
                if count == 0:
                    painter.setBrush(QColor("#12182a"))
                else:
                    alpha = MIN_ALPHA + int((MAX_ALPHA - MIN_ALPHA) * (count / rmax))
                    fill = QColor(base)
                    fill.setAlpha(alpha)
                    painter.setBrush(fill)
                painter.setPen(Qt.NoPen)
                painter.drawRect(cell)

        # Bottom axis: 0:00 / 6:00 / 12:00 / 18:00 / 24:00.
        axis_y = TOP_PAD + len(sources) * ROW_HEIGHT
        painter.setPen(QColor("#4a5a7a"))
        for hour in (0, 6, 12, 18, 24):
            x = grid_left + (hour / 24.0) * grid_width
            align = Qt.AlignHCenter
            rect = QRectF(x - 20, axis_y, 40, AXIS_HEIGHT)
            if hour == 0:
                rect = QRectF(grid_left, axis_y, 40, AXIS_HEIGHT); align = Qt.AlignLeft
            elif hour == 24:
                rect = QRectF(grid_left + grid_width - 40, axis_y, 40, AXIS_HEIGHT); align = Qt.AlignRight
            painter.drawText(rect, align | Qt.AlignVCenter, f"{hour}:00")
        painter.end()

    @staticmethod
    def _small_font() -> QFont:
        f = QFont()
        f.setPixelSize(9)
        return f

    @staticmethod
    def _elide(text: str, max_chars: int) -> str:
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

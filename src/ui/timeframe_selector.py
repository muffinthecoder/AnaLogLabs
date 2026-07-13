"""
TimeFrameSelector — investigation window filter controls in the left sidebar
(Section 6.3.4 Zone 2, subsection 2 "Inquiry Period").

Per the design doc's class diagram (Section 4.6):
    start_inputs: dict   {day, month, year, hour, min, sec, ms}
    end_inputs: dict      (same keys)
    timezone: str
    use_24hr: bool

Owned by: Fatima

"""

from datetime import datetime, timedelta

import pytz
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton

from src.models.data_classes import FilterConfig

# R4 — the investigation window is automatically widened by this much on each
# side, so an investigator asking for "14:00 to 16:00" actually sees events
# from 13:59 to 16:01. Catches events that land right on the boundary of the
# period of interest.
INVESTIGATION_OFFSET = timedelta(minutes=1)

# Accepted input formats for the Start/End fields. Tried in order; the first
# that parses wins. Covers the strict ms form plus the common no-ms and
# 'T'-separated ISO variants, so investigators aren't forced to type
# milliseconds they don't have.
_INPUT_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
]


class TimeFrameSelector(QWidget):
    """Section 6.3.4 Zone 2 — Inquiry Period filter controls."""

    # Emitted when "Apply Filter" is clicked with a valid FilterConfig.
    filter_applied = Signal(object)  # FilterConfig

    # Emitted when "Clear Filter" is clicked.
    filter_cleared = Signal()

    def __init__(self, timezone: str = "Australia/Perth", parent=None):
        super().__init__(parent)
        self.timezone = timezone
        self.use_24hr = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(4)

        title = QLabel("INVESTIGATION WINDOW")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        # Themeable — these previously hardcoded white text, which is
        # invisible once the sidebar background goes light (Light theme).
        self._theme_text = "#c8d3ea"
        self._theme_dim = "#7284a8"

        self._start_label = QLabel("Start")
        self._start_label.setStyleSheet(f"font-size: 11px; color: {self._theme_text}; background: transparent;")
        layout.addWidget(self._start_label)

        self.start_input = QLineEdit()
        self.start_input.setObjectName("FilterInput")
        self.start_input.setPlaceholderText("YYYY-MM-DD HH:MM:SS.mmm")
        layout.addWidget(self.start_input)

        self._end_label = QLabel("End")
        self._end_label.setStyleSheet(f"font-size: 11px; color: {self._theme_text}; background: transparent;")
        layout.addWidget(self._end_label)

        self.end_input = QLineEdit()
        self.end_input.setObjectName("FilterInput")
        self.end_input.setPlaceholderText("YYYY-MM-DD HH:MM:SS.mmm")
        layout.addWidget(self.end_input)

        # R4 — make the auto-applied boundary offset visible so the widened
        # window isn't a surprise ("why am I seeing 13:59 events?").
        self._offset_note = QLabel("A ±1 min offset is applied automatically.")
        self._offset_note.setStyleSheet(f"font-size: 11px; color: {self._theme_dim}; background: transparent;")
        self._offset_note.setWordWrap(True)
        layout.addWidget(self._offset_note)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("font-size: 11px; color: #e06060; background: transparent;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.apply_button = QPushButton("Apply filter")
        self.apply_button.setObjectName("ApplyFilterButton")
        self.apply_button.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self.apply_button)

        self.clear_button = QPushButton("Clear filter")
        self.clear_button.setObjectName("ClearFilterButton")
        self.clear_button.clicked.connect(self._on_clear_clicked)
        layout.addWidget(self.clear_button)

    def set_theme(self, theme: dict) -> None:
        self._theme_text = theme["text_primary"]
        self._theme_dim = theme["text_secondary"]
        self._start_label.setStyleSheet(f"font-size: 11px; color: {self._theme_text}; background: transparent;")
        self._end_label.setStyleSheet(f"font-size: 11px; color: {self._theme_text}; background: transparent;")
        self._offset_note.setStyleSheet(f"font-size: 11px; color: {self._theme_dim}; background: transparent;")

    def _parse_user_datetime(self, text: str) -> tuple[datetime | None, bool]:
        """Parses a Start/End field, returning (naive_datetime, is_utc).

        Accepts pasted timestamps from either log column:
          * CONVERTED TIMESTAMP copies as "YYYY-MM-DD HH:MM:SS.mmm" in the
            display timezone → interpreted in the display timezone.
          * ORIGINAL LOG TIME may end in "Z" (e.g. "2026-03-25T01:05:02Z") →
            that is UTC, so is_utc is returned True and the display timezone is
            NOT applied.
        Returns (None, False) if nothing matched.
        """
        cleaned = text.strip()
        is_utc = False
        if cleaned.endswith(("Z", "z")):
            cleaned = cleaned[:-1].strip()
            is_utc = True
        for fmt in _INPUT_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt), is_utc
            except ValueError:
                continue
        return None, is_utc

    def _on_apply_clicked(self) -> None:
        """Section 4.7.2 ApplyFilter step 1 — validation before emitting.

        The entered times are interpreted in the investigator's selected
        DISPLAY timezone, converted to UTC, then widened by INVESTIGATION_
        OFFSET on each side (R4) before being handed to LogFilter.
        """
        self.error_label.hide()

        start_text = self.start_input.text().strip()
        end_text = self.end_input.text().strip()

        if not start_text or not end_text:
            self._show_error("Both start and end times are required.")
            return

        start_dt_naive, start_is_utc = self._parse_user_datetime(start_text)
        end_dt_naive, end_is_utc = self._parse_user_datetime(end_text)
        if start_dt_naive is None or end_dt_naive is None:
            self._show_error("Invalid date/time format entered.")
            return

        if start_dt_naive >= end_dt_naive:
            self._show_error("Start time must be before end time.")
            return

        # LogFilter.apply_filter requires UTC-aware datetimes. A value that
        # carried a "Z" is already UTC; otherwise localise using the selected
        # display timezone, then convert to UTC.
        display_tz = pytz.timezone(self.timezone)

        def to_utc(naive, is_utc):
            zone = pytz.UTC if is_utc else display_tz
            return zone.localize(naive).astimezone(pytz.UTC)

        start_dt = to_utc(start_dt_naive, start_is_utc)
        end_dt = to_utc(end_dt_naive, end_is_utc)

        # R4 — widen the window by ±1 minute so boundary events are caught.
        # Applied on the UTC datetimes since an offset is timezone-agnostic.
        start_dt -= INVESTIGATION_OFFSET
        end_dt += INVESTIGATION_OFFSET

        config = FilterConfig(
            start_time=start_dt,
            end_time=end_dt,
            timezone=self.timezone,
            use_ms_precision=True,
        )
        self.filter_applied.emit(config)

    def _on_clear_clicked(self) -> None:
        self.start_input.clear()
        self.end_input.clear()
        self.error_label.hide()
        self.filter_cleared.emit()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def set_timezone(self, timezone: str) -> None:
        self.timezone = timezone
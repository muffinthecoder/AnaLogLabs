"""
TimeFrameSelector — investigation window filter controls in the left sidebar
(Section 6.3.4 Zone 2, subsection 2 "Inquiry Period").

Per the design doc's class diagram (Section 4.6):
    start_inputs: dict   {day, month, year, hour, min, sec, ms}
    end_inputs: dict      (same keys)
    timezone: str
    use_24hr: bool
"""

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton

from src.models.data_classes import FilterConfig


class TimeFrameSelector(QWidget):
    """Section 6.3.4 Zone 2 — Inquiry Period filter controls."""

    # Emitted when "Apply Filter" is clicked with a valid FilterConfig.
    filter_applied = Signal(object)  # FilterConfig

    # Emitted when "Clear Filter" is clicked.
    filter_cleared = Signal()

    def __init__(self, timezone: str = "Asia/Dubai", parent=None):
        super().__init__(parent)
        self.timezone = timezone
        self.use_24hr = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(4)

        title = QLabel("INVESTIGATION WINDOW")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        start_label = QLabel("Start")
        start_label.setStyleSheet("font-size: 10px; color: #4a5a7a;")
        layout.addWidget(start_label)

        self.start_input = QLineEdit()
        self.start_input.setObjectName("FilterInput")
        self.start_input.setPlaceholderText("YYYY-MM-DD HH:MM:SS.mmm")
        layout.addWidget(self.start_input)

        end_label = QLabel("End")
        end_label.setStyleSheet("font-size: 10px; color: #4a5a7a;")
        layout.addWidget(end_label)

        self.end_input = QLineEdit()
        self.end_input.setObjectName("FilterInput")
        self.end_input.setPlaceholderText("YYYY-MM-DD HH:MM:SS.mmm")
        layout.addWidget(self.end_input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("font-size: 10px; color: #e06060;")
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

    def _on_apply_clicked(self) -> None:
        """Section 4.7.2 ApplyFilter step 1 — validation before emitting.

        TODO (Fatima/Hiba):
            Replace the naive datetime.strptime calls below with the real
            parser that supports the format chain from Section 4.7.5
            NormalizeTimestamp (ISO 8601, DD/MM/YYYY, MM-DD-YYYY, compact).
            Currently only accepts "YYYY-MM-DD HH:MM:SS.mmm" exactly.
        """
        self.error_label.hide()

        start_text = self.start_input.text().strip()
        end_text = self.end_input.text().strip()

        if not start_text or not end_text:
            self._show_error("Both start and end times are required.")
            return

        try:
            start_dt = datetime.strptime(start_text, "%Y-%m-%d %H:%M:%S.%f")
            end_dt = datetime.strptime(end_text, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            self._show_error("Invalid date/time format entered.")
            return

        if start_dt >= end_dt:
            self._show_error("Start time must be before end time.")
            return

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

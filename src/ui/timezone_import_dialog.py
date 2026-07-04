"""
timezone_import_dialog.py — modal dialog shown before log files are parsed.

Now asks only for the DISPLAY timezone (how the investigator wants to VIEW
timestamps), not per-file source timezones. Rules are:
  - Timestamps ending in Z are already UTC; they are converted to display tz.
  - Timestamps without Z are assumed to be Perth time (Australia/Perth),
    then converted to UTC, then to display tz.
"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QLabel, QComboBox,
)

from src.normaliser.timezone_map import SUPPORTED_TIMEZONES, display_label_for_timezone

# Phase 1: options now come from timezone_map.SUPPORTED_TIMEZONES (9 zones)
# instead of a hardcoded 3-entry list, and the combo stores each entry's IANA
# string as userData rather than requiring a label round-trip — three of the
# new zones (Adelaide, Melbourne, Sydney) observe DST, so their display label
# alone is not a safe/unique key to parse a fixed offset back out of.


class TimezoneImportDialog(QDialog):
    """Ask the investigator which timezone they want to VIEW times in."""

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Display Timezone")
        self.setMinimumWidth(420)
        self.setModal(True)

        self.display_timezone: str = "Asia/Dubai"        # IANA, set on accept
        # Keep the old attribute name so MainWindow's loop still compiles,
        # but it now maps every file to the same display tz (unused by
        # TimestampNormalizer — the normalizer uses source tz, not display tz).
        self.timezone_assignments: dict[str, str] = {}
        self._file_paths = file_paths

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(
            "Which timezone do you want to <b>view</b> timestamps in?<br>"
            "<br>"
            "Timestamps already in UTC (ending in <b>Z</b>) will be converted "
            "to your selected timezone.<br>"
            "Timestamps <i>without</i> a Z are assumed to be <b>Perth time "
            "(AWST, UTC+8)</b> and will be converted accordingly."
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 11px; color: #8090b0; padding-bottom: 4px;")
        layout.addWidget(header)

        self._combo = QComboBox()
        # No log data is loaded yet when this dialog is shown, so
        # display_label_for_timezone() falls back to "now" for DST zones'
        # UTC offset here — correct, DST-aware per-panel offsets are
        # computed later, once actual entry timestamps exist to anchor to.
        for iana_tz in SUPPORTED_TIMEZONES:
            self._combo.addItem(display_label_for_timezone(iana_tz), userData=iana_tz)
        self._combo.setMinimumWidth(260)
        layout.addWidget(self._combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Import")
        buttons.accepted.connect(self._on_accepted)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accepted(self) -> None:
        self.display_timezone = self._combo.currentData() or "Asia/Dubai"
        # Populate timezone_assignments so MainWindow's existing loop
        # (`for file_path, iana_tz in dialog.timezone_assignments.items()`)
        # still runs without errors — but these values are now the DISPLAY
        # timezone, not the source timezone. The source timezone is handled
        # implicitly in TimestampNormalizer (Z → UTC, no-Z → Perth).
        self.timezone_assignments = {
            path: self.display_timezone for path in self._file_paths
        }
        self.accept()
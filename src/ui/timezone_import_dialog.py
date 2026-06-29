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

_TIMEZONE_OPTIONS: list[tuple[str, str]] = [
    ("Asia/Dubai",      "Dubai (GST, UTC+4)"),
    ("Asia/Singapore",  "Singapore (SGT, UTC+8)"),
    ("Australia/Perth", "Perth (AWST, UTC+8)"),
]
_LABEL_TO_IANA = {label: iana for iana, label in _TIMEZONE_OPTIONS}
_DISPLAY_LABELS = [label for _, label in _TIMEZONE_OPTIONS]


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
        self._combo.addItems(_DISPLAY_LABELS)
        self._combo.setMinimumWidth(260)
        layout.addWidget(self._combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Import")
        buttons.accepted.connect(self._on_accepted)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accepted(self) -> None:
        label = self._combo.currentText()
        self.display_timezone = _LABEL_TO_IANA.get(label, "Asia/Dubai")
        # Populate timezone_assignments so MainWindow's existing loop
        # (`for file_path, iana_tz in dialog.timezone_assignments.items()`)
        # still runs without errors — but these values are now the DISPLAY
        # timezone, not the source timezone. The source timezone is handled
        # implicitly in TimestampNormalizer (Z → UTC, no-Z → Perth).
        self.timezone_assignments = {
            path: self.display_timezone for path in self._file_paths
        }
        self.accept()
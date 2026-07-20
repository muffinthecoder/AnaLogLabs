"""
Owned by: Minal

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
from src.ui.theme import THEMES, DEFAULT_THEME

# Phase 1: options now come from timezone_map.SUPPORTED_TIMEZONES (9 zones)
# instead of a hardcoded 3-entry list, and the combo stores each entry's IANA
# string as userData rather than requiring a label round-trip — three of the
# new zones (Adelaide, Melbourne, Sydney) observe DST, so their display label
# alone is not a safe/unique key to parse a fixed offset back out of.
class TimezoneImportDialog(QDialog):
    """Ask the investigator which timezone they want to VIEW times in."""
    def __init__(self, file_paths: list[str], theme: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Display Timezone")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.display_timezone: str = "Asia/Dubai"        # IANA, set on accept

        # TimestampNormalizer — the normalizer uses source tz, not display tz).
        self.timezone_assignments: dict[str, str] = {}
        self._file_paths = file_paths
        self._theme = theme or THEMES[DEFAULT_THEME]
        self._build_ui()
        self._apply_theme()
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        self._header = QLabel(
            "Which timezone do you want to <b>view</b> timestamps in?<br>"
            "<br>"
            "Timestamps already in UTC (ending in <b>Z</b>) will be converted "
            "to your selected timezone.<br>"
            "Timestamps <i>without</i> a Z are assumed to be <b>Perth time "
            "(AWST, UTC+8)</b> and will be converted accordingly."
        )
        self._header.setWordWrap(True)
        layout.addWidget(self._header)
        self._combo = QComboBox()
        # No log data is loaded yet when this dialog is shown, so
        # display_label_for_timezone() falls back to "now" for DST zones'
        # UTC offset here — correct, DST-aware per-panel offsets are
        # computed later, once actual entry timestamps exist to anchor to.
        for iana_tz in SUPPORTED_TIMEZONES:
            self._combo.addItem(display_label_for_timezone(iana_tz), userData=iana_tz)
        self._combo.setMinimumWidth(260)
        layout.addWidget(self._combo)
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Import")
        self._buttons.accepted.connect(self._on_accepted)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _apply_theme(self) -> None:
        t = self._theme
        self.setStyleSheet(f"""
            QDialog {{ background-color: {t['bg_sidebar']}; }}
            QLabel {{ color: {t['text_primary']}; background: transparent; }}
            QComboBox {{
                background-color: {t['bg_input']}; color: {t['text_primary']};
                border: 1px solid {t['border']}; border-radius: 6px; padding: 4px 8px;
            }}
            QDialogButtonBox QPushButton {{
                background-color: {t['bg_input']}; color: {t['text_primary']};
                border: 1px solid {t['border']}; border-radius: 6px; padding: 5px 14px;
            }}
            QDialogButtonBox QPushButton:hover {{ border-color: {t['accent']}; }}
        """)
        self._header.setStyleSheet(
            f"font-size: 13px; color: {t['text_primary']}; padding-bottom: 4px; background: transparent;"
        )
    def _on_accepted(self) -> None:
        self.display_timezone = self._combo.currentData() or "Asia/Dubai"
        # Populate timezone_assignments so MainWindow's existing loop
        # (`for file_path, iana_tz in dialog.timezone_assignments.items()`)
        self.timezone_assignments = {
            path: self.display_timezone for path in self._file_paths
        }
        self.accept()
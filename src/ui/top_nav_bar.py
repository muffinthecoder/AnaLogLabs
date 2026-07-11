"""
TopNavBar — fixed top bar.

Controls, left to right:
    AnaLog Labs logo
    Import logs
    Sync scroll toggle   — pressable; if pressed with no time range set, the
                           user is prompted to enter one (handled in MainWindow).
    Convert to           — ONE display-timezone dropdown (UTC, Perth, the other
                           Australian cities, Dubai, Singapore). There is no
                           separate "original" timezone control: raw timestamps
                           ending in "Z" are treated as UTC and all others as
                           Perth local time, automatically.
    Session stats        — Total / Highlighted / Flagged, live-updated.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame

from src.normaliser.timezone_map import SUPPORTED_TIMEZONES, DEFAULT_TIMEZONE


class TopNavBar(QWidget):
    """Top bar."""

    import_logs_clicked = Signal()
    sync_scroll_toggled = Signal(bool)
    display_timezone_changed = Signal(str)   # IANA name — the "convert to" zone

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopNavBar")
        self.setFixedHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        logo = QLabel("AnaLog Labs")
        logo.setObjectName("LogoLabel")
        layout.addWidget(logo)

        self._add_separator(layout)

        self.import_button = QPushButton("Import logs")
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.clicked.connect(self.import_logs_clicked.emit)
        layout.addWidget(self.import_button)

        # Sync scroll starts OFF but is always pressable: pressing it without a
        # valid time range prompts the user (handled in MainWindow) rather than
        # being silently disabled.
        self.sync_scroll_button = QPushButton("Sync scroll")
        self.sync_scroll_button.setCheckable(True)
        self.sync_scroll_button.toggled.connect(self._on_sync_toggled)
        layout.addWidget(self.sync_scroll_button)

        self._add_separator(layout)

        # ONE display-timezone dropdown ("convert to"). Raw "Z" timestamps are
        # UTC and non-"Z" timestamps are Perth local — that assumption is fixed
        # in the parser, so there is no separate "original timezone" control.
        #layout.addWidget(self._tz_caption("Convert to"))
        convert_label = QLabel("Convert to")
        
        # Update its style to pure white (keeping whatever font size is already there)
        convert_label.setStyleSheet("color: #ffffff; font-size: 12px;") 
        
        layout.addWidget(convert_label)
        self.display_tz_dropdown = QComboBox()
        for iana, label in SUPPORTED_TIMEZONES.items():
            self.display_tz_dropdown.addItem(label, iana)
        # Default display = Perth (the client's primary zone; matches the "+8"
        # converted times seen in the reference screenshot).
        self._select(self.display_tz_dropdown, DEFAULT_TIMEZONE)
        self.display_tz_dropdown.currentIndexChanged.connect(
            lambda _i: self.display_timezone_changed.emit(self.display_tz_dropdown.currentData())
        )
        layout.addWidget(self.display_tz_dropdown)

        layout.addStretch()

        # Live session stats.
        self.total_label = self._stat_label("Total", "0", "#00c4e8")
        self.highlighted_label = self._stat_label("Highlighted", "0", "#ffd60a")
        self.flagged_label = self._stat_label("Flagged", "0", "#e8b840")        
        
        for w in (self.total_label, self.highlighted_label, self.flagged_label):
            layout.addWidget(w)

    # -- construction helpers --------------------------------------------------

    def _add_separator(self, layout: QHBoxLayout) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #2a3050;")
        layout.addWidget(sep)

    def _tz_caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 10px; color: #5a6a8a;")
        return label

    def _stat_label(self, caption: str, value: str, color: str) -> QLabel:
        label = QLabel()
        label.setProperty("caption", caption)
        label.setProperty("color", color)
        label.setStyleSheet("font-size: 11px; color: #8090b0;")
        self._render_stat(label, value)
        return label

    def _render_stat(self, label: QLabel, value: str) -> None:
        caption = label.property("caption")
        color = label.property("color")
        label.setText(
            f"<span style='color:#ffffff'>{caption}</span> "
            f"<span style='color:{color}; font-weight:600'>{value}</span>"
        )

    @staticmethod
    def _select(combo: QComboBox, iana: str) -> None:
        idx = combo.findData(iana)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _on_sync_toggled(self, checked: bool) -> None:
        self.sync_scroll_button.setObjectName("ToggleActive" if checked else "")
        self.sync_scroll_button.setStyleSheet("")  # force re-polish
        self.sync_scroll_toggled.emit(checked)

    # -- public API ------------------------------------------------------------

    def current_display_timezone(self) -> str:
        return self.display_tz_dropdown.currentData() or DEFAULT_TIMEZONE

    def set_display_timezone(self, iana_tz: str) -> None:
        """Programmatically reflects an externally-chosen display timezone in
        the "Convert to" dropdown — used after the investigator picks a
        timezone in TimezoneImportDialog at import time, so the dropdown
        doesn't silently disagree with what was just chosen.

        Signals are blocked while setting the index: this method is called
        FROM the import flow (which already applies the chosen timezone
        directly via MainWindow._on_display_tz_changed), so letting the
        dropdown's own currentIndexChanged fire here would just re-run that
        same update a second time for no reason. Selecting the SAME zone
        already active is a no-op either way (findData returns the already-
        current index), so this is safe to call unconditionally.
        """
        self.display_tz_dropdown.blockSignals(True)
        self._select(self.display_tz_dropdown, iana_tz)
        self.display_tz_dropdown.blockSignals(False)

    def force_sync_off(self) -> None:
        """Reset the sync toggle to OFF without emitting toggled — used after
        the "please enter a time range" prompt to undo the user's press.
        """
        self.sync_scroll_button.blockSignals(True)
        self.sync_scroll_button.setChecked(False)
        self.sync_scroll_button.setObjectName("")
        self.sync_scroll_button.setStyleSheet("")
        self.sync_scroll_button.blockSignals(False)

    def set_stats(self, total: int, highlighted: int, flagged: int) -> None:
        self._render_stat(self.total_label, f"{total:,}")
        self._render_stat(self.highlighted_label, f"{highlighted:,}")
        self._render_stat(self.flagged_label, f"{flagged:,}")
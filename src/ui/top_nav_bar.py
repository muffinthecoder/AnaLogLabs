"""
Owned by: Minal

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

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame

from src.normaliser.timezone_map import SUPPORTED_TIMEZONES, DEFAULT_TIMEZONE
from src.ui.theme import THEMES, THEME_LABELS, DEFAULT_THEME


class TopNavBar(QWidget):
    """Top bar."""
    import_logs_clicked = Signal()
    sync_scroll_toggled = Signal(bool)
    display_timezone_changed = Signal(str)  # IANA name — the "convert to" zone
    theme_changed = Signal(str)  # theme key — see theme.py
    clear_flags_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopNavBar")
        # Plain QWidget subclasses don't paint a QSS background-color at all
        # unless this is set — without it, a theme's nav_bg color silently
        # falls through to whatever's behind it instead of actually applying.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

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
        # layout.addWidget(self._tz_caption("Convert to"))
        convert_label = QLabel("Convert to")

        # Update its style to pure white (keeping whatever font size is already there)
        convert_label.setStyleSheet("color: #ffffff; font-size: 13px; background: transparent;")

        layout.addWidget(convert_label)
        self.display_tz_dropdown = QComboBox()
        self.display_tz_dropdown.setMaximumWidth(170)
        for iana, label in SUPPORTED_TIMEZONES.items():
            self.display_tz_dropdown.addItem(label, iana)
        # Default display = Perth (the client's primary zone; matches the "+8"
        # converted times seen in the reference screenshot).
        self._select(self.display_tz_dropdown, DEFAULT_TIMEZONE)
        self.display_tz_dropdown.currentIndexChanged.connect(
            lambda _i: self.display_timezone_changed.emit(self.display_tz_dropdown.currentData())
        )
        layout.addWidget(self.display_tz_dropdown)

        self._add_separator(layout)

        theme_label = QLabel("Theme")
        theme_label.setStyleSheet("color: #ffffff; font-size: 13px; background: transparent;")
        layout.addWidget(theme_label)
        self.theme_dropdown = QComboBox()
        self.theme_dropdown.setMaximumWidth(110)
        for key in THEMES:
            self.theme_dropdown.addItem(THEME_LABELS.get(key, key), key)
        self._select(self.theme_dropdown, DEFAULT_THEME)
        self.theme_dropdown.currentIndexChanged.connect(
            lambda _i: self.theme_changed.emit(self.theme_dropdown.currentData())
        )
        layout.addWidget(self.theme_dropdown)

        layout.addStretch()

        # Live session stats.
        self.total_label = self._stat_label("Total", "0", "#00c4e8")
        self.highlighted_label = self._stat_label("Highlighted", "0", "#ffd60a")
        self.flagged_label = self._stat_label("Flagged", "0", "#e8b840")

        for w in (self.total_label, self.highlighted_label, self.flagged_label):
            layout.addWidget(w)

        self.clear_flags_button = QPushButton("Clear flags")
        self.clear_flags_button.setToolTip("Remove every flag in this session")
        self.clear_flags_button.setMaximumWidth(90)
        self.clear_flags_button.clicked.connect(self.clear_flags_clicked.emit)
        layout.addWidget(self.clear_flags_button)

    #  construction helpers

    def _add_separator(self, layout: QHBoxLayout) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #2a3050;")
        layout.addWidget(sep)

    def _tz_caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 11px; color: #5a6a8a;")
        return label

    def _stat_label(self, caption: str, value: str, color: str) -> QLabel:
        label = QLabel()
        label.setProperty("caption", caption)
        label.setProperty("color", color)
        label.setStyleSheet("font-size: 12px; color: #8090b0;")
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

    # public API

    def current_display_timezone(self) -> str:
        return self.display_tz_dropdown.currentData() or DEFAULT_TIMEZONE

    def set_display_timezone(self, iana_tz: str) -> None:
        """Programmatically reflects an externally-chosen display timezone in
        the "Convert to" dropdown — used after the investigator picks a
        timezone in TimezoneImportDialog at import time, so the dropdown
        doesn't silently disagree with what was just chosen.
        """
        self.display_tz_dropdown.blockSignals(True)
        self._select(self.display_tz_dropdown, iana_tz)
        self.display_tz_dropdown.blockSignals(False)

    def set_current_theme(self, theme_key: str) -> None:
        """Programmatically reflects an externally-set theme (e.g. restored
        from saved settings at startup) without re-emitting theme_changed.
        """
        self.theme_dropdown.blockSignals(True)
        self._select(self.theme_dropdown, theme_key)
        self.theme_dropdown.blockSignals(False)

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
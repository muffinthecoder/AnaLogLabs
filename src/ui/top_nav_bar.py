"""
TopNavBar — fixed top navigation bar (Section 6.3.4 Zone 1).

Controls (per design doc table):
    AnaLog Labs logo  — static label, branding only
    Import logs       — primary button, opens native OS file dialog
    Sync scroll        — toggle button
    Time zone          — dropdown: Perth | Singapore | Dubai | UTC | Adelaide |
                         Darwin | Brisbane | Melbourne | Sydney (Phase 1)
    Session status      — status indicator (logs loaded count + active dot)

Owned by: Fatima

Phase 1 note: the dropdown now sources its options from
src.normaliser.timezone_map.SUPPORTED_TIMEZONES instead of a hardcoded local
list, so every timezone the rest of the app understands is guaranteed to
appear here too — adding a zone only ever requires editing timezone_map.py.
Each entry's underlying IANA string (e.g. "Australia/Sydney") is stored as
the QComboBox item's userData rather than parsed back out of the display
label, since three of the new zones observe DST and therefore don't have a
single fixed "UTC+X" that could safely be baked into a static label string.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame

from src.normaliser.timezone_map import SUPPORTED_TIMEZONES, display_label_for_timezone


class TopNavBar(QWidget):
    """Section 6.3.4 Zone 1 — top navigation bar."""

    import_logs_clicked = Signal()
    sync_scroll_toggled = Signal(bool)
    timezone_changed = Signal(str)

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

        self.sync_scroll_button = QPushButton("Sync scroll")
        self.sync_scroll_button.setCheckable(True)
        self.sync_scroll_button.toggled.connect(self._on_sync_toggled)
        layout.addWidget(self.sync_scroll_button)

        self._add_separator(layout)

        tz_label = QLabel("Timezone")
        tz_label.setStyleSheet("font-size: 11px; color: #5a6a8a;")
        layout.addWidget(tz_label)

        self.timezone_dropdown = QComboBox()
        # Populated from SUPPORTED_TIMEZONES so this list can never drift out
        # of sync with what the rest of the app (parsing, normalisation,
        # display) actually supports. No log data is loaded yet at this
        # point, so display_label_for_timezone() falls back to "now" for its
        # UTC offset here — a DST zone's badge will be recomputed correctly
        # per-panel once real data exists (see LogWindowWidget.set_display_
        # timezone / MainWindow._on_timezone_changed).
        for iana_tz, _country_name in SUPPORTED_TIMEZONES.items():
            self.timezone_dropdown.addItem(display_label_for_timezone(iana_tz), userData=iana_tz)
        self.timezone_dropdown.currentIndexChanged.connect(self._on_timezone_index_changed)
        layout.addWidget(self.timezone_dropdown)

        layout.addStretch()

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(7, 7)
        self.status_dot.setStyleSheet("background-color: #57cc99; border-radius: 4px;")
        layout.addWidget(self.status_dot)

        self.status_label = QLabel("0 logs loaded")
        self.status_label.setStyleSheet("font-size: 11px; color: #57cc99;")
        layout.addWidget(self.status_label)

    def _add_separator(self, layout: QHBoxLayout) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #2a3050;")
        layout.addWidget(sep)

    def _on_timezone_index_changed(self, index: int) -> None:
        """Emits the IANA timezone string (e.g. "Australia/Sydney") rather
        than the display label — see the module docstring's Phase 1 note on
        why the label can no longer be parsed back into an IANA string for
        the DST-observing zones.
        """
        iana_tz = self.timezone_dropdown.itemData(index)
        if iana_tz:
            self.timezone_changed.emit(iana_tz)

    def _on_sync_toggled(self, checked: bool) -> None:
        self.sync_scroll_button.setObjectName("ToggleActive" if checked else "")
        self.sync_scroll_button.setStyleSheet("")  # force re-polish
        self.sync_scroll_toggled.emit(checked)

    def set_loaded_count(self, count: int) -> None:
        self.status_label.setText(f"{count} log{'s' if count != 1 else ''} loaded")

    def set_sync_scroll_enabled(self, enabled: bool) -> None:
        """TODO (Section 6.3.6 edge case):
        Disable sync scroll toggle with a tooltip when fewer than 2 panels
        are open: "Requires at least 2 log panels."
        """
        self.sync_scroll_button.setEnabled(enabled)
        if not enabled:
            self.sync_scroll_button.setToolTip("Requires at least 2 log panels.")
        else:
            self.sync_scroll_button.setToolTip("")
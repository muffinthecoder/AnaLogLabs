"""
TopNavBar — fixed top navigation bar (Section 6.3.4 Zone 1).

Controls (per design doc table, extended for the MVP changes):
    AnaLog Labs logo  — static label, branding only
    Import logs       — primary button, opens native OS file dialog
    Sync scroll        — toggle button (timestamp-aligned scrolling)
    Lock windows       — toggle button (R7): docks all panels side-by-side
                         into one puzzle-locked view with a single unified
                         scrollbar
    Display timezone   — dropdown: Australian cities + Dubai + Singapore (R3)
    Session status      — status indicator (logs loaded count + active dot)

Owned by: Fatima
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QComboBox, QFrame

from src.normaliser.timezone_map import SUPPORTED_TIMEZONES, DEFAULT_TIMEZONE


class TopNavBar(QWidget):
    """Section 6.3.4 Zone 1 — top navigation bar."""

    import_logs_clicked = Signal()
    sync_scroll_toggled = Signal(bool)
    lock_windows_toggled = Signal(bool)
    # Emits the IANA timezone name (e.g. "Australia/Perth"), not the display
    # label — so downstream code never has to reverse-map a label back to a
    # zone. This is the DISPLAY timezone only (R3); it does not change how
    # imported logs are parsed (that assumption is Perth, see timezone_map).
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

        # R7 — puzzle-lock all open panels into one unified, single-scrollbar
        # view. Kept separate from Sync scroll so investigators can still use
        # timestamp-aligned scrolling with free-floating windows if they
        # prefer; Lock windows is the "snap everything together" mode.
        self.lock_windows_button = QPushButton("Lock windows")
        self.lock_windows_button.setCheckable(True)
        self.lock_windows_button.toggled.connect(self._on_lock_toggled)
        layout.addWidget(self.lock_windows_button)

        self._add_separator(layout)

        tz_label = QLabel("Display TZ")
        tz_label.setStyleSheet("font-size: 11px; color: #5a6a8a;")
        layout.addWidget(tz_label)

        self.timezone_dropdown = QComboBox()
        # Store the IANA name as the item's userData so currentData() gives us
        # the zone directly, while the visible text stays the friendly label.
        for iana, label in SUPPORTED_TIMEZONES.items():
            self.timezone_dropdown.addItem(label, iana)
        default_index = self.timezone_dropdown.findData(DEFAULT_TIMEZONE)
        if default_index >= 0:
            self.timezone_dropdown.setCurrentIndex(default_index)
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

    def _on_sync_toggled(self, checked: bool) -> None:
        self.sync_scroll_button.setObjectName("ToggleActive" if checked else "")
        self.sync_scroll_button.setStyleSheet("")  # force re-polish
        self.sync_scroll_toggled.emit(checked)

    def _on_lock_toggled(self, checked: bool) -> None:
        self.lock_windows_button.setObjectName("ToggleActive" if checked else "")
        self.lock_windows_button.setStyleSheet("")  # force re-polish
        self.lock_windows_button.setText("Unlock windows" if checked else "Lock windows")
        self.lock_windows_toggled.emit(checked)

    def _on_timezone_index_changed(self, _index: int) -> None:
        iana = self.timezone_dropdown.currentData()
        if iana:
            self.timezone_changed.emit(iana)

    def current_timezone(self) -> str:
        """Returns the currently selected DISPLAY timezone (IANA name)."""
        return self.timezone_dropdown.currentData() or DEFAULT_TIMEZONE

    def set_loaded_count(self, count: int) -> None:
        self.status_label.setText(f"{count} log{'s' if count != 1 else ''} loaded")

    def set_sync_scroll_enabled(self, enabled: bool) -> None:
        """Disable the sync-scroll toggle (with a tooltip) when fewer than 2
        panels are open — sync only means something across multiple logs.
        """
        self.sync_scroll_button.setEnabled(enabled)
        self.sync_scroll_button.setToolTip(
            "" if enabled else "Requires at least 2 log panels."
        )

    def set_lock_windows_enabled(self, enabled: bool) -> None:
        """Lock mode also needs at least 2 panels to be meaningful."""
        self.lock_windows_button.setEnabled(enabled)
        self.lock_windows_button.setToolTip(
            "" if enabled else "Requires at least 2 log panels."
        )

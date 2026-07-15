"""
EventDetailPanel — bottom panel populated when the investigator clicks any
log table row (Section 6.3.4 Zone 4).

Left side: parsed fields (timestamp, username, IP, status, source type,
correlation count).
Right side: complete raw record as JSON, monospace font, for forensic
verification.

Owned by: Fatima
"""

import json

import pytz
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame

from src.models.data_classes import RawLogEntry
from src.normaliser.timezone_map import utc_offset_label, DEFAULT_TIMEZONE
from PySide6.QtCore import Qt, QEvent  # Added QEvent
from PySide6.QtWidgets import QWidget, QApplication, QMenu  # Added QApplication, QMenu, QAction
from PySide6.QtGui import QAction  # or PyQt6

STATUS_COLORS = {
    "Success": "#57cc99",
    "Failure": "#e06060",
    "Risky": "#e8b840",
    "Warning": "#e8b840",
}


class FieldDisplay(QWidget):
    """One key/value pair in the parsed fields section (e.g. "USERNAME" / "j.smith")."""

    def __init__(self, key: str, value: str, value_color: str | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.key_label = QLabel(key.upper())
        self.key_label.setProperty("class", "FieldKey")
        layout.addWidget(self.key_label)

        self.value_label = QLabel(value)
        self.value_label.setProperty("class", "FieldValue")
        if value_color:
            self.value_label.setStyleSheet(f"font-size: 12px; color: {value_color};")
        layout.addWidget(self.value_label)

    def _restore_header(self):
        """Restores the header text after the 'COPIED' alert."""
        if self._last_entry:
            username = self._last_entry.fields.get("username", self._last_entry.fields.get("account", "--"))
            self.header_label.setText(
                f"EVENT DETAIL — {username} \u00b7 {self._last_entry.fields.get('timestamp', '--')} \u00b7 {self._last_entry.source_label}"
            )

    def set_value(self, value: str, value_color: str | None = None) -> None:
        self.value_label.setText(value)
        if value_color:
            self.value_label.setStyleSheet(f"font-size: 12px; color: {value_color};")


class EventDetailPanel(QWidget):
    """Section 6.3.4 Zone 4 — bottom event detail panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EventDetailPanel")
        # self.setFixedHeight(110)

        # R3 — the detail timestamp is rendered in this display timezone,
        # kept in step with the top-nav dropdown via set_display_timezone().
        self._display_tz = DEFAULT_TIMEZONE
        self._last_entry: RawLogEntry | None = None
        self._last_correlation = 0

        # Themeable — this panel had its own hardcoded colors (a leftover
        # cyan accent and a hardcoded dark-navy JSON box) completely outside
        # the theme system, which is exactly what showed up as "random blue"
        # in a light theme. Defaults match what shipped before theming existed.
        self._theme_accent = "#00c4e8"
        self._theme_text_dim = "#4a5a7a"
        self._theme_bg = "#0f1526"
        self._theme_json_text = "#5a7a9a"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header bar
        self.header_label = QLabel("EVENT DETAIL — no event selected")
        self.header_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {self._theme_accent}; "
            "padding: 6px 10px; text-transform: uppercase;"
        )
        outer.addWidget(self.header_label)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ---- Left: parsed fields -------------------------------------------
        self.fields_container = QHBoxLayout()
        self.fields_container.setContentsMargins(12, 8, 12, 8)
        self.fields_container.setSpacing(16)

        self.field_timestamp = FieldDisplay(
            f"Timestamp ({utc_offset_label(self._display_tz)})", "--", value_color=self._theme_accent
        )
        self.field_username = FieldDisplay("Username", "--")
        self.field_ip = FieldDisplay("IP address", "--")
        self.field_status = FieldDisplay("Status", "--")
        self.field_source = FieldDisplay("Source type", "--")

        for field in (
                self.field_timestamp, self.field_username, self.field_ip,
                self.field_status, self.field_source,
        ):
            self.fields_container.addWidget(field)

        fields_widget = QWidget()
        fields_widget.setLayout(self.fields_container)
        body_layout.addWidget(fields_widget, stretch=1)

        # ---- Right: raw JSON ------------------------------------------------
        self.raw_json_label = QLabel("Select an event to view raw data.")
        self.raw_json_label.setObjectName("RawJsonLabel")
        self.raw_json_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.raw_json_label.customContextMenuRequested.connect(self._show_detail_menu)
        self.raw_json_label.setWordWrap(True)
        self.raw_json_label.setStyleSheet(
            f"background-color: {self._theme_bg}; color: {self._theme_json_text}; font-family: Consolas, monospace; "
            "font-size: 10px; padding: 8px 10px;"
        )
        body_layout.addWidget(self.raw_json_label, stretch=1)

        outer.addWidget(body, stretch=1)
        self.raw_json_label.installEventFilter(self)

    def _show_detail_menu(self, pos):
        menu = QMenu(self)
        copy_all = QAction("Copy full event details", self)

        # The text() method on a QLabel gets the raw JSON string you set in show_event()
        copy_all.triggered.connect(
            lambda: QApplication.clipboard().setText(self.raw_json_label.text())
        )

        menu.addAction(copy_all)
        menu.exec(self.raw_json_label.mapToGlobal(pos))

    def eventFilter(self, obj, event) -> bool:
        if obj == self.raw_json_label and event.type() == QEvent.MouseButtonDblClick:
            # Copy to clipboard immediately
            QApplication.clipboard().setText(self.raw_json_label.text())

            # Optional: Visual feedback to the user
            self.header_label.setText("COPIED TO CLIPBOARD!")

            # Reset header text after 1 second
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: self._restore_header())

            return True  # Event handled

        return super().eventFilter(obj, event)

    def _restore_header(self):
        """Restores the header text after the 'COPIED' alert."""
        if self._last_entry:
            username = self._last_entry.fields.get("username", self._last_entry.fields.get("account", "--"))
            self.header_label.setText(
                f"EVENT DETAIL — {username} \u00b7 {self._last_entry.fields.get('timestamp', '--')} \u00b7 {self._last_entry.source_label}"
            )

    def show_event(self, entry: RawLogEntry, correlation_count: int = 0) -> None:
        """Populate the panel from a clicked RawLogEntry. Field keys below are
        the canonical names produced by LogParser._map_fields().

        correlation_count is accepted (not just dropped) so MainWindow's
        existing call signature doesn't need to change, but it's no longer
        rendered anywhere — see the Correlation-field removal note above.
        """
        self._last_entry = entry
        self._last_correlation = correlation_count

        username = entry.fields.get("username", entry.fields.get("account", "--"))
        ip_address = entry.fields.get("ip_address", entry.fields.get("source_ip", "--"))
        status = entry.fields.get("status", "--")
        status_color = STATUS_COLORS.get(status)

        self.header_label.setText(
            f"EVENT DETAIL — {username} \u00b7 {entry.fields.get('timestamp', '--')} \u00b7 {entry.source_label}"
        )

        # R3 — render the normalized (UTC) timestamp in the current display
        # timezone, matching the log table and every other display element.
        timestamp_display = entry.fields.get("timestamp", "--")
        if entry.normalized_timestamp is not None:
            try:
                tz_obj = pytz.timezone(self._display_tz)
            except pytz.UnknownTimeZoneError:
                tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
            local_dt = entry.normalized_timestamp.utc_datetime.astimezone(tz_obj)
            timestamp_display = local_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        self.field_timestamp.set_value(timestamp_display, value_color=self._theme_accent)
        self.field_username.set_value(username)
        self.field_ip.set_value(ip_address)
        self.field_status.set_value(status, value_color=status_color)
        self.field_source.set_value(entry.source_label)

        raw_payload = dict(entry.fields)
        raw_payload["source"] = entry.source_label
        raw_payload["row_index"] = entry.row_index
        self.raw_json_label.setText(json.dumps(raw_payload))

    def set_display_timezone(self, tz_name: str) -> None:
        """R3 — switch the timestamp field to a new display timezone and
        re-render the currently shown event (if any) so it updates live.
        """
        self._display_tz = tz_name
        self.field_timestamp.key_label.setText(f"TIMESTAMP ({utc_offset_label(tz_name)})")
        if self._last_entry is not None:
            self.show_event(self._last_entry, self._last_correlation)

    def set_theme(self, theme: dict) -> None:
        """Applies a theme switch — this panel previously had its own
        hardcoded colors entirely outside the theme system (see the comment
        in __init__), which is what caused the "random blue in light mode"
        bug. Re-renders the currently shown event so its colors pick up the
        new theme too, not just the static chrome.
        """
        self._theme_accent = theme["accent"]
        self._theme_text_dim = theme["text_secondary"]
        self._theme_bg = theme["bg_app"]
        self._theme_json_text = theme["text_secondary"]

        self.header_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {self._theme_accent}; "
            "padding: 6px 10px; text-transform: uppercase;"
        )
        self.raw_json_label.setStyleSheet(
            f"background-color: {self._theme_bg}; color: {self._theme_json_text}; font-family: Consolas, monospace; "
            "font-size: 10px; padding: 8px 10px;"
        )
        if self._last_entry is not None:
            self.show_event(self._last_entry, self._last_correlation)
        else:
            self.field_timestamp.set_value("--", value_color=self._theme_accent)

    def clear(self) -> None:
        self.header_label.setText("EVENT DETAIL — no event selected")
        self.raw_json_label.setText("Select an event to view raw data.")
        self._last_entry = None
        self._last_correlation = 0
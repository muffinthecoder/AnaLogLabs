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

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame

from src.models.data_classes import RawLogEntry


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

        key_label = QLabel(key.upper())
        key_label.setProperty("class", "FieldKey")
        layout.addWidget(key_label)

        self.value_label = QLabel(value)
        self.value_label.setProperty("class", "FieldValue")
        if value_color:
            self.value_label.setStyleSheet(f"font-size: 11px; color: {value_color};")
        layout.addWidget(self.value_label)

    def set_value(self, value: str, value_color: str | None = None) -> None:
        self.value_label.setText(value)
        if value_color:
            self.value_label.setStyleSheet(f"font-size: 11px; color: {value_color};")


class EventDetailPanel(QWidget):
    """Section 6.3.4 Zone 4 — bottom event detail panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EventDetailPanel")
        self.setFixedHeight(110)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header bar
        self.header_label = QLabel("EVENT DETAIL — no event selected")
        self.header_label.setStyleSheet(
            "font-size: 10px; font-weight: 500; color: #4a5a7a; "
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

        self.field_timestamp = FieldDisplay("Timestamp (UTC+4)", "--", value_color="#00c4e8")
        self.field_username = FieldDisplay("Username", "--")
        self.field_ip = FieldDisplay("IP address", "--")
        self.field_status = FieldDisplay("Status", "--")
        self.field_source = FieldDisplay("Source type", "--")
        self.field_correlation = FieldDisplay("Correlation", "--", value_color="#ffd60a")

        for field in (
            self.field_timestamp, self.field_username, self.field_ip,
            self.field_status, self.field_source, self.field_correlation,
        ):
            self.fields_container.addWidget(field)

        fields_widget = QWidget()
        fields_widget.setLayout(self.fields_container)
        body_layout.addWidget(fields_widget, stretch=1)

        # ---- Right: raw JSON ------------------------------------------------
        self.raw_json_label = QLabel("Select an event to view raw data.")
        self.raw_json_label.setObjectName("RawJsonLabel")
        self.raw_json_label.setWordWrap(True)
        self.raw_json_label.setStyleSheet(
            "background-color: #0f1526; color: #5a7a9a; font-family: Consolas, monospace; "
            "font-size: 9px; padding: 8px 10px;"
        )
        body_layout.addWidget(self.raw_json_label, stretch=1)

        outer.addWidget(body, stretch=1)

    def show_event(self, entry: RawLogEntry, correlation_count: int = 0) -> None:
        """Populate the panel from a clicked RawLogEntry.

        TODO (Hiba/Fatima):
            entry.fields keys are placeholders pending the real field mapper
            (Section 4.7.1 step 3 _map_fields). Update .get() keys below to
            match the canonical field names once finalised.
        """
        username = entry.fields.get("username", entry.fields.get("account", "--"))
        ip_address = entry.fields.get("ip_address", entry.fields.get("source_ip", "--"))
        status = entry.fields.get("status", "--")
        status_color = STATUS_COLORS.get(status)

        self.header_label.setText(
            f"EVENT DETAIL — {username} \u00b7 {entry.fields.get('timestamp', '--')} \u00b7 {entry.source_label}"
        )

        timestamp_display = entry.fields.get("timestamp", "--")
        if entry.normalized_timestamp is not None:
            timestamp_display = entry.normalized_timestamp.utc_datetime.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        self.field_timestamp.set_value(timestamp_display, value_color="#00c4e8")
        self.field_username.set_value(username)
        self.field_ip.set_value(ip_address)
        self.field_status.set_value(status, value_color=status_color)
        self.field_source.set_value(entry.source_label)
        self.field_correlation.set_value(
            f"{correlation_count} related events" if correlation_count else "No correlations",
            value_color="#ffd60a" if correlation_count else "#4a5a7a",
        )

        raw_payload = dict(entry.fields)
        raw_payload["source"] = entry.source_label
        raw_payload["row_index"] = entry.row_index
        self.raw_json_label.setText(json.dumps(raw_payload))

    def clear(self) -> None:
        self.header_label.setText("EVENT DETAIL — no event selected")
        self.raw_json_label.setText("Select an event to view raw data.")

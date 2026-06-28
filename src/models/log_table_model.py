"""
LogTableModel — QAbstractTableModel that backs each LogWindowWidget's QTableView.

Binding to a real Qt model (rather than QTableWidget) means that when Hiba's
LogParser starts returning real RawLogEntry lists (or Pandas DataFrames), this
model only needs its data source swapped — the view, sorting, and highlighting
logic in LogWindowWidget do not need to change.
"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
import pytz

from src.models.data_classes import RawLogEntry


# Row highlight states — must match the color spec in Section 6.3.2 of the
# design document exactly.
COLOR_HIGHLIGHTED_BG = QColor("#1a2a10")  # event within investigation window
COLOR_SELECTED_BG = QColor("#0a1e30")     # currently selected event
COLOR_DEFAULT_TEXT = QColor("#8090b0")    # secondary text
COLOR_HIGHLIGHTED_TEXT = QColor("#c8e89a")
COLOR_SELECTED_TEXT = QColor("#c0e4f8")

STATUS_COLORS = {
    "Success": QColor("#57cc99"),
    "Failure": QColor("#e06060"),
    "Risky": QColor("#e8b840"),
    "Warning": QColor("#e8b840"),
}


class LogTableModel(QAbstractTableModel):
    """Generic table model for displaying RawLogEntry rows.

    Column configuration varies per log source type (Section 6.3.4, Zone 3,
    "Log table" — column configuration can differ per log source).
    """

    def __init__(self, columns: list[str], entries: list[RawLogEntry] | None = None, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._entries: list[RawLogEntry] = entries or []
        self._matched_indices: set[int] = set()
        self._selected_row: int | None = None

        # The timezone the TIMESTAMP column is currently rendered in. This
        # is intentionally separate from each entry's normalized_timestamp
        # (always stored internally as UTC) and from SOURCE_TIMEZONE_
        # ASSIGNMENTS (the timezone a source's raw timestamps are assumed
        # to be AUTHORED in, used only at parse time). This is the
        # investigator-facing DISPLAY timezone — what TopNavBar's dropdown
        # should actually control, separate from the parsing assumption.
        self._display_tz = "Asia/Dubai"

    # -- Qt required overrides -------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._columns[section].upper()
        return str(section)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        entry = self._entries[index.row()]
        column_key = self._columns[index.column()]

        if role == Qt.DisplayRole:
            if column_key == "timestamp":
                return self.format_timestamp(entry)

            # entry.fields is the raw dict mapped by LogParser._map_fields()
            # — every other column displays straight from it since only
            # the timestamp column needs timezone conversion before display.
            return str(entry.fields.get(column_key, ""))

        if role == Qt.BackgroundRole:
            if index.row() == self._selected_row:
                return COLOR_SELECTED_BG
            if index.row() in self._matched_indices:
                return COLOR_HIGHLIGHTED_BG
            return None

        if role == Qt.ForegroundRole:
            if column_key == "status":
                status_value = entry.fields.get("status", "")
                if status_value in STATUS_COLORS:
                    return STATUS_COLORS[status_value]
            if index.row() == self._selected_row:
                return COLOR_SELECTED_TEXT
            if index.row() in self._matched_indices:
                return COLOR_HIGHLIGHTED_TEXT
            return COLOR_DEFAULT_TEXT

        return None

    def format_timestamp(self, entry: RawLogEntry) -> str:
        """Renders the TIMESTAMP column from entry.normalized_timestamp
        (always UTC internally) converted into self._display_tz, rather
        than entry.fields["timestamp"] (the raw original string from the
        source file).

        This is the actual fix for a bug where the table showed identical
        text regardless of which timezone was selected: the raw string
        ("Mar 25 09:30:14") was being displayed verbatim every time, while
        the correctly-converted normalized_timestamp.utc_datetime sat on
        the entry unused. Confirmed during debugging that the backend
        conversion itself was correct (Dubai vs Perth produced UTC values
        4 hours apart, as expected) — only the display layer was wrong.

        Falls back to the raw string when normalized_timestamp is None
        (TimestampNormalizer couldn't parse this row, or hasn't run at
        all) — this is a legitimate fallback, not silently masking a bug,
        since not every row is guaranteed to parse (Section 4.7.1's error
        handling deliberately keeps unparseable rows visible).
        """
        if entry.normalized_timestamp is None:
            return str(entry.fields.get("timestamp", ""))

        try:
            tz_obj = pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone("Asia/Dubai")

        local_dt = entry.normalized_timestamp.utc_datetime.astimezone(tz_obj)
        ms = entry.normalized_timestamp.milliseconds
        return local_dt.strftime("%H:%M:%S") + f".{ms:03d}"

    # -- Public API used by LogWindowWidget -------------------------------------

    def set_display_timezone(self, tz_name: str) -> None:
        """Called by LogWindowWidget.set_timezone_label() (or directly by
        MainWindow) whenever the investigator changes the timezone
        dropdown. Triggers a full repaint so every visible TIMESTAMP cell
        re-renders in the new timezone immediately.
        """
        if self._display_tz == tz_name:
            return
        self._display_tz = tz_name
        if self._entries:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    def load_entries(self, entries: list[RawLogEntry]) -> None:
        """Replace all rows. Called after import (R1) or after a new file load."""
        self.beginResetModel()
        self._entries = entries
        self._matched_indices.clear()
        self._selected_row = None
        self.endResetModel()

    def highlight_matched(self, matched_row_indices: list[int]) -> None:
        """Mark rows as within the active investigation window.

        TODO (R5/R6 — Section 4.7.2 ApplyFilter step 4):
            Called by LogFilter.apply_filter() results, routed through
            LogWindowWidget.highlight_matched().
        """
        self.beginResetModel()
        self._matched_indices = set(matched_row_indices)
        self.endResetModel()

    def set_selected_row(self, row: int | None) -> None:
        """Mark a single row as selected — populates the EventDetailPanel."""
        self.beginResetModel()
        self._selected_row = row
        self.endResetModel()

    def entry_at(self, row: int) -> RawLogEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def get_entries(self) -> list[RawLogEntry]:
        return self._entries

    def column_key_at(self, column: int) -> str | None:
        """Returns the raw field key (e.g. "username", "ip_address") for a
        given column index — NOT the upper-cased display header text that
        headerData() returns. Needed so callers like LogWindowWidget can
        apply per-field rules (e.g. a minimum width for "username") keyed
        on the same canonical field names log_parser.py's _map_fields()
        produces, without having to lower-case/guess from the display text.
        """
        if 0 <= column < len(self._columns):
            return self._columns[column]
        return None
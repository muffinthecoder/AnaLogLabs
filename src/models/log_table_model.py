"""
LogTableModel — QAbstractTableModel that backs each LogWindowWidget's QTableView.

Binding to a real Qt model (rather than QTableWidget) means that when Hiba's
LogParser starts returning real RawLogEntry lists (or Pandas DataFrames), this
model only needs its data source swapped — the view, sorting, and highlighting
logic in LogWindowWidget do not need to change.
"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

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

    # -- Qt required overrides -------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section].upper()
        return str(section)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        entry = self._entries[index.row()]
        column_key = self._columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            # For timestamp columns, always show the normalized UTC datetime
            # if available. This ensures WLC "Mar 25 09:30:14", MUPC
            # "2026-03-25T02:59:59.638" and Azure "2026-03-25T03:24:52Z" all
            # display in the same consistent format regardless of source.
            if column_key == "timestamp" and entry.normalized_timestamp is not None:
                return entry.normalized_timestamp.utc_datetime.strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )[:-3]  # trim to milliseconds: "2026-03-25 05:30:14.000"
            return str(entry.fields.get(column_key, ""))

        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() == self._selected_row:
                return COLOR_SELECTED_BG
            if index.row() in self._matched_indices:
                return COLOR_HIGHLIGHTED_BG
            return None

        if role == Qt.ItemDataRole.ForegroundRole:
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

    # -- Public API used by LogWindowWidget -------------------------------------

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

    def column_key_at(self, index: int) -> str:
        """Returns the column key (field name) at the given index."""
        if 0 <= index < len(self._columns):
            return self._columns[index].lower()
        return ""

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
            # TODO (Hiba — Section 3.4 Data Structures and Operations):
            #   entry.fields is the raw dict mapped by LogParser. Column keys
            #   here are placeholders ("timestamp", "username", "ip_address",
            #   "status") — confirm exact field names once the field mapper
            #   (_map_fields in Section 4.7.1) is implemented.
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

"""
LogTableModel — QAbstractTableModel that backs each LogWindowWidget's QTableView.

Binding to a real Qt model (rather than QTableWidget) means that when Hiba's
LogParser starts returning real RawLogEntry lists (or Pandas DataFrames), this
model only needs its data source swapped — the view, sorting, and highlighting
logic in LogWindowWidget do not need to change.
"""

from datetime import datetime, timedelta

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

# R5 / Section 4.2 — flag markers. Flags live in SHARED app state as a list of
# absolute-time "anchors"; a row is flagged if its true (UTC) time falls within
# FLAG_WINDOW of any anchor. Because every file's model tests the same anchors,
# a flag set in one window automatically shows on every correlated event across
# all files (±30s), and always renders identically regardless of focus.
COLOR_FLAG_BG = QColor("#3a2e0a")
FLAG_GLYPH = "⚑"

# ±30 seconds cross-file correlation window (Section 4.2 / 6).
FLAG_WINDOW = timedelta(seconds=30)

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

        # Section 4.2 — shared flag anchors (absolute UTC datetimes). A row is
        # flagged when its true time is within FLAG_WINDOW of any anchor.
        self._flag_anchors: list[datetime] = []

        # The timezone the TIMESTAMP column is currently rendered in. This
        # is intentionally separate from each entry's normalized_timestamp
        # (always stored internally as UTC) and from SOURCE_TIMEZONE_
        # ASSIGNMENTS (the timezone a source's raw timestamps are assumed
        # to be AUTHORED in, used only at parse time). This is the
        # investigator-facing DISPLAY timezone — what TopNavBar's dropdown
        # should actually control, separate from the parsing assumption.
        # Defaults to Perth (the app-wide default, R2/R3); MainWindow sets the
        # real selection on every panel as soon as it's created.
        self._display_tz = "Australia/Perth"

        # Themeable row colors — instance state so different open panels
        # could theoretically use different themes, though in practice
        # MainWindow applies the same theme to all of them. Defaults match
        # the module constants above exactly, so nothing changes unless
        # set_theme() is explicitly called. This is a color-only override —
        # it does not touch which rows get flagged/matched/selected, only
        # what color is RETURNED for a row already in one of those states.
        self._color_highlighted_bg = COLOR_HIGHLIGHTED_BG
        self._color_highlighted_text = COLOR_HIGHLIGHTED_TEXT
        self._color_selected_bg = COLOR_SELECTED_BG
        self._color_selected_text = COLOR_SELECTED_TEXT
        self._color_default_text = COLOR_DEFAULT_TEXT
        self._color_flag_bg = COLOR_FLAG_BG
        self._color_flag_text = QColor("#ffd60a")

    def set_theme(self, theme: dict) -> None:
        """Swaps the color-only instance state above for theme-provided
        values. Does not read or change _matched_indices, _selected_row,
        _flag_anchors, _display_tz, or any timestamp/filter logic — those
        are untouched by this method entirely.
        """
        self._color_highlighted_bg = QColor(theme["row_highlighted_bg"])
        self._color_highlighted_text = QColor(theme["row_highlighted_text"])
        self._color_selected_bg = QColor(theme["row_selected_bg"])
        self._color_selected_text = QColor(theme["row_selected_text"])
        self._color_default_text = QColor(theme["row_default_text"])
        self._color_flag_bg = QColor(theme["row_flag_bg"])
        self._color_flag_text = QColor(theme["row_flag_text"])
        # Notify the view so already-visible rows repaint with the new colors.
        if self.rowCount() > 0:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.BackgroundRole, Qt.ForegroundRole])

    # -- Qt required overrides -------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            key = self._columns[section]
            if key == "original_log_time":
                return "ORIGINAL LOG TIME"
            if key == "timestamp":
                return "CONVERTED TIMESTAMP"
            return key.upper()
        return str(section)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        entry = self._entries[index.row()]
        column_key = self._columns[index.column()]

        if role == Qt.DisplayRole:
            if column_key == "original_log_time":
                # The raw, unconverted timestamp exactly as it appeared in the
                # source file (e.g. "2026-03-25T01:05:02Z").
                return entry.raw_timestamp or str(entry.fields.get("timestamp", ""))

            if column_key == "timestamp":
                # The CONVERTED TIMESTAMP — rendered in the display timezone.
                # Prefix with a flag glyph so a flagged moment is spottable
                # even when the row background is subtle.
                ts_text = self.format_timestamp(entry)
                if self._is_flagged_row(index.row()):
                    return f"{FLAG_GLYPH} {ts_text}"
                return ts_text

            # entry.fields is the raw dict mapped by LogParser._map_fields()
            # — every other column displays straight from it since only
            # the timestamp column needs timezone conversion before display.
            return str(entry.fields.get(column_key, ""))

        if role == Qt.BackgroundRole:
            # Flags sit ABOVE selection/highlight so a flagged row stays
            # visually distinct regardless of the current filter or selection.
            if self._is_flagged_row(index.row()):
                return self._color_flag_bg
            if index.row() == self._selected_row:
                return self._color_selected_bg
            if index.row() in self._matched_indices:
                return self._color_highlighted_bg
            return None

        if role == Qt.ForegroundRole:
            # Highlight the flag glyph / timestamp of a flagged row.
            if column_key == "timestamp" and self._is_flagged_row(index.row()):
                return self._color_flag_text
            if column_key == "status":
                status_value = entry.fields.get("status", "")
                if status_value in STATUS_COLORS:
                    return STATUS_COLORS[status_value]
            if index.row() == self._selected_row:
                return self._color_selected_text
            if index.row() in self._matched_indices:
                return self._color_highlighted_text
            return self._color_default_text

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
            tz_obj = pytz.timezone("Australia/Perth")

        local_dt = entry.normalized_timestamp.utc_datetime.astimezone(tz_obj)
        ms = entry.normalized_timestamp.milliseconds
        return local_dt.strftime("%H:%M:%S") + f".{ms:03d}"

    def full_display_datetime(self, entry: RawLogEntry) -> str:
        """Full DATE + time of an entry in the display timezone, e.g.
        "2026-03-25 09:05:02.000" — used when the investigator copies a row so
        the pasted value carries a date (the CONVERTED TIMESTAMP column shows
        time only) and drops straight into the time-range boxes.
        """
        if entry.normalized_timestamp is None:
            return str(entry.fields.get("timestamp", ""))
        try:
            tz_obj = pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone("Australia/Perth")
        local_dt = entry.normalized_timestamp.utc_datetime.astimezone(tz_obj)
        ms = entry.normalized_timestamp.milliseconds
        return local_dt.strftime("%Y-%m-%d %H:%M:%S") + f".{ms:03d}"

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
        # Flag anchors are shared app state (not per-load), so they are NOT
        # cleared here — a reloaded/re-sorted file keeps showing flags for any
        # of its events that still fall within the active ±30s windows.
        self.endResetModel()

    def highlight_matched(self, matched_row_indices: list[int]) -> None:
        """Mark rows (by their CURRENT display position, not original file row
        index) as within the active investigation window. Called from
        MainWindow._apply_filter_highlighting with positions computed against
        this model's current sort order. This ONLY highlights — it never flags.
        """
        self.beginResetModel()
        self._matched_indices = set(matched_row_indices)
        self.endResetModel()

    # -- Section 4.2 flags (anchor-based, shared across files) ------------------

    def _entry_time(self, entry: RawLogEntry) -> datetime | None:
        nts = entry.normalized_timestamp
        if nts is None:
            return None
        return nts.utc_datetime + timedelta(milliseconds=nts.milliseconds)

    def _is_flagged_row(self, row: int) -> bool:
        if not self._flag_anchors or not (0 <= row < len(self._entries)):
            return False
        t = self._entry_time(self._entries[row])
        if t is None:
            return False
        return any(abs((t - a).total_seconds()) <= FLAG_WINDOW.total_seconds()
                   for a in self._flag_anchors)

    def set_flag_anchors(self, anchors: list[datetime]) -> None:
        """Replaces the shared set of flag anchors and repaints. Called by
        MainWindow whenever any flag is added/removed anywhere.
        """
        self._flag_anchors = list(anchors)
        self._repaint_all()

    def flagged_count(self) -> int:
        """Number of THIS file's events that fall within ±30s of any anchor —
        summed across all models by MainWindow for the Flagged stat."""
        return sum(1 for r in range(len(self._entries)) if self._is_flagged_row(r))

    def entry_time_for_row(self, row: int) -> datetime | None:
        """Public access to a row's true (UTC, ms-inclusive) time — used by
        MainWindow to add/remove flag anchors from a clicked row."""
        if 0 <= row < len(self._entries):
            return self._entry_time(self._entries[row])
        return None

    # -- Sorting (Section 3 / 4.3) ---------------------------------------------

    def sort_by_time(self, descending: bool = False) -> None:
        """Re-order rows into true chronological order (post-normalisation).
        Unparseable rows (no normalized timestamp) always sort to the end,
        regardless of direction. Flags follow the rows automatically since
        they're keyed on absolute time, not row index.
        """
        valid = [e for e in self._entries if e.normalized_timestamp is not None]
        invalid = [e for e in self._entries if e.normalized_timestamp is None]
        valid.sort(key=lambda e: e.normalized_timestamp.utc_datetime, reverse=descending)

        self.beginResetModel()
        self._entries = valid + invalid
        # Row-index-based selection/highlight no longer maps to the same entry.
        self._selected_row = None
        self._matched_indices.clear()
        self.endResetModel()

    def _repaint_all(self) -> None:
        if self._entries:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right)

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
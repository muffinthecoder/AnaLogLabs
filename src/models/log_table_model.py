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

        # Phase 5 — matched/highlighted state is tracked by entry IDENTITY
        # (id()), not by row position. Before this, highlight_matched()
        # took a list[int] that MainWindow built from LogFilter.
        # get_matched_row_indices(), i.e. each entry's *original file*
        # row_index (Section 4.7.1 order) — and stored those ints as if
        # they were current row POSITIONS in this model. That happened to
        # look correct immediately after a fresh load (position == file
        # order at that moment), but the moment the table is re-sorted
        # (Phase 4) — or if a filter is applied while some other order is
        # already active — row_index no longer has any relationship to
        # where that entry actually sits on screen, so the highlight
        # painted the wrong rows entirely. Keying on id() instead means
        # "is this entry matched" no longer depends on position at all, so
        # nothing goes stale when the position changes.
        self._matched_ids: set[int] = set()
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
            key = self._columns[section]
            # Give the virtual column a human-readable header rather than
            # the internal snake_case key name.
            if key == "original_timestamp":
                return "ORIGINAL LOG TIME"
            return key.upper()
        return str(section)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        entry = self._entries[index.row()]
        column_key = self._columns[index.column()]

        if role == Qt.DisplayRole:
            # "original_timestamp" is a virtual column injected by
            # LogWindowWidget (not a real key in entry.fields) — shows the
            # raw unmodified timestamp string from the source file so
            # investigators can always compare the display-tz-converted value
            # against what was actually recorded.
            if column_key == "original_timestamp":
                return self.format_raw_timestamp(entry)

            if column_key == "timestamp":
                return self.format_timestamp(entry)

            # entry.fields is the raw dict mapped by LogParser._map_fields()
            # — every other column displays straight from it since only
            # the timestamp column needs timezone conversion before display.
            return str(entry.fields.get(column_key, ""))

        if role == Qt.BackgroundRole:
            if index.row() == self._selected_row:
                return COLOR_SELECTED_BG
            # Phase 5 — identity check, not a row-position set membership
            # test, so this stays correct regardless of sort order.
            if id(entry) in self._matched_ids:
                return COLOR_HIGHLIGHTED_BG
            return None

        if role == Qt.ForegroundRole:
            if column_key == "status":
                status_value = entry.fields.get("status", "")
                if status_value in STATUS_COLORS:
                    return STATUS_COLORS[status_value]
            if index.row() == self._selected_row:
                return COLOR_SELECTED_TEXT
            if id(entry) in self._matched_ids:
                return COLOR_HIGHLIGHTED_TEXT
            return COLOR_DEFAULT_TEXT

        return None

    def format_raw_timestamp(self, entry: RawLogEntry) -> str:
        """Returns the original timestamp string exactly as it appeared in the
        source log file — no timezone conversion, no reformatting.  Used by
        the "Original Log Time" column so investigators can always compare the
        display-timezone-converted value against what was actually recorded.

        Falls back to entry.fields["timestamp"] if raw_timestamp is empty (e.g.
        when a mock entry was constructed without setting raw_timestamp), then
        to the empty string so the cell is never None.
        """
        if entry.raw_timestamp and entry.raw_timestamp.strip():
            return entry.raw_timestamp
        return str(entry.fields.get("timestamp", ""))

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

        Includes the full date (not just HH:MM:SS.mmm) — this is what
        Phase 2 (copy/paste) depends on: LogWindowWidget's copy action
        copies this exact string to the clipboard, and it needs to be
        pasteable directly into TimeFrameSelector's Start/End fields
        (which expect "YYYY-MM-DD HH:MM:SS.mmm") without the investigator
        having to manually add today's date back in.

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
        self._matched_ids.clear()
        self._selected_row = None
        self.endResetModel()

    def highlight_matched(self, matched_entries: list[RawLogEntry]) -> None:
        """Mark entries as within the active investigation window.

        Phase 5 — takes the matched RawLogEntry objects themselves, not a
        list of row indices. The previous version took list[int] built by
        MainWindow from LogFilter.get_matched_row_indices(), which is each
        entry's `row_index` — its position in the ORIGINAL file/import
        order (Section 4.7.1) — and treated those ints as current row
        POSITIONS in this model. That's only ever true immediately after a
        fresh load; the instant the model is re-sorted (Phase 4), or if a
        filter is (re-)applied while a non-default sort is already active,
        row_index no longer lines up with where that entry is actually
        displayed, so the wrong rows got highlighted. Storing by id()
        instead means membership no longer depends on position at all.
        """
        self.beginResetModel()
        self._matched_ids = {id(e) for e in matched_entries}
        self.endResetModel()

    def set_selected_row(self, row: int | None) -> None:
        """Mark a single row as selected — populates the EventDetailPanel."""
        self.beginResetModel()
        self._selected_row = row
        self.endResetModel()

    def sort_by_timestamp(self, ascending: bool = True) -> None:
        """Phase 4 — global sort, keyed on normalized_timestamp (UTC
        datetime + milliseconds), so ordering is correct regardless of
        display timezone or the raw/original timestamp string.

        Preserves the current selection across the re-sort by remapping it
        via entry IDENTITY (Python's id()) rather than by row index — row
        index is exactly what changes when we sort, so the old
        _selected_row integer would otherwise point at the wrong row the
        instant the order changes. This is the same principle Phase 5
        applies to highlighting more generally (see LogTableModel.
        highlight_matched()): matched state is stored by id() there too,
        so — unlike selection — it doesn't need any remapping here at all;
        it was never expressed in terms of row position to begin with.

        Entries with no normalized_timestamp (TimestampNormalizer couldn't
        parse that row, or hasn't run yet) are always placed at the end,
        regardless of ascending/descending, rather than sorting them to
        whichever end the current direction happens to put them — an
        unparseable row doesn't have a "newest" or "oldest" position, so it
        shouldn't jump from the bottom to the top just because the
        direction was flipped.
        """
        selected_id = None
        if self._selected_row is not None and 0 <= self._selected_row < len(self._entries):
            selected_id = id(self._entries[self._selected_row])

        parsed = [e for e in self._entries if e.normalized_timestamp is not None]
        unparsed = [e for e in self._entries if e.normalized_timestamp is None]
        parsed.sort(
            key=lambda e: (e.normalized_timestamp.utc_datetime, e.normalized_timestamp.milliseconds),
            reverse=not ascending,
        )

        self.beginResetModel()
        self._entries = parsed + unparsed
        # _matched_ids is intentionally left untouched — see docstring above.
        self._selected_row = None
        if selected_id is not None:
            for i, e in enumerate(self._entries):
                if id(e) == selected_id:
                    self._selected_row = i
                    break
        self.endResetModel()

    def entry_at(self, row: int) -> RawLogEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def first_matched_row(self) -> int | None:
        """Returns the row POSITION (in current display/sort order) of the
        first matched entry, or None if nothing is currently matched.

        Used by LogWindowWidget.scroll_to_first_match() so investigators
        land on the actual topmost highlighted row after applying a filter,
        rather than having to scroll and hunt for it manually. Iterates
        self._entries in display order (not the matched-ids set itself,
        which has no order) so "first" always means "topmost as currently
        sorted" — e.g. earliest chronologically under Oldest→Newest,
        latest under Newest→Oldest — consistent with whatever direction
        Phase 4's sort control is set to at the time.
        """
        if not self._matched_ids:
            return None
        for row, entry in enumerate(self._entries):
            if id(entry) in self._matched_ids:
                return row
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
"""
timeline_widget.py — implements Section 6.3.4 Zone 5 subsection 2 (Timeline)
using PyQtGraph, plus the event-linking visualization concept referenced in
Minal's task list.

Per the design doc: "Multi-row horizontal timeline. One row per log source,
each event a small colored block at its timestamp position."

Event-linking concept:
    When two or more events across different sources are part of the same
    CorrelatedEvent (Section 4.7.4, Fatima's Week 2 EventCorrelator), this
    widget draws a thin connecting line between their points across rows —
    e.g. j.smith's sign-in failure on Interactive_signin linked to the
    matching Cmd exec on MUPC_events at the same moment. This is the visual
    proof-of-concept for that feature; it renders from whatever correlation
    data it's given (currently mock_data.MOCK_CORRELATED_EVENTS, since the
    real EventCorrelator does not exist yet) and requires no changes once
    real CorrelatedEvent objects are wired in (Section 4.7.4 still TODO).

Owned by: Minal
Initial code provided by: Fatima
Consumed by: src/ui/investigation_dashboard.py (replaces the QLabel
placeholder built by Fatima in _build_timeline_section()).
"""

from datetime import datetime

import pyqtgraph as pg
import pytz
from PySide6.QtCore import Qt, Signal

from src.models.data_classes import RawLogEntry
from src.normaliser.timezone_map import get_utc_offset_seconds

# Vertical spacing between source rows, in plot Y units. Rows are simply
# integers (0, 1, 2, ...) — the axis below replaces the numeric ticks with
# source labels so the row index itself is never shown to the investigator.
ROW_HEIGHT = 1.0

POINT_SIZE = 8
LINK_LINE_COLOR = "#ffd60a"
LINK_LINE_ALPHA = 140


class TimelineWidget(pg.PlotWidget):
    """Section 6.3.4 Zone 5 subsection 2 — multi-row horizontal timeline
    with cross-source event-linking overlays.

    Data flow:
        InvestigationDashboard.load_entries() -> self.set_entries()
        InvestigationDashboard.set_correlated_events() -> self.set_links()
        Clicking a point -> point_clicked(timestamp_iso_str), which
            InvestigationDashboard re-emits as correlated_event_clicked so
            MainWindow can scroll all open log panels to that moment,
            exactly like clicking a CorrelatedEventItem already does.
    """

    point_clicked = Signal(str)  # ISO-format UTC timestamp string

    def __init__(self, parent=None, display_tz: str = "Asia/Dubai"):
        # No log data is loaded yet at construction time, so there is no
        # real-data reference date to anchor a DST-observing zone's offset
        # to — get_utc_offset_seconds() falls back to "now" here, same as
        # before Phase 1. Once set_entries()/set_display_timezone() run with
        # real data, _rebuild_axis() recomputes against that data's own
        # dates instead.
        self._display_tz = display_tz

        # DateAxisItem's utcOffset is "seconds to ADD to a UTC timestamp's
        # offset", applied with its sign inverted internally — verified
        # empirically (Dubai/UTC+4 needs utcOffset=-14400, not +14400) since
        # this is a known point of confusion in PyQtGraph's own docs/issues.
        offset_seconds = -get_utc_offset_seconds(display_tz)
        super().__init__(parent, axisItems={"bottom": pg.DateAxisItem(utcOffset=offset_seconds)})
        self.setBackground(None)

        self.showGrid(x=False, y=False)
        self.getAxis("bottom").setTextPen(pg.mkPen("#4a5a7a"))
        self.getAxis("left").setTextPen(pg.mkPen("#4a5a7a"))
        self.getAxis("left").setStyle(tickLength=0)
        self.getAxis("bottom").setStyle(tickLength=0)
        self.getPlotItem().setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        self.setFixedHeight(110)

        # source_label -> row index (0-based, in the order sources were
        # first added — stable so a source's row doesn't jump around as
        # other sources are opened/closed elsewhere).
        self._row_for_source: dict[str, int] = {}

        # source_label -> ScatterPlotItem currently on the plot.
        self._scatter_items: dict[str, pg.ScatterPlotItem] = {}

        # source_label -> list[RawLogEntry], as given to set_entries().
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}

        # Kept so a click on a scatter point can be mapped back to the
        # RawLogEntry it represents (for point_clicked's timestamp string,
        # and as the natural extension point if a future requirement needs
        # the full entry rather than just its timestamp).
        self._entry_lookup: dict[tuple[str, float], RawLogEntry] = {}

        # Correlation link lines currently drawn, kept so clear_links() can
        # remove exactly these items without disturbing the scatter points.
        self._link_items: list[pg.PlotDataItem] = []

        self._show_empty_state()

    def _earliest_reference_dt(self) -> datetime | None:
        """Returns the earliest normalized UTC timestamp across all
        currently loaded entries, used to anchor a DST-observing zone's
        offset to the actual period the loaded data falls in — NOT to
        "today", which was the source of the pre-Phase-1 bug (Perth,
        Singapore, and Dubai never observe DST, so this distinction was
        invisible until Adelaide/Melbourne/Sydney were added).

        Returns None if no valid entries are loaded yet (e.g. at startup,
        or immediately after clear_timeline()) — callers fall back to "now"
        in that case via get_utc_offset_seconds()'s own default.
        """
        all_timestamps = [
            entry.normalized_timestamp.utc_datetime
            for entries in self._entries_by_source.values()
            for entry in entries
            if entry.normalized_timestamp is not None
        ]
        return min(all_timestamps) if all_timestamps else None

    def _rebuild_axis(self) -> None:
        """Rebuilds the bottom axis using the current self._display_tz,
        with its UTC offset computed against the loaded data's own
        earliest timestamp rather than "now" — this is the actual DST fix.
        Called whenever the display timezone changes AND whenever new
        entries are loaded (loading new data can change which reference
        date is available, which can change a DST zone's correct offset).
        """
        reference_dt = self._earliest_reference_dt()
        offset_seconds = -get_utc_offset_seconds(self._display_tz, reference_dt)
        new_axis = pg.DateAxisItem(utcOffset=offset_seconds)
        self.getPlotItem().setAxisItems({"bottom": new_axis})
        new_axis.setTextPen(pg.mkPen("#4a5a7a"))
        new_axis.setStyle(tickLength=0)

    def set_display_timezone(self, tz_name: str) -> None:
        """Called by MainWindow._on_timezone_changed() so the timeline's
        x-axis labels switch timezone along with every other display
        element (LogWindowWidget's timezone badge, EventDetailPanel, etc).
        Rebuilds the bottom axis in place rather than recreating the whole
        PlotWidget, so existing scatter/link items are left untouched.
        """
        self._display_tz = tz_name
        self._rebuild_axis()

    # -- Public API --------------------------------------------------------------

    def set_entries(self, entries_by_source: dict[str, list[RawLogEntry]], colors: dict[str, str]) -> None:
        """Replaces all timeline rows and points. Called whenever a log is
        imported or a panel is closed — mirrors
        ActivityFrequencyChart.set_entries() so InvestigationDashboard can
        drive both charts from the same call site.
        """
        self._entries_by_source = entries_by_source
        # Recompute the axis offset before redrawing rows — newly loaded
        # data can change the earliest available reference date, which can
        # change a DST-observing zone's correct offset (see _rebuild_axis).
        self._rebuild_axis()
        self._redraw_rows(colors)

    def set_links(self, correlated_events: list[dict], display_tz: str = "Asia/Dubai") -> None:
        """Event-linking visualization — draws a connecting line between
        every pair of entries that share a correlated event's timestamp.

        Args:
            correlated_events: list of dicts shaped like
                mock_data.MOCK_CORRELATED_EVENTS — {"description", "time",
                "severity"}. "time" is an "HH:MM" string in the
                investigator's currently selected DISPLAY timezone (the
                same one TopNavBar's timezone dropdown controls), matching
                what mock_data's entry.fields["timestamp"] shows — NOT UTC.
                entry.normalized_timestamp.utc_datetime is always UTC
                regardless of display timezone, so it must be converted
                back to display_tz before comparing HH:MM strings, or every
                lookup silently fails whenever display_tz isn't UTC+0 (this
                was caught during testing: Dubai is UTC+4, so "08:07" local
                never matched "04:07" UTC until this conversion was added).
            display_tz: IANA timezone name. Defaults to "Asia/Dubai" to
                match mock_data's scenario; MainWindow should pass
                TimeFrameSelector's current .timezone here once real
                CorrelatedEvent data replaces the mock list.

        TODO (Fatima — Section 4.7.4 Correlate):
            Once EventCorrelator exists, replace this mock "match by HH:MM
            string" lookup with real CorrelatedEvent.entries tuples — those
            already carry direct references to the exact RawLogEntry
            objects involved, which removes the timestamp-string matching
            (and the timezone conversion it requires) entirely.
        """
        self._clear_links()

        drawn_signatures = set()
        for event in correlated_events:
            matched_points = self._find_points_near_time(event.get("time", ""), display_tz)
            if len(matched_points) < 2:
                continue

            # mock_data.MOCK_CORRELATED_EVENTS currently has several entries
            # sharing the same minute-level "time" string, which would
            # otherwise produce several identical, fully-overlapping lines
            # for what is visually a single link. A real CorrelatedEvent
            # (Section 4.7.4) carries its own distinct entries tuple per
            # group, so this dedup step becomes unnecessary — and harmless
            # to leave in — once that replaces the mock lookup.
            signature = tuple(sorted((label, round(x, 3)) for label, x, _ in matched_points))
            if signature in drawn_signatures:
                continue
            drawn_signatures.add(signature)

            self._draw_link(matched_points, severity=event.get("severity", "timestamp"))

    def clear_timeline(self) -> None:
        """Called when the last log panel is closed."""
        self._entries_by_source = {}
        self._row_for_source = {}
        self.clear()
        self._scatter_items.clear()
        self._entry_lookup.clear()
        self._link_items.clear()
        self._show_empty_state()

    # -- Internal: row layout + drawing -----------------------------------------

    def _redraw_rows(self, colors: dict[str, str]) -> None:
        self.clear()
        self._scatter_items.clear()
        self._entry_lookup.clear()
        self._link_items.clear()

        valid_sources = [
            label for label, entries in self._entries_by_source.items()
            if any(e.normalized_timestamp is not None for e in entries)
        ]
        if not valid_sources:
            self._show_empty_state()
            return

        # Assign row indices for any source seen for the first time, while
        # leaving existing sources' rows untouched — this keeps a source's
        # row stable across repeated imports in the same session rather
        # than reshuffling every time a new log is added.
        for source_label in sorted(valid_sources):
            if source_label not in self._row_for_source:
                self._row_for_source[source_label] = len(self._row_for_source)

        for source_label in valid_sources:
            entries = [e for e in self._entries_by_source[source_label] if e.normalized_timestamp is not None]
            row = self._row_for_source[source_label]
            color = colors.get(source_label, "#4A90D9")

            xs = [e.normalized_timestamp.utc_datetime.timestamp() for e in entries]
            ys = [row] * len(xs)

            scatter = pg.ScatterPlotItem(
                x=xs, y=ys, size=POINT_SIZE, brush=pg.mkBrush(color), pen=pg.mkPen(None),
            )
            scatter.sigClicked.connect(self._on_scatter_clicked)
            self.addItem(scatter)
            self._scatter_items[source_label] = scatter

            for entry, x in zip(entries, xs):
                self._entry_lookup[(source_label, x)] = entry

        # Y-axis: replace numeric row indices with source labels so the
        # investigator sees source names, not row numbers.
        self.getAxis("left").setTicks([[
            (row, label) for label, row in self._row_for_source.items()
        ]])
        self.getViewBox().setYRange(-0.5, len(self._row_for_source) - 0.5, padding=0.1)
        self.getViewBox().autoRange()
        # autoRange() re-fits both axes from the scatter data, including Y —
        # immediately re-pin Y so row spacing stays fixed regardless of how
        # many points are on the busiest row.
        self.getViewBox().setYRange(-0.5, len(self._row_for_source) - 0.5, padding=0.1)

    def _find_points_near_time(self, time_str: str, display_tz: str) -> list[tuple[str, float, float]]:
        """Finds (source_label, x, y) for every plotted point whose
        HH:MM — AS SHOWN IN display_tz, not raw UTC — matches time_str.
        Used by set_links() until real CorrelatedEvent objects replace
        this mock lookup.
        """
        try:
            tz_obj = pytz.timezone(display_tz)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone("Asia/Dubai")

        matches = []
        for (source_label, x), entry in self._entry_lookup.items():
            utc_ts = entry.normalized_timestamp.utc_datetime
            local_ts = utc_ts.astimezone(tz_obj)
            if local_ts.strftime("%H:%M") == time_str:
                row = self._row_for_source.get(source_label)
                if row is not None:
                    matches.append((source_label, x, float(row)))
        return matches

    def _draw_link(self, points: list[tuple[str, float, float]], severity: str) -> None:
        """Draws a polyline connecting every matched point for one
        correlated event, ordered left-to-right by timestamp so the line
        reads naturally rather than zig-zagging.
        """
        points_sorted = sorted(points, key=lambda p: p[1])
        xs = [p[1] for p in points_sorted]
        ys = [p[2] for p in points_sorted]

        color = "#e06060" if severity == "attribute" else LINK_LINE_COLOR
        pen = pg.mkPen(color, width=1, style=Qt.DotLine)
        line = pg.PlotDataItem(xs, ys, pen=pen)
        self.addItem(line)
        self._link_items.append(line)

    def _clear_links(self) -> None:
        for item in self._link_items:
            self.removeItem(item)
        self._link_items.clear()

    def _on_scatter_clicked(self, scatter_item, spot_items) -> None:
        """Section 6.3.4 Zone 5: clicking any timeline point should behave
        like clicking a CorrelatedEventItem — scroll all open log panels to
        that moment. Re-emitted up through InvestigationDashboard so
        MainWindow only needs one connection point for both interactions.
        """
        if not spot_items:
            return
        x, y = spot_items[0].pos()
        for (source_label, entry_x), entry in self._entry_lookup.items():
            if abs(entry_x - x) < 1e-6:
                self.point_clicked.emit(entry.normalized_timestamp.utc_datetime.isoformat())
                return

    def _show_empty_state(self) -> None:
        text = pg.TextItem("No log data loaded", color="#4a5a7a", anchor=(0.5, 0.5))
        self.addItem(text)
        self.getViewBox().autoRange()
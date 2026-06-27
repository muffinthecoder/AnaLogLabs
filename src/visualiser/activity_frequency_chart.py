"""
activity_frequency_chart.py — implements Section 6.3.4 Zone 5 subsection 1
(Activity Frequency Chart) using PyQtGraph.

Per the design doc: "Bars within the investigation window render at full
opacity in source color; bars outside are dimmed. X-axis shows start,
midpoint, end of investigation window."

Owned by: Minal
Initial code provided by: Fatima
Consumed by: src/ui/investigation_dashboard.py (replaces the QLabel
placeholder built by Fatima in _build_activity_chart_section()).
"""

from datetime import datetime, timedelta

import pyqtgraph as pg
from PySide6.QtCore import Qt

from src.models.data_classes import RawLogEntry

# Bars outside the investigation window are drawn at this opacity instead of
# full color — matches the "dimmed" requirement in Section 6.3.4 Zone 5.
DIMMED_ALPHA = 60
FULL_ALPHA = 230

# Number of time buckets shown across the full loaded range. More buckets =
# finer-grained activity resolution but thinner/more crowded bars; 24 is a
# reasonable default for the dashboard's fixed 220px width.
DEFAULT_BUCKET_COUNT = 24


class ActivityFrequencyChart(pg.PlotWidget):
    """Section 6.3.4 Zone 5 subsection 1 — bucketed event-count bar chart,
    one bar series per log source, colored to match that source's tab/dot
    color elsewhere in the UI.

    Data flow:
        InvestigationDashboard.load_entries() -> self.set_entries()
        InvestigationDashboard.refresh() (after ApplyFilter)
            -> self.set_investigation_window()

    TimestampNormalizer dependency:
        Bucketing relies entirely on entry.normalized_timestamp.utc_datetime.
        Entries with normalized_timestamp=None (rows TimestampNormalizer
        could not parse, or any row before Hiba's normalizer is wired in)
        are silently excluded from the chart — they still count in
        SESSION STATS totals (Pooja/Fatima's territory), just not here.
    """

    def __init__(self, parent=None):
        super().__init__(parent, axisItems={"bottom": pg.DateAxisItem(utcOffset=0)})
        self.setBackground(None)  # transparent — let the dashboard's own
        # dark panel background (set in styles.py) show through instead of
        # PyQtGraph's default white.

        self.showGrid(x=False, y=True, alpha=0.15)
        self.getAxis("left").setStyle(tickLength=0)
        self.getAxis("bottom").setStyle(tickLength=0)
        self.getAxis("left").setTextPen(pg.mkPen("#4a5a7a"))
        self.getAxis("bottom").setTextPen(pg.mkPen("#4a5a7a"))
        self.getPlotItem().setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        self.setFixedHeight(90)

        # source_label -> BarGraphItem currently on the plot. Rebuilt
        # wholesale on every set_entries()/set_investigation_window() call
        # rather than mutated in place — PyQtGraph's BarGraphItem doesn't
        # support updating x/height/brush incrementally without recreating
        # the underlying graphics primitives anyway, and the data volumes
        # here (tens of buckets, not thousands) make that approach not worth
        # extra bookkeeping.
        self._bar_items: dict[str, pg.BarGraphItem] = {}

        # source_label -> list[RawLogEntry], set via set_entries().
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}

        # source_label -> "#rrggbb", set via set_entries(colors=...).
        self._colors: dict[str, str] = {}

        # Current investigation window, set via set_investigation_window().
        # None means "no filter applied" — every bucket renders at full
        # opacity in that case.
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None

        self._show_empty_state()

    # -- Public API ------------------------------------------------------------

    def set_entries(self, entries_by_source: dict[str, list[RawLogEntry]], colors: dict[str, str]) -> None:
        """Replaces all chart data. Called by InvestigationDashboard
        whenever a log is imported or a panel is closed (Section 4.7.1
        step 7 territory, but the chart needs the full unfiltered entries —
        not just the matched ones LogFilter returns — so it can show
        activity both inside and outside the investigation window).

        Args:
            entries_by_source: source_label -> ALL entries for that source
                (not pre-filtered). Entries with normalized_timestamp=None
                are dropped internally before bucketing.
            colors: source_label -> hex color string, matching the same
                color each source uses in its LogTab/LogWindowWidget dot.
        """
        self._entries_by_source = entries_by_source
        self._colors = colors
        self._redraw()

    def set_investigation_window(self, start: datetime | None, end: datetime | None) -> None:
        """Called by InvestigationDashboard.refresh() after ApplyFilter.
        Re-dims/un-dims existing bars and redraws the window markers — does
        NOT require re-bucketing since bucket boundaries are independent of
        the investigation window itself (only their opacity changes).
        """
        self._window_start = start
        self._window_end = end
        self._redraw()

    def clear_chart(self) -> None:
        """Called when the last log panel is closed — Section 4.7.2's
        get_active_inactive_sources would otherwise report an empty source
        list and the chart should reflect that rather than show stale bars.
        """
        self._entries_by_source = {}
        self._colors = {}
        self._window_start = None
        self._window_end = None
        self._redraw()

    # -- Internal: bucketing + drawing -----------------------------------------

    def _all_valid_entries(self) -> list[tuple[str, RawLogEntry]]:
        """Flattens self._entries_by_source into (source_label, entry)
        pairs, dropping any entry with no normalized_timestamp.
        """
        pairs = []
        for source_label, entries in self._entries_by_source.items():
            for entry in entries:
                if entry.normalized_timestamp is not None:
                    pairs.append((source_label, entry))
        return pairs

    def _redraw(self) -> None:
        # Clear previous bars before redrawing — BarGraphItem has no public
        # "update data" method that's cheaper than remove+recreate for a
        # dataset this size, and clear() also drops the empty-state text
        # item if one was showing.
        self.clear()
        self._bar_items.clear()

        valid_pairs = self._all_valid_entries()
        if not valid_pairs:
            self._show_empty_state()
            return

        all_timestamps = [entry.normalized_timestamp.utc_datetime for _, entry in valid_pairs]
        range_start = min(all_timestamps)
        range_end = max(all_timestamps)

        # Guard against a single-instant range (e.g. only one entry loaded,
        # or all entries share an identical timestamp) — timedelta(0) would
        # make every bucket the same width of zero and divide-by-zero later.
        if range_end <= range_start:
            range_end = range_start + timedelta(seconds=1)

        bucket_width = (range_end - range_start) / DEFAULT_BUCKET_COUNT
        bucket_seconds = bucket_width.total_seconds()

        source_labels = sorted(self._entries_by_source.keys())
        num_sources = len(source_labels)
        # Each source gets a slim sub-bar within its bucket so multiple
        # sources at the same time don't fully occlude each other — grouped
        # bars rather than stacked, since stacking would hide which source
        # contributed to a spike (useful forensic signal: "WLC_events spiked
        # at 08:07" is a more actionable read than "something spiked").
        sub_bar_width = bucket_seconds / max(num_sources, 1) * 0.9

        for source_index, source_label in enumerate(source_labels):
            entries = self._entries_by_source[source_label]
            valid_entries = [e for e in entries if e.normalized_timestamp is not None]
            if not valid_entries:
                continue

            bucket_counts = [0] * DEFAULT_BUCKET_COUNT
            bucket_in_window = [True] * DEFAULT_BUCKET_COUNT

            for entry in valid_entries:
                ts = entry.normalized_timestamp.utc_datetime
                bucket_index = int((ts - range_start).total_seconds() // bucket_seconds)
                bucket_index = min(bucket_index, DEFAULT_BUCKET_COUNT - 1)
                bucket_counts[bucket_index] += 1

                if self._window_start is not None and self._window_end is not None:
                    if not (self._window_start <= ts <= self._window_end):
                        bucket_in_window[bucket_index] = False

            base_color = self._colors.get(source_label, "#4A90D9")
            qcolor_full = pg.mkColor(base_color)
            qcolor_full.setAlpha(FULL_ALPHA)
            qcolor_dim = pg.mkColor(base_color)
            qcolor_dim.setAlpha(DIMMED_ALPHA)

            xs, heights, brushes = [], [], []
            for bucket_index, count in enumerate(bucket_counts):
                if count == 0:
                    continue
                bucket_centre = range_start + bucket_width * (bucket_index + 0.5)
                # Offset each source's sub-bar within the bucket so grouped
                # bars sit side-by-side rather than directly overlapping.
                offset = (source_index - (num_sources - 1) / 2) * sub_bar_width
                xs.append(bucket_centre.timestamp() + offset)
                heights.append(count)
                brushes.append(qcolor_full if bucket_in_window[bucket_index] else qcolor_dim)

            if not xs:
                continue

            bar_item = pg.BarGraphItem(
                x=xs, height=heights, width=sub_bar_width, brushes=brushes, pen=pg.mkPen(None),
            )
            self.addItem(bar_item)
            self._bar_items[source_label] = bar_item

        self._draw_window_markers(range_start, range_end)

        # PyQtGraph's ViewBox does not automatically re-fit to newly added
        # BarGraphItems in every code path — without this call the chart
        # would stay at its initial default range and the bars would render
        # off-screen or invisible despite having correct data.
        self.getViewBox().autoRange()

        # X-axis: investigation doc calls for start/midpoint/end of the
        # investigation window specifically (not the full loaded range) once
        # a filter is active; before that, fall back to the full data range
        # so the chart isn't unlabeled while no filter has been applied yet.
        axis_start = self._window_start or range_start
        axis_end = self._window_end or range_end
        axis_mid = axis_start + (axis_end - axis_start) / 2
        self.getAxis("bottom").setTicks([[
            (axis_start.timestamp(), axis_start.strftime("%H:%M:%S")),
            (axis_mid.timestamp(), axis_mid.strftime("%H:%M:%S")),
            (axis_end.timestamp(), axis_end.strftime("%H:%M:%S")),
        ]])

    def _draw_window_markers(self, range_start: datetime, range_end: datetime) -> None:
        """Draws vertical dashed lines at the investigation window's start
        and end, when a filter is active, so the dimmed/full-opacity bar
        split has an explicit visual boundary rather than relying on the
        opacity difference alone (which can be subtle on a small dashboard
        chart).
        """
        if self._window_start is None or self._window_end is None:
            return

        pen = pg.mkPen("#00c4e8", width=1, style=Qt.DashLine)
        for boundary in (self._window_start, self._window_end):
            line = pg.InfiniteLine(pos=boundary.timestamp(), angle=90, pen=pen)
            self.addItem(line)

    def _show_empty_state(self) -> None:
        text = pg.TextItem("No log data loaded", color="#4a5a7a", anchor=(0.5, 0.5))
        self.addItem(text)
        self.getViewBox().autoRange()
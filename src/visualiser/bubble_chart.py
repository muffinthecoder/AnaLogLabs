"""
Owned by: Hiba

bubble_chart.py — Section 5.2 / Zone 5 Entity Bubble Chart.

X-axis = Time (investigation range).
Y-axis = Top Entities (Usernames or IP Addresses).
Bubble Size = Volume of events for that entity in a time bucket.
Bubble Color = Log Source (tied to shared SourceColorMap).

This visualization immediately highlights brute-force attacks (one massive
bubble on one user/IP) or password spraying/lateral movement (many small bubbles
across different users/IPs at the exact same timestamp).

Interactivity (visual layer only — the investigation-range filter, entity
ranking, and bucket counts computed below are unchanged):
  - Pan/zoom is pyqtgraph's native behaviour (left-drag pans, scroll zooms,
    right-click gives "View All" to reset) — explicitly enabled below.
  - Hovering a bubble shows a tooltip (entity, source, count, time).
  - Clicking a bubble emits element_clicked(source_label, utc_datetime) so
    MainWindow can jump the matching log window there.
"""

from datetime import datetime, timedelta, timezone
from collections import defaultdict
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QRadialGradient, QGradient, QBrush, QCursor, QFont
from PySide6.QtWidgets import QToolTip, QMenu, QApplication
from src.models.data_classes import RawLogEntry
from src.models.log_table_model import FLAG_WINDOW
from src.normaliser.timezone_map import utc_offset_label
from src.visualiser.axis_utils import choose_tick_count, evenly_spaced_fractions

# Max entities to show on the Y-axis so it doesn't get cluttered
MAX_ENTITIES = 8
# Number of time buckets across the X-axis range
TIME_BUCKETS = 25

AXIS_TEXT_COLOR = "#7284a8"
EMPTY_STATE_TEXT = "#7284a8"
# Bubbles sharing the same entity + time bucket (e.g. two sources firing on
# the same user at once) are nudged apart along X so neither is hidden —
# a lightweight stand-in for a full force-directed layout.
OVERLAP_SPREAD_FRACTION = 0.34

Y_AXIS_WIDTH = 140  # widened so entity names truncate less aggressively
Y_LABEL_ELIDE_CHARS = 18
ZOOM_BTN_FACTOR = 0.85  # matches ZOOM_FACTOR in the other two charts, for a consistent zoom step

# Matches the heatmap's ROW_HEIGHT so both charts share the same vertical
# rhythm — the eye should read them as one system, not two different widgets.
ROW_HEIGHT_PX = 22
TOP_PAD = 4
AXIS_HEIGHT = 16

FLAG_GLOW_COLOR = "#ffffff"

# Cross-chart hover sync (see VisualizationRow._on_chart_hover) — same
# neutral off-white used on the other two charts.
HOVER_SYNC_LINE_COLOR = "#e8ecf5"

# Only the single busiest bubbles glow for "activity" — a relative percentage
# threshold looked fine in isolation but let too MANY bubbles qualify at once
# in a dense cluster, and their glow layers compounded into a washed-out
# white blob instead of reading as a few real standouts. Capping it to a
# fixed count keeps activity-glow rare and meaningful, matching how the
# flag-glow tier is already exclusive by nature.
ACTIVITY_GLOW_MAX_BUBBLES = 3


class BubbleChart(pg.PlotWidget):
    """Entity-focused scatter plot."""

    # (source_label, utc_datetime) — emitted when a bubble is clicked.
    element_clicked = Signal(str, object)
    # utc_datetime | None — emitted on hover so the OTHER two charts can draw
    # a synced highlight at the same moment (see VisualizationRow._on_chart_hover).
    hover_moved = Signal(object)
    # (source_label, utc_datetime) — "Flag this event" from the right-click menu.
    flag_requested = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackground(None)

        # We enforce styled backgrounds so the styles.py background-color applies
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._entries_by_source: dict[str, list[RawLogEntry]] = {}
        self._colors: dict[str, str] = {}
        self._display_tz = "Australia/Perth"
        self._range_start: datetime | None = None
        self._range_end: datetime | None = None
        self._entity_names: list[str] = []
        self._entity_totals: dict[str, int] = {}
        self._entity_rank: dict[str, int] = {}
        self._flag_anchors: list[datetime] = []
        # Right-click has no natural "what's under the cursor" query on a
        # pyqtgraph ScatterPlotItem the way the QPainter charts' _hit_test
        # does, so the context menu acts on whatever the mouse was hovering
        # most recently — kept in sync by _on_scatter_hovered.
        self._last_hovered_data: dict | None = None

        # Themeable — see ActivityHeatmap.set_theme for why these need to be
        # instance state rather than the module constants they default to.
        self._axis_text_color = AXIS_TEXT_COLOR
        self._empty_state_text = EMPTY_STATE_TEXT
        self._flag_glow_color = FLAG_GLOW_COLOR
        self._hover_sync_color = HOVER_SYNC_LINE_COLOR

        # Setup Axes
        self.getAxis("bottom").setTextPen(pg.mkPen(self._axis_text_color))
        self.getAxis("left").setTextPen(pg.mkPen(self._axis_text_color))
        self.getAxis("left").setWidth(Y_AXIS_WIDTH)  # Room for entity names
        axis_font = self._small_font()
        self.getAxis("bottom").setStyle(tickFont=axis_font)
        self.getAxis("left").setStyle(tickFont=axis_font)
        # Without this, pyqtgraph auto-detects the X-axis's raw value
        # magnitude (epoch timestamps, ~1.7 billion) and silently appends a
        # scale suffix like "(x1e+09)" to the axis title — meaningless here
        # since every tick already has its own real HH:MM:SS label.
        self.getAxis("bottom").enableAutoSIPrefix(False)
        self.getAxis("left").enableAutoSIPrefix(False)

        # Strip pyqtgraph's default chrome — the boxed border and full x+y
        # grid made this chart look like a different widget embedded in the
        # app, instead of matching the heatmap/spike chart's flat, borderless
        # look. Only a faint horizontal grid remains (row separators), same
        # visual weight as the spike chart's reference gridlines.
        plot_item = self.getPlotItem()
        plot_item.hideButtons()
        plot_item.showAxis('top', False)
        plot_item.showAxis('right', False)
        plot_item.getViewBox().setBorder(pg.mkPen(None))
        plot_item.getViewBox().setMenuEnabled(False)
        self.showGrid(x=False, y=True, alpha=0.06)

        # Native pyqtgraph pan/zoom: left-drag pans, scroll wheel zooms,
        # right-click context menu offers "View All" to reset.
        self.setMouseEnabled(x=True, y=True)

        self._scatter = pg.ScatterPlotItem(
            size=10,
            pen=pg.mkPen(None),
            hoverable=True,
            hoverSymbol='s',
            hoverSize=15,
            hoverPen=pg.mkPen('w', width=2)
        )
        self._scatter.sigClicked.connect(self._on_scatter_clicked)
        self._scatter.sigHovered.connect(self._on_scatter_hovered)
        self.addItem(self._scatter)

        # Activity-glow layer — subtler, colored (per-source) glow for large
        # but not-necessarily-flagged bubbles. Sits above the main bubbles so
        # it's never hidden by a neighbor, but below the flag-glow layer so a
        # flagged bubble's brighter white glow always wins visually.
        self._activity_glow_scatter = pg.ScatterPlotItem(pen=pg.mkPen(None))
        self.addItem(self._activity_glow_scatter)

        # Halo layer — added AFTER the main scatter so it renders on TOP.
        # Bubbles can sit close together, so a halo behind the main layer
        # risks being covered by a neighboring bubble; on top, a flagged
        # bubble's glow is never hidden by whatever's next to it. Real glow
        # (multiple oversized, increasingly translucent white spots per
        # flagged bubble) rather than a flat effect, since pyqtgraph has no
        # built-in blur/shadow for scatter points.
        self._halo_scatter = pg.ScatterPlotItem(pen=pg.mkPen(None))
        self.addItem(self._halo_scatter)

        self._empty_text = pg.TextItem("No log data loaded", color=self._empty_state_text, anchor=(0.5, 0.5))
        self.addItem(self._empty_text)

        # Cross-chart hover sync guide — one persistent line, moved/shown or
        # hidden by set_external_highlight() rather than recreated each time.
        self._highlight_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(HOVER_SYNC_LINE_COLOR, width=2, style=Qt.DashLine),
        )
        self._highlight_line.setVisible(False)
        self.addItem(self._highlight_line)

    def set_theme(self, theme: dict) -> None:
        """See ActivityHeatmap.set_theme — pyqtgraph's axis pens and TextItem
        color are also set once at creation time, not re-read from QSS, so
        they need the same explicit update on a theme switch.

        The re-call to setBackground(None) below matters more than it looks:
        pyqtgraph's GraphicsView resolves and CACHES its background brush at
        the moment setBackground() is called, rather than re-reading the
        widget's QSS-styled background live — so on a THEME SWITCH (as
        opposed to first construction), the chart's background silently kept
        showing the OLD theme's color until this was added. Found by
        pixel-sampling an actual live switch, not just checking the
        stylesheet string updated (which it always did — the bug was Qt/
        pyqtgraph not repainting from it).
        """
        self._axis_text_color = theme["chart_text_dim"]
        self._empty_state_text = theme["chart_text_dim"]
        self._flag_glow_color = theme["flag_color"]
        self.getAxis("bottom").setTextPen(pg.mkPen(self._axis_text_color))
        self.getAxis("left").setTextPen(pg.mkPen(self._axis_text_color))
        # Explicit tick font size, matching the other two charts' 11px tick
        # labels (pyqtgraph's own default otherwise varies by platform).
        tick_font = QFont()
        tick_font.setPixelSize(11)
        self.getAxis("bottom").setTickFont(tick_font)
        self.getAxis("left").setTickFont(tick_font)
        self._empty_text.setColor(self._empty_state_text)
        # See ActivityHeatmap.set_theme for why accent (not a fixed color)
        # is used for the cross-chart hover sync line and axis titles — a
        # fixed near-white was invisible against the "original"/"coral_reef"
        # themes' light chart backgrounds.
        self._hover_sync_color = theme["accent"]
        self._highlight_line.setPen(pg.mkPen(theme["accent"], width=2, style=Qt.DashLine))

        # Axis TITLES are normally (re)colored inside _refresh_plot(), which
        # only runs on a data/range change — re-applying them here too means
        # a live theme switch updates their color immediately instead of
        # lagging behind until the next refresh.
        title_style = {"font-size": "13px", "font-weight": "bold"}
        left_axis = self.getAxis("left")
        left_axis.setLabel(left_axis.labelText or "Top entities (users / IPs)",
                           color=self._hover_sync_color, **title_style)
        bottom_axis = self.getAxis("bottom")
        bottom_axis.setLabel(bottom_axis.labelText or "Time", color=self._hover_sync_color, **title_style)

        self.setBackground(None)
        self._refresh_plot()

        self._resize_for_rows(MAX_ENTITIES)

    def _resize_for_rows(self, n_rows: int) -> None:
        """Mirrors ActivityHeatmap._resize_for_sources — same per-row pixel
        height, so the two charts share one consistent vertical rhythm
        instead of reading as two differently-scaled widgets side by side.
        """
        rows = max(n_rows, 1)
        self.setMinimumHeight(TOP_PAD + rows * ROW_HEIGHT_PX + AXIS_HEIGHT)

    # -- Public API -----------------------------------------------------------

    def set_entries(self, entries_by_source: dict, colors: dict) -> None:
        self._entries_by_source = entries_by_source
        self._colors = colors
        self._refresh_plot()

    def set_flag_anchors(self, anchors: list[datetime]) -> None:
        """Mirrors LogTableModel.set_flag_anchors — same shared anchors, same
        ±30s FLAG_WINDOW, so a bubble only glows when it contains an entry
        the investigator actually flagged (Section 4.2).
        """
        self._flag_anchors = list(anchors)
        self._refresh_plot()

    def set_display_timezone(self, tz_name: str) -> None:
        self._display_tz = tz_name
        # Note: in a fully robust version, we'd use pytz to convert axis labels here
        self._refresh_plot()

    def set_investigation_range(self, start_utc: datetime | None, end_utc: datetime | None) -> None:
        self._range_start = start_utc
        self._range_end = end_utc
        self._refresh_plot()

    # -- Interactivity ----------------------------------------------------------

    # -- Toolbar-driven zoom (button clicks, not scroll/drag) -------------------

    def zoom_in(self) -> None:
        """Scales the X (time) axis only — Y is a discrete entity list, so
        scaling it doesn't mean anything the way it does for a continuous
        time axis. Centered on the current view via pyqtgraph's default.
        """
        self.getViewBox().scaleBy((ZOOM_BTN_FACTOR, 1.0))

    def zoom_out(self) -> None:
        self.getViewBox().scaleBy((1.0 / ZOOM_BTN_FACTOR, 1.0))

    def reset_view(self) -> None:
        """Re-derives the X/Y range from the current investigation range —
        pyqtgraph's own 'View All' autoRange() would fit to the bubbles'
        bounding box instead, which isn't the same as the actual filtered
        range this chart represents.
        """
        self._refresh_plot()

    def set_external_highlight(self, anchor_dt: datetime | None) -> None:
        """Called by VisualizationRow when a SIBLING chart is being hovered,
        so this chart can draw a synced vertical guide at the matching
        absolute moment (or hide it when anchor_dt is None / hover leaves).
        Entirely separate from this widget's OWN hover state — never emits
        hover_moved itself, so there's no feedback loop between charts.
        """
        if anchor_dt is None:
            self._highlight_line.setVisible(False)
            return
        if self._range_start is not None and self._range_end is not None:
            if not (self._range_start <= anchor_dt <= self._range_end):
                self._highlight_line.setVisible(False)
                return
        self._highlight_line.setPos(anchor_dt.timestamp())
        self._highlight_line.setVisible(True)

    def _resolve_flag_anchor(self, data: dict) -> datetime | None:
        """Finds one REAL entry's exact (ms-precise) timestamp within the
        bucket a bubble represents, for use as a flag anchor.

        Each bubble is an AGGREGATE of every entry for (entity, source,
        bucket) — its plotted utc_dt is the bucket's geometric center
        (occasionally nudged for overlap spreading), not any actual row's
        timestamp. Flagging needs to land within FLAG_WINDOW (±30s) of a
        real row, and on a wide investigation range a bucket can span
        minutes, so the center can silently miss every real entry it
        represents. This scans for one real matching entry instead.
        """
        source_label = data["source_label"]
        entity = data["entity"]
        bucket_idx = data.get("bucket_idx")
        if bucket_idx is None or self._range_start is None or self._range_end is None:
            return None
        duration = (self._range_end - self._range_start).total_seconds()
        bucket_size = duration / TIME_BUCKETS
        bucket_start = self._range_start + timedelta(seconds=bucket_idx * bucket_size)
        bucket_end = bucket_start + timedelta(seconds=bucket_size)
        for entry in self._entries_by_source.get(source_label, []):
            nts = entry.normalized_timestamp
            if nts is None:
                continue
            t = nts.utc_datetime
            if bucket_start <= t <= bucket_end and self._extract_entity(entry) == entity:
                return t + timedelta(milliseconds=nts.milliseconds)
        return None

    def _point_tooltip_text(self, data: dict) -> str:
        """Builds the exact text shown in the hover tooltip — factored out
        so the right-click 'Copy details' action can put IDENTICAL text on
        the clipboard instead of duplicating this formatting.
        """
        tz = self._tz()
        local_str = data["utc_dt"].astimezone(tz).strftime("%H:%M:%S")
        flag_suffix = "\n⚑ Flagged event nearby" if data.get("flagged") else ""

        entity = data["entity"]
        entity_total = self._entity_totals.get(entity, data["count"])
        rank = self._entity_rank.get(entity)
        rank_note = f"  ·  #{rank} busiest entity" if rank else ""
        bubble_share_pct = (data["count"] / entity_total * 100) if entity_total else 100

        return (
            f"{entity}{rank_note}\n"
            f"{data['source_label']}  ·  {data['count']} event{'s' if data['count'] != 1 else ''} "
            f"({bubble_share_pct:.0f}% of this entity's {entity_total} total)\n"
            f"{local_str}  ({utc_offset_label(self._display_tz)})"
            f"{flag_suffix}"
        )

    def _on_scatter_clicked(self, plot, points, ev=None) -> None:
        if not points:
            return
        data = points[0].data()
        if not data:
            return
        self.element_clicked.emit(data["source_label"], data["utc_dt"])

    def _on_scatter_hovered(self, plot, points, ev=None) -> None:
        if not points:
            QToolTip.hideText()
            self._last_hovered_data = None
            self.hover_moved.emit(None)
            return
        data = points[0].data()
        if not data:
            return
        self._last_hovered_data = data
        QToolTip.showText(QCursor.pos(), self._point_tooltip_text(data), self)
        self.hover_moved.emit(data["utc_dt"])

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        self._last_hovered_data = None
        self.hover_moved.emit(None)
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        """Right-click menu: Copy details / Flag this event, mirroring the
        other two charts' context menus. Acts on whichever bubble was
        hovered most recently (see _last_hovered_data) since pyqtgraph has
        no direct 'what's under this exact pixel' query the way the
        QPainter charts' _hit_test does.
        """
        data = self._last_hovered_data
        if not data:
            return
        menu = QMenu(self)
        text = self._point_tooltip_text(data)
        menu.addAction("Copy details", lambda: QApplication.clipboard().setText(text))
        anchor = self._resolve_flag_anchor(data)
        if anchor is not None:
            menu.addAction("Flag this event", lambda: self.flag_requested.emit(data["source_label"], anchor))
        menu.exec(event.globalPos())

    def _tz(self):
        import pytz
        try:
            return pytz.timezone(self._display_tz)
        except Exception:
            return pytz.timezone("Australia/Perth")

    @staticmethod
    def _small_font():
        from PySide6.QtGui import QFont
        f = QFont()
        f.setPixelSize(11)
        return f

    # -- Internal Logic -------------------------------------------------------

    def _extract_entity(self, entry: RawLogEntry) -> str:
        """Prioritize usernames, then IPs, then hostnames to define 'Who/Where'."""
        return (
                entry.fields.get("username") or
                entry.fields.get("ip_address") or
                entry.fields.get("hostname") or
                "Unknown"
        )

    @staticmethod
    def _elide(text: str, max_chars: int) -> str:
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def _show_empty(self, text: str) -> None:
        """Centers the empty-state message across the FULL widget width —
        previously the Y-axis gutter (140px, needed once real entity labels
        exist) stayed reserved even with nothing to show in it, and the text
        was never given an explicit position, so it rendered off-center in
        whatever arbitrary range pyqtgraph happened to default to. Both are
        fixed here: axes hidden (no gutter to leave blank) and a known fixed
        range with the text explicitly centered in it.
        """
        self.getAxis("left").setTicks([])
        self.getAxis("bottom").setTicks([])
        self.showAxis("left", False)
        self.showAxis("bottom", False)
        self.setXRange(0, 1, padding=0)
        self.setYRange(0, 1, padding=0)
        self._empty_text.setPos(0.5, 0.5)
        self._empty_text.setText(text)
        self._empty_text.setVisible(True)

    def _refresh_plot(self) -> None:
        self._scatter.clear()
        self._activity_glow_scatter.clear()
        self._halo_scatter.clear()

        # 1. Empty State Checks
        if not self._entries_by_source:
            self._show_empty("No logs loaded yet")
            return

        if not self._range_start or not self._range_end or self._range_end <= self._range_start:
            self._show_empty("Enter a time range to see the bubble chart")
            return

        self._empty_text.setVisible(False)
        self.showAxis("left", True)
        self.showAxis("bottom", True)
        self.getAxis("left").setWidth(Y_AXIS_WIDTH)

        # 2. Filter data to the active time range
        range_start_ts = self._range_start.timestamp()
        range_end_ts = self._range_end.timestamp()
        duration = range_end_ts - range_start_ts
        bucket_size = duration / TIME_BUCKETS

        entity_totals = defaultdict(int)
        # Structure: buckets[(entity, source_label, bucket_index)] = count
        buckets = defaultdict(int)
        # True if ANY entry in that (entity, source, bucket) falls within
        # ±30s of a flag anchor the investigator set manually (Section 4.2).
        buckets_flagged = defaultdict(bool)

        for source_label, entries in self._entries_by_source.items():
            for entry in entries:
                if entry.normalized_timestamp is None:
                    continue

                utc_dt = entry.normalized_timestamp.utc_datetime
                ts = utc_dt.timestamp()
                if range_start_ts <= ts <= range_end_ts:
                    entity = self._extract_entity(entry)
                    if entity == "Unknown":
                        continue  # Skip rows without identifiable entities

                    bucket_idx = int((ts - range_start_ts) / bucket_size)
                    # Clamp to max bucket in case of exact edge match
                    bucket_idx = min(bucket_idx, TIME_BUCKETS - 1)

                    entity_totals[entity] += 1
                    key = (entity, source_label, bucket_idx)
                    buckets[key] += 1
                    if self._flag_anchors and any(
                            abs((utc_dt - a).total_seconds()) <= FLAG_WINDOW.total_seconds()
                            for a in self._flag_anchors
                    ):
                        buckets_flagged[key] = True

        if not entity_totals:
            self._show_empty("No identifiable entities (Users/IPs) in this range")
            return

        # 3. Rank top entities
        top_entities = sorted(entity_totals.items(), key=lambda x: x[1], reverse=True)[:MAX_ENTITIES]
        entity_names = [e[0] for e in top_entities]
        self._entity_names = entity_names
        self._resize_for_rows(len(entity_names))

        # Kept for the hover tooltip — "this entity is #2 busiest, with N
        # total events across the range" needs the full ranking, not just
        # which row it's drawn on.
        self._entity_totals = dict(entity_totals)
        self._entity_rank = {name: i + 1 for i, (name, _) in enumerate(top_entities)}

        # Map entity name to Y-axis coordinate (0 to N)
        y_map = {name: i for i, name in enumerate(entity_names)}

        # Activity glow is capped to a fixed number of the single largest
        # (entity, source, bucket) combinations shown — see
        # ACTIVITY_GLOW_MAX_BUBBLES for why this replaced a percentage
        # threshold. Flagged bubbles are excluded here since they already
        # get the brighter, exclusive flag-glow tier.
        non_flagged_by_count = sorted(
            (key for key in buckets if not buckets_flagged[key] and key[0] in y_map),
            key=lambda k: buckets[k], reverse=True,
        )
        activity_glow_keys = set(non_flagged_by_count[:ACTIVITY_GLOW_MAX_BUBBLES])

        # 4. Generate Scatter Points
        spots = []
        halo_spots = []
        activity_glow_spots = []
        max_bucket_vol = max(buckets.values()) if buckets else 1

        # Group by (entity, bucket) first so sources landing on the exact same
        # entity + time bucket can be spread apart instead of stacking exactly
        # on top of one another.
        groups: dict[tuple, list[tuple[str, int, bool, tuple]]] = defaultdict(list)
        for (entity, source_label, b_idx), count in buckets.items():
            if entity not in y_map:
                continue
            key = (entity, source_label, b_idx)
            groups[(entity, b_idx)].append((source_label, count, buckets_flagged[key], key))

        for (entity, b_idx), members in groups.items():
            y_coord = y_map[entity]
            base_x_ts = range_start_ts + (b_idx * bucket_size) + (bucket_size / 2)
            recency_frac = (b_idx + 0.5) / TIME_BUCKETS  # 0 = oldest bucket, ~1 = most recent
            bucket_center_utc = datetime.fromtimestamp(base_x_ts, tz=timezone.utc)

            n = len(members)
            for i, (source_label, count, flagged, key) in enumerate(members):
                # Spread overlapping members symmetrically around the bucket
                # center instead of stacking exactly on top of each other.
                if n > 1:
                    offset_frac = (i - (n - 1) / 2) / max(n, 1)
                    x_ts = base_x_ts + offset_frac * bucket_size * OVERLAP_SPREAD_FRACTION * 2
                else:
                    x_ts = base_x_ts

                # Base size 8, scales up to 30 based on volume (tightened
                # from 35 — smaller max size means fewer bubbles overlap in
                # dense clusters, which was the root cause of the glow
                # compounding into a washed-out blob).
                bubble_size = 8 + (22 * (count / max_bucket_vol))

                hex_color = self._colors.get(source_label, "#4a5a7a")
                base_color = QColor(hex_color)
                # Brightness encodes recency: more recent buckets render fuller
                # and lighter, older ones dimmer and more muted.
                lit_color = base_color.lighter(100 + int(35 * recency_frac))
                alpha = 90 + int(140 * recency_frac)

                gradient = QRadialGradient(0.35, 0.3, 0.85)
                gradient.setCoordinateMode(QGradient.ObjectBoundingMode)
                core = QColor(lit_color)
                core.setAlpha(min(alpha + 60, 255))
                edge = QColor(base_color)
                edge.setAlpha(alpha)
                gradient.setColorAt(0.0, core)
                gradient.setColorAt(1.0, edge)

                spots.append({
                    'pos': (x_ts, y_coord),
                    'size': bubble_size,
                    'brush': QBrush(gradient),
                    'data': {
                        'entity': entity,
                        'source_label': source_label,
                        'count': count,
                        'utc_dt': datetime.fromtimestamp(x_ts, tz=timezone.utc),
                        'flagged': flagged,
                        'bucket_idx': b_idx,
                    },
                })

                if flagged:
                    # Real glow: several oversized, increasingly translucent
                    # spots stacked behind the bubble on the halo layer —
                    # reserved exclusively for flagged entries, never tied
                    # to bubble size/volume.
                    flag_c = QColor(self._flag_glow_color)
                    for layer in range(3, 0, -1):
                        glow_c = QColor(flag_c)
                        glow_c.setAlpha(int(90 / layer))
                        halo_spots.append({
                            'pos': (x_ts, y_coord),
                            'size': bubble_size + layer * 10,
                            'brush': QBrush(glow_c),
                        })
                elif key in activity_glow_keys:
                    # One of the fixed top-N largest non-flagged bubbles —
                    # subtler glow in the bubble's OWN color, so it reads as
                    # "busy" rather than "flagged" (that distinction is the
                    # whole point of keeping this a separate, weaker tier).
                    for layer in range(2, 0, -1):
                        glow_c = QColor(base_color)
                        glow_c.setAlpha(int(45 / layer))
                        activity_glow_spots.append({
                            'pos': (x_ts, y_coord),
                            'size': bubble_size + layer * 7,
                            'brush': QBrush(glow_c),
                        })

        self._activity_glow_scatter.addPoints(activity_glow_spots)
        self._halo_scatter.addPoints(halo_spots)
        self._scatter.addPoints(spots)

        # 5. Update Axes Labels
        # Y-Axis: Entities (elided — full name available via hover tooltip on the bubble)
        y_ticks = [[(i, self._elide(name, Y_LABEL_ELIDE_CHARS)) for name, i in y_map.items()]]
        self.getAxis("left").setTicks(y_ticks)
        # Bold + accent-colored (not the dimmed tick color) so the axis name
        # reads as prominently as the other two charts' axis titles.
        self.getAxis("left").setLabel("Top entities (users / IPs)", color=self._hover_sync_color,
                                      **{"font-size": "13px", "font-weight": "bold"})

        # X-Axis: density-aware ticks (more of them the wider this widget is,
        # e.g. popped out) instead of a fixed start/mid/end. Formatting is
        # left exactly as it was (system local time via datetime.fromtimestamp
        # with no tz arg) — only the NUMBER of ticks changed here, not how
        # they're converted, since timezone handling isn't something this
        # pass should touch.
        plot_width_px = max(self.width() - Y_AXIS_WIDTH - 20, 50)
        tick_count = choose_tick_count(plot_width_px)
        fractions = evenly_spaced_fractions(tick_count)
        fmt = lambda t: datetime.fromtimestamp(t).strftime("%H:%M:%S")
        x_ticks = [[
            (range_start_ts + frac * duration, fmt(range_start_ts + frac * duration))
            for frac in fractions
        ]]
        self.getAxis("bottom").setTicks(x_ticks)
        self.getAxis("bottom").setLabel("Time", color=self._hover_sync_color,
                                        **{"font-size": "13px", "font-weight": "bold"})

        # Set plot limits so bubbles don't clip on the edges
        self.setXRange(range_start_ts - (bucket_size / 2), range_end_ts + (bucket_size / 2), padding=0.05)
        self.setYRange(-1, len(entity_names), padding=0.05)
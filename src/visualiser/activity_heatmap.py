"""
activity_heatmap.py — R6 / Section 5.1 activity heat map.

Grid: X-axis = time of day (0:00 → 24:00), Y-axis = log source (one row per
imported file). Every event is bucketed by its time-of-day (in the current
DISPLAY timezone), aggregated across the FULL imported range — this view is
deliberately independent of any investigation-window filter (Section 5.1).

Each file has ONE fixed hue (from the shared SourceColorMap). Within a file's
row, cell intensity encodes frequency — busier buckets render at full hue,
quiet buckets fade toward the background — normalised PER FILE so each source's
own busy periods are visible regardless of how its volume compares to others.
Hue never changes with frequency, only intensity (Section 5.1). This
normalisation is always computed over the FULL day regardless of current
zoom — zoom only changes which buckets are drawn, never how intensity or
flag/activity status is computed.

Pure QPainter (no PyQtGraph dependency) so it always renders.

Interactivity (visual layer only — no data/time logic changes):
  - Mouse wheel zooms in/out around the cursor's time-of-day. Left-drag pans
    the zoomed view. Double-click resets to the full 24h view.
  - Hovering a cell shows a tooltip with the source, time-of-day bucket, and
    event count. Hovering a row label shows the full (untruncated) source name.
  - A plain click (no drag) on a cell emits element_clicked(source_label,
    utc_datetime) with the absolute timestamp of the first entry in that
    source falling in the clicked time-of-day bucket, so MainWindow can jump
    the matching log window / event detail panel there.
"""

from datetime import datetime, timedelta

import pytz
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QFont, QPen
from PySide6.QtWidgets import QWidget, QToolTip, QMenu, QApplication

from src.models.data_classes import RawLogEntry
from src.models.log_table_model import FLAG_WINDOW
from src.normaliser.timezone_map import utc_offset_label
from src.visualiser.axis_utils import choose_tick_count, evenly_spaced_fractions, format_timeofday_tick

# 48 half-hour buckets across the day give a readable "busy period" resolution.
BUCKETS_PER_DAY = 48
MINUTES_PER_BUCKET = 24 * 60 // BUCKETS_PER_DAY  # 30

MIN_ALPHA = 30
MAX_ALPHA = 245

ROW_HEIGHT = 22
LABEL_GUTTER = 132   # left area: colour dot + file name (widened so more sources stay readable)
AXIS_HEIGHT = 32    # tick-label row + a second, larger/bold row for the axis title
TOP_PAD = 4

CELL_RADIUS = 3.0
EMPTY_CELL_OUTLINE = "#1c2740"   # faint outline so zero-activity buckets still read as grid
AXIS_TEXT_COLOR = "#7284a8"
LABEL_TEXT_COLOR = "#c8d3ea"
EMPTY_STATE_TEXT = "#7284a8"
LABEL_ELIDE_CHARS = 17

FLAG_GLOW_COLOR = "#ffffff"
GLOW_LAYERS = 4          # concentric translucent layers simulating a soft blur
GLOW_MAX_PAD = 5.0        # how far the outermost glow layer extends past the cell

# Cross-chart hover sync (see VisualizationRow._on_chart_hover) — a dashed
# vertical guide drawn when the SAME moment is currently hovered on one of
# the *other* two charts. Deliberately a neutral off-white rather than any
# source's own hue, so it never looks like a real data cue.
# Cross-chart hover sync (see VisualizationRow._on_chart_hover) — color is
# set from the active theme's accent (see set_theme()), not fixed here. A
# fixed near-white line was invisible against the "original"/"coral_reef"
# themes' light chart backgrounds; this constant only serves as the
# pre-set_theme() fallback before any theme has been applied.
HOVER_SYNC_LINE_COLOR = "#e8ecf5"

# Subtler, colored glow for busy (but not necessarily flagged) cells — uses
# each source's own hue rather than the reserved white flag color, and is
# always visually weaker than a flag glow so flagged still reads as "more
# important" than merely busy.
ACTIVITY_GLOW_THRESHOLD = 0.7   # fraction of that row's own max count
ACTIVITY_GLOW_LAYERS = 3
ACTIVITY_GLOW_MAX_PAD = 3.0
ACTIVITY_GLOW_ALPHA = 50

# Zoom/pan — purely a rendering viewport into the fixed 0..BUCKETS_PER_DAY
# time-of-day axis. Never changes how buckets are computed, only which of
# them are currently drawn.
ZOOM_FACTOR = 0.85
MIN_VIEW_BUCKETS = 2.0     # don't let zoom collapse below ~1 hour of buckets
DRAG_THRESHOLD_PX = 4      # movement beyond this counts as a pan, not a click


class ActivityHeatmap(QWidget):
    """Time-of-day × file activity heat map (Section 5.1)."""

    # (source_label, utc_datetime) — emitted on cell click for chart-to-log navigation.
    element_clicked = Signal(str, object)
    # utc_datetime | None — emitted on hover so the OTHER two charts can draw
    # a synced highlight at the same moment (see VisualizationRow._on_chart_hover).
    hover_moved = Signal(object)
    # (source_label, utc_datetime) — "Flag this event" from the right-click menu.
    flag_requested = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self._entries_by_source: dict[str, list[RawLogEntry]] = {}
        self._colors: dict[str, str] = {}
        self._display_tz = "Australia/Perth"
        self._flag_anchors: list[datetime] = []
        # Set by VisualizationRow when the SAME moment is hovered on a
        # sibling chart — draws a synced vertical guide, independent of this
        # widget's own internal hover state.
        self._external_highlight_dt: datetime | None = None

        # Zoom/pan view window, in fractional bucket indices [0, BUCKETS_PER_DAY].
        self._view_start = 0.0
        self._view_end = float(BUCKETS_PER_DAY)

        self._drag_active = False
        self._drag_start_pos = None
        self._drag_view_start = None
        self._drag_view_end = None

        # Themeable — QPainter reads these at paint time, so unlike the rest
        # of the app (pure QSS, re-themed for free) these need to be instance
        # state with a set_theme() that triggers a repaint. Defaults match
        # what shipped before theme switching existed.
        self._empty_cell_outline = EMPTY_CELL_OUTLINE
        self._axis_text_color = AXIS_TEXT_COLOR
        self._label_text_color = LABEL_TEXT_COLOR
        self._empty_state_text = EMPTY_STATE_TEXT
        self._flag_glow_color = FLAG_GLOW_COLOR
        self._hover_sync_color = HOVER_SYNC_LINE_COLOR

        self.setMinimumHeight(ROW_HEIGHT + AXIS_HEIGHT + TOP_PAD)
        # NOTE: deliberately no static setToolTip() here — see the matching
        # note in SpikeChart.__init__.

    def set_theme(self, theme: dict) -> None:
        """Applies a theme dict (see theme.py) to this chart's internal
        QPainter colors — the one part of the app QSS re-theming can't
        reach, since paintEvent reads Python state, not stylesheet rules.
        """
        self._empty_cell_outline = theme["chart_outline"]
        self._axis_text_color = theme["chart_text_dim"]
        self._label_text_color = theme["chart_text"]
        self._empty_state_text = theme["chart_text_dim"]
        self._flag_glow_color = theme["flag_color"]
        # Cross-chart hover sync line — theme["accent"] rather than a fixed
        # color, since a fixed near-white was invisible against the
        # "original"/"coral_reef" themes' light chart backgrounds. accent is
        # already relied on elsewhere to read clearly against these exact
        # backgrounds (section titles, borders), so it's a safe choice here too.
        self._hover_sync_color = theme["accent"]
        self.update()

    # -- Public API ------------------------------------------------------------

    def set_entries(self, entries_by_source: dict[str, list[RawLogEntry]], colors: dict[str, str]) -> None:
        self._entries_by_source = entries_by_source
        self._colors = colors
        self._resize_for_sources()
        self._apply_auto_zoom()
        self.update()

    def clear_chart(self) -> None:
        self._entries_by_source = {}
        self._colors = {}
        self._resize_for_sources()
        self.update()

    def set_display_timezone(self, tz_name: str) -> None:
        """Bucket assignment is time-of-day IN this display timezone, so
        changing it shifts where the data cluster falls on the 0..24 axis —
        the auto-zoom is recomputed here for the same reason it's computed
        in set_entries().
        """
        self._display_tz = tz_name
        self._apply_auto_zoom()
        self.update()

    def set_flag_anchors(self, anchors: list[datetime]) -> None:
        """Mirrors LogTableModel.set_flag_anchors — same shared anchors, same
        ±30s FLAG_WINDOW, so a cell only glows when it contains an entry the
        investigator actually flagged (Section 4.2), never on activity level.
        """
        self._flag_anchors = list(anchors)
        self.update()

    # -- Internal --------------------------------------------------------------

    def _valid_sources(self) -> list[str]:
        return [
            label for label, entries in self._entries_by_source.items()
            if any(e.normalized_timestamp is not None for e in entries)
        ]

    def _resize_for_sources(self) -> None:
        rows = max(len(self._valid_sources()), 1)
        self.setMinimumHeight(TOP_PAD + rows * ROW_HEIGHT + AXIS_HEIGHT)

    def _tz(self):
        try:
            return pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone("Australia/Perth")

    def _compute_auto_zoom(self):
        """Finds the tightest time-of-day window that actually contains
        activity across every source, in the CURRENT display timezone —
        so the heatmap opens zoomed into the relevant period instead of a
        mostly-empty 24h grid. Returns (start_bucket, end_bucket) with a
        little padding, or None if there's no data (falls back to the full
        24h view in that case).
        """
        tz = self._tz()
        min_bucket = None
        max_bucket = None
        for label in self._valid_sources():
            for entry in self._entries_by_source.get(label, []):
                nts = entry.normalized_timestamp
                if nts is None:
                    continue
                local = nts.utc_datetime.astimezone(tz)
                minute_of_day = local.hour * 60 + local.minute
                idx = min(minute_of_day // MINUTES_PER_BUCKET, BUCKETS_PER_DAY - 1)
                if min_bucket is None or idx < min_bucket:
                    min_bucket = idx
                if max_bucket is None or idx > max_bucket:
                    max_bucket = idx
        if min_bucket is None:
            return None

        pad = 2  # ~1 hour of breathing room on each side of the actual data
        start = max(0.0, float(min_bucket - pad))
        end = min(float(BUCKETS_PER_DAY), float(max_bucket + 1 + pad))
        if end - start < MIN_VIEW_BUCKETS:
            center = (start + end) / 2
            start = max(0.0, center - MIN_VIEW_BUCKETS / 2)
            end = min(float(BUCKETS_PER_DAY), start + MIN_VIEW_BUCKETS)
        return start, end

    def _apply_auto_zoom(self) -> None:
        result = self._compute_auto_zoom()
        if result is not None:
            self._view_start, self._view_end = result
        else:
            self._view_start = 0.0
            self._view_end = float(BUCKETS_PER_DAY)

    def _effective_view(self):
        """Current zoom/pan window, clamped to the full 0..BUCKETS_PER_DAY axis."""
        start = max(0.0, min(self._view_start, BUCKETS_PER_DAY - MIN_VIEW_BUCKETS))
        end = min(float(BUCKETS_PER_DAY), max(self._view_end, start + MIN_VIEW_BUCKETS))
        return start, end

    def _layout(self):
        """Shared geometry/bucket computation used by both paintEvent and the
        mouse handlers, so hit-testing always matches what's on screen.
        Intensity normalisation (row_max) is always over the FULL day —
        only which buckets get DRAWN depends on the current zoom window.
        """
        sources = sorted(self._valid_sources())
        tz = self._tz()

        counts_by_source: dict[str, list[int]] = {}
        flagged_by_source: dict[str, list[bool]] = {}
        row_max: dict[str, int] = {}
        for label in sources:
            buckets = [0] * BUCKETS_PER_DAY
            flagged = [False] * BUCKETS_PER_DAY
            for entry in self._entries_by_source[label]:
                if entry.normalized_timestamp is None:
                    continue
                utc_dt = entry.normalized_timestamp.utc_datetime
                local = utc_dt.astimezone(tz)
                minute_of_day = local.hour * 60 + local.minute
                idx = min(minute_of_day // MINUTES_PER_BUCKET, BUCKETS_PER_DAY - 1)
                buckets[idx] += 1
                if self._flag_anchors and any(
                    abs((utc_dt - a).total_seconds()) <= FLAG_WINDOW.total_seconds()
                    for a in self._flag_anchors
                ):
                    flagged[idx] = True
            counts_by_source[label] = buckets
            flagged_by_source[label] = flagged
            row_max[label] = max(1, max(buckets))

        view_start, view_end = self._effective_view()
        grid_left = LABEL_GUTTER
        grid_width = max(self.width() - grid_left - 4, 1)
        cell_width = grid_width / (view_end - view_start)
        return {
            "sources": sources, "counts_by_source": counts_by_source,
            "flagged_by_source": flagged_by_source, "row_max": row_max, "tz": tz,
            "grid_left": grid_left, "grid_width": grid_width, "cell_width": cell_width,
            "view_start": view_start, "view_end": view_end,
        }

    def _vertical_offset(self, num_sources: int) -> float:
        """Shared by paintEvent and _hit_test so hover/click accuracy can
        never drift out of sync with where rows are actually painted.
        """
        content_height = TOP_PAD + num_sources * ROW_HEIGHT + AXIS_HEIGHT
        return max(0.0, (self.height() - content_height) / 2)

    def _hit_test(self, pos):
        """Returns ('cell', label, bucket_idx, count) | ('label', label) | None
        for the given widget-local mouse position.
        """
        L = self._layout()
        sources = L["sources"]
        if not sources:
            return None

        y_offset = self._vertical_offset(len(sources))
        row = int((pos.y() - y_offset - TOP_PAD) // ROW_HEIGHT)
        if row < 0 or row >= len(sources):
            return None
        label = sources[row]

        if pos.x() < L["grid_left"]:
            return ("label", label)

        if pos.x() > L["grid_left"] + L["grid_width"]:
            return None

        bucket_idx = int(L["view_start"] + (pos.x() - L["grid_left"]) / L["cell_width"])
        bucket_idx = max(0, min(bucket_idx, BUCKETS_PER_DAY - 1))
        count = L["counts_by_source"][label][bucket_idx]
        return ("cell", label, bucket_idx, count)

    def _first_entry_in_bucket(self, label: str, bucket_idx: int):
        """Earliest (absolute UTC) entry for `label` whose local time-of-day
        falls in `bucket_idx`, used to resolve a heatmap click (a time-of-day
        aggregate) to one concrete, navigable timestamp.
        """
        tz = self._tz()
        candidates = []
        for entry in self._entries_by_source.get(label, []):
            nts = entry.normalized_timestamp
            if nts is None:
                continue
            local = nts.utc_datetime.astimezone(tz)
            minute_of_day = local.hour * 60 + local.minute
            idx = min(minute_of_day // MINUTES_PER_BUCKET, BUCKETS_PER_DAY - 1)
            if idx == bucket_idx:
                candidates.append(nts.utc_datetime)
        return min(candidates) if candidates else None

    def _resolve_flag_anchor(self, label: str, bucket_idx: int) -> datetime | None:
        """Same real entry as _first_entry_in_bucket, but WITH milliseconds
        included, matching exactly how a normal row-click flag anchor is
        built (utc_datetime + ms) — see SpikeChart._resolve_flag_anchor for
        why flagging specifically needs this precision that navigation
        doesn't.
        """
        tz = self._tz()
        candidates = []
        for entry in self._entries_by_source.get(label, []):
            nts = entry.normalized_timestamp
            if nts is None:
                continue
            local = nts.utc_datetime.astimezone(tz)
            minute_of_day = local.hour * 60 + local.minute
            idx = min(minute_of_day // MINUTES_PER_BUCKET, BUCKETS_PER_DAY - 1)
            if idx == bucket_idx:
                candidates.append(nts.utc_datetime + timedelta(milliseconds=nts.milliseconds))
        return min(candidates) if candidates else None

    def set_external_highlight(self, anchor_dt: datetime | None) -> None:
        """Called by VisualizationRow when a SIBLING chart is being hovered,
        so this chart can draw a synced vertical guide at the matching
        time-of-day (or clear it when anchor_dt is None / hover leaves).
        Entirely separate from this widget's OWN hover state — never emits
        hover_moved itself, so there's no feedback loop between charts.
        """
        if self._external_highlight_dt == anchor_dt:
            return
        self._external_highlight_dt = anchor_dt
        self.update()

    def _cell_tooltip_text(self, label: str, bucket_idx: int, count: int) -> str:
        """Builds the exact text shown in the hover tooltip — factored out
        so the right-click 'Copy details' action can put IDENTICAL text on
        the clipboard instead of duplicating this formatting.
        """
        start_minute = bucket_idx * MINUTES_PER_BUCKET
        h, m = divmod(start_minute, 60)
        end_h, end_m = divmod(start_minute + MINUTES_PER_BUCKET, 60)
        time_range = f"{h:02d}:{m:02d}–{end_h:02d}:{end_m:02d}"
        L = self._layout()
        flagged = L["flagged_by_source"].get(label, [False] * BUCKETS_PER_DAY)[bucket_idx]

        day_counts = L["counts_by_source"].get(label, [])
        day_total = sum(day_counts)
        row_peak = L["row_max"].get(label, 1)
        share_pct = (count / day_total * 100) if day_total else 0
        is_busiest = count > 0 and count == row_peak
        peak_suffix = "  ★ peak" if is_busiest else ""
        flag_suffix = "  ⚑" if flagged else ""

        return (
            f"{label}\n"
            f"{time_range}  ·  {count} event{'s' if count != 1 else ''} "
            f"({share_pct:.0f}%){peak_suffix}{flag_suffix}"
        )

    # -- Mouse interaction: zoom / pan / hover / click ---------------------------

    def zoom_in(self) -> None:
        """Button-driven zoom (toolbar), centered on the current view."""
        self._zoom_by(ZOOM_FACTOR)

    def zoom_out(self) -> None:
        self._zoom_by(1.0 / ZOOM_FACTOR)

    def _zoom_by(self, factor: float) -> None:
        view_start, view_end = self._effective_view()
        span = view_end - view_start
        center = (view_start + view_end) / 2

        new_span = max(span * factor, MIN_VIEW_BUCKETS)
        new_span = min(new_span, float(BUCKETS_PER_DAY))

        new_start = center - new_span / 2
        new_end = center + new_span / 2
        if new_start < 0:
            new_end -= new_start
            new_start = 0.0
        if new_end > BUCKETS_PER_DAY:
            new_start -= (new_end - BUCKETS_PER_DAY)
            new_end = float(BUCKETS_PER_DAY)

        self._view_start = max(0.0, new_start)
        self._view_end = min(float(BUCKETS_PER_DAY), new_end)
        self.update()

    def reset_view(self) -> None:
        """Resets zoom/pan back to the full 24h view — same effect as
        double-clicking, exposed for the floating-window toolbar's Home
        button.
        """
        self._view_start = 0.0
        self._view_end = float(BUCKETS_PER_DAY)
        self.update()

    def wheelEvent(self, event) -> None:
        if not self._valid_sources():
            return
        view_start, view_end = self._effective_view()
        span = view_end - view_start

        L = self._layout()
        plot_x = max(0.0, min(event.position().x() - L["grid_left"], L["grid_width"]))
        anchor_frac = plot_x / L["grid_width"] if L["grid_width"] else 0.5
        anchor_bucket = view_start + anchor_frac * span

        factor = ZOOM_FACTOR if event.angleDelta().y() > 0 else (1.0 / ZOOM_FACTOR)
        new_span = max(span * factor, MIN_VIEW_BUCKETS)
        new_span = min(new_span, float(BUCKETS_PER_DAY))

        new_start = anchor_bucket - anchor_frac * new_span
        new_end = new_start + new_span
        if new_start < 0:
            new_start = 0.0
            new_end = new_span
        if new_end > BUCKETS_PER_DAY:
            new_end = float(BUCKETS_PER_DAY)
            new_start = new_end - new_span

        self._view_start = new_start
        self._view_end = new_end
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._valid_sources():
            self._drag_active = True
            self._drag_start_pos = event.position()
            self._drag_view_start, self._drag_view_end = self._effective_view()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_active and self._drag_start_pos is not None:
            dx = event.position().x() - self._drag_start_pos.x()
            if abs(dx) > DRAG_THRESHOLD_PX:
                L = self._layout()
                span = self._drag_view_end - self._drag_view_start
                if L["grid_width"] > 0:
                    delta_buckets = -(dx / L["grid_width"]) * span
                    new_start = self._drag_view_start + delta_buckets
                    new_end = self._drag_view_end + delta_buckets
                    if new_start < 0:
                        shift = -new_start
                        new_start += shift
                        new_end += shift
                    if new_end > BUCKETS_PER_DAY:
                        shift = new_end - BUCKETS_PER_DAY
                        new_start -= shift
                        new_end -= shift
                    self._view_start = new_start
                    self._view_end = new_end
                    self.update()
            QToolTip.hideText()
            self.hover_moved.emit(None)
            super().mouseMoveEvent(event)
            return

        hit = self._hit_test(event.position().toPoint())
        if hit is None:
            QToolTip.hideText()
            self.hover_moved.emit(None)
            super().mouseMoveEvent(event)
            return

        if hit[0] == "label":
            _, label = hit
            QToolTip.showText(event.globalPosition().toPoint(), label, self)
            self.hover_moved.emit(None)
        else:
            _, label, bucket_idx, count = hit
            QToolTip.showText(event.globalPosition().toPoint(), self._cell_tooltip_text(label, bucket_idx, count),
                              self)
            # Anchor for cross-chart sync: the same real entry a click here
            # would navigate to (see _first_entry_in_bucket) — nothing to
            # anchor on for an empty bucket.
            anchor = self._first_entry_in_bucket(label, bucket_idx) if count > 0 else None
            self.hover_moved.emit(anchor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_drag = False
        if self._drag_active and self._drag_start_pos is not None:
            dx = event.position().x() - self._drag_start_pos.x()
            was_drag = abs(dx) > DRAG_THRESHOLD_PX
        self._drag_active = False
        self._drag_start_pos = None

        if event.button() == Qt.LeftButton and not was_drag:
            hit = self._hit_test(event.position().toPoint())
            if hit is not None and hit[0] == "cell":
                _, label, bucket_idx, count = hit
                if count > 0:
                    target = self._first_entry_in_bucket(label, bucket_idx)
                    if target is not None:
                        self.element_clicked.emit(label, target)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        """Right-click menu: Copy details / Flag this event. Only meaningful
        on a cell with actual events — a row-label right-click has no
        specific moment to copy or flag, so no menu appears there.
        """
        hit = self._hit_test(event.pos())
        if hit is None or hit[0] != "cell":
            return
        _, label, bucket_idx, count = hit
        if count <= 0:
            return

        menu = QMenu(self)
        text = self._cell_tooltip_text(label, bucket_idx, count)
        menu.addAction("Copy details", lambda: QApplication.clipboard().setText(text))

        target = self._resolve_flag_anchor(label, bucket_idx)
        if target is not None:
            menu.addAction("Flag this event", lambda: self.flag_requested.emit(label, target))

        if not menu.isEmpty():
            menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event) -> None:
        # Reset zoom/pan back to the full 24h view.
        self.reset_view()
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        self.hover_moved.emit(None)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        L = self._layout()
        sources = L["sources"]
        if not sources:
            painter.setPen(QColor(self._empty_state_text))
            painter.drawText(self.rect(), Qt.AlignCenter, "No logs loaded yet")
            painter.end()
            return

        counts_by_source = L["counts_by_source"]
        flagged_by_source = L["flagged_by_source"]
        row_max = L["row_max"]
        grid_left, grid_width, cell_width = L["grid_left"], L["grid_width"], L["cell_width"]
        view_start, view_end = L["view_start"], L["view_end"]

        first_bucket = max(0, int(view_start))
        last_bucket = min(BUCKETS_PER_DAY - 1, int(view_end - 1e-9))

        painter.setFont(self._small_font())

        # Center the grid+axis block vertically when the panel is taller than
        # the content actually needs (e.g. the splitter gave this panel more
        # room than heatmap.setMinimumHeight() asked for) — previously rows
        # always started at y=0, leaving a dead gap below instead of the
        # content sitting centered in the space it was given.
        y_offset = self._vertical_offset(len(sources))

        glow_queue = []            # flagged cells -> bright white glow, painted last (on top)
        activity_glow_queue = []   # busy cells -> subtler colored glow, painted first
        for row, label in enumerate(sources):
            y = y_offset + TOP_PAD + row * ROW_HEIGHT
            base = QColor(self._colors.get(label, "#4A90D9"))

            # Left gutter — colour dot + (truncated) file name.
            painter.setPen(Qt.NoPen)
            painter.setBrush(base)
            painter.drawEllipse(QRectF(4, y + ROW_HEIGHT / 2 - 3, 6, 6))
            painter.setPen(QColor(self._label_text_color))
            painter.drawText(
                QRectF(16, y, grid_left - 18, ROW_HEIGHT),
                Qt.AlignVCenter | Qt.AlignLeft,
                self._elide(label, LABEL_ELIDE_CHARS),
            )

            rmax = row_max[label]
            for b in range(first_bucket, last_bucket + 1):
                count = counts_by_source[label][b]
                x = grid_left + (b - view_start) * cell_width
                cell = QRectF(x, y + 1, cell_width - 0.5, ROW_HEIGHT - 2)

                if flagged_by_source[label][b]:
                    # Cells can be narrower than the glow's own radius when
                    # zoomed out — painting the glow now would just get
                    # painted over by the next cell drawn immediately after
                    # it. So queue it and paint every glow in one final pass,
                    # on top of the ENTIRE grid, once every cell fill is down.
                    glow_queue.append(cell)
                elif count > 0 and (count / rmax) >= ACTIVITY_GLOW_THRESHOLD:
                    # Busy-but-not-flagged cell — queue for the subtler,
                    # source-colored glow tier (flagged always wins visually
                    # since its white glow is painted afterward, on top).
                    activity_glow_queue.append((cell, base))

                if count == 0:
                    # Faint outline only, so the full 24h grid stays readable
                    # even where there's no activity, instead of vanishing.
                    painter.setPen(QColor(self._empty_cell_outline))
                    painter.setBrush(Qt.NoBrush)
                else:
                    alpha = MIN_ALPHA + int((MAX_ALPHA - MIN_ALPHA) * (count / rmax))
                    fill = QColor(base)
                    fill.setAlpha(alpha)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(fill)
                painter.drawRoundedRect(cell, CELL_RADIUS, CELL_RADIUS)

        # Final passes — glow painted on top of EVERY cell already drawn, so
        # it's never hidden by whichever neighbor was drawn after it above.
        # Activity glow first (subtler), flag glow last (brighter) so a
        # flagged cell always reads as more important than a merely busy one.
        painter.setPen(Qt.NoPen)
        for cell, color in activity_glow_queue:
            for layer in range(ACTIVITY_GLOW_LAYERS, 0, -1):
                pad = ACTIVITY_GLOW_MAX_PAD * (layer / ACTIVITY_GLOW_LAYERS)
                glow_alpha = int(ACTIVITY_GLOW_ALPHA * (1 - (layer - 1) / ACTIVITY_GLOW_LAYERS))
                glow_color = QColor(color)
                glow_color.setAlpha(glow_alpha)
                painter.setBrush(glow_color)
                glow_rect = cell.adjusted(-pad, -pad, pad, pad)
                painter.drawRoundedRect(glow_rect, CELL_RADIUS + pad, CELL_RADIUS + pad)

        for cell in glow_queue:
            for layer in range(GLOW_LAYERS, 0, -1):
                pad = GLOW_MAX_PAD * (layer / GLOW_LAYERS)
                glow_alpha = int(70 * (1 - (layer - 1) / GLOW_LAYERS))
                glow_color = QColor(self._flag_glow_color)
                glow_color.setAlpha(glow_alpha)
                painter.setBrush(glow_color)
                glow_rect = cell.adjusted(-pad, -pad, pad, pad)
                painter.drawRoundedRect(glow_rect, CELL_RADIUS + pad, CELL_RADIUS + pad)

        # Bottom axis — density-aware ticks (more of them the wider this
        # widget is, e.g. popped out) across the CURRENT (possibly zoomed)
        # view, each with a faint vertical gridline through the grid above,
        # rather than the previous fixed 3 marks regardless of chart size.
        axis_y = y_offset + TOP_PAD + len(sources) * ROW_HEIGHT
        grid_top = y_offset + TOP_PAD
        span_minutes = (view_end - view_start) * MINUTES_PER_BUCKET
        tick_count = choose_tick_count(grid_width)
        fractions = evenly_spaced_fractions(tick_count)

        grid_pen = QColor(self._empty_cell_outline)
        painter.setPen(grid_pen)
        for frac in fractions[1:-1]:
            gx = grid_left + frac * grid_width
            painter.drawLine(QPointF(gx, grid_top), QPointF(gx, axis_y))

        painter.setPen(QColor(self._axis_text_color))
        label_w = 56
        for i, frac in enumerate(fractions):
            bucket = view_start + frac * (view_end - view_start)
            label = format_timeofday_tick(bucket * MINUTES_PER_BUCKET, span_minutes)
            gx = grid_left + frac * grid_width
            if i == 0:
                rect = QRectF(gx, axis_y, label_w, 12)
                align = Qt.AlignLeft | Qt.AlignVCenter
            elif i == len(fractions) - 1:
                rect = QRectF(gx - label_w, axis_y, label_w, 12)
                align = Qt.AlignRight | Qt.AlignVCenter
            else:
                rect = QRectF(gx - label_w / 2, axis_y, label_w, 12)
                align = Qt.AlignHCenter | Qt.AlignVCenter
            painter.drawText(rect, align, label)

        # X-axis title — makes explicit that this is time-OF-DAY (aggregated
        # across the whole imported range), not an absolute timeline like the
        # spike chart, which is a real source of confusion otherwise. Bold +
        # accent-colored (not the dimmed tick-label color) so it reads as a
        # clear axis label rather than blending into the tick row above it.
        title_font = QFont()
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(self._hover_sync_color))
        painter.drawText(QRectF(grid_left, axis_y + 14, grid_width, 16), Qt.AlignHCenter | Qt.AlignVCenter,
                         f"Time of day  ·  {utc_offset_label(self._display_tz)}")

        # Cross-chart hover sync — a dashed vertical guide at whatever
        # moment is currently hovered on a SIBLING chart, converted to this
        # chart's time-of-day axis. Drawn last so it sits on top of bars/grid.
        if self._external_highlight_dt is not None:
            local = self._external_highlight_dt.astimezone(self._tz())
            minute_of_day = local.hour * 60 + local.minute + local.second / 60
            bucket_pos = minute_of_day / MINUTES_PER_BUCKET
            if view_start <= bucket_pos <= view_end:
                hx = grid_left + (bucket_pos - view_start) * cell_width
                pen = QPen(QColor(self._hover_sync_color))
                pen.setWidth(2)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.drawLine(QPointF(hx, grid_top), QPointF(hx, axis_y))

        painter.end()

    @staticmethod
    def _small_font() -> QFont:
        f = QFont()
        f.setPixelSize(11)
        return f

    @staticmethod
    def _elide(text: str, max_chars: int) -> str:
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
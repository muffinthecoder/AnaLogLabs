"""
spike_chart.py — Section 5.2 master timeline / spike chart.

X-axis = time (the active investigation range only), Y-axis = total event
volume per time bucket, STACKED by source using the shared per-file colours so
a spike's contributing sources are identifiable at a glance.

Unlike the heatmap (which always shows the full range), the spike chart renders
ONLY after a time range has been entered, and only for that filtered range
(Section 5.2 / user journey step 4). Before a range is set it shows a prompt.

Pure QPainter, so it always renders and shares the exact colour system.

Interactivity (visual layer only — the investigation-range filter set via
set_range() is untouched; zoom/pan below only changes what part of that
already-filtered range is currently drawn):
  - Mouse wheel zooms in/out around the cursor's timestamp.
  - Left-drag pans the zoomed view. Double-click resets to the full range.
  - Hovering a bar segment shows a tooltip (source, bucket time range, count).
  - A plain click (no drag) on a segment emits element_clicked(source_label,
    utc_datetime) so MainWindow can jump the matching log window there.
"""

from datetime import datetime, timedelta

import pytz
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QFont, QLinearGradient, QPen
from PySide6.QtWidgets import QWidget, QToolTip, QMenu, QApplication

from src.models.data_classes import RawLogEntry
from src.models.log_table_model import FLAG_WINDOW
from src.normaliser.timezone_map import utc_offset_label
from src.visualiser.axis_utils import choose_tick_count, evenly_spaced_fractions, format_time_tick

BUCKETS = 40
AXIS_HEIGHT = 34   # tick-label row + a second, larger/bold row for the axis title
LEFT_GUTTER = 46    # room for a Y scale (0 / mid / max) + rotated axis title (now larger/bold)
TOP_PAD = 6
BAR_RADIUS = 2.0
GRIDLINE_COLOR = "#1c2740"
AXIS_TEXT_COLOR = "#7284a8"
EMPTY_STATE_TEXT = "#7284a8"
GRIDLINE_FRACTIONS = (0.25, 0.5, 0.75)  # quarter/half/three-quarter reference lines

ZOOM_FACTOR = 0.85          # per wheel notch
MIN_VIEW_SECONDS = 5.0      # don't let zoom collapse the view to nothing
DRAG_THRESHOLD_PX = 4       # movement beyond this counts as a pan, not a click

FLAG_GLOW_COLOR = "#ffffff"
GLOW_LAYERS = 4
GLOW_MAX_PAD = 4.0

# Cross-chart hover sync (see VisualizationRow._on_chart_hover) — same
# neutral off-white used in activity_heatmap.py, so the guide reads the
# same way on every chart.
# Cross-chart hover sync (see VisualizationRow._on_chart_hover) — color is
# set from the active theme's accent (see set_theme()); this is only the
# pre-set_theme() fallback.
HOVER_SYNC_LINE_COLOR = "#e8ecf5"

# Subtler, colored glow for tall (but not necessarily flagged) segments —
# always weaker than the flag-glow tier so flagged still reads as more
# important than merely busy.
ACTIVITY_GLOW_THRESHOLD = 0.6   # fraction of the chart-wide peak bucket total
ACTIVITY_GLOW_LAYERS = 3
ACTIVITY_GLOW_MAX_PAD = 3.0
ACTIVITY_GLOW_ALPHA = 55


class SpikeChart(QWidget):
    """Filtered-range stacked-volume timeline (Section 5.2)."""

    # (source_label, utc_datetime) — emitted on a plain (non-drag) segment click.
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
        self._range_start: datetime | None = None  # UTC — full investigation range
        self._range_end: datetime | None = None    # UTC — full investigation range

        # Rendering-level zoom/pan window into [_range_start, _range_end].
        # None means "not zoomed" — falls back to the full range.
        self._view_start: datetime | None = None
        self._view_end: datetime | None = None

        self._drag_active = False
        self._drag_start_pos = None
        self._drag_view_start = None
        self._drag_view_end = None

        self._flag_anchors: list[datetime] = []
        # Set by VisualizationRow when the SAME moment is hovered on a
        # sibling chart — draws a synced vertical guide, independent of this
        # widget's own internal hover state.
        self._external_highlight_dt: datetime | None = None

        self._gridline_color = GRIDLINE_COLOR
        self._axis_text_color = AXIS_TEXT_COLOR
        self._empty_state_text = EMPTY_STATE_TEXT
        self._flag_glow_color = FLAG_GLOW_COLOR
        self._hover_sync_color = HOVER_SYNC_LINE_COLOR

        self.setMinimumHeight(80)
        # NOTE: deliberately no static setToolTip() here — this widget shows
        # its own dynamic per-bar tooltip via mouseMoveEvent. Having both
        # active caused Qt's built-in static tooltip to re-fire on almost
        # every small mouse movement, fighting the per-bar one and making
        # hovering feel overly sensitive/flickery.

    def set_theme(self, theme: dict) -> None:
        """See ActivityHeatmap.set_theme — same reasoning: QPainter colors
        are Python state, not QSS, so they need an explicit update+repaint.
        """
        self._gridline_color = theme["chart_outline"]
        self._axis_text_color = theme["chart_text_dim"]
        self._empty_state_text = theme["chart_text_dim"]
        self._flag_glow_color = theme["flag_color"]
        # See ActivityHeatmap.set_theme for why accent (not a fixed color)
        # is used for the cross-chart hover sync line.
        self._hover_sync_color = theme["accent"]
        self.update()

    # -- Public API ------------------------------------------------------------

    def set_entries(self, entries_by_source: dict[str, list[RawLogEntry]], colors: dict[str, str]) -> None:
        self._entries_by_source = entries_by_source
        self._colors = colors
        self.update()

    def set_range(self, start_utc: datetime | None, end_utc: datetime | None) -> None:
        """Section 5.2 — set (or clear) the filtered range this chart draws.
        A new range always resets any zoom/pan back to showing it in full.
        """
        self._range_start = start_utc
        self._range_end = end_utc
        self._view_start = None
        self._view_end = None
        self.update()

    def set_display_timezone(self, tz_name: str) -> None:
        self._display_tz = tz_name
        self.update()

    def set_flag_anchors(self, anchors: list[datetime]) -> None:
        """Mirrors LogTableModel.set_flag_anchors — same shared anchors, same
        ±30s FLAG_WINDOW, so a bar segment only glows when it contains an
        entry the investigator actually flagged (Section 4.2).
        """
        self._flag_anchors = list(anchors)
        self.update()

    def clear_chart(self) -> None:
        self._entries_by_source = {}
        self._colors = {}
        self._range_start = self._range_end = None
        self._view_start = self._view_end = None
        self.update()

    # -- Internal --------------------------------------------------------------

    def _tz(self):
        try:
            return pytz.timezone(self._display_tz)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone("Australia/Perth")

    def _effective_view(self):
        """Current zoom/pan window, clamped to the full investigation range."""
        start = self._view_start or self._range_start
        end = self._view_end or self._range_end
        start = max(start, self._range_start)
        end = min(end, self._range_end)
        if end <= start:
            end = start + timedelta(seconds=MIN_VIEW_SECONDS)
        return start, end

    def _layout(self):
        """Shared bucket/geometry computation used by paintEvent and hit-testing."""
        view_start, view_end = self._effective_view()
        sources = sorted(
            label for label, entries in self._entries_by_source.items()
            if any(e.normalized_timestamp is not None for e in entries)
        )

        span = (view_end - view_start).total_seconds()
        bucket_seconds = max(span / BUCKETS, 1e-6)

        stacks: list[list[tuple[str, str, int, bool]]] = [[] for _ in range(BUCKETS)]  # (label, color, count, flagged)
        totals = [0] * BUCKETS
        for label in sources:
            color = self._colors.get(label, "#4A90D9")
            per_bucket = [0] * BUCKETS
            per_bucket_flagged = [False] * BUCKETS
            for entry in self._entries_by_source[label]:
                nts = entry.normalized_timestamp
                if nts is None:
                    continue
                t = nts.utc_datetime
                if not (view_start <= t <= view_end):
                    continue
                idx = int((t - view_start).total_seconds() // bucket_seconds)
                idx = min(max(idx, 0), BUCKETS - 1)
                per_bucket[idx] += 1
                if self._flag_anchors and any(
                    abs((t - a).total_seconds()) <= FLAG_WINDOW.total_seconds()
                    for a in self._flag_anchors
                ):
                    per_bucket_flagged[idx] = True
            for b in range(BUCKETS):
                if per_bucket[b]:
                    stacks[b].append((label, color, per_bucket[b], per_bucket_flagged[b]))
                    totals[b] += per_bucket[b]

        plot_left = LEFT_GUTTER
        plot_width = max(self.width() - plot_left - 4, 1)
        plot_bottom = self.height() - AXIS_HEIGHT
        plot_top = TOP_PAD
        plot_height = max(plot_bottom - plot_top, 1)
        max_total = max(totals) if any(totals) else 1
        bar_width = plot_width / BUCKETS

        return {
            "view_start": view_start, "view_end": view_end, "bucket_seconds": bucket_seconds,
            "stacks": stacks, "totals": totals, "plot_left": plot_left, "plot_width": plot_width,
            "plot_bottom": plot_bottom, "plot_top": plot_top, "plot_height": plot_height,
            "max_total": max_total, "bar_width": bar_width,
        }

    def _hit_test(self, pos):
        """Returns (bucket_idx, label, color, count, seg_top_frac, seg_bottom_frac) or None."""
        if self._range_start is None or self._range_end is None or self._range_end <= self._range_start:
            return None
        L = self._layout()
        if pos.x() < L["plot_left"] or pos.x() > L["plot_left"] + L["plot_width"]:
            return None
        if pos.y() < L["plot_top"] or pos.y() > L["plot_bottom"]:
            return None

        bucket_idx = int((pos.x() - L["plot_left"]) // L["bar_width"])
        bucket_idx = max(0, min(bucket_idx, BUCKETS - 1))
        stack = L["stacks"][bucket_idx]
        if not stack:
            return None

        # Walk the stack bottom-up to find which segment the cursor y falls in.
        y_from_bottom = L["plot_bottom"] - pos.y()
        cursor = 0.0
        for label, color, count, flagged in stack:
            seg_h = (count / L["max_total"]) * L["plot_height"]
            if cursor <= y_from_bottom <= cursor + seg_h:
                return (bucket_idx, label, color, count, flagged)
            cursor += seg_h
        return None

    def _bucket_center_time(self, bucket_idx: int) -> datetime:
        L = self._layout()
        return L["view_start"] + timedelta(seconds=(bucket_idx + 0.5) * L["bucket_seconds"])

    def _resolve_flag_anchor(self, bucket_idx: int, label: str) -> datetime | None:
        """Finds one REAL entry's exact (ms-precise) timestamp within this
        bucket for `label`, for use as a flag anchor.

        _bucket_center_time() is fine for navigation (scrolling to "roughly
        here" is forgiving), but flagging needs to land within FLAG_WINDOW
        (±30s) of an actual row's timestamp — on a wide investigation range
        a bucket can span minutes, so the geometric center can be nowhere
        near any real entry in it, and flagging with it silently matches
        nothing in the raw log window. Using a real entry's own timestamp
        instead guarantees the anchor matches (0s away from itself).
        """
        L = self._layout()
        bucket_start = L["view_start"] + timedelta(seconds=bucket_idx * L["bucket_seconds"])
        bucket_end = bucket_start + timedelta(seconds=L["bucket_seconds"])
        for entry in self._entries_by_source.get(label, []):
            nts = entry.normalized_timestamp
            if nts is None:
                continue
            t = nts.utc_datetime
            if bucket_start <= t <= bucket_end:
                return t + timedelta(milliseconds=nts.milliseconds)
        return None

    def set_external_highlight(self, anchor_dt: datetime | None) -> None:
        """Called by VisualizationRow when a SIBLING chart is being hovered,
        so this chart can draw a synced vertical guide at the matching
        absolute moment (or clear it when anchor_dt is None / hover leaves).
        Entirely separate from this widget's OWN hover state — never emits
        hover_moved itself, so there's no feedback loop between charts.
        """
        if self._external_highlight_dt == anchor_dt:
            return
        self._external_highlight_dt = anchor_dt
        self.update()

    def _segment_tooltip_text(self, bucket_idx: int, label: str, count: int, flagged: bool) -> str:
        """Builds the exact text shown in the hover tooltip — factored out
        so the right-click 'Copy details' action can put IDENTICAL text on
        the clipboard instead of duplicating this formatting.
        """
        L = self._layout()
        b_start = L["view_start"] + timedelta(seconds=bucket_idx * L["bucket_seconds"])
        b_end = b_start + timedelta(seconds=L["bucket_seconds"])
        tz = self._tz()
        time_range = f"{b_start.astimezone(tz).strftime('%H:%M:%S')}–{b_end.astimezone(tz).strftime('%H:%M:%S')}"

        bucket_total = L["totals"][bucket_idx]
        share_pct = (count / bucket_total * 100) if bucket_total else 0
        is_peak = bucket_total > 0 and bucket_total == max(L["totals"])
        peak_suffix = "  ★ peak" if is_peak else ""
        flag_suffix = "  ⚑" if flagged else ""

        return (
            f"{label}\n"
            f"{time_range}  ·  {count} event{'s' if count != 1 else ''} "
            f"({share_pct:.0f}%){peak_suffix}{flag_suffix}"
        )

    # -- Mouse interaction: zoom / pan / hover / click ---------------------------

    def zoom_in(self) -> None:
        """Button-driven zoom (toolbar), centered on the current view rather
        than a cursor position — see wheelEvent for the cursor-anchored
        version used for scroll-to-zoom.
        """
        self._zoom_by(ZOOM_FACTOR)

    def zoom_out(self) -> None:
        self._zoom_by(1.0 / ZOOM_FACTOR)

    def _zoom_by(self, factor: float) -> None:
        if self._range_start is None or self._range_end is None or self._range_end <= self._range_start:
            return
        view_start, view_end = self._effective_view()
        span = (view_end - view_start).total_seconds()
        center = view_start + timedelta(seconds=span / 2)

        new_span = max(span * factor, MIN_VIEW_SECONDS)
        full_span = (self._range_end - self._range_start).total_seconds()
        new_span = min(new_span, full_span)

        new_start = center - timedelta(seconds=new_span / 2)
        new_end = center + timedelta(seconds=new_span / 2)
        if new_start < self._range_start:
            shift = self._range_start - new_start
            new_start += shift
            new_end += shift
        if new_end > self._range_end:
            shift = new_end - self._range_end
            new_start -= shift
            new_end -= shift

        self._view_start = new_start
        self._view_end = new_end
        self.update()

    def reset_view(self) -> None:
        """Resets zoom/pan back to the full investigation range — same
        effect as double-clicking the chart, exposed as a callable method so
        the floating-window toolbar's Home button can trigger it directly.
        """
        self._view_start = None
        self._view_end = None
        self.update()

    def wheelEvent(self, event) -> None:
        if self._range_start is None or self._range_end is None or self._range_end <= self._range_start:
            return
        view_start, view_end = self._effective_view()
        span = (view_end - view_start).total_seconds()

        L = self._layout()
        plot_x = max(0.0, min(event.position().x() - L["plot_left"], L["plot_width"]))
        anchor_frac = plot_x / L["plot_width"] if L["plot_width"] else 0.5
        anchor_time = view_start + timedelta(seconds=anchor_frac * span)

        factor = ZOOM_FACTOR if event.angleDelta().y() > 0 else (1.0 / ZOOM_FACTOR)
        new_span = max(span * factor, MIN_VIEW_SECONDS)
        full_span = (self._range_end - self._range_start).total_seconds()
        new_span = min(new_span, full_span)

        new_start = anchor_time - timedelta(seconds=anchor_frac * new_span)
        new_end = new_start + timedelta(seconds=new_span)
        if new_start < self._range_start:
            new_start = self._range_start
            new_end = new_start + timedelta(seconds=new_span)
        if new_end > self._range_end:
            new_end = self._range_end
            new_start = new_end - timedelta(seconds=new_span)

        self._view_start = new_start
        self._view_end = new_end
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._range_start is not None:
            self._drag_active = True
            self._drag_start_pos = event.position()
            self._drag_view_start, self._drag_view_end = self._effective_view()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_active and self._drag_start_pos is not None:
            dx = event.position().x() - self._drag_start_pos.x()
            if abs(dx) > DRAG_THRESHOLD_PX:
                L = self._layout()
                span = (self._drag_view_end - self._drag_view_start).total_seconds()
                if L["plot_width"] > 0:
                    delta_seconds = -(dx / L["plot_width"]) * span
                    new_start = self._drag_view_start + timedelta(seconds=delta_seconds)
                    new_end = self._drag_view_end + timedelta(seconds=delta_seconds)
                    if new_start < self._range_start:
                        shift = self._range_start - new_start
                        new_start += shift
                        new_end += shift
                    if new_end > self._range_end:
                        shift = new_end - self._range_end
                        new_start -= shift
                        new_end -= shift
                    self._view_start = new_start
                    self._view_end = new_end
                    self.update()
            QToolTip.hideText()
            self.hover_moved.emit(None)
        else:
            hit = self._hit_test(event.position().toPoint())
            if hit is None:
                QToolTip.hideText()
                self.hover_moved.emit(None)
            else:
                bucket_idx, label, color, count, flagged = hit
                QToolTip.showText(event.globalPosition().toPoint(),
                                  self._segment_tooltip_text(bucket_idx, label, count, flagged), self)
                self.hover_moved.emit(self._bucket_center_time(bucket_idx))
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
            if hit is not None:
                bucket_idx, label, color, count, flagged = hit
                self.element_clicked.emit(label, self._bucket_center_time(bucket_idx))
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        """Right-click menu: Copy details / Flag this event, mirroring
        ActivityHeatmap's context menu.
        """
        hit = self._hit_test(event.pos())
        if hit is None:
            return
        bucket_idx, label, color, count, flagged = hit

        menu = QMenu(self)
        text = self._segment_tooltip_text(bucket_idx, label, count, flagged)
        menu.addAction("Copy details", lambda: QApplication.clipboard().setText(text))
        anchor = self._resolve_flag_anchor(bucket_idx, label)
        if anchor is not None:
            menu.addAction("Flag this event", lambda: self.flag_requested.emit(label, anchor))
        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event) -> None:
        # Reset zoom/pan back to the full investigation range.
        self.reset_view()
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        self.hover_moved.emit(None)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(self._small_font())

        # Section 5.2 — nothing until a range is chosen.
        if self._range_start is None or self._range_end is None or self._range_end <= self._range_start:
            painter.setPen(QColor(self._empty_state_text))
            painter.drawText(self.rect(), Qt.AlignCenter, "Enter a time range to see the spike chart")
            painter.end()
            return

        L = self._layout()
        plot_left, plot_width = L["plot_left"], L["plot_width"]
        plot_top, plot_bottom, plot_height = L["plot_top"], L["plot_bottom"], L["plot_height"]
        max_total, bar_width = L["max_total"], L["bar_width"]
        stacks = L["stacks"]

        # Subtle horizontal reference gridlines (quarter / half / three-quarter).
        painter.setPen(QColor(self._gridline_color))
        for frac in GRIDLINE_FRACTIONS:
            gy = plot_bottom - frac * plot_height
            painter.drawLine(QPointF(plot_left, gy), QPointF(plot_left + plot_width, gy))

        # Y scale ticks: 0 / mid / max, aligned to the 0% and 100% gridlines
        # plus the (already-drawn, unlabeled) 50% one, so every labeled value
        # has a line to anchor to instead of floating unattached to the grid.
        painter.setPen(QColor(self._axis_text_color))
        painter.drawText(QRectF(0, plot_top - 6, LEFT_GUTTER - 6, 12), Qt.AlignRight | Qt.AlignVCenter, str(max_total))
        painter.drawText(QRectF(0, plot_bottom - 0.5 * plot_height - 6, LEFT_GUTTER - 6, 12),
                         Qt.AlignRight | Qt.AlignVCenter, str(max_total // 2))
        painter.drawText(QRectF(0, plot_bottom - 12, LEFT_GUTTER - 6, 12), Qt.AlignRight | Qt.AlignVCenter, "0")

        # Rotated Y-axis title ("EVENTS"), read bottom-to-top along the gutter.
        # Bold + accent-colored (not dimmed) for prominence; save/restore
        # scopes the bigger font to just this draw call, so it doesn't bleed
        # into the tick labels below.
        painter.save()
        title_font = QFont()
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(self._hover_sync_color))
        painter.translate(13, plot_top + plot_height / 2)
        painter.rotate(-90)
        painter.drawText(QRectF(-plot_height / 2, -14, plot_height, 16), Qt.AlignCenter, "EVENTS")
        painter.restore()

        # Draw stacked bars — thin, gapped, gradient-fade top-to-bottom.
        glow_queue = []            # flagged segments -> bright white glow, painted last (on top)
        activity_glow_queue = []   # tall segments -> subtler colored glow, painted first
        for b in range(BUCKETS):
            x = plot_left + b * bar_width
            y = plot_bottom
            for label, color, count, flagged in stacks[b]:
                seg_h = (count / max_total) * plot_height
                w = max(bar_width - 1.5, 1)
                rect = QRectF(x, y - seg_h, w, seg_h)

                if flagged:
                    # Bars are thin and packed tight — painting the glow now
                    # would just get overwritten by the next bucket's bar
                    # immediately after it. Queue it, paint on top at the end.
                    glow_queue.append(rect)
                elif (count / max_total) >= ACTIVITY_GLOW_THRESHOLD:
                    activity_glow_queue.append((rect, color))

                gradient = QLinearGradient(QPointF(x, y - seg_h), QPointF(x, y))
                bright = QColor(color)
                dim = QColor(color)
                dim.setAlpha(60)
                gradient.setColorAt(0.0, bright)
                gradient.setColorAt(1.0, dim)
                painter.setPen(Qt.NoPen)
                painter.setBrush(gradient)
                painter.drawRoundedRect(rect, BAR_RADIUS, BAR_RADIUS)
                y -= seg_h

        # Final passes — glow on top of every bar. Activity glow first
        # (subtler), flag glow last (brighter) so flagged always wins visually.
        painter.setPen(Qt.NoPen)
        for rect, color in activity_glow_queue:
            for layer in range(ACTIVITY_GLOW_LAYERS, 0, -1):
                pad = ACTIVITY_GLOW_MAX_PAD * (layer / ACTIVITY_GLOW_LAYERS)
                glow_alpha = int(ACTIVITY_GLOW_ALPHA * (1 - (layer - 1) / ACTIVITY_GLOW_LAYERS))
                glow_color = QColor(color)
                glow_color.setAlpha(glow_alpha)
                painter.setBrush(glow_color)
                glow_rect = rect.adjusted(-pad, -pad, pad, pad)
                painter.drawRoundedRect(glow_rect, BAR_RADIUS + pad, BAR_RADIUS + pad)

        for rect in glow_queue:
            for layer in range(GLOW_LAYERS, 0, -1):
                pad = GLOW_MAX_PAD * (layer / GLOW_LAYERS)
                glow_alpha = int(80 * (1 - (layer - 1) / GLOW_LAYERS))
                glow_color = QColor(self._flag_glow_color)
                glow_color.setAlpha(glow_alpha)
                painter.setBrush(glow_color)
                glow_rect = rect.adjusted(-pad, -pad, pad, pad)
                painter.drawRoundedRect(glow_rect, BAR_RADIUS + pad, BAR_RADIUS + pad)

        # X axis: density-aware ticks across the CURRENT (possibly zoomed)
        # view — more of them the wider this widget is (e.g. popped out),
        # each with its own faint vertical gridline so a tick label always
        # has something to point at rather than floating free below the bars.
        tz = self._tz()
        view_start, view_end = L["view_start"], L["view_end"]
        span_seconds = (view_end - view_start).total_seconds()
        tick_count = choose_tick_count(plot_width)
        fractions = evenly_spaced_fractions(tick_count)

        grid_pen = QColor(self._gridline_color)
        painter.setPen(grid_pen)
        for frac in fractions[1:-1]:  # skip the plot's own left/right border
            gx = plot_left + frac * plot_width
            painter.drawLine(QPointF(gx, plot_top), QPointF(gx, plot_bottom))

        painter.setPen(QColor(self._axis_text_color))
        label_w = 70
        for i, frac in enumerate(fractions):
            tick_time = view_start + timedelta(seconds=frac * span_seconds)
            label = format_time_tick(tick_time.astimezone(tz), span_seconds)
            gx = plot_left + frac * plot_width
            if i == 0:
                rect = QRectF(gx, plot_bottom, label_w, 12)
                align = Qt.AlignLeft | Qt.AlignVCenter
            elif i == len(fractions) - 1:
                rect = QRectF(gx - label_w, plot_bottom, label_w, 12)
                align = Qt.AlignRight | Qt.AlignVCenter
            else:
                rect = QRectF(gx - label_w / 2, plot_bottom, label_w, 12)
                align = Qt.AlignHCenter | Qt.AlignVCenter
            painter.drawText(rect, align, label)

        # X-axis title — names the timezone so "detailed" ticks are also
        # unambiguous, not just more numerous. Bold + accent-colored (not
        # dimmed) to match the Y-axis title treatment.
        title_font = QFont()
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(self._hover_sync_color))
        painter.drawText(QRectF(plot_left, plot_bottom + 14, plot_width, 16), Qt.AlignHCenter | Qt.AlignVCenter,
                         f"Time  ·  {utc_offset_label(self._display_tz)}")

        # Cross-chart hover sync — a dashed vertical guide at whatever
        # moment is currently hovered on a SIBLING chart. Drawn last so it
        # sits on top of bars/grid.
        if self._external_highlight_dt is not None and view_start <= self._external_highlight_dt <= view_end:
            frac = (self._external_highlight_dt - view_start).total_seconds() / max(span_seconds, 1e-6)
            hx = plot_left + frac * plot_width
            pen = QPen(QColor(self._hover_sync_color))
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(hx, plot_top), QPointF(hx, plot_bottom))

        painter.end()

    @staticmethod
    def _small_font() -> QFont:
        f = QFont()
        f.setPixelSize(11)
        return f
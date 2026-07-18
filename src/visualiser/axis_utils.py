"""
Owned by: Minal

axis_utils.py — shared axis-tick helpers for the three investigation charts
(ActivityHeatmap, SpikeChart, BubbleChart).

Previously each chart hand-rolled its own "draw exactly 3 labels — start,
mid, end" axis, regardless of how much room it actually had. That made a
popped-out chart (with 4-5x the width of its embedded counterpart) look just
as sparse as the small dashboard version, and gave no sense of the actual
time scale between those three points. This module centralises:

  1. Deciding how many ticks fit an axis at its CURRENT pixel width, so the
     axis gets more detailed as a chart is popped out / resized, and stays
     uncluttered when small.
  2. Formatting a tick's time label with the right precision for the span
     being shown (seconds when zoomed into a narrow window, dates added
     when a range crosses a day boundary), instead of a fixed HH:MM:SS.
"""

from datetime import datetime


def choose_tick_count(pixel_width: float, min_spacing_px: float = 80.0,
                       min_ticks: int = 3, max_ticks: int = 9) -> int:
    """How many evenly-spaced ticks fit along an axis of this pixel width.

    Odd counts are preferred (3, 5, 7, 9) so there's always a clean center
    tick, matching the previous start/mid/end convention while allowing
    more graduations as the chart grows.
    """
    if pixel_width <= 0:
        return min_ticks
    raw = int(pixel_width // min_spacing_px) + 1
    raw = max(min_ticks, min(max_ticks, raw))
    if raw % 2 == 0:
        raw -= 1  # bias down to the nearest odd count so mid-point stays exact
    return max(min_ticks, raw)


def evenly_spaced_fractions(count: int) -> list[float]:
    """count values in [0.0, 1.0] inclusive, evenly spaced (count >= 2)."""
    if count < 2:
        return [0.0]
    return [i / (count - 1) for i in range(count)]


def format_time_tick(dt: datetime, span_seconds: float, *, show_date: bool | None = None) -> str:
    """Formats one axis tick's datetime with precision suited to the span.

    - span >= 24h (or show_date=True): includes the date, no seconds
      ("07/15 14:00") since sub-minute precision isn't meaningful at that zoom.
    - span < 90s: includes seconds AND a decisecond so fast bursts of events
      are still distinguishable ("14:32:05.3").
    - otherwise: "HH:MM:SS", the previous default.
    """
    if show_date is None:
        show_date = span_seconds >= 86400
    if show_date:
        return dt.strftime("%m/%d %H:%M")
    if span_seconds < 90:
        return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 100000}"
    return dt.strftime("%H:%M:%S")


def format_timeofday_tick(total_minutes: float, span_minutes: float) -> str:
    """Formats a time-of-day tick (0..1440 minutes from midnight).

    Adds seconds once the visible span is under 30 minutes (heatmap zoomed
    in close), otherwise just HH:MM.
    """
    total_minutes = total_minutes % 1440
    if span_minutes < 30:
        total_seconds = int(round(total_minutes * 60))
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    h, m = divmod(int(total_minutes), 60)
    return f"{h:02d}:{m:02d}"
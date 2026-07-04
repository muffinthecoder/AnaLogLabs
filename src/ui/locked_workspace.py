"""
locked_workspace.py — the unified "Sync Scroll" lock (single global scrollbar).

When Sync Scroll is enabled (a valid time range must already be set), every open
log panel is snapped side-by-side into this one container and driven by a SINGLE
shared vertical scrollbar on the far right — the individual panel scrollbars are
hidden. The panels can no longer be dragged/moved while locked; they all behave
as if "attached to the same timeline". Turning Sync Scroll off returns them to
the normal movable MDI workspace.

Synchronisation is STRICTLY TIME-BASED (never rows/percent/pixels):

    visible CENTER timestamp  →  nearest-timestamp lookup (bisect, to the
    millisecond)  →  centre the corresponding row in every other panel

Key properties:
  * Center-of-viewport anchor (not the top row).
  * O(log n) nearest lookup via precomputed, sorted timestamp arrays (built once
    in set_panels(), never during scrolling).
  * Recursive-loop prevention via blockSignals() during programmatic scrolls
    plus an is-syncing guard — only USER scrolls propagate.
  * QTimer throttle (~12 ms) so followers keep updating *during* a continuous
    scroll (wheel/touchpad), not only after it stops.
  * The global scrollbar represents the shared TIMELINE position (mapped from
    the union time range), not any panel's row count.
"""

import bisect

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QScrollBar, QLabel

MASTER_RESOLUTION = 100000
SYNC_THROTTLE_MS = 12


class LockedWorkspace(QWidget):
    """Single-scrollbar, strictly time-based locked view of all panels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: dict[str, object] = {}
        # source_label -> (sorted_times[list[float]], row_indices[list[int]])
        self._times: dict[str, tuple[list, list]] = {}
        self._min_t: float | None = None
        self._max_t: float | None = None

        self._syncing = False
        self._pending = None  # ("child", source) | ("master", value)

        self._throttle = QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(SYNC_THROTTLE_MS)
        self._throttle.timeout.connect(self._flush)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        self._panels_container = QWidget()
        self._panels_layout = QHBoxLayout(self._panels_container)
        self._panels_layout.setContentsMargins(0, 0, 0, 0)
        self._panels_layout.setSpacing(2)
        root.addWidget(self._panels_container, stretch=1)

        self._placeholder = QLabel("No log panels to lock.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #4a5a7a; font-size: 12px;")
        self._panels_layout.addWidget(self._placeholder)

        self._master = QScrollBar(Qt.Vertical)
        self._master.setRange(0, MASTER_RESOLUTION)
        self._master.setSingleStep(MASTER_RESOLUTION // 500)
        self._master.setPageStep(MASTER_RESOLUTION // 20)
        self._master.valueChanged.connect(self._on_master_changed)
        root.addWidget(self._master)

    # -- Lifecycle -------------------------------------------------------------

    def set_panels(self, panels: dict) -> None:
        self._panels = dict(panels)
        if self._placeholder.parent() is not None:
            self._placeholder.setParent(None)

        all_times: list[float] = []
        for source_label, panel in self._panels.items():
            panel.table_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._panels_layout.addWidget(panel, stretch=1)
            panel.show()

            times, rows = [], []
            for row, entry in enumerate(panel.table_model.get_entries()):
                nts = entry.normalized_timestamp
                if nts is not None:
                    # Millisecond precision — utc_datetime already carries the
                    # sub-second component.
                    times.append(nts.utc_datetime.timestamp())
                    rows.append(row)
            if times and any(times[i] > times[i + 1] for i in range(len(times) - 1)):
                paired = sorted(zip(times, rows))
                times = [t for t, _ in paired]
                rows = [r for _, r in paired]
            self._times[source_label] = (times, rows)
            all_times.extend((times[0], times[-1]) if times else ())

            panel.scrolled.connect(self._on_child_scrolled)

        self._min_t = min(all_times) if all_times else None
        self._max_t = max(all_times) if all_times else None

    def release_panels(self) -> dict:
        released = dict(self._panels)
        self._throttle.stop()
        for source_label, panel in self._panels.items():
            try:
                panel.scrolled.disconnect(self._on_child_scrolled)
            except (TypeError, RuntimeError):
                pass
            panel.table_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            panel.setParent(None)
        self._panels = {}
        self._times = {}
        self._min_t = self._max_t = None
        self._pending = None
        self._panels_layout.addWidget(self._placeholder)
        return released

    # -- Initial positioning (datum = highlighted range start) -----------------

    def align_to_datum(self, datum_dt) -> None:
        if datum_dt is None:
            return
        t = datum_dt.timestamp()
        # Deferred to the next event-loop tick so the just-reparented panels
        # have a laid-out viewport before scrollTo() runs.
        QTimer.singleShot(0, lambda: self._align_all(t))

    # -- Time <-> master mapping -----------------------------------------------

    def _value_to_time(self, value: int) -> float:
        if self._min_t is None or self._max_t is None or self._max_t <= self._min_t:
            return self._min_t if self._min_t is not None else 0.0
        return self._min_t + (value / MASTER_RESOLUTION) * (self._max_t - self._min_t)

    def _time_to_value(self, t: float) -> int:
        if self._min_t is None or self._max_t is None or self._max_t <= self._min_t:
            return 0
        frac = (t - self._min_t) / (self._max_t - self._min_t)
        frac = min(max(frac, 0.0), 1.0)
        return int(frac * MASTER_RESOLUTION)

    def _set_master_silently(self, t: float) -> None:
        self._master.blockSignals(True)
        self._master.setValue(self._time_to_value(t))
        self._master.blockSignals(False)

    # -- Nearest-row lookup (bisect, O(log n)) ---------------------------------

    def _nearest_row(self, source_label: str, t: float):
        times, rows = self._times.get(source_label, ([], []))
        if not times:
            return None
        pos = bisect.bisect_left(times, t)
        if pos == 0:
            return rows[0]
        if pos == len(times):
            return rows[-1]
        before, after = times[pos - 1], times[pos]
        return rows[pos - 1] if (t - before) <= (after - before) / 2 else rows[pos]

    # -- Alignment -------------------------------------------------------------

    def _align_all(self, t: float) -> None:
        self._syncing = True
        try:
            for source_label, panel in self._panels.items():
                row = self._nearest_row(source_label, t)
                if row is not None:
                    panel.center_on_row(row)
            self._set_master_silently(t)
        finally:
            self._syncing = False

    def _align_others(self, source_label: str, t: float) -> None:
        self._syncing = True
        try:
            for label, panel in self._panels.items():
                if label == source_label:
                    continue
                row = self._nearest_row(label, t)
                if row is not None:
                    panel.center_on_row(row)
            self._set_master_silently(t)
        finally:
            self._syncing = False

    # -- Event handlers (throttled) --------------------------------------------

    def _on_child_scrolled(self, source_label: str, _top_row: int) -> None:
        # THROTTLE (not debounce): start the timer only if it isn't already
        # running, so followers keep updating every ~12 ms *during* a
        # continuous scroll. Programmatic scrolls never reach here because
        # center_on_row() blocks the scrollbar signal.
        if self._syncing:
            return
        self._pending = ("child", source_label)
        if not self._throttle.isActive():
            self._throttle.start()

    def _on_master_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._pending = ("master", value)
        if not self._throttle.isActive():
            self._throttle.start()

    def _flush(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        kind, payload = pending
        if kind == "master":
            self._align_all(self._value_to_time(payload))
        elif kind == "child":
            panel = self._panels.get(payload)
            if panel is None:
                return
            t = panel.visible_center_time()
            if t is not None:
                self._align_others(payload, t)

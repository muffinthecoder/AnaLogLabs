"""
scroll_sync_manager.py — implements ALGORITHM: SyncScroll from Section 4.7.3
of the design document.

Ensures all open log windows scroll together based on the same UTC timestamp
position, not pixel offset, since different logs have different row counts
and event densities.

Owned by: Hiba
Consumed by: src/ui/main_window.py (wires LogWindowWidget.scrolled signal here)
"""

from datetime import datetime

from src.models.data_classes import RawLogEntry


class ScrollSyncManager:
    """Coordinates scroll position across multiple LogWindowWidget instances.

    Per Section 4.7.3, the core challenge is that different log sources have
    different event densities — log A might have 10,000 rows in the same
    time span that log B has only 50 rows. Pixel-based or row-count-based
    sync would desynchronise immediately. This manager instead finds the
    entry in each OTHER window whose timestamp is closest to the anchor
    window's currently-visible timestamp, using binary search since entries
    are pre-sorted by utc_datetime.
    """

    def __init__(self):
        # source_label -> LogWindowWidget. Populated via register_window().
        self.registered_windows: dict = {}
        self.is_syncing: bool = False

    def register_window(self, source_label: str, window) -> None:
        """Adds a LogWindowWidget to the set of windows kept in sync.
        Called when Sync Scroll is toggled on, or when a new log panel
        is opened while sync is already active.
        """
        self.registered_windows[source_label] = window

    def unregister_window(self, source_label: str) -> None:
        """Removes a window from sync — called when Sync Scroll is toggled
        off, or when a log panel is closed.
        """
        self.registered_windows.pop(source_label, None)

    def clear(self) -> None:
        self.registered_windows.clear()

    def sync_scroll(self, source_window, scroll_position: int) -> None:
        """ALGORITHM: SyncScroll(source_window, scroll_position)

        Args:
            source_window: the LogWindowWidget the investigator just
                scrolled. Must have a `.source_label` attribute and a
                `.table_model.get_entries()` method returning entries
                sorted ascending by utc_datetime.
            scroll_position: the row index visible at the CENTER of
                source_window's viewport (see LogWindowWidget._on_scroll for
                why the center row is used as the anchor rather than the top
                row).

        Side effect:
            Calls `.receive_sync_scroll(index)` on every OTHER registered
            window, moving it to the row whose timestamp is closest to
            source_window's current anchor timestamp.
        """
        # Step 1 — guard against recursive sync loops. When window B is
        # told to scroll by this method, it must not re-trigger sync_scroll
        # for window A.
        if self.is_syncing:
            return

        # Step 2
        self.is_syncing = True

        try:
            # Step 3 — get the anchor timestamp from the source window's
            # currently center-visible entry.
            source_entries = source_window.table_model.get_entries()
            if not source_entries or scroll_position >= len(source_entries):
                return

            anchor_entry: RawLogEntry = source_entries[scroll_position]
            if anchor_entry.normalized_timestamp is None:
                return
            anchor_ts = anchor_entry.normalized_timestamp.utc_datetime

            # Step 4 — for every other registered window, binary search for
            # the closest entry by timestamp, then move it there.
            for label, other_window in self.registered_windows.items():
                if label == source_window.source_label:
                    continue

                other_entries = other_window.table_model.get_entries()
                if not other_entries:
                    continue

                closest_index = self._find_closest_index(other_entries, anchor_ts)
                other_window.receive_sync_scroll(closest_index)

        finally:
            # Step 5 — always release the lock, even if an exception occurs
            # above, or every subsequent scroll event would be silently
            # dropped.
            self.is_syncing = False

    def move_all_to_timestamp(self, anchor_ts: datetime) -> None:
        """Moves EVERY currently registered window to the row whose timestamp
        is closest to `anchor_ts`, with no source window involved.

        Used the moment Sync Scroll is switched on: the investigator's
        already-applied highlighted time range has a start timestamp, and that
        becomes the reference/datum every open panel is snapped to immediately,
        before any further user-driven scrolling takes over and starts
        panel-to-panel syncing via sync_scroll() above.

        Deliberately a separate entry point from sync_scroll() rather than
        routing through it with a fake "source" — there IS no source panel for
        this move, and forcing one in just to reuse the loop would skip
        whichever panel matched that fake source (sync_scroll always skips
        source_window.source_label); here every panel needs to move.
        """
        if self.is_syncing:
            return
        self.is_syncing = True
        try:
            for window in self.registered_windows.values():
                entries = window.table_model.get_entries()
                if not entries:
                    continue
                closest_index = self._find_closest_index(entries, anchor_ts)
                window.receive_sync_scroll(closest_index)
        finally:
            self.is_syncing = False

    @staticmethod
    def _find_closest_index(entries: list[RawLogEntry], anchor_ts: datetime) -> int:
        """Return the MODEL ROW INDEX in `entries` whose timestamp is closest
        to anchor_ts.

        A linear scan (rather than bisect) on purpose: `entries` is in the
        panel's CURRENT display order, which may be newest-first (descending)
        as well as oldest-first — bisect assumes ascending and would return the
        wrong row under a descending sort. Scanning is also None-safe: it
        returns the row's actual position even when earlier rows have no
        normalized timestamp (a bisect over a filtered timestamp list would
        desync the index). For this tool's log sizes the scan cost is
        negligible, and correctness across sort orders matters more here.
        """
        best_index = 0
        best_delta = None
        for index, entry in enumerate(entries):
            nts = entry.normalized_timestamp
            if nts is None:
                continue
            delta = abs((nts.utc_datetime - anchor_ts).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_index = index
        return best_index

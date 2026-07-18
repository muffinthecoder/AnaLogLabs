"""
Owned by: Hiba

timeline_merger.py — implements Section 4.7.1 step 5: merging entries from
all loaded log sources into a single chronologically sorted list (R2: Unified
Timeline Synchronization).

Consumed by: src/parser/log_parser.py (final step of ImportAndParse), and by
ScrollSyncManager indirectly (each window's per-source list must already be
sorted ascending for binary search to work).
"""

from src.models.data_classes import RawLogEntry


class TimelineMerger:
    """Merges and sorts RawLogEntry objects from multiple log sources into
    one unified chronological timeline.
    """

    @staticmethod
    def merge_chronological(entries: list[RawLogEntry]) -> list[RawLogEntry]:
        """Section 4.7.1 step 5:
            'Sort all NormalizedTimestamp entries by utc_datetime ascending
            (merge all sources into single chronological list for R2)'

        Entries without a normalized_timestamp (i.e. invalid/unparseable
        rows) are excluded from the merged result — they remain visible in
        their own per-source LogWindowWidget per Section 4.7.1's error
        handling note, but cannot participate in cross-log time ordering.

        Args:
            entries: RawLogEntry objects from any number of log sources,
                in any order.

        Returns:
            A new list, sorted ascending by utc_datetime, containing only
            entries that have a valid normalized_timestamp. Each entry
            retains its original source_label so the merged view can still
            be split back out per source if needed.
        """
        valid_entries = [e for e in entries if e.normalized_timestamp is not None]
        return sorted(valid_entries, key=lambda e: e.normalized_timestamp.utc_datetime)

    @staticmethod
    def split_by_source(entries: list[RawLogEntry]) -> dict[str, list[RawLogEntry]]:
        """Splits a merged chronological list back into per-source lists,
        preserving chronological order within each source. Each resulting
        list is what gets passed to LogWindowWidget.load_rows() for that
        source (Section 4.7.1 step 6).
        """
        by_source: dict[str, list[RawLogEntry]] = {}
        for entry in entries:
            by_source.setdefault(entry.source_label, []).append(entry)
        return by_source
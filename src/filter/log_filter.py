"""
Owned by: Pooja

log_filter.py — implements ALGORITHM: ApplyFilter from Section 4.7.2 of the
design document (R4, R5, R6).

Consumed by: src/ui/main_window.py (_on_filter_applied wires to this)
"""

from datetime import timedelta
from src.models.data_classes import FilterConfig, RawLogEntry

class FilterValidationError(Exception):
    """Raised when a FilterConfig fails validation. Carries a message
    suitable for direct display to the investigator (Section 4.7.2 step 1).
    """
    pass

class LogFilter:
    """Applies an investigator-defined timeframe to all loaded entries and
    determines which entries should be highlighted vs de-emphasised.
    """

    @staticmethod
    def apply_filter(
        filter_config: FilterConfig,
        all_entries: dict[str, list[RawLogEntry]],
    ) -> dict[str, list[RawLogEntry]]:
        """ALGORITHM: ApplyFilter(filter_config) -> matched

        Args:
            filter_config: FilterConfig with start_time, end_time, timezone,
                use_ms_precision. start_time/end_time must already be
                timezone-aware datetimes.
            all_entries: dict mapping source_label -> list of RawLogEntry
                for every currently loaded log source.

        Returns:
            dict mapping source_label -> list of matched RawLogEntry
            (entries whose normalized timestamp falls within the window).

        Raises:
            FilterValidationError: if start_time >= end_time, or either is
                None. Per Section 4.7.2 step 1, this should be caught by
                the caller (TimeFrameSelector) and shown as an inline error
                — apply_filter raises rather than silently returning {} so
                callers can't accidentally treat a validation failure as
                "no matches".
        """
        # Step 1 — validate.
        if filter_config.start_time is None or filter_config.end_time is None:
            raise FilterValidationError("Both start and end times are required")

        if filter_config.start_time >= filter_config.end_time:
            raise FilterValidationError("Start time must be before end time")

        # Step 2 — both start_time and end_time are expected to already be
        # timezone-aware (UTC or otherwise). astimezone(None) would be
        # wrong here since it converts to LOCAL system time, not UTC — so
        # we require the caller (TimeFrameSelector) to hand us UTC-aware
        # datetimes already. This matches how FilterConfig is constructed
        # in TimeFrameSelector._on_apply_clicked.
        start_utc = filter_config.start_time
        end_utc = filter_config.end_time

        matched: dict[str, list[RawLogEntry]] = {
            source: [] for source in all_entries
        }

        # Step 3 — check every entry across every source.
        for source_label, entries in all_entries.items():
            for entry in entries:
                ts = entry.normalized_timestamp
                if ts is None:
                    # Entries with no normalized timestamp cannot be
                    # time-filtered; they are excluded from matched results
                    # but remain visible in their LogWindowWidget (handled
                    # by the UI layer, not here).
                    continue

                if filter_config.use_ms_precision:
                    entry_dt = ts.utc_datetime + timedelta(milliseconds=ts.milliseconds)
                else:
                    entry_dt = ts.utc_datetime

                in_range = start_utc <= entry_dt <= end_utc

                if in_range:
                    matched[source_label].append(entry)

        return matched

    @staticmethod
    def get_active_inactive_sources(
        matched: dict[str, list[RawLogEntry]]
    ) -> tuple[list[str], list[str]]:
        """Section 4.7.2 step 5:
            'active_sources = sources with len(matched[source]) > 0
             inactive_sources = sources with len(matched[source]) == 0'
        """
        active_sources = [src for src, entries in matched.items() if len(entries) > 0]
        inactive_sources = [src for src, entries in matched.items() if len(entries) == 0]
        return active_sources, inactive_sources

    @staticmethod
    def build_dashboard_summary(matched: dict[str, list[RawLogEntry]]) -> dict[str, int]:
        """Section 4.7.2 step 7:
            'summary = {src: len(matched[src]) for src in all_sources}'

        Used directly by InvestigationDashboard.refresh().
        """
        return {source: len(entries) for source, entries in matched.items()}

    @staticmethod
    def get_matched_row_indices(matched_entries: list[RawLogEntry]) -> list[int]:
        """Section 4.7.2 step 4:
            'matched_indices = [e.row_index for e in matched[widget.source_label]]'

        Used directly by LogWindowWidget.highlight_matched().
        """
        return [entry.row_index for entry in matched_entries]

"""
timestamp_normalizer.py — implements ALGORITHM: NormalizeTimestamp from
Section 4.7.5 of the design document (R3).

This is the real implementation, not a placeholder. It converts a raw
timestamp string plus a source timezone into a NormalizedTimestamp object
with a UTC-aware datetime.

Owned by: Hiba
Consumed by: src/parser/log_parser.py (Pooja's module)
"""

from datetime import datetime

import pytz

from src.models.data_classes import NormalizedTimestamp
from src.normaliser.timezone_map import get_timezone_for_source, SUPPORTED_TIMEZONES


class TimestampParseError(Exception):
    """Raised when a raw timestamp string cannot be parsed by any known
    format. Per Section 4.7.5 step 1: 'IF all formats fail: RAISE ParseError
    with raw_ts and source_label'.
    """

    def __init__(self, raw_ts: str, source_label: str):
        self.raw_ts = raw_ts
        self.source_label = source_label
        super().__init__(
            f"Could not parse timestamp '{raw_ts}' for source '{source_label}'. "
            f"No known format matched."
        )


# Format chain in the exact order specified by Section 4.7.5 step 1.
# Order matters — more specific formats are tried first to avoid ambiguous
# matches (e.g. ISO 8601 with microseconds must be tried before the
# microsecond-less version, or the parser would silently truncate ms data).
_FORMAT_CHAIN = [
    "%Y-%m-%dT%H:%M:%S.%f",   # ISO 8601 with microseconds
    "%Y-%m-%dT%H:%M:%S",      # ISO 8601 without microseconds
    "%d/%m/%Y %H:%M:%S.%f",   # common log format with ms
    "%d/%m/%Y %H:%M:%S",      # common log format without ms
    "%m-%d-%Y %H:%M:%S",      # US format
    "%Y%m%d%H%M%S",           # compact format
]


class TimestampNormalizer:
    """Converts raw timestamp strings into UTC-aware NormalizedTimestamp
    objects, per Section 4.7.5.
    """

    @staticmethod
    def normalize_timestamp(raw_ts: str, source_tz: str) -> NormalizedTimestamp:
        """ALGORITHM: NormalizeTimestamp(raw_ts, source_tz) -> NormalizedTimestamp

        Args:
            raw_ts: timestamp string from the raw log row.
            source_tz: IANA timezone string, one of "Australia/Perth",
                "Asia/Singapore", "Asia/Dubai".

        Returns:
            NormalizedTimestamp with utc_datetime, milliseconds, source_tz.

        Raises:
            TimestampParseError: if raw_ts matches none of the supported
                formats in the format chain.
            ValueError: if source_tz is not one of the three supported zones.
        """
        if source_tz not in SUPPORTED_TIMEZONES:
            raise ValueError(
                f"Unsupported source_tz '{source_tz}'. "
                f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
            )

        # Step 1 — try each format in the chain, in order.
        parsed_dt: datetime | None = None
        for fmt in _FORMAT_CHAIN:
            try:
                parsed_dt = datetime.strptime(raw_ts.strip(), fmt)
                break
            except ValueError:
                continue

        if parsed_dt is None:
            raise TimestampParseError(raw_ts=raw_ts, source_label=source_tz)

        # Step 2 — extract milliseconds from the parsed microseconds.
        milliseconds = parsed_dt.microsecond // 1000

        # Step 3 — attach the source timezone (localize the naive datetime).
        tz_obj = pytz.timezone(source_tz)
        localised_dt = tz_obj.localize(parsed_dt)

        # Step 4 — convert to UTC.
        utc_dt = localised_dt.astimezone(pytz.UTC)

        # Perth, Singapore, and Dubai do not observe DST, so this is always
        # False for the prototype's supported timezone set. Kept explicit
        # rather than hardcoded in case future timezones are added.
        is_dst_adjusted = bool(localised_dt.dst())

        return NormalizedTimestamp(
            utc_datetime=utc_dt,
            source_tz=source_tz,
            milliseconds=milliseconds,
            is_dst_adjusted=is_dst_adjusted,
        )

    @staticmethod
    def normalize_for_source(raw_ts: str, source_label: str) -> NormalizedTimestamp:
        """Convenience wrapper — looks up the timezone assigned to a log
        source label, then normalizes. This is what LogParser should call,
        since the parser only knows source_label, not the raw IANA timezone
        string directly.
        """
        source_tz = get_timezone_for_source(source_label)
        return TimestampNormalizer.normalize_timestamp(raw_ts, source_tz)

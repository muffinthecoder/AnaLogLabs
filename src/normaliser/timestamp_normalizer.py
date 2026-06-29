"""
timestamp_normalizer.py — implements ALGORITHM: NormalizeTimestamp from
Section 4.7.5 of the design document (R3).

Owned by: Hiba
Consumed by: src/parser/log_parser.py (Pooja's module)

Fixes applied for real log data (Week 1 integration):
    - Added Z-suffix ISO 8601 formats (files 2–8: all sign-in CSVs use
      "2026-03-25T03:24:52Z")
    - Added Cisco WLC syslog format ("Mar 25 09:30:14")
"""

from datetime import datetime
import pytz

from src.models.data_classes import NormalizedTimestamp
from src.normaliser.timezone_map import (
    get_timezone_for_source,
    SUPPORTED_TIMEZONES,
)


class TimestampParseError(Exception):
    def __init__(self, raw_ts: str, source_label: str):
        self.raw_ts = raw_ts
        self.source_label = source_label
        super().__init__(
            f"Could not parse timestamp '{raw_ts}' for source '{source_label}'. "
            f"No known format matched."
        )


_FORMAT_CHAIN = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%m-%d-%Y %H:%M:%S",
    "%Y%m%d%H%M%S",
]

_SYSLOG_FORMATS = [
    "%b %d %H:%M:%S %Y",
    "%b  %d %H:%M:%S %Y",
]


def _parse_syslog_ts(raw_ts: str) -> datetime | None:
    parts = raw_ts.strip().split()
    if not parts or len(parts[0]) != 3 or not parts[0].isalpha():
        return None

    year = datetime.now().year
    raw_with_year = f"{raw_ts.strip()} {year}"

    for fmt in _SYSLOG_FORMATS:
        try:
            return datetime.strptime(raw_with_year, fmt)
        except ValueError:
            continue

    return None


class TimestampNormalizer:

    @staticmethod
    def normalize_timestamp(raw_ts: str, source_tz: str) -> NormalizedTimestamp:
        if source_tz not in SUPPORTED_TIMEZONES:
            raise ValueError(
                f"Unsupported source_tz '{source_tz}'. "
                f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
            )

        cleaned = raw_ts.strip()

        parsed_dt = None
        for fmt in _FORMAT_CHAIN:
            try:
                parsed_dt = datetime.strptime(cleaned, fmt)
                break
            except ValueError:
                continue

        if parsed_dt is None:
            parsed_dt = _parse_syslog_ts(cleaned)

        if parsed_dt is None:
            raise TimestampParseError(raw_ts, source_tz)

        milliseconds = parsed_dt.microsecond // 1000

        tz_obj = pytz.timezone(source_tz)

        # ── FIXED SAFE TIMEZONE HANDLING ────────────────────────────────
        if cleaned.endswith("Z"):
            utc_dt = pytz.UTC.localize(parsed_dt)
            is_dst_adjusted = False
        else:
            localised_dt = tz_obj.localize(parsed_dt)
            utc_dt = localised_dt.astimezone(pytz.UTC)
            is_dst_adjusted = bool(localised_dt.dst())

        return NormalizedTimestamp(
            utc_datetime=utc_dt,
            source_tz=source_tz,
            milliseconds=milliseconds,
            is_dst_adjusted=is_dst_adjusted,
        )

    @staticmethod
    def normalize_for_source(raw_ts: str, source_label: str) -> NormalizedTimestamp:
        source_tz = get_timezone_for_source(source_label)

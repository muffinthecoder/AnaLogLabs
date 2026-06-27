"""
timestamp_normalizer.py — implements ALGORITHM: NormalizeTimestamp from
Section 4.7.5 of the design document (R3).

Owned by: Hiba
Consumed by: src/parser/log_parser.py (Pooja's module)

Fixes applied for real log data (Week 1 integration):
    - Added Z-suffix ISO 8601 formats (files 2–8: all sign-in CSVs use
      "2026-03-25T03:24:52Z" not "2026-03-25T03:24:52")
    - Added Cisco WLC syslog format (file 1: "Mar 25 09:30:14")
    - Both of these were the bugs Pooja's test_real_data.py was hitting
      because _NORMALIZER_AVAILABLE was True on her machine but the
      normalizer rejected valid timestamps.
"""

from datetime import datetime

import pytz

from src.models.data_classes import NormalizedTimestamp
from src.normaliser.timezone_map import get_timezone_for_source, SUPPORTED_TIMEZONES


class TimestampParseError(Exception):
    """Raised when a raw timestamp string cannot be parsed by any known format.

    Per Section 4.7.5 step 1: 'IF all formats fail: RAISE ParseError with
    raw_ts and source_label'.
    """

    def __init__(self, raw_ts: str, source_label: str):
        self.raw_ts = raw_ts
        self.source_label = source_label
        super().__init__(
            f"Could not parse timestamp '{raw_ts}' for source '{source_label}'. "
            f"No known format matched."
        )


# ---------------------------------------------------------------------------
# Format chain — Section 4.7.5 step 1, extended for real log data.
#
# IMPORTANT ordering rules:
#   1. Z-suffix variants must come BEFORE their non-Z counterparts, because
#      strptime will fail on "2026-03-25T03:24:52Z" if you try the no-Z
#      format first — it would consume "2026-03-25T03:24:52" and leave "Z"
#      unconsumed, raising ValueError. So Z-first is correct.
#   2. Microsecond variants must come before second-only variants for the
#      same reason (parsing "...52.123" with the no-ms format truncates).
#   3. WLC syslog ("Mar 25 09:30:14") has no year component. We handle this
#      with a pre-processing step in normalize_timestamp() below — see the
#      _parse_syslog_ts() helper.
# ---------------------------------------------------------------------------

_FORMAT_CHAIN = [
    # ── ISO 8601 — Z-suffix (files 2–8: all Azure sign-in CSVs) ───────────
    "%Y-%m-%dT%H:%M:%S.%fZ",   # ISO 8601 with microseconds + Z
    "%Y-%m-%dT%H:%M:%SZ",      # ISO 8601 without microseconds + Z

    # ── ISO 8601 — no Z suffix ─────────────────────────────────────────────
    "%Y-%m-%dT%H:%M:%S.%f",    # ISO 8601 with microseconds
    "%Y-%m-%dT%H:%M:%S",       # ISO 8601 without microseconds

    # ── MUPC XLSX (file 6: "2026-03-25T02:59:59.638") ─────────────────────
    # Already covered by "%Y-%m-%dT%H:%M:%S.%f" above — no extra entry needed.

    # ── Common log formats ─────────────────────────────────────────────────
    "%d/%m/%Y %H:%M:%S.%f",    # DD/MM/YYYY with ms
    "%d/%m/%Y %H:%M:%S",       # DD/MM/YYYY without ms
    "%m-%d-%Y %H:%M:%S",       # US format
    "%Y%m%d%H%M%S",            # compact format
]

# WLC syslog has the form "Mar 25 09:30:14" — no year, so we inject the
# current year at parse time.  The three-letter month abbreviation and
# single/double digit day are handled by %b and %d respectively.
_SYSLOG_FORMATS = [
    "%b %d %H:%M:%S %Y",   # "Mar 25 09:30:14 2026" (after year injection)
    "%b  %d %H:%M:%S %Y",  # "Mar  5 09:30:14 2026" (space-padded single-digit day)
]


def _parse_syslog_ts(raw_ts: str) -> datetime | None:
    """Try to parse a Cisco WLC syslog timestamp like "Mar 25 09:30:14".

    Since the year is absent in the raw log line, we inject the current year.
    This is correct for forensic investigation of recent logs (within the same
    calendar year). If logs span a year boundary the caller should note this
    limitation.

    Returns a naive datetime on success, None on failure.
    """
    # Detect syslog format: starts with a three-letter month abbreviation.
    parts = raw_ts.strip().split()
    if not parts or len(parts[0]) != 3 or not parts[0].isalpha():
        return None

    # Inject year — use the year from the first two digits of the timestamp
    # if available, otherwise use datetime.now().year.
    year = datetime.now().year
    raw_with_year = f"{raw_ts.strip()} {year}"

    for fmt in _SYSLOG_FORMATS:
        try:
            return datetime.strptime(raw_with_year, fmt)
        except ValueError:
            continue
    return None


class TimestampNormalizer:
    """Converts raw timestamp strings into UTC-aware NormalizedTimestamp objects."""

    @staticmethod
    def normalize_timestamp(raw_ts: str, source_tz: str) -> NormalizedTimestamp:
        """ALGORITHM: NormalizeTimestamp(raw_ts, source_tz) -> NormalizedTimestamp

        Args:
            raw_ts:     Timestamp string from the raw log row.
            source_tz:  IANA timezone string — one of "Australia/Perth",
                        "Asia/Singapore", "Asia/Dubai".

        Returns:
            NormalizedTimestamp with utc_datetime, milliseconds, source_tz.

        Raises:
            TimestampParseError: if raw_ts matches none of the supported formats.
            ValueError:          if source_tz is not one of the three supported zones.
        """
        if source_tz not in SUPPORTED_TIMEZONES:
            raise ValueError(
                f"Unsupported source_tz '{source_tz}'. "
                f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
            )

        cleaned = raw_ts.strip()

        # ── Step 1: Try the main format chain ─────────────────────────────
        parsed_dt: datetime | None = None
        for fmt in _FORMAT_CHAIN:
            try:
                parsed_dt = datetime.strptime(cleaned, fmt)
                break
            except ValueError:
                continue

        # ── Step 1b: Fallback — try WLC syslog format ─────────────────────
        if parsed_dt is None:
            parsed_dt = _parse_syslog_ts(cleaned)

        if parsed_dt is None:
            raise TimestampParseError(raw_ts=raw_ts, source_label=source_tz)

        # ── Step 2: Extract milliseconds ──────────────────────────────────
        milliseconds = parsed_dt.microsecond // 1000

        # ── Step 3: Attach the source timezone ────────────────────────────
        tz_obj = pytz.timezone(source_tz)
        localised_dt = tz_obj.localize(parsed_dt)

        # ── Step 4: Convert to UTC ────────────────────────────────────────
        utc_dt = localised_dt.astimezone(pytz.UTC)

        # Perth, Singapore, and Dubai do not observe DST, so this is always
        # False for the prototype's supported timezone set.
        is_dst_adjusted = bool(localised_dt.dst())

        return NormalizedTimestamp(
            utc_datetime=utc_dt,
            source_tz=source_tz,
            milliseconds=milliseconds,
            is_dst_adjusted=is_dst_adjusted,
        )

    @staticmethod
    def normalize_for_source(raw_ts: str, source_label: str) -> NormalizedTimestamp:
        """Convenience wrapper — looks up the timezone assigned to a log source
        label, then normalises. This is what LogParser calls.
        """
        source_tz = get_timezone_for_source(source_label)
        return TimestampNormalizer.normalize_timestamp(raw_ts, source_tz)
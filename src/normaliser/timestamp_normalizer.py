"""
Owned by: Pooja

timestamp_normalizer.py — implements ALGORITHM: NormalizeTimestamp from
Section 4.7.5 of the design document (R3).

Consumed by: src/parser/log_parser.py (Pooja's module)

"""

import re
import warnings
from datetime import datetime
import pytz


try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    _PANDAS_AVAILABLE = False

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

# Format chain — Section 4.7.5 step 1, extended for real log data.
#
# NOTE: Z-suffix and numeric-offset formats are intentionally NOT in this
# chain — they are handled exclusively (and correctly) by _try_stdlib_aware()
# / _try_pandas_aware() in Step 0, before this chain ever runs. Adding a
# "%Y-%m-%dT%H:%M:%SZ"-style entry here would be actively dangerous: strptime
# treats a literal "Z" in a format string as text to match, not a timezone
# marker, so it would silently produce a NAIVE result that gets localised to
# source_tz — which is exactly the bug this revision removes.
#
# IMPORTANT ordering rule that still applies: microsecond variants must come
# before second-only variants, or parsing "...52.123" with the no-ms format
# truncates.

_FORMAT_CHAIN = [
    # ISO 8601 — naive (no timezone marker)
    "%Y-%m-%dT%H:%M:%S.%f",    # ISO 8601 with microseconds
    "%Y-%m-%dT%H:%M:%S",       # ISO 8601 without microseconds

    # Common log formats
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

# Explicit, stdlib-parseable formats for a NUMERIC UTC offset, e.g.
# "2026-03-25T03:24:52+04:00" or "...+0400". Deliberately separate from the
# Z-suffix case (handled by string-slicing in _try_stdlib_aware) since %z
# does not accept a literal "Z" character.
_NUMERIC_OFFSET_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
]

_NAIVE_ISO_FORMATS_FOR_Z_STRIP = [
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
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

# Matches a trailing explicit timezone: "Z"/"z", or a "+HH:MM" / "-HHMM" /
# "+HH" numeric offset at the end of the string. Used to decide whether a raw
# timestamp already carries its own timezone (R2 auto-detection) BEFORE handing
# it to pandas — this both avoids unnecessary work on the common naive case and
# sidesteps pandas' dayfirst-ambiguity warning for DD/MM strings, which never
# reach the aware path.
_TZ_AWARE_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2}|[+-]\d{2})$")


def _looks_tz_aware(cleaned: str) -> bool:
    return bool(_TZ_AWARE_RE.search(cleaned))


def _try_stdlib_aware(cleaned: str) -> datetime | None:
    """Pure-stdlib recognition of an explicitly timezone-marked timestamp —
    either a "Z"/"z" suffix or a numeric "+HH:MM"/"+HHMM"/"+HH" offset.

    This is now the AUTHORITATIVE handler for the "Z = UTC" rule: it does not
    depend on pandas being installed. pandas (_try_pandas_aware) is tried
    first purely because it also handles a couple of exotic aware variants
    stdlib doesn't (e.g. a space instead of "T"), but if pandas is missing OR
    fails, this function still guarantees a "Z"-suffixed or explicitly-offset
    timestamp is recognised correctly rather than silently falling through to
    the naive format chain and being mis-localised to source_tz.

    Returns a timezone-AWARE datetime, or None if `cleaned` doesn't match a
    recognised aware pattern at all.
    """
    if cleaned.endswith("Z") or cleaned.endswith("z"):
        naive_part = cleaned[:-1]
        for fmt in _NAIVE_ISO_FORMATS_FOR_Z_STRIP:
            try:
                naive_dt = datetime.strptime(naive_part, fmt)
                return naive_dt.replace(tzinfo=pytz.UTC)
            except ValueError:
                continue
        return None

    for fmt in _NUMERIC_OFFSET_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    return None


def _try_pandas_aware(cleaned: str) -> datetime | None:
    """Secondary/enhancement path for an explicitly timezone-marked
    timestamp, tried before _try_stdlib_aware() since pandas can recognise a
    couple of aware variants stdlib's strptime chains above don't (e.g. a
    space separator instead of "T"). NOT relied upon as the sole handler for
    the common "Z" case — see _try_stdlib_aware()'s docstring for why.

    Returns None when pandas is unavailable, the string doesn't look
    tz-aware, it can't be parsed, or the parsed value is naive.
    """
    if not _PANDAS_AVAILABLE or not _looks_tz_aware(cleaned):
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ts = pd.to_datetime(cleaned)
    except Exception:
        return None
    # pandas returns a NaT for unparseable input, and NaT.tzinfo is None.
    if ts is None or pd.isna(ts):
        return None
    if getattr(ts, "tzinfo", None) is None:
        return None  # naive — not an embedded-offset timestamp
    return ts.to_pydatetime()


def _try_pandas_naive(cleaned: str) -> datetime | None:
    """Last-resort parse for a naive timestamp the strptime chain and the
    syslog fallback both missed. dayfirst=True matches the client's log
    conventions (DD/MM/YYYY), and utc=False keeps the result naive so the
    caller can localise it with the correct SOURCE timezone.
    """
    if not _PANDAS_AVAILABLE:
        return None
    try:
        with warnings.catch_warnings():
            # Format is genuinely unknown at this last-resort stage, so the
            # dayfirst-ambiguity warning is expected noise — suppress it.
            warnings.simplefilter("ignore")
            ts = pd.to_datetime(cleaned, dayfirst=True)
    except Exception:
        return None
    if ts is None or pd.isna(ts):
        return None
    if getattr(ts, "tzinfo", None) is not None:
        # Shouldn't happen (aware case is handled earlier) but guard anyway.
        return None
    return ts.to_pydatetime()


class TimestampNormalizer:
    """Converts raw timestamp strings into UTC-aware NormalizedTimestamp objects."""

    @staticmethod
    def normalize_timestamp(raw_ts: str, source_tz: str) -> NormalizedTimestamp:
        """ALGORITHM: NormalizeTimestamp(raw_ts, source_tz) -> NormalizedTimestamp

        Args:
            raw_ts:     Timestamp string from the raw log row.
            source_tz:  IANA timezone string assumed for timestamps with NO
                        explicit timezone marker (see module docstring —
                        defaults to Perth per R2).

        Returns:
            NormalizedTimestamp with utc_datetime, milliseconds, source_tz.

        Raises:
            TimestampParseError: if raw_ts matches none of the supported formats.
            ValueError:          if source_tz is not a supported zone.
        """
        if source_tz not in SUPPORTED_TIMEZONES:
            raise ValueError(
                f"Unsupported source_tz '{source_tz}'. "
                f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
            )

        cleaned = raw_ts.strip()

        # Step 0: Auto-detect an embedded timezone (R2)
        # If the raw string already specifies its own offset ("...Z" or
        # "+04:00"), that offset is authoritative — convert straight to UTC
        # and do NOT re-localise using source_tz. _try_stdlib_aware() is the
        # guaranteed-correct handler for this (works with or without
        # pandas); _try_pandas_aware() is tried first only as an enhancement
        # for a couple of exotic aware variants stdlib doesn't cover.
        aware_dt = _try_pandas_aware(cleaned)
        if aware_dt is None:
            aware_dt = _try_stdlib_aware(cleaned)
        if aware_dt is not None:
            utc_dt = aware_dt.astimezone(pytz.UTC)
            return NormalizedTimestamp(
                utc_datetime=utc_dt,
                source_tz=source_tz,
                milliseconds=utc_dt.microsecond // 1000,
                is_dst_adjusted=False,
            )

        #  Step 1: Try the main strptime format chain (naive formats only)
        parsed_dt: datetime | None = None
        for fmt in _FORMAT_CHAIN:
            try:
                parsed_dt = datetime.strptime(cleaned, fmt)
                break
            except ValueError:
                continue

        # Step 1b: Fallback — try WLC syslog format
        if parsed_dt is None:
            parsed_dt = _parse_syslog_ts(cleaned)

        # Step 1c: Last resort — let pandas try (R2 "use pandas")
        # Catches naive formats not in _FORMAT_CHAIN (e.g. "2026-03-25
        # 03:24" without seconds, or locale variants) before giving up.
        if parsed_dt is None:
            parsed_dt = _try_pandas_naive(cleaned)

        if parsed_dt is None:
            raise TimestampParseError(raw_ts=raw_ts, source_label=source_tz)

        # Step 2: Extract milliseconds
        milliseconds = parsed_dt.microsecond // 1000

        # Step 3: Attach the source timezone
        # Only reached for a genuinely NAIVE timestamp (no "Z", no numeric
        # offset — those are both handled and returned in Step 0 above).
        # localize() correctly resolves the DST offset for the DST-observing
        # Australian zones now in SUPPORTED_TIMEZONES; is_dst=False (pytz
        # default) is a safe deterministic choice for the rare ambiguous
        # fall-back hour in forensic logs.
        tz_obj = pytz.timezone(source_tz)
        localised_dt = tz_obj.localize(parsed_dt)

        # Step 4: Convert to UTC
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
        """Convenience wrapper — looks up the timezone assigned to a log source
        label, then normalises. This is what LogParser calls.
        """
        source_tz = get_timezone_for_source(source_label)
        return TimestampNormalizer.normalize_timestamp(raw_ts, source_tz)

    @staticmethod
    def renormalize_entries(entries: list, source_tz: str) -> list:
        """Re-derives every entry's UTC value by re-parsing its ORIGINAL raw
        timestamp under a new source timezone (Section 2.1 — changing the
        "Original timezone" control).

        RawLogEntry is frozen, so this returns a NEW list of entries with
        refreshed normalized_timestamp. Rows whose raw timestamp carried an
        explicit offset are unaffected (auto-detection ignores source_tz for
        them); rows that now fail to parse get normalized_timestamp=None.
        """
        from dataclasses import replace

        out = []
        for entry in entries:
            try:
                nts = TimestampNormalizer.normalize_timestamp(entry.raw_timestamp, source_tz)
            except TimestampParseError:
                nts = None
            out.append(replace(entry, normalized_timestamp=nts))
        return out
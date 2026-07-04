"""
timezone_map.py — maps log source labels to their IANA timezone string, and
holds the list of timezones the investigator can VIEW logs in.

Two distinct concepts live here (they used to be conflated):

  1. SOURCE timezone  — the timezone a log file's raw timestamps are assumed
     to have been AUTHORED in. Per the client requirement (R2), imported logs
     are assumed to be Perth local time unless the raw timestamp itself carries
     an explicit offset (e.g. an ISO-8601 "Z" or "+04:00"), in which case
     TimestampNormalizer auto-detects and uses that instead. This is what
     DEFAULT_TIMEZONE controls.

  2. DISPLAY timezone  — the timezone the investigator wants to READ times in
     (R3). This is chosen from the top-nav dropdown and can be any zone in
     SUPPORTED_TIMEZONES. It never changes the stored UTC value, only how it
     is rendered (see LogTableModel.format_timestamp).

The supported set now spans the major Australian cities plus Dubai and
Singapore (R3). Note that unlike the original three-zone prototype, several of
these (Sydney/Melbourne/Adelaide) DO observe daylight saving — pytz.localize()
handles the DST offset correctly, so no special-casing is needed here.
"""

from datetime import datetime

# Ordered so the dropdown reads Australia-first (the client's primary region),
# then the two Asia/Gulf offices. Keys are IANA names; values are the
# human-readable labels shown in the UI, including the UTC offset range (R3
# "add offset time range").
SUPPORTED_TIMEZONES = {
    "UTC":                 "UTC (UTC+0)",
    "Australia/Perth":     "Perth (AWST, UTC+8)",
    "Australia/Adelaide":  "Adelaide (ACST/ACDT, UTC+9:30/+10:30)",
    "Australia/Darwin":    "Darwin (ACST, UTC+9:30)",
    "Australia/Brisbane":  "Brisbane (AEST, UTC+10)",
    "Australia/Sydney":    "Sydney (AEST/AEDT, UTC+10/+11)",
    "Australia/Melbourne": "Melbourne (AEST/AEDT, UTC+10/+11)",
    "Asia/Dubai":          "Dubai (GST, UTC+4)",
    "Asia/Singapore":      "Singapore (SGT, UTC+8)",
}

# Maps a log SOURCE LABEL (filename-derived, e.g. "Interactive_signin") to the
# IANA timezone the raw timestamps in that file are assumed to be authored in.
# Populated by set_timezone_for_source() if the investigator ever overrides a
# specific file's source zone; otherwise every source falls back to
# DEFAULT_TIMEZONE below.
SOURCE_TIMEZONE_ASSIGNMENTS: dict[str, str] = {}

# R2 — imported logs are assumed to be Perth local time by default (changed
# from the old Dubai default). Perth (AWST, UTC+8, no DST) is the client's
# primary operating timezone.
DEFAULT_TIMEZONE = "Australia/Perth"

# The currently-selected GLOBAL original/source timezone — what the top bar's
# "Original timezone" control sets (Section 2.1). Starts at Perth; the
# investigator can change it, which re-parses every loaded row's raw timestamp
# against the new zone. Kept separate from the immutable DEFAULT_TIMEZONE so a
# reset is always possible.
_CURRENT_DEFAULT_SOURCE_TZ = DEFAULT_TIMEZONE


def set_default_source_timezone(iana_timezone: str) -> None:
    """Sets the global original/source timezone applied to files that don't
    have an explicit per-file override (Section 2.1).
    """
    if iana_timezone not in SUPPORTED_TIMEZONES:
        raise ValueError(
            f"Unsupported timezone '{iana_timezone}'. "
            f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
        )
    global _CURRENT_DEFAULT_SOURCE_TZ
    _CURRENT_DEFAULT_SOURCE_TZ = iana_timezone


def get_default_source_timezone() -> str:
    return _CURRENT_DEFAULT_SOURCE_TZ


def get_timezone_for_source(source_label: str) -> str:
    """Returns the IANA source timezone assigned to a given log source.

    Falls back to the current global original timezone (Perth unless changed)
    if the investigator has not set a per-file override.
    """
    return SOURCE_TIMEZONE_ASSIGNMENTS.get(source_label, _CURRENT_DEFAULT_SOURCE_TZ)


def set_timezone_for_source(source_label: str, iana_timezone: str) -> None:
    """Assigns a SOURCE (authoring) timezone to a log source.

    This affects how TimestampNormalizer interprets that source's raw naive
    timestamps at parse time — it is NOT the display timezone (see module
    docstring). Kept for completeness / future per-file overrides.
    """
    if iana_timezone not in SUPPORTED_TIMEZONES:
        raise ValueError(
            f"Unsupported timezone '{iana_timezone}'. "
            f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
        )
    SOURCE_TIMEZONE_ASSIGNMENTS[source_label] = iana_timezone


def display_label_for_timezone(iana_timezone: str) -> str:
    """Returns the human-readable label, e.g. 'Dubai (GST, UTC+4)'."""
    return SUPPORTED_TIMEZONES.get(iana_timezone, iana_timezone)


def utc_offset_label(iana_timezone: str, at: datetime | None = None) -> str:
    """Returns a compact current UTC-offset badge for a zone, e.g. "UTC+8"
    or "UTC+9:30".

    Computed against `at` (defaults to now) so DST-observing zones report
    their currently-effective offset. Used for the per-panel timezone badge
    and the dropdown so the investigator always sees the live offset (R3).
    """
    try:
        import pytz
        tz = pytz.timezone(iana_timezone)
        offset = tz.utcoffset(at or datetime.now())
    except Exception:
        return "UTC"

    if offset is None:
        return "UTC"

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def detect_system_timezone() -> str | None:
    """Best-effort auto-detection of the machine's local IANA timezone (R2
    "check if auto detect can work with our system").

    Tries tzlocal first (most reliable), then Python's own zoneinfo/datetime
    resolution. Returns an IANA name only if it is one we actually support,
    otherwise None so callers can fall back to DEFAULT_TIMEZONE rather than
    silently using an unsupported zone.
    """
    candidate: str | None = None

    # 1) tzlocal, if the optional dependency is present.
    try:
        import tzlocal
        candidate = str(tzlocal.get_localzone_name())
    except Exception:
        candidate = None

    # 2) Fall back to the stdlib's local tzinfo key (Python 3.9+ zoneinfo).
    if not candidate:
        try:
            local_tz = datetime.now().astimezone().tzinfo
            key = getattr(local_tz, "key", None)  # ZoneInfo exposes .key
            candidate = str(key) if key else None
        except Exception:
            candidate = None

    if candidate and candidate in SUPPORTED_TIMEZONES:
        return candidate
    return None

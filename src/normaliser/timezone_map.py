"""
timezone_map.py — maps log source labels to their IANA timezone string.

Per Section 4.7.5 of the design document (Phase 1 expansion), AnaLog Labs now
supports nine timezones:
    Perth      -> Australia/Perth      (no DST)
    Singapore  -> Asia/Singapore       (no DST)
    Dubai      -> Asia/Dubai           (no DST)
    UTC        -> UTC                  (no DST, by definition)
    Adelaide   -> Australia/Adelaide   (observes DST)
    Darwin     -> Australia/Darwin     (no DST)
    Brisbane   -> Australia/Brisbane   (no DST)
    Melbourne  -> Australia/Melbourne  (observes DST)
    Sydney     -> Australia/Sydney     (observes DST)

Three of the Australian zones (Adelaide, Melbourne, Sydney) observe daylight
saving time, which the original three-zone prototype never had to handle.
Anywhere a UTC offset is shown to the investigator (the per-panel timezone
badge, the dashboard timeline chart's x-axis, etc.) MUST compute that offset
against the actual date being displayed — never against "today" — or the
offset will be silently wrong for entries that fall in a different DST period
than the moment the app happens to be running in. get_utc_offset_label() below
is the single shared implementation of that calculation; every UI surface
that needs to show a live UTC+X value should call it rather than
recalculating its own.
"""

from datetime import datetime

import pytz

SUPPORTED_TIMEZONES = {
    "Australia/Perth": "Australia (Perth)",
    "Asia/Singapore": "Singapore",
    "Asia/Dubai": "United Arab Emirates (Dubai)",
    "UTC": "UTC",
    "Australia/Adelaide": "Australia (Adelaide)",
    "Australia/Darwin": "Australia (Darwin)",
    "Australia/Brisbane": "Australia (Brisbane)",
    "Australia/Melbourne": "Australia (Melbourne)",
    "Australia/Sydney": "Australia (Sydney)",
}

# Maps a log SOURCE LABEL (filename-derived, e.g. "Interactive_signin") to the
# IANA timezone the investigator has assigned to it.
#
# TODO (Hiba/Fatima — UI wiring):
#   This dict should be populated/updated when the investigator picks a
#   timezone per log file (Section 6.3.4 Zone 1, Timezone dropdown). For the
#   prototype, every source defaults to Perth unless explicitly set.
SOURCE_TIMEZONE_ASSIGNMENTS: dict[str, str] = {}

DEFAULT_TIMEZONE = "Australia/Perth"


def get_timezone_for_source(source_label: str) -> str:
    """Returns the IANA timezone string assigned to a given log source.

    Falls back to DEFAULT_TIMEZONE if the investigator has not explicitly
    assigned one yet.
    """
    return SOURCE_TIMEZONE_ASSIGNMENTS.get(source_label, DEFAULT_TIMEZONE)


def set_timezone_for_source(source_label: str, iana_timezone: str) -> None:
    """Assigns a timezone to a log source. Called when the investigator
    selects a timezone for a specific loaded log (Section 6.3.4 Zone 1).
    """
    if iana_timezone not in SUPPORTED_TIMEZONES:
        raise ValueError(
            f"Unsupported timezone '{iana_timezone}'. "
            f"Must be one of: {list(SUPPORTED_TIMEZONES.keys())}"
        )
    SOURCE_TIMEZONE_ASSIGNMENTS[source_label] = iana_timezone


def get_utc_offset_seconds(iana_timezone: str, reference_dt: datetime | None = None) -> int:
    """Returns the UTC offset, in seconds, for iana_timezone AT reference_dt
    — not at "now". This is the single shared implementation every UI
    surface (panel badges, the timeline chart's x-axis, etc.) should call
    rather than each computing its own offset, since getting this wrong is
    exactly how the old "offset computed from today's date instead of the
    log data's date" bug happened for DST-observing zones in the first place.

    Args:
        iana_timezone: an IANA zone string, e.g. "Australia/Sydney".
        reference_dt: a datetime (naive or aware) representing the moment
            whose offset we want — normally a timestamp from the log data
            actually being viewed, NOT datetime.utcnow()/datetime.now().
            Defaults to the current moment only when no better reference is
            available (e.g. populating a dropdown before any file is
            loaded), since no log data exists yet to anchor the offset to.
    """
    try:
        tz_obj = pytz.timezone(iana_timezone)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone("Asia/Dubai")

    if reference_dt is None:
        reference_dt = datetime.utcnow()

    # utcoffset() needs a naive datetime interpreted as "wall clock time in
    # this zone" — if reference_dt is already tz-aware, convert it to naive
    # local wall-clock time in tz_obj first so pytz resolves DST correctly
    # for that exact instant rather than misinterpreting an aware datetime.
    if reference_dt.tzinfo is not None:
        local_dt = reference_dt.astimezone(tz_obj)
        naive_local = local_dt.replace(tzinfo=None)
    else:
        naive_local = reference_dt

    offset = tz_obj.utcoffset(naive_local)
    return int(offset.total_seconds())


def get_utc_offset_label(iana_timezone: str, reference_dt: datetime | None = None) -> str:
    """Returns a computed "UTC+X" / "UTC-X" string for iana_timezone, valid
    AT reference_dt — not at "now". This matters for the three DST-observing
    zones (Adelaide, Melbourne, Sydney): their offset genuinely differs
    between DST and standard time, so a fixed hardcoded string (the old
    approach for the original three no-DST zones) would be wrong for roughly
    half the year.

    Returns:
        "UTC+4", "UTC+11", "UTC+9:30" (half-hour offsets render the minutes),
        or "UTC" for a zero offset.
    """
    total_minutes = get_utc_offset_seconds(iana_timezone, reference_dt) // 60

    if total_minutes == 0:
        return "UTC"

    sign = "+" if total_minutes > 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def display_label_for_timezone(iana_timezone: str, reference_dt: datetime | None = None) -> str:
    """Returns the human-readable label combining the full country/city name
    with a computed, DST-correct UTC offset, e.g. "Australia (Sydney), UTC+11".

    reference_dt should be a timestamp from the actual log data being shown
    wherever possible (see get_utc_offset_label's docstring) so DST-observing
    zones render the correct offset for the period actually being viewed.
    """
    country_name = SUPPORTED_TIMEZONES.get(iana_timezone, iana_timezone)
    offset_label = get_utc_offset_label(iana_timezone, reference_dt)
    return f"{country_name}, {offset_label}"
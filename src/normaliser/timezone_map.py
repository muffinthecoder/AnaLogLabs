"""
timezone_map.py — maps log source labels to their IANA timezone string.

Per Section 4.7.5 of the design document, AnaLog Labs supports exactly three
source timezones for this prototype:
    Perth      -> Australia/Perth   (AWST, UTC+8, no DST)
    Singapore  -> Asia/Singapore    (SGT,  UTC+8, no DST)
    Dubai      -> Asia/Dubai        (GST,  UTC+4, no DST)

None of these three zones observe daylight saving time, which simplifies
normalisation considerably (no DST transition edge cases to handle for the
prototype scope).
"""

SUPPORTED_TIMEZONES = {
    "Australia/Perth": "Perth (AWST, UTC+8)",
    "Asia/Singapore": "Singapore (SGT, UTC+8)",
    "Asia/Dubai": "Dubai (GST, UTC+4)",
}

# Maps a log SOURCE LABEL (filename-derived, e.g. "Interactive_signin") to the
# IANA timezone the investigator has assigned to it.
#
# TODO (Hiba/Fatima — UI wiring):
#   This dict should be populated/updated when the investigator picks a
#   timezone per log file (Section 6.3.4 Zone 1, Timezone dropdown). For the
#   prototype, every source defaults to Dubai unless explicitly set.
SOURCE_TIMEZONE_ASSIGNMENTS: dict[str, str] = {}

DEFAULT_TIMEZONE = "Asia/Dubai"


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


def display_label_for_timezone(iana_timezone: str) -> str:
    """Returns the human-readable label, e.g. 'Dubai (GST, UTC+4)'."""
    return SUPPORTED_TIMEZONES.get(iana_timezone, iana_timezone)

"""
Data model classes for AnaLog Labs.

These dataclasses mirror Section 4.6 (Class Diagram and Data Dictionary) of the
System Design document exactly. They are intentionally immutable where the design
doc specifies "dataclass" (RawLogEntry, NormalizedTimestamp, CorrelatedEvent) and
left as plain mutable classes elsewhere (FilterConfig, LogFile).

All datetime attributes are timezone-aware (UTC). Naive datetimes must never be
used anywhere in this system per the design doc's class diagram assumptions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# LogFile
# ---------------------------------------------------------------------------
@dataclass
class LogFile:
    """Represents a single imported log file on disk."""

    file_path: str
    file_format: str  # "csv" | "xlsx" | "txt"
    source_label: str
    is_read_only: bool = True

    def __post_init__(self) -> None:
        if self.file_format not in ("csv", "xlsx", "txt"):
            raise ValueError(f"Unsupported file_format: {self.file_format}")


# ---------------------------------------------------------------------------
# NormalizedTimestamp
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NormalizedTimestamp:
    """UTC-normalised timestamp with original timezone preserved for display."""

    utc_datetime: datetime
    source_tz: str  # "Australia/Perth" | "Asia/Singapore" | "Asia/Dubai"
    milliseconds: int  # 0-999
    is_dst_adjusted: bool = False

    # TODO (R3 — Section 4.7.5 NormalizeTimestamp):
    #   Hiba — this object is produced by TimestampNormalizer.normalize_timestamp().
    #   Do not construct this directly anywhere else in the codebase.


# ---------------------------------------------------------------------------
# RawLogEntry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RawLogEntry:
    """A single parsed row from a log file, before or after normalisation."""

    source_label: str
    raw_timestamp: str
    fields: dict
    row_index: int
    is_valid: bool = True
    normalized_timestamp: Optional[NormalizedTimestamp] = None

    # TODO (R1, R2 — Section 4.7.1 ImportAndParse):
    #   Hiba — produced by LogParser. fields must contain every column from the
    #   source row with no truncation (per design doc constraint).


# ---------------------------------------------------------------------------
# FilterConfig
# ---------------------------------------------------------------------------
@dataclass
class FilterConfig:
    """Investigator-defined investigation timeframe."""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: str = "Asia/Dubai"
    use_ms_precision: bool = False

    def is_valid(self) -> bool:
        # TODO (R4 — Section 4.7.2 ApplyFilter step 1):
        #   Fatima — wire this into TimeFrameSelector's Apply Filter button.
        #   Must return False if start_time is None, end_time is None, or
        #   start_time >= end_time.
        if self.start_time is None or self.end_time is None:
            return False
        return self.start_time < self.end_time


# ---------------------------------------------------------------------------
# CorrelatedEvent
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CorrelatedEvent:
    """A group of related RawLogEntry objects across one or more log sources."""

    group_id: str
    entries: tuple  # tuple[RawLogEntry, ...] — minimum 2 entries
    correlation_basis: str  # "time" | "ip" | "username" | "merged"
    timestamp_range: tuple  # tuple[datetime, datetime]

    # TODO (R13 — Section 4.7.4 Correlate):
    #   Fatima — produced by EventCorrelator.correlate(). Used directly by
    #   InvestigationDashboard's "Correlated Events List" subsection.


# ---------------------------------------------------------------------------
# EventCorrelator (config holder — logic lives in src/correlator/ later)
# ---------------------------------------------------------------------------
@dataclass
class EventCorrelator:
    """Holds correlation configuration. Actual correlation logic is a
    placeholder in src/correlator/event_correlator.py (Section 4.7.4)."""

    proximity_threshold: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    entries: list = field(default_factory=list)

"""
log_parser.py — implements ALGORITHM: ImportAndParse from Section 4.7.1 of
the design document (R1, R2, R3), steps 1 through 4.

Step 5 (chronological merge) lives in src/correlator/timeline_merger.py
(Hiba's module) since it operates across sources, not within a single
LogParser.parse_file() call.

Owned by: Pooja
Depends on: src/normaliser/timestamp_normalizer.py (Hiba's module)
"""

from pathlib import Path

from src.models.data_classes import LogFile, RawLogEntry
from src.normaliser.timestamp_normalizer import TimestampNormalizer, TimestampParseError
from src.parser.csv_parser import parse_csv
from src.parser.xlsx_parser import parse_xlsx
from src.parser.txt_parser import parse_txt


# Canonical field names that every log source is mapped to, regardless of
# its original column headers. Required fields must be present (after
# mapping) for a row to be considered valid.
REQUIRED_FIELDS = {"timestamp"}

# Maps known raw column header variants -> canonical field name. Extend
# this as new log source schemas are confirmed by the client (Mike).
#
# TODO (Pooja/Hiba — confirm against real sample logs once provided):
#   These mappings are best-effort guesses based on the R&A document's
#   listed log sources (Interactive Sign-In, MUPC, WLC). Update once real
#   column headers are confirmed against actual exported files.
_FIELD_NAME_ALIASES = {
    # timestamp variants
    "timestamp": "timestamp",
    "time": "timestamp",
    "event_time": "timestamp",
    "datetime": "timestamp",
    # username variants
    "username": "username",
    "user": "username",
    "account": "username",
    "account_name": "username",
    # ip address variants
    "ip_address": "ip_address",
    "ip": "ip_address",
    "source_ip": "ip_address",
    "client_ip": "ip_address",
    # status variants
    "status": "status",
    "result": "status",
    "outcome": "status",
}


class ParsedFileResult:
    """Return value of LogParser.parse_file() — bundles valid entries with
    error/skip reporting, per Section 4.7.1's error handling note: 'the
    count of skipped rows is reported to the user'.
    """

    def __init__(self, source_label: str):
        self.source_label = source_label
        self.valid_entries: list[RawLogEntry] = []
        self.skipped_count: int = 0
        self.skip_reasons: list[str] = []

    def __repr__(self) -> str:
        return (
            f"ParsedFileResult(source_label={self.source_label!r}, "
            f"valid={len(self.valid_entries)}, skipped={self.skipped_count})"
        )


class LogParser:
    """Implements Section 4.7.1 steps 1-4: file detection, format-specific
    parsing, field mapping, row validation, and timestamp normalization.
    """

    @staticmethod
    def create_log_file(file_path: str) -> LogFile:
        """Section 4.7.1 step 1:
            'Create LogFile(file_path), Detect format from extension
            (.csv / .xlsx / .txt), Mark file as read-only, Assign
            source_label from filename (strip extension)'
        """
        path = Path(file_path)
        extension = path.suffix.lower().lstrip(".")

        if extension not in ("csv", "xlsx", "txt"):
            raise ValueError(
                f"Unsupported file extension '.{extension}'. "
                f"AnaLog Labs only supports .csv, .xlsx, and .txt log files."
            )

        source_label = path.stem  # filename without extension

        return LogFile(
            file_path=str(path),
            file_format=extension,
            source_label=source_label,
            is_read_only=True,
        )

    @staticmethod
    def _map_fields(raw_row: dict) -> dict:
        """Section 4.7.1 step 3: '_map_fields(row) - map raw column names
        to canonical field names'.

        Matching is case-insensitive and ignores surrounding whitespace in
        the original header. Any column that doesn't match a known alias
        is kept under its original (lowercased) key so no data is silently
        dropped — it just won't be treated as a canonical field for
        filtering/correlation purposes.
        """
        mapped = {}
        for raw_key, value in raw_row.items():
            normalised_key = raw_key.strip().lower().replace(" ", "_")
            canonical_key = _FIELD_NAME_ALIASES.get(normalised_key, normalised_key)
            mapped[canonical_key] = value
        return mapped

    @staticmethod
    def _validate_row(mapped_row: dict) -> tuple[bool, str | None]:
        """Section 4.7.1 step 3: '_validate_row(row)'.

        Returns:
            (is_valid, reason) — reason is None if is_valid is True.
        """
        timestamp_value = mapped_row.get("timestamp", "")
        if not timestamp_value or not str(timestamp_value).strip():
            return False, "Missing timestamp field"

        missing_required = REQUIRED_FIELDS - set(
            k for k, v in mapped_row.items() if v not in (None, "")
        )
        if missing_required:
            return False, f"Missing required field(s): {', '.join(missing_required)}"

        return True, None

    @classmethod
    def parse_file(cls, file_path: str) -> ParsedFileResult:
        """Parses a single log file end to end: format detection, raw
        parsing, field mapping, validation, and timestamp normalization.

        This corresponds to Section 4.7.1 steps 1-4 for ONE file. The
        caller (typically MainWindow._on_import_logs) is responsible for
        looping over multiple files and merging results via
        TimelineMerger.merge_chronological().

        Returns:
            ParsedFileResult containing valid RawLogEntry objects plus
            skip/error reporting.
        """
        log_file = cls.create_log_file(file_path)
        result = ParsedFileResult(source_label=log_file.source_label)

        # Step 2 — dispatch to the correct format-specific parser.
        if log_file.file_format == "csv":
            raw_rows = parse_csv(log_file.file_path)
        elif log_file.file_format == "xlsx":
            raw_rows = parse_xlsx(log_file.file_path)
        elif log_file.file_format == "txt":
            raw_rows = parse_txt(log_file.file_path)
        else:
            # create_log_file already validates this, so this branch should
            # be unreachable, but fail loudly if it ever happens.
            raise ValueError(f"Unhandled file_format: {log_file.file_format}")

        # Step 3 — map fields, validate, build entries.
        for row_index, raw_row in enumerate(raw_rows):
            mapped_row = cls._map_fields(raw_row)
            is_valid, reason = cls._validate_row(mapped_row)

            if not is_valid:
                result.skipped_count += 1
                result.skip_reasons.append(f"Row {row_index}: {reason}")
                continue

            entry = RawLogEntry(
                source_label=log_file.source_label,
                raw_timestamp=str(mapped_row.get("timestamp", "")),
                fields=mapped_row,
                row_index=row_index,
                is_valid=True,
                normalized_timestamp=None,  # filled in below
            )

            # Step 4 — normalize the timestamp via Hiba's module.
            try:
                normalized = TimestampNormalizer.normalize_for_source(
                    raw_ts=entry.raw_timestamp,
                    source_label=entry.source_label,
                )
            except TimestampParseError as exc:
                result.skipped_count += 1
                result.skip_reasons.append(f"Row {row_index}: {exc}")
                continue

            # RawLogEntry is frozen, so rebuild it with the normalized
            # timestamp attached rather than mutating in place.
            entry = RawLogEntry(
                source_label=entry.source_label,
                raw_timestamp=entry.raw_timestamp,
                fields=entry.fields,
                row_index=entry.row_index,
                is_valid=True,
                normalized_timestamp=normalized,
            )

            result.valid_entries.append(entry)

        return result

    @classmethod
    def parse_files(cls, file_paths: list[str]) -> list[ParsedFileResult]:
        """Parses multiple files, one ParsedFileResult per file. Does NOT
        merge across sources — call TimelineMerger.merge_chronological() on
        the combined valid_entries afterwards for the unified timeline (R2).
        """
        return [cls.parse_file(path) for path in file_paths]

"""
Owned by: Pooja
log_parser.py — implements ALGORITHM: ImportAndParse from Section 4.7.1.

"""

from pathlib import Path
from src.parser.csv_parser import parse_csv, MalformedFileError
from src.parser.xlsx_parser import parse_xlsx
from src.parser.txt_parser import parse_txt
from src.models.data_classes import LogFile, RawLogEntry
from src.correlator.timeline_merger import TimelineMerger

"""
from src.models.data_classes import LogFile, RawLogEntry
from csv_parser import parse_csv, MalformedFileError
from xlsx_parser import parse_xlsx
from txt_parser import parse_txt
"""


# Imported here once it exists; until then normalization is skipped and
# normalized_timestamp is left as None. The try/except block in parse_file()
# handles ImportError gracefully so the rest of the pipeline still runs.
try:
    from src.normaliser.timestamp_normalizer import TimestampNormalizer, TimestampParseError
    _NORMALIZER_AVAILABLE = True
except ImportError:
    TimestampNormalizer = None
    TimestampParseError = None
    _NORMALIZER_AVAILABLE = False

REQUIRED_FIELDS = {"timestamp"}

# Maps every known raw column header -> canonical field name.
# Covers all 8 log sources confirmed from the client (Mike) briefing.
_FIELD_NAME_ALIASES = {
    # Timestamp variants
    "timestamp":                    "timestamp",
    "time":                         "timestamp",
    "date_utc":                     "timestamp",
    "date":                         "timestamp",
    "event_time":                   "timestamp",
    "datetime":                     "timestamp",

    # Username / identity variants
    "username":                     "username",
    "user":                         "username",
    "user_username":                "username",
    "account":                      "username",
    "account_name":                 "username",
    "service_principal_name":       "username",   # App/MSI sign-in logs

    # IP address variants
    "ip_address":                   "ip_address",
    "ip":                           "ip_address",
    "source_ip":                    "ip_address",
    "client_ip":                    "ip_address",
    "ip_address_seen_by_resource":  "ip_address",

    # Status / result variants
    "status":                       "status",
    "result":                       "status",
    "outcome":                      "status",
    "succeeded":                    "status",     # Auth details CSVs

    # Application / resource
    "application":                  "application",
    "resource":                     "resource",

    # Device / client info
    "device_id":                    "device_id",
    "client_app":                   "client_app",
    "browser":                      "browser",
    "operating_system":             "operating_system",
    "user_agent":                   "user_agent",

    # MFA
    "multifactor_authentication_result":      "mfa_result",
    "multifactor_authentication_auth_method": "mfa_method",

    # Conditional access
    "conditional_access":           "conditional_access",

    # WLC-specific (parsed from syslog freetext by txt_parser)
    "mac":                          "mac_address",
    "ssid":                         "ssid",
    "ap":                           "access_point",

    # MUPC (MDE) specific
    "machine_id":                   "device_id",
    "computer_name":                "hostname",
    "action_type":                  "action_type",
    "file_name":                    "file_name",
    "folder_path":                  "folder_path",
    "sha1":                         "sha1",
    "sha256":                       "sha256",
    "md5":                          "md5",
    "process_command_line":         "process_command_line",
    "account_domain":               "account_domain",
    "account_sid":                  "account_sid",
    "logon_id":                     "logon_id",
    "process_id":                   "process_id",
    "remote_ip":                    "ip_address",
    "remote_port":                  "remote_port",
    "local_ip":                     "local_ip",
    "local_port":                   "local_port",
    "remote_url":                   "remote_url",
    "remote_computer_name":         "remote_hostname",
    "initiating_process_file_name": "initiating_process",
    "initiating_process_account_name": "initiating_account",
    "initiating_process_command_line": "initiating_command",
    "report_id":                    "report_id",
    "alert_ids":                    "alert_ids",
    "categories":                   "categories",
    "severities":                   "severities",
    "protocol":                     "protocol",
    "logon_type":                   "logon_type",
}


class ParsedFileResult:
    def __init__(self, source_label: str):
        self.source_label = source_label
        self.valid_entries: list[RawLogEntry] = []
        self.skipped_count: int = 0
        self.skip_reasons: list[str] = []
        self.file_error: str | None = None   # set if the whole file fails

    def __repr__(self) -> str:
        return (
            f"ParsedFileResult(source_label={self.source_label!r}, "
            f"valid={len(self.valid_entries)}, skipped={self.skipped_count}, "
            f"file_error={self.file_error!r})"
        )

    @property
    def failed(self) -> bool:
        """True if the entire file could not be parsed at all."""
        return self.file_error is not None


class LogParser:

    @staticmethod
    def create_log_file(file_path: str) -> LogFile:
        path = Path(file_path)
        extension = path.suffix.lower().lstrip(".")

        if extension not in ("csv", "xlsx", "txt"):
            raise ValueError(
                f"Unsupported file extension '.{extension}'. "
                f"AnaLog Labs supports .csv, .xlsx, and .txt only."
            )

        return LogFile(
            file_path=str(path),
            file_format=extension,
            source_label=path.stem,
            is_read_only=True,
        )

    @staticmethod
    def _map_fields(raw_row: dict) -> dict:
        mapped = {}
        for raw_key, value in raw_row.items():
            normalised_key = (
                raw_key.strip()
                .lower()
                .replace("(", "")
                .replace(")", "")
                .replace(" ", "_")
            )
            canonical_key = _FIELD_NAME_ALIASES.get(normalised_key, normalised_key)
            mapped[canonical_key] = value
        return mapped

    @staticmethod
    def _validate_row(mapped_row: dict) -> tuple[bool, str | None]:
        timestamp_value = mapped_row.get("timestamp", "")
        if not timestamp_value or not str(timestamp_value).strip():
            return False, "Missing timestamp field"

        missing_required = REQUIRED_FIELDS - {
            k for k, v in mapped_row.items() if v not in (None, "")
        }
        if missing_required:
            return False, f"Missing required field(s): {', '.join(missing_required)}"

        return True, None

    @classmethod
    def parse_file(cls, file_path: str) -> ParsedFileResult:
        """Parse a single log file. If the file itself is unreadable/malformed,
        result.failed will be True and result.file_error will contain the reason.
        Row-level errors increment result.skipped_count instead.
        """
        try:
            log_file = cls.create_log_file(file_path)
        except ValueError as exc:
            result = ParsedFileResult(source_label=Path(file_path).stem)
            result.file_error = str(exc)
            return result

        result = ParsedFileResult(source_label=log_file.source_label)

        # Dispatch to format-specific parser
        try:
            if log_file.file_format == "csv":
                raw_rows = parse_csv(log_file.file_path)
            elif log_file.file_format == "xlsx":
                raw_rows = parse_xlsx(log_file.file_path)
            else:
                raw_rows = parse_txt(log_file.file_path)
        except FileNotFoundError as exc:
            result.file_error = str(exc)
            return result
        except MalformedFileError as exc:
            result.file_error = str(exc)
            return result

        # Row-level processing
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
                normalized_timestamp=None,
            )

            # Timestamp normalisation
            # Skipped gracefully until TimestampNormalizer is implemented.
            # Once src/normaliser/timestamp_normalizer.py exists, this block
            # will run automatically — no changes needed here.
            if _NORMALIZER_AVAILABLE:
                try:
                    normalized = TimestampNormalizer.normalize_for_source(
                        raw_ts=entry.raw_timestamp,
                        source_label=entry.source_label,
                    )
                except TimestampParseError as exc:
                    result.skipped_count += 1
                    result.skip_reasons.append(f"Row {row_index}: {exc}")
                    continue

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
        """Parse all files, then sort every source's valid entries into
        chronological order per Section 4.7.1 step 5.

        The merged timeline is stored back into each ParsedFileResult so
        LogWindowWidget.load_rows() receives entries already sorted by
        utc_datetime. Results with no valid entries are left unchanged.
        """
        results = [cls.parse_file(path) for path in file_paths]

        # Section 4.7.1 step 5 — unified chronological sort
        # Collect every valid entry across all files into one flat list,
        # merge-sort it by utc_datetime, then split back out per source so
        # each LogWindowWidget gets its own sorted slice.
        all_valid: list = []
        for result in results:
            all_valid.extend(result.valid_entries)

        if all_valid:
            merged = TimelineMerger.merge_chronological(all_valid)
            by_source = TimelineMerger.split_by_source(merged)

            # Write the sorted slices back into their ParsedFileResult objects
            # so the rest of the pipeline sees chronologically ordered entries.
            for result in results:
                if result.source_label in by_source:
                    result.valid_entries = by_source[result.source_label]

        return results
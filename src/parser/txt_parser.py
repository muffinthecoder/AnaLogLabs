"""
txt_parser.py — parses TXT log files line by line.

Per Section 4.7.1 step 2: 'IF format == "txt": Parse line by line'.

Owned by: Pooja
Consumed by: log_parser.py
"""

import re
from pathlib import Path
from src.parser.csv_parser import MalformedFileError


def _detect_delimiter(header_line: str) -> str | None:
    candidates = ["|", "\t", ","]
    counts = {d: header_line.count(d) for d in candidates}
    best_delimiter = max(counts, key=counts.get)
    return best_delimiter if counts[best_delimiter] > 0 else None


def _is_syslog_format(lines: list[str]) -> bool:
    """Detects Cisco WLC syslog format — lines start with 'Mon DD HH:MM:SS'"""
    syslog_pattern = re.compile(r'^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}')
    matches = sum(1 for line in lines[:5] if syslog_pattern.match(line))
    return matches >= 2


def _parse_syslog_line(line: str) -> dict:
    """Extracts fields from a Cisco WLC syslog line."""
    row = {}

    # timestamp — first 3 tokens: Mon DD HH:MM:SS
    parts = line.split()
    if len(parts) >= 3:
        row["timestamp"] = f"{parts[0]} {parts[1]} {parts[2]}"

    # username
    username_match = re.search(r'Username[:\s]+(\S+)', line)
    if username_match:
        row["username"] = username_match.group(1).strip("()")

    # MAC
    mac_match = re.search(r'(?:MAC[:\s]+|client \()([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})', line)
    if mac_match:
        row["mac"] = mac_match.group(1)

    # IP
    ip_match = re.search(r'IP\s+(\d+\.\d+\.\d+\.\d+)', line)
    if ip_match:
        row["ip_address"] = ip_match.group(1)

    # SSID
    ssid_match = re.search(r'SSID[:\s]+\(([^)]+)\)', line)
    if ssid_match:
        row["ssid"] = ssid_match.group(1)

    # AP
    ap_match = re.search(r'AP[:\s]+\(([^)]+)\)', line)
    if ap_match:
        row["ap"] = ap_match.group(1)

    # status — derive from log level keyword
    if "FAIL" in line or "Cred Fail" in line:
        row["status"] = "Failure"
    elif "RUN_STATE" in line or "ASSOCIATED" in line:
        row["status"] = "Success"

    # raw line for reference
    row["raw_log"] = line

    return row


def parse_txt(file_path: str) -> list[dict]:
    """Reads a TXT log file and returns a list of raw row dicts.

    For WLC syslog freetext, each line is parsed via regex into structured
    fields. For structured TXT files (pipe-, tab-, or comma-delimited), the
    first non-empty line is treated as a header row.

    Raises:
        FileNotFoundError: if file_path does not exist.
        MalformedFileError: if the file is unreadable or has no header.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"TXT file not found: {file_path}")

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = [line.rstrip("\n").rstrip("\r") for line in f]
    except UnicodeDecodeError as exc:
        raise MalformedFileError(
            f"TXT file could not be decoded as UTF-8: {file_path} — {exc}"
        ) from exc

    non_empty_lines = [line for line in lines if line.strip()]
    if not non_empty_lines:
        raise MalformedFileError(
            f"TXT file is empty or contains only blank lines: {file_path}"
        )

    # WLC syslog freetext — handle separately
    if _is_syslog_format(non_empty_lines):
        return [_parse_syslog_line(line) for line in non_empty_lines]

    # delimiter-based parsing for structured TXT files
    header_line = non_empty_lines[0]
    delimiter = _detect_delimiter(header_line)

    if delimiter is not None:
        headers = [h.strip() for h in header_line.split(delimiter)]
    else:
        headers = header_line.split()

    if not headers:
        raise MalformedFileError(
            f"TXT file header row could not be parsed: {file_path}"
        )

    rows: list[dict] = []
    for line in non_empty_lines[1:]:
        if delimiter is not None:
            values = [v.strip() for v in line.split(delimiter)]
        else:
            values = line.split()

        row_dict = {
            header: (values[i] if i < len(values) else "")
            for i, header in enumerate(headers)
        }
        rows.append(row_dict)

    return rows
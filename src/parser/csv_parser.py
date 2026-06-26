"""
csv_parser.py — parses CSV log files using csv.DictReader.

Per Section 4.7.1 step 2: 'IF format == "csv": Parse using csv.DictReader'.

Owned by: Pooja
Consumed by: src/parser/log_parser.py
"""

import csv
from pathlib import Path


def parse_csv(file_path: str) -> list[dict]:
    """Reads a CSV log file and returns a list of raw row dicts, one per
    data row. Keys are the original column headers exactly as they appear
    in the file (no renaming at this stage — that happens later in
    LogParser._map_fields).

    Args:
        file_path: path to a .csv file.

    Returns:
        List of dicts, e.g. [{"Timestamp": "...", "Username": "...", ...}, ...]

    Raises:
        FileNotFoundError: if file_path does not exist.
        UnicodeDecodeError: if the file is not UTF-8 / cannot be decoded.
        csv.Error: if the file is malformed beyond recovery.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    rows: list[dict] = []
    # newline="" is required by the csv module to avoid double-newline
    # issues on Windows-originated files.
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # DictReader returns None for missing trailing columns and puts
            # extras under None key if a row has MORE columns than headers.
            # Strip those edge cases so downstream code only sees clean
            # str -> str mappings.
            clean_row = {k: v for k, v in row.items() if k is not None}
            rows.append(clean_row)

    return rows

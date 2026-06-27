"""
csv_parser.py — parses CSV log files using csv.DictReader.

Per Section 4.7.1 step 2: 'IF format == "csv": Parse using csv.DictReader'.

Owned by: Pooja
Initial code provided by: Fatima
Consumed by: log_parser.py
"""

import csv
from pathlib import Path


class MalformedFileError(Exception):
    """Raised when a file is so badly broken that no rows can be recovered."""
    pass


def parse_csv(file_path: str) -> list[dict]:
    """Reads a CSV log file and returns a list of raw row dicts.

    Raises:
        FileNotFoundError: if file_path does not exist.
        MalformedFileError: if the file has no headers or is unreadable.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    rows: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                raise MalformedFileError(
                    f"CSV file has no header row or is empty: {file_path}"
                )

            for row in reader:
                clean_row = {k: v for k, v in row.items() if k is not None}
                rows.append(clean_row)

    except UnicodeDecodeError as exc:
        raise MalformedFileError(
            f"CSV file could not be decoded as UTF-8: {file_path} — {exc}"
        ) from exc
    except csv.Error as exc:
        raise MalformedFileError(
            f"CSV file is malformed and could not be parsed: {file_path} — {exc}"
        ) from exc

    return rows
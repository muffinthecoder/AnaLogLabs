"""
txt_parser.py — parses TXT log files line by line.

Per Section 4.7.1 step 2: 'IF format == "txt": Parse line by line; split on
whitespace or delimiter'.

Owned by: Pooja
Consumed by: src/parser/log_parser.py

Design decision: TXT log files in this prototype are expected to be
delimited (pipe, tab, or comma), with the delimiter character consistent
throughout the file and a header line as the first non-empty line. This
matches how WLC and MUPC event exports are typically formatted when
exported as plain text rather than CSV.
"""

from pathlib import Path


def _detect_delimiter(header_line: str) -> str:
    """Guesses the delimiter used in a TXT log file by counting candidate
    delimiter characters in the header line and picking whichever appears
    most often. Falls back to whitespace splitting if none of the common
    delimiters appear more than once.
    """
    candidates = ["|", "\t", ","]
    counts = {d: header_line.count(d) for d in candidates}
    best_delim = max(counts, key=counts.get)
    if counts[best_delim] > 0:
        return best_delim
    return None  # signals "split on whitespace" per the design doc wording


def parse_txt(file_path: str) -> list[dict]:
    """Reads a TXT log file and returns a list of raw row dicts, one per
    data line. The first non-empty line is treated as the header. Delimiter
    is auto-detected from pipe, tab, or comma; falls back to splitting on
    any run of whitespace if none of those are present.

    Args:
        file_path: path to a .txt file.

    Returns:
        List of dicts keyed by the header line's column names.

    Raises:
        FileNotFoundError: if file_path does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"TXT file not found: {file_path}")

    with open(path, "r", encoding="utf-8-sig") as f:
        lines = [line.rstrip("\n").rstrip("\r") for line in f]

    # Find the first non-empty line to use as the header.
    non_empty_lines = [line for line in lines if line.strip()]
    if not non_empty_lines:
        return []

    header_line = non_empty_lines[0]
    delimiter = _detect_delimiter(header_line)

    if delimiter is not None:
        headers = [h.strip() for h in header_line.split(delimiter)]
    else:
        headers = header_line.split()

    rows: list[dict] = []
    for line in non_empty_lines[1:]:
        if delimiter is not None:
            values = [v.strip() for v in line.split(delimiter)]
        else:
            values = line.split()

        row_dict = {}
        for col_index, header in enumerate(headers):
            row_dict[header] = values[col_index] if col_index < len(values) else ""
        rows.append(row_dict)

    return rows

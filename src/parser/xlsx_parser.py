"""
xlsx_parser.py — parses XLSX log files using openpyxl.

Per Section 4.7.1 step 2: 'IF format == "xlsx": Parse using openpyxl,
iterate rows'.

Owned by: Pooja
Consumed by: src/parser/log_parser.py
"""

from pathlib import Path

from openpyxl import load_workbook


def parse_xlsx(file_path: str) -> list[dict]:
    """Reads an XLSX log file and returns a list of raw row dicts, one per
    data row. The first row of the active worksheet is treated as the
    header row. Keys are the original column headers exactly as they
    appear in the file (no renaming at this stage).

    Args:
        file_path: path to an .xlsx file.

    Returns:
        List of dicts, e.g. [{"Timestamp": "...", "Computer": "...", ...}, ...]

    Raises:
        FileNotFoundError: if file_path does not exist.
        openpyxl.utils.exceptions.InvalidFileException: if the file is not
            a valid XLSX workbook.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"XLSX file not found: {file_path}")

    # read_only=True streams the file rather than loading it fully into
    # memory, which matters for the 500MB file size constraint noted in
    # the Requirements & Analysis document (NR3 Capacity).
    # data_only=True returns cell values rather than formulas.
    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    worksheet = workbook.active

    rows: list[dict] = []
    row_iter = worksheet.iter_rows(values_only=True)

    try:
        header_row = next(row_iter)
    except StopIteration:
        workbook.close()
        return rows  # empty file, no header even

    headers = [str(h) if h is not None else f"column_{i}" for i, h in enumerate(header_row)]

    for raw_row in row_iter:
        # Skip fully empty rows (openpyxl can yield trailing blank rows).
        if all(cell is None for cell in raw_row):
            continue

        row_dict = {}
        for col_index, header in enumerate(headers):
            cell_value = raw_row[col_index] if col_index < len(raw_row) else None
            # Normalise to string so downstream parsing (timestamps etc.)
            # behaves the same regardless of whether openpyxl returned a
            # native Python datetime, int, float, or str for that cell.
            row_dict[header] = "" if cell_value is None else str(cell_value)
        rows.append(row_dict)

    workbook.close()
    return rows

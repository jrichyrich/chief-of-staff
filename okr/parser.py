"""Parse OKR data from an Excel spreadsheet."""
from datetime import datetime
from pathlib import Path

import openpyxl

from okr.models import Initiative, KeyResult, OKRSnapshot, Objective


def _cell_str(value) -> str:
    """Convert a cell value to a clean string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _cell_float(value) -> float:
    """Convert a cell value to a float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _cell_pct(value) -> float:
    """Convert an Excel decimal percentage to a display percentage.

    Excel stores percentages as decimals (0.5 = 50%).  This function
    multiplies by 100 so the stored value reads as a human-friendly
    percentage (50.0 instead of 0.5).
    """
    return round(_cell_float(value) * 100, 2)


def parse_okr_spreadsheet(path: Path) -> OKRSnapshot:
    """Parse an OKR Excel spreadsheet and return an OKRSnapshot.

    Args:
        path: Path to the .xlsx file.

    Returns:
        OKRSnapshot with parsed objectives, key results, and initiatives.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"OKR spreadsheet not found: {path}")

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)

    try:
        objectives = _parse_objectives(wb["Objectives"])
        key_results = _parse_key_results(wb["Key Results"])
        initiatives = _parse_initiatives(wb["Initiatives"])
    finally:
        wb.close()

    return OKRSnapshot(
        timestamp=datetime.now().isoformat(),
        source_file=str(path),
        objectives=objectives,
        key_results=key_results,
        initiatives=initiatives,
    )


def _parse_objectives(ws) -> list[Objective]:
    """Parse the Objectives tab (header row 1, data from row 2)."""
    objectives = []
    first = True
    for row in ws.iter_rows():
        if first:
            first = False
            continue  # skip header
        cells = [c.value for c in row]
        if cells[0] is None:
            continue
        objectives.append(
            Objective(
                okr_id=_cell_str(cells[0]),
                name=_cell_str(cells[1]),
                statement=_cell_str(cells[2]),
                owner=_cell_str(cells[3]),
                team=_cell_str(cells[4]),
                year=_cell_str(cells[5]),
                status=_cell_str(cells[7]),
                pct_complete=_cell_pct(cells[8]),
            )
        )
    return objectives


def _parse_key_results(ws) -> list[KeyResult]:
    """Parse the Key Results tab."""
    key_results = []
    first = True
    for row in ws.iter_rows():
        if first:
            first = False
            continue
        cells = [c.value for c in row]
        if cells[0] is None:
            continue
        key_results.append(
            KeyResult(
                kr_id=_cell_str(cells[0]),
                okr_id=_cell_str(cells[1]),
                name=_cell_str(cells[3]),
                status=_cell_str(cells[4]),
                pct_complete=_cell_pct(cells[5]),
                baseline=_cell_str(cells[9]),
                target=_cell_str(cells[11]),
                owner=_cell_str(cells[13]),
                team=_cell_str(cells[14]),
                q1_milestone=_cell_str(cells[15]),
                q2_milestone=_cell_str(cells[16]),
                q3_milestone=_cell_str(cells[17]),
                q4_milestone=_cell_str(cells[18]),
                current_actual=_cell_str(cells[19]),
                gap_to_target=_cell_str(cells[21]),
            )
        )
    return key_results


def _parse_initiatives(ws) -> list[Initiative]:
    """Parse the Initiatives tab."""
    initiatives = []
    first = True
    for row in ws.iter_rows():
        if first:
            first = False
            continue
        cells = [c.value for c in row]
        if cells[0] is None:
            continue
        initiatives.append(
            Initiative(
                initiative_id=_cell_str(cells[0]),
                kr_ids=_cell_str(cells[1]),
                okr_id=_cell_str(cells[2]),
                name=_cell_str(cells[4]),
                pct_complete=_cell_pct(cells[5]),
                status=_cell_str(cells[6]),
                blocker=_cell_str(cells[7]),
                description=_cell_str(cells[11]),
                investment_tier=_cell_str(cells[12]),
                maturity_type=_cell_str(cells[14]),
                owner=_cell_str(cells[15]),
                team=_cell_str(cells[16]),
                timeline_start=_cell_str(cells[17]),
                timeline_end=_cell_str(cells[18]),
                investment_dollars=_cell_float(cells[20]),
            )
        )
    return initiatives

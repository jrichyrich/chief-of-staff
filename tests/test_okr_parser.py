"""Tests for OKR Excel parser — runs against the real spreadsheet."""
import pytest
from pathlib import Path

from okr.parser import parse_okr_spreadsheet
from okr.models import OKRSnapshot

SPREADSHEET = Path("data/okr/2026_ISP_OKR_Master_Final.xlsx")

pytestmark = pytest.mark.skipif(
    not SPREADSHEET.exists(),
    reason="Real OKR spreadsheet not found",
)


@pytest.fixture(scope="module")
def snapshot() -> OKRSnapshot:
    return parse_okr_spreadsheet(SPREADSHEET)


def test_returns_okr_snapshot(snapshot):
    assert isinstance(snapshot, OKRSnapshot)
    assert snapshot.source_file == str(SPREADSHEET)
    assert snapshot.timestamp  # non-empty


def test_parses_three_objectives(snapshot):
    assert len(snapshot.objectives) == 3


def test_objective_fields_correct(snapshot):
    obj1 = snapshot.objectives[0]
    assert obj1.okr_id == "OKR 1"
    assert obj1.name == "Trusted Security & Privacy Controls"
    assert "trust" in obj1.statement.lower()
    assert obj1.owner == "Jason Richards"
    assert obj1.team == "Information Security & Privacy"
    assert obj1.year == "2026"
    assert obj1.status == "On Track"
    assert obj1.pct_complete == pytest.approx(15.0, abs=1.0)


def test_more_than_10_key_results(snapshot):
    assert len(snapshot.key_results) > 10


def test_more_than_30_initiatives(snapshot):
    assert len(snapshot.initiatives) > 30


def test_isp003_investment_380000(snapshot):
    isp003 = [i for i in snapshot.initiatives if i.initiative_id == "ISP-003"]
    assert len(isp003) == 1
    assert isp003[0].investment_dollars == pytest.approx(380000, abs=1)


def test_snapshot_summary_counts(snapshot):
    summary = snapshot.summary()
    assert summary["objectives"] == 3
    assert summary["key_results"] == len(snapshot.key_results)
    assert summary["initiatives"] == len(snapshot.initiatives)


def test_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_okr_spreadsheet(Path("/nonexistent/file.xlsx"))

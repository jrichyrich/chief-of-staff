"""Tests for OKR MCP tools."""
import json
import pytest

from okr.models import Initiative, KeyResult, Objective, OKRSnapshot
from okr.store import OKRStore


@pytest.fixture
def okr_store(tmp_path):
    store = OKRStore(tmp_path / "okr")
    snapshot = OKRSnapshot(
        timestamp="2026-02-16T10:00:00",
        source_file="test.xlsx",
        objectives=[
            Objective(okr_id="OKR 1", name="Trusted Controls", statement="",
                      owner="Jason", team="ISP", year="2026", status="On Track",
                      pct_complete=0.15),
        ],
        key_results=[
            KeyResult(kr_id="KR 1.1", okr_id="OKR 1", name="Provisioning time",
                      status="Not Started", owner="Shawn", team="IAM"),
        ],
        initiatives=[
            Initiative(initiative_id="ISP-003", kr_ids="KR 1.1", okr_id="OKR 1",
                       name="RBAC Automation", status="On Track", owner="Shawn",
                       team="IAM", investment_dollars=380000),
        ],
    )
    store.save(snapshot)
    return store


def test_query_okr_status_summary(okr_store):
    summary = okr_store.executive_summary()
    assert summary["objectives_count"] == 1
    assert summary["initiatives_count"] == 1
    assert summary["total_investment"] == 380000


def test_query_by_team(okr_store):
    results = okr_store.query(team="IAM")
    assert len(results["initiatives"]) == 1


def test_query_text_search(okr_store):
    results = okr_store.query(text="RBAC")
    assert len(results["initiatives"]) == 1

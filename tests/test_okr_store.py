"""Tests for OKR JSON snapshot store."""
import pytest
from pathlib import Path

from okr.models import Objective, KeyResult, Initiative, OKRSnapshot
from okr.store import OKRStore


@pytest.fixture
def sample_snapshot() -> OKRSnapshot:
    """A small but realistic OKR snapshot for testing."""
    return OKRSnapshot(
        timestamp="2026-02-16T12:00:00",
        source_file="test.xlsx",
        objectives=[
            Objective("OKR 1", "Security Controls", "Earn trust", "Alice", "Security", "2026", "On Track", 15),
            Objective("OKR 2", "Resilient Systems", "Recover quickly", "Bob", "Engineering", "2026", "At Risk", 5),
            Objective("OKR 3", "Team Excellence", "Build great team", "Carol", "Security", "2026", "On Track", 20),
        ],
        key_results=[
            KeyResult("KR 1.1", "OKR 1", "Access provisioning time", "On Track", 10, owner="Alice", team="Security"),
            KeyResult("KR 1.2", "OKR 1", "SSO coverage", "At Risk", 20, owner="Dave", team="IAM"),
            KeyResult("KR 2.1", "OKR 2", "Recovery time", "Blocked", 0, owner="Bob", team="Engineering"),
            KeyResult("KR 3.1", "OKR 3", "Training hours", "On Track", 30, owner="Carol", team="Security"),
        ],
        initiatives=[
            Initiative("ISP-001", "KR 1.1", "OKR 1", "RBAC Automation", 5, "On Track", "", "Alice", "Security", investment_dollars=380000),
            Initiative("ISP-002", "KR 1.2", "OKR 1", "SSO Rollout", 10, "At Risk", "", "Dave", "IAM", investment_dollars=50000),
            Initiative("ISP-003", "KR 2.1", "OKR 2", "DR Testing", 0, "Blocked", "Vendor delay", "Bob", "Engineering", investment_dollars=120000),
            Initiative("ISP-004", "KR 3.1", "OKR 3", "Security Training", 15, "On Track", "", "Carol", "Security", investment_dollars=25000),
            Initiative("ISP-005", "KR 1.1", "OKR 1", "MFA Enforcement", 20, "On Track", "", "Alice", "Security", investment_dollars=0),
        ],
    )


@pytest.fixture
def store(tmp_path) -> OKRStore:
    return OKRStore(tmp_path)


def test_save_and_load(store, sample_snapshot):
    path = store.save(sample_snapshot)
    assert path.exists()

    loaded = store.load_latest()
    assert loaded is not None
    assert loaded.timestamp == sample_snapshot.timestamp
    assert loaded.source_file == sample_snapshot.source_file
    assert len(loaded.objectives) == len(sample_snapshot.objectives)
    assert len(loaded.key_results) == len(sample_snapshot.key_results)
    assert len(loaded.initiatives) == len(sample_snapshot.initiatives)

    # Verify deep reconstruction
    assert loaded.objectives[0].okr_id == "OKR 1"
    assert loaded.objectives[0].name == "Security Controls"
    assert loaded.key_results[0].kr_id == "KR 1.1"
    assert loaded.initiatives[0].initiative_id == "ISP-001"
    assert loaded.initiatives[0].investment_dollars == 380000


def test_load_latest_no_data(store):
    result = store.load_latest()
    assert result is None


def test_query_by_okr(store, sample_snapshot):
    store.save(sample_snapshot)
    result = store.query(okr_id="OKR 1")
    # OKR 1 has 1 objective, 2 key results (KR 1.1, KR 1.2), 3 initiatives (ISP-001, ISP-002, ISP-005)
    assert len(result["objectives"]) == 1
    assert result["objectives"][0]["okr_id"] == "OKR 1"
    assert len(result["key_results"]) == 2
    assert len(result["initiatives"]) == 3


def test_query_by_team(store, sample_snapshot):
    store.save(sample_snapshot)
    result = store.query(team="Security")
    # Security team: objectives OKR 1 + OKR 3, KRs KR 1.1 + KR 3.1, initiatives ISP-001 + ISP-004 + ISP-005
    assert len(result["objectives"]) == 2
    assert len(result["key_results"]) == 2
    assert len(result["initiatives"]) == 3


def test_query_by_status(store, sample_snapshot):
    store.save(sample_snapshot)
    result = store.query(status="At Risk")
    # At Risk: objective OKR 2, KR 1.2, initiative ISP-002
    assert len(result["objectives"]) == 1
    assert result["objectives"][0]["okr_id"] == "OKR 2"
    assert len(result["key_results"]) == 1
    assert len(result["initiatives"]) == 1


def test_query_blocked(store, sample_snapshot):
    store.save(sample_snapshot)
    result = store.query(blocked_only=True)
    # Only ISP-003 has a blocker
    assert len(result["initiatives"]) == 1
    assert result["initiatives"][0]["initiative_id"] == "ISP-003"
    assert result["initiatives"][0]["blocker"] == "Vendor delay"


def test_query_text_search(store, sample_snapshot):
    store.save(sample_snapshot)
    result = store.query(text="training")
    # "Security Training" initiative and "Training hours" KR
    assert len(result["initiatives"]) == 1
    assert result["initiatives"][0]["name"] == "Security Training"
    assert len(result["key_results"]) == 1
    assert result["key_results"][0]["name"] == "Training hours"


def test_query_no_data(store):
    result = store.query(okr_id="OKR 1")
    assert result["objectives"] == []
    assert result["key_results"] == []
    assert result["initiatives"] == []


def test_executive_summary(store, sample_snapshot):
    store.save(sample_snapshot)
    summary = store.executive_summary()

    assert summary["objectives_count"] == 3
    assert summary["key_results_count"] == 4
    assert summary["initiatives_count"] == 5
    assert summary["total_investment"] == pytest.approx(575000)

    # Status tallies
    assert summary["on_track"] == 2  # objectives on track
    assert summary["at_risk"] == 1   # objectives at risk
    assert summary["blocked"] == 0   # no objective is "Blocked"

    # Objectives summary list
    assert len(summary["objectives_summary"]) == 3
    obj1_summary = summary["objectives_summary"][0]
    assert obj1_summary["okr_id"] == "OKR 1"
    assert obj1_summary["name"] == "Security Controls"
    assert obj1_summary["status"] == "On Track"
    assert obj1_summary["pct_complete"] == 15


def test_executive_summary_no_data(store):
    summary = store.executive_summary()
    assert summary["objectives_count"] == 0
    assert summary["key_results_count"] == 0
    assert summary["initiatives_count"] == 0
    assert summary["total_investment"] == 0
    assert summary["on_track"] == 0
    assert summary["at_risk"] == 0
    assert summary["blocked"] == 0
    assert summary["objectives_summary"] == []

"""Tests for OKR data models."""
import pytest
from okr.models import Objective, KeyResult, Initiative, OKRSnapshot


def test_objective_from_kwargs():
    obj = Objective(
        okr_id="OKR 1",
        name="Trusted Security",
        statement="Earn trust through security",
        owner="Jason Richards",
        team="ISP",
        year="2026",
        status="On Track",
        pct_complete=0.15,
    )
    assert obj.okr_id == "OKR 1"
    assert obj.name == "Trusted Security"
    assert obj.statement == "Earn trust through security"
    assert obj.owner == "Jason Richards"
    assert obj.team == "ISP"
    assert obj.year == "2026"
    assert obj.status == "On Track"
    assert obj.pct_complete == 0.15


def test_key_result_from_kwargs():
    kr = KeyResult(
        kr_id="KR 1.1",
        okr_id="OKR 1",
        name="Time to provision access",
        status="Not Started",
        pct_complete=0.1,
        baseline="25 min",
        target="<10 minutes",
        current_actual="25",
        gap_to_target="15",
        owner="Shawn Farnworth",
        team="IAM",
        q1_milestone="<20 minutes",
        q2_milestone="<15 minutes",
        q3_milestone="<12 minutes",
        q4_milestone="<10 minutes",
    )
    assert kr.kr_id == "KR 1.1"
    assert kr.okr_id == "OKR 1"
    assert kr.name == "Time to provision access"
    assert kr.status == "Not Started"
    assert kr.pct_complete == 0.1
    assert kr.baseline == "25 min"
    assert kr.target == "<10 minutes"
    assert kr.current_actual == "25"
    assert kr.gap_to_target == "15"
    assert kr.owner == "Shawn Farnworth"
    assert kr.team == "IAM"
    assert kr.q1_milestone == "<20 minutes"
    assert kr.q4_milestone == "<10 minutes"


def test_initiative_from_kwargs():
    init = Initiative(
        initiative_id="ISP-003",
        kr_ids="KR 1.1",
        okr_id="OKR 1",
        name="RBAC Automation",
        pct_complete=0.05,
        status="On Track",
        blocker="",
        owner="Shawn Farnworth",
        team="IAM",
        investment_tier="1",
        maturity_type="Grow",
        timeline_start="Q1",
        timeline_end="Q4",
        investment_dollars=380000.0,
        description="Phase 1 deployment",
    )
    assert init.initiative_id == "ISP-003"
    assert init.kr_ids == "KR 1.1"
    assert init.okr_id == "OKR 1"
    assert init.name == "RBAC Automation"
    assert init.pct_complete == 0.05
    assert init.status == "On Track"
    assert init.blocker == ""
    assert init.owner == "Shawn Farnworth"
    assert init.team == "IAM"
    assert init.investment_tier == "1"
    assert init.maturity_type == "Grow"
    assert init.timeline_start == "Q1"
    assert init.timeline_end == "Q4"
    assert init.investment_dollars == 380000.0
    assert init.description == "Phase 1 deployment"


def test_okr_snapshot_summary():
    snap = OKRSnapshot(
        timestamp="2026-02-16T00:00:00",
        source_file="test.xlsx",
        objectives=[
            Objective("OKR 1", "Obj1", "Stmt1", "Owner1", "Team1", "2026", "On Track", 0.1),
        ],
        key_results=[
            KeyResult("KR 1.1", "OKR 1", "KR Name", "On Track", 0.2),
            KeyResult("KR 1.2", "OKR 1", "KR Name2", "At Risk", 0.1),
        ],
        initiatives=[
            Initiative("ISP-001", "KR 1.1", "OKR 1", "Init1"),
            Initiative("ISP-002", "KR 1.2", "OKR 1", "Init2"),
            Initiative("ISP-003", "KR 1.1", "OKR 1", "Init3"),
        ],
    )
    summary = snap.summary()
    assert summary["timestamp"] == "2026-02-16T00:00:00"
    assert summary["source_file"] == "test.xlsx"
    assert summary["objectives"] == 1
    assert summary["key_results"] == 2
    assert summary["initiatives"] == 3

    # Also test to_dict
    d = snap.to_dict()
    assert len(d["objectives"]) == 1
    assert len(d["key_results"]) == 2
    assert len(d["initiatives"]) == 3

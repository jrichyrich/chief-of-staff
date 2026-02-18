"""Data models for OKR tracking."""
from dataclasses import dataclass, field, asdict


@dataclass
class Objective:
    okr_id: str
    name: str
    statement: str
    owner: str
    team: str
    year: str
    status: str
    pct_complete: float = 0.0


@dataclass
class KeyResult:
    kr_id: str
    okr_id: str
    name: str
    status: str
    pct_complete: float = 0.0
    baseline: str = ""
    target: str = ""
    current_actual: str = ""
    gap_to_target: str = ""
    owner: str = ""
    team: str = ""
    q1_milestone: str = ""
    q2_milestone: str = ""
    q3_milestone: str = ""
    q4_milestone: str = ""


@dataclass
class Initiative:
    initiative_id: str
    kr_ids: str
    okr_id: str
    name: str
    pct_complete: float = 0.0
    status: str = ""
    blocker: str = ""
    owner: str = ""
    team: str = ""
    investment_tier: str = ""
    maturity_type: str = ""
    timeline_start: str = ""
    timeline_end: str = ""
    investment_dollars: float = 0.0
    description: str = ""


@dataclass
class OKRSnapshot:
    timestamp: str
    source_file: str
    objectives: list[Objective] = field(default_factory=list)
    key_results: list[KeyResult] = field(default_factory=list)
    initiatives: list[Initiative] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "source_file": self.source_file,
            "objectives": len(self.objectives),
            "key_results": len(self.key_results),
            "initiatives": len(self.initiatives),
        }

    def to_dict(self) -> dict:
        return asdict(self)

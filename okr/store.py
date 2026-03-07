"""JSON-backed snapshot store for OKR data."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from okr.models import Initiative, KeyResult, OKRSnapshot, Objective, KR_WEIGHT, INITIATIVE_WEIGHT
from utils.atomic import atomic_write, locked_read


def _compute_blended(key_results: list, initiatives: list, okr_id: str) -> dict:
    """Compute kr_avg_pct, initiative_avg_pct, and blended_pct for a single OKR.

    Filters key_results and initiatives by okr_id, averages their pct_complete,
    then applies the blended formula: (KR_avg * KR_WEIGHT) + (Initiative_avg * INITIATIVE_WEIGHT).
    Returns a dict with kr_avg_pct, initiative_avg_pct, and blended_pct (all rounded to 2dp).
    """
    okr_krs = [kr for kr in key_results if kr["okr_id"] == okr_id]
    okr_inits = [i for i in initiatives if i["okr_id"] == okr_id]

    kr_avg = round(sum(kr["pct_complete"] for kr in okr_krs) / len(okr_krs), 2) if okr_krs else 0.0
    init_avg = round(sum(i["pct_complete"] for i in okr_inits) / len(okr_inits), 2) if okr_inits else 0.0
    blended = round((kr_avg * KR_WEIGHT) + (init_avg * INITIATIVE_WEIGHT), 2)

    return {
        "kr_avg_pct": kr_avg,
        "initiative_avg_pct": init_avg,
        "blended_pct": blended,
    }


class OKRStore:
    """Persists OKR snapshots as JSON and provides query capabilities."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_path = self._data_dir / "latest_snapshot.json"
        self._lock_path = self._data_dir / ".okr_store.lock"

    def save(self, snapshot: OKRSnapshot) -> Path:
        """Serialize snapshot to JSON and write to disk atomically."""
        data = asdict(snapshot)
        content = json.dumps(data, indent=2, default=str)
        atomic_write(self._snapshot_path, content, self._lock_path)
        return self._snapshot_path

    def load_latest(self) -> Optional[OKRSnapshot]:
        """Load the most recent snapshot from disk, or None if none exists."""
        if not self._snapshot_path.exists():
            return None

        data = json.loads(locked_read(self._snapshot_path, self._lock_path))
        return OKRSnapshot(
            timestamp=data["timestamp"],
            source_file=data["source_file"],
            objectives=[Objective(**o) for o in data["objectives"]],
            key_results=[KeyResult(**kr) for kr in data["key_results"]],
            initiatives=[Initiative(**i) for i in data["initiatives"]],
        )

    def query(
        self,
        *,
        okr_id: str = "",
        team: str = "",
        status: str = "",
        blocked_only: bool = False,
        text: str = "",
    ) -> dict:
        """Filter snapshot data by the given criteria.

        Returns a dict with keys: objectives, key_results, initiatives.
        Each value is a list of dicts matching the filters.
        """
        snapshot = self.load_latest()
        if snapshot is None:
            return {"objectives": [], "key_results": [], "initiatives": []}

        objectives = [asdict(o) for o in snapshot.objectives]
        key_results = [asdict(kr) for kr in snapshot.key_results]
        initiatives = [asdict(i) for i in snapshot.initiatives]

        if okr_id:
            objectives = [o for o in objectives if o["okr_id"] == okr_id]
            key_results = [kr for kr in key_results if kr["okr_id"] == okr_id]
            initiatives = [i for i in initiatives if i["okr_id"] == okr_id]

        if team:
            team_lower = team.lower()
            objectives = [o for o in objectives if o["team"].lower() == team_lower]
            key_results = [kr for kr in key_results if kr["team"].lower() == team_lower]
            initiatives = [i for i in initiatives if i["team"].lower() == team_lower]

        if status:
            status_lower = status.lower()
            objectives = [o for o in objectives if o["status"].lower() == status_lower]
            key_results = [kr for kr in key_results if kr["status"].lower() == status_lower]
            initiatives = [i for i in initiatives if i["status"].lower() == status_lower]

        if blocked_only:
            initiatives = [i for i in initiatives if i["blocker"]]
            # For blocked_only, only return initiatives (objectives/KRs not filtered)

        if text:
            text_lower = text.lower()
            objectives = [
                o for o in objectives
                if text_lower in o["name"].lower()
                or text_lower in o["statement"].lower()
            ]
            key_results = [
                kr for kr in key_results
                if text_lower in kr["name"].lower()
            ]
            initiatives = [
                i for i in initiatives
                if text_lower in i["name"].lower()
                or text_lower in i["description"].lower()
            ]

        # Enrich each objective with computed blended percentages.
        # Use the full (unfiltered) key_results and initiatives lists so that
        # averages are always computed over all items belonging to the OKR,
        # regardless of any active filters on the sibling lists.
        all_key_results = [asdict(kr) for kr in snapshot.key_results]
        all_initiatives = [asdict(i) for i in snapshot.initiatives]
        for o in objectives:
            computed = _compute_blended(all_key_results, all_initiatives, o["okr_id"])
            o.update(computed)
            o["pct_complete"] = computed["blended_pct"]

        return {
            "objectives": objectives,
            "key_results": key_results,
            "initiatives": initiatives,
        }

    def executive_summary(self) -> dict:
        """Return high-level OKR status counts and investment totals."""
        snapshot = self.load_latest()
        if snapshot is None:
            return {
                "objectives_count": 0,
                "key_results_count": 0,
                "initiatives_count": 0,
                "total_investment": 0,
                "on_track": 0,
                "at_risk": 0,
                "blocked": 0,
                "objectives_summary": [],
            }

        on_track = sum(1 for o in snapshot.objectives if o.status == "On Track")
        at_risk = sum(1 for o in snapshot.objectives if o.status == "At Risk")
        blocked = sum(1 for o in snapshot.objectives if o.status == "Blocked")
        total_investment = sum(i.investment_dollars for i in snapshot.initiatives)

        all_key_results = [asdict(kr) for kr in snapshot.key_results]
        all_initiatives = [asdict(i) for i in snapshot.initiatives]

        objectives_summary = []
        for o in snapshot.objectives:
            computed = _compute_blended(all_key_results, all_initiatives, o.okr_id)
            objectives_summary.append(
                {
                    "okr_id": o.okr_id,
                    "name": o.name,
                    "status": o.status,
                    "kr_avg_pct": computed["kr_avg_pct"],
                    "initiative_avg_pct": computed["initiative_avg_pct"],
                    "blended_pct": computed["blended_pct"],
                    "pct_complete": computed["blended_pct"],  # backward compat; replaces stale Objectives tab value
                }
            )

        return {
            "objectives_count": len(snapshot.objectives),
            "key_results_count": len(snapshot.key_results),
            "initiatives_count": len(snapshot.initiatives),
            "total_investment": total_investment,
            "on_track": on_track,
            "at_risk": at_risk,
            "blocked": blocked,
            "objectives_summary": objectives_summary,
        }

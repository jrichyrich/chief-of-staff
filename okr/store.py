"""JSON-backed snapshot store for OKR data."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from okr.models import Initiative, KeyResult, OKRSnapshot, Objective


class OKRStore:
    """Persists OKR snapshots as JSON and provides query capabilities."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_path = self._data_dir / "latest_snapshot.json"

    def save(self, snapshot: OKRSnapshot) -> Path:
        """Serialize snapshot to JSON and write to disk."""
        data = asdict(snapshot)
        self._snapshot_path.write_text(json.dumps(data, indent=2, default=str))
        return self._snapshot_path

    def load_latest(self) -> Optional[OKRSnapshot]:
        """Load the most recent snapshot from disk, or None if none exists."""
        if not self._snapshot_path.exists():
            return None

        data = json.loads(self._snapshot_path.read_text())
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
            objectives = [o for o in objectives if o["team"] == team]
            key_results = [kr for kr in key_results if kr["team"] == team]
            initiatives = [i for i in initiatives if i["team"] == team]

        if status:
            objectives = [o for o in objectives if o["status"] == status]
            key_results = [kr for kr in key_results if kr["status"] == status]
            initiatives = [i for i in initiatives if i["status"] == status]

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

        objectives_summary = [
            {
                "okr_id": o.okr_id,
                "name": o.name,
                "status": o.status,
                "pct_complete": o.pct_complete,
            }
            for o in snapshot.objectives
        ]

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

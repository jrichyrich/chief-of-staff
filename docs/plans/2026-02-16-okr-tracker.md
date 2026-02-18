# OKR Tracker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pipeline that parses the ISP OKR Excel spreadsheet into structured data, stores it as queryable JSON snapshots, exposes MCP tools for refresh/query, and creates an `okr_tracker` agent.

**Architecture:** New `okr/` package with parser (openpyxl) and snapshot store (JSON). MCP server gets two new tools: `refresh_okr_data` (parses Excel → JSON snapshot + memory facts) and `query_okr_status` (queries snapshot data by OKR, team, status, etc.). A fetch-and-download workflow opens the SharePoint URL, waits for user confirmation, and moves the file into place.

**Tech Stack:** openpyxl (Excel parsing), dataclasses (models), JSON (snapshot persistence), pytest (testing)

---

## Task 1: Add openpyxl Dependency

**Files:**
- Modify: `pyproject.toml:10-17`

**Step 1: Add openpyxl to dependencies**

In `pyproject.toml`, add `"openpyxl>=3.1.0"` to the `dependencies` list:

```toml
dependencies = [
    "anthropic>=0.42.0",
    "chromadb>=0.5.0",
    "openpyxl>=3.1.0",
    "pyyaml>=6.0",
    "rich>=13.0.0",
    "mcp[cli]>=1.26,<2",
    "pyobjc-framework-EventKit>=10.0; sys_platform == 'darwin'",
]
```

**Step 2: Install**

Run: `pip install -e ".[dev]"`

**Step 3: Verify**

Run: `python3 -c "import openpyxl; print(openpyxl.__version__)"`
Expected: Version number printed (e.g., `3.1.5`)

---

## Task 2: OKR Data Models

**Files:**
- Create: `okr/__init__.py`
- Create: `okr/models.py`
- Test: `tests/test_okr_models.py`

**Step 1: Write the failing test**

Create `tests/test_okr_models.py`:

```python
"""Tests for OKR data models."""
from okr.models import Initiative, KeyResult, Objective, OKRSnapshot


def test_objective_from_row():
    row = {
        "okr_id": "OKR 1",
        "name": "Trusted Security & Privacy Controls",
        "statement": "CHG earns and maintains trust...",
        "owner": "Jason Richards",
        "team": "Information Security & Privacy",
        "year": "2026",
        "status": "On Track",
        "pct_complete": 0.15,
    }
    obj = Objective(**row)
    assert obj.okr_id == "OKR 1"
    assert obj.status == "On Track"
    assert obj.pct_complete == 0.15


def test_key_result_from_row():
    row = {
        "kr_id": "KR 1.1",
        "okr_id": "OKR 1",
        "name": "Time to provision/deprovision access",
        "status": "Not Started",
        "pct_complete": 0.1,
        "baseline": "25 min (automated new hire), 50 min (manual)",
        "target": "<10 minutes (automated)",
        "current_actual": "25",
        "gap_to_target": "15",
        "owner": "Shawn Farnworth",
        "team": "IAM",
        "q1_milestone": "<20 minutes",
        "q2_milestone": "<15 minutes",
        "q3_milestone": "<12 minutes",
        "q4_milestone": "<10 minutes",
    }
    kr = KeyResult(**row)
    assert kr.kr_id == "KR 1.1"
    assert kr.okr_id == "OKR 1"
    assert kr.target == "<10 minutes (automated)"


def test_initiative_from_row():
    row = {
        "initiative_id": "ISP-003",
        "kr_ids": "KR 1.1",
        "okr_id": "OKR 1",
        "name": "RBAC Automation",
        "pct_complete": 0.05,
        "status": "On Track",
        "blocker": "",
        "owner": "Shawn Farnworth",
        "team": "IAM",
        "investment_tier": "1",
        "maturity_type": "Grow",
        "timeline_start": "Q1",
        "timeline_end": "Q4",
        "investment_dollars": 380000,
        "description": "Phase 1 deployment...",
    }
    init = Initiative(**row)
    assert init.initiative_id == "ISP-003"
    assert init.investment_dollars == 380000


def test_snapshot_summary():
    snap = OKRSnapshot(
        timestamp="2026-02-16T10:00:00",
        source_file="data/okr/2026_ISP_OKR_Master_Final.xlsx",
        objectives=[
            Objective(okr_id="OKR 1", name="Test", statement="", owner="",
                      team="", year="2026", status="On Track", pct_complete=0.15),
        ],
        key_results=[],
        initiatives=[],
    )
    summary = snap.summary()
    assert summary["objectives"] == 1
    assert summary["key_results"] == 0
    assert summary["initiatives"] == 0
    assert summary["timestamp"] == "2026-02-16T10:00:00"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_okr_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'okr'`

**Step 3: Write implementation**

Create `okr/__init__.py` (empty file).

Create `okr/models.py`:

```python
"""Data models for OKR tracking."""
from dataclasses import dataclass, field, asdict
from typing import Optional


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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_okr_models.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add okr/__init__.py okr/models.py tests/test_okr_models.py
git commit -m "feat(okr): add OKR data models"
```

---

## Task 3: Excel Parser

**Files:**
- Create: `okr/parser.py`
- Test: `tests/test_okr_parser.py`

**Step 1: Write the failing test**

Create `tests/test_okr_parser.py`. Uses the real spreadsheet at `data/okr/2026_ISP_OKR_Master_Final.xlsx`:

```python
"""Tests for OKR Excel parser."""
import pytest
from pathlib import Path

from okr.parser import parse_okr_spreadsheet
from okr.models import OKRSnapshot

SPREADSHEET = Path(__file__).parent.parent / "data" / "okr" / "2026_ISP_OKR_Master_Final.xlsx"


@pytest.fixture
def snapshot():
    if not SPREADSHEET.exists():
        pytest.skip("OKR spreadsheet not available")
    return parse_okr_spreadsheet(SPREADSHEET)


def test_returns_snapshot(snapshot):
    assert isinstance(snapshot, OKRSnapshot)


def test_parses_objectives(snapshot):
    assert len(snapshot.objectives) == 3
    ids = [o.okr_id for o in snapshot.objectives]
    assert "OKR 1" in ids
    assert "OKR 2" in ids
    assert "OKR 3" in ids


def test_objective_fields(snapshot):
    okr1 = next(o for o in snapshot.objectives if o.okr_id == "OKR 1")
    assert okr1.name == "Trusted Security & Privacy Controls"
    assert okr1.owner == "Jason Richards"
    assert okr1.status == "On Track"
    assert 0 <= okr1.pct_complete <= 1.0


def test_parses_key_results(snapshot):
    assert len(snapshot.key_results) > 10
    kr11 = next((kr for kr in snapshot.key_results if kr.kr_id == "KR 1.1"), None)
    assert kr11 is not None
    assert kr11.okr_id == "OKR 1"
    assert kr11.owner == "Shawn Farnworth"


def test_parses_initiatives(snapshot):
    assert len(snapshot.initiatives) > 30
    isp003 = next((i for i in snapshot.initiatives if i.initiative_id == "ISP-003"), None)
    assert isp003 is not None
    assert isp003.name == "RBAC Automation"
    assert isp003.team == "IAM"


def test_initiative_investment(snapshot):
    isp003 = next(i for i in snapshot.initiatives if i.initiative_id == "ISP-003")
    assert isp003.investment_dollars == 380000


def test_snapshot_summary(snapshot):
    s = snapshot.summary()
    assert s["objectives"] == 3
    assert s["key_results"] > 10
    assert s["initiatives"] > 30


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_okr_spreadsheet(Path("/nonexistent/file.xlsx"))
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_okr_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'okr.parser'`

**Step 3: Write implementation**

Create `okr/parser.py`:

```python
"""Parse the ISP OKR Excel spreadsheet into structured data."""
from datetime import datetime
from pathlib import Path

import openpyxl

from okr.models import Initiative, KeyResult, Objective, OKRSnapshot


def _cell_str(value) -> str:
    """Convert a cell value to a clean string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _cell_float(value) -> float:
    """Convert a cell value to float, defaulting to 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _parse_objectives(ws) -> list[Objective]:
    """Parse the Objectives tab (header on row 1, data from row 2)."""
    objectives = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:  # skip empty rows
            continue
        objectives.append(Objective(
            okr_id=_cell_str(row[0]),
            name=_cell_str(row[1]),
            statement=_cell_str(row[2]),
            owner=_cell_str(row[3]),
            team=_cell_str(row[4]),
            year=_cell_str(row[5]),
            status=_cell_str(row[7]),
            pct_complete=_cell_float(row[8]),
        ))
    return objectives


def _parse_key_results(ws) -> list[KeyResult]:
    """Parse the Key Results tab (header on row 1, data from row 2)."""
    results = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        results.append(KeyResult(
            kr_id=_cell_str(row[0]),
            okr_id=_cell_str(row[1]),
            name=_cell_str(row[3]),
            status=_cell_str(row[4]),
            pct_complete=_cell_float(row[5]),
            baseline=_cell_str(row[9]),
            target=_cell_str(row[11]),
            current_actual=_cell_str(row[19]),
            gap_to_target=_cell_str(row[21]),
            owner=_cell_str(row[13]),
            team=_cell_str(row[14]),
            q1_milestone=_cell_str(row[15]),
            q2_milestone=_cell_str(row[16]),
            q3_milestone=_cell_str(row[17]),
            q4_milestone=_cell_str(row[18]),
        ))
    return results


def _parse_initiatives(ws) -> list[Initiative]:
    """Parse the Initiatives tab (header on row 1, data from row 2)."""
    initiatives = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        initiatives.append(Initiative(
            initiative_id=_cell_str(row[0]),
            kr_ids=_cell_str(row[1]),
            okr_id=_cell_str(row[2]),
            name=_cell_str(row[4]),
            pct_complete=_cell_float(row[5]),
            status=_cell_str(row[6]),
            blocker=_cell_str(row[7]),
            owner=_cell_str(row[15]),
            team=_cell_str(row[16]),
            investment_tier=_cell_str(row[12]),
            maturity_type=_cell_str(row[14]),
            timeline_start=_cell_str(row[17]),
            timeline_end=_cell_str(row[18]),
            investment_dollars=_cell_float(row[20]),
            description=_cell_str(row[11]),
        ))
    return initiatives


def parse_okr_spreadsheet(path: Path) -> OKRSnapshot:
    """Parse an ISP OKR Excel file and return a structured snapshot.

    Args:
        path: Path to the .xlsx file.

    Returns:
        OKRSnapshot with objectives, key results, and initiatives.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Spreadsheet not found: {path}")

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)

    objectives = _parse_objectives(wb["Objectives"])
    key_results = _parse_key_results(wb["Key Results"])
    initiatives = _parse_initiatives(wb["Initiatives"])

    wb.close()

    return OKRSnapshot(
        timestamp=datetime.now().isoformat(),
        source_file=str(path),
        objectives=objectives,
        key_results=key_results,
        initiatives=initiatives,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_okr_parser.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add okr/parser.py tests/test_okr_parser.py
git commit -m "feat(okr): add Excel parser for ISP OKR spreadsheet"
```

---

## Task 4: JSON Snapshot Store

**Files:**
- Create: `okr/store.py`
- Test: `tests/test_okr_store.py`

**Step 1: Write the failing test**

Create `tests/test_okr_store.py`:

```python
"""Tests for OKR snapshot store."""
import json
import pytest
from pathlib import Path

from okr.models import Initiative, KeyResult, Objective, OKRSnapshot
from okr.store import OKRStore


@pytest.fixture
def store(tmp_path):
    return OKRStore(tmp_path / "okr")


@pytest.fixture
def sample_snapshot():
    return OKRSnapshot(
        timestamp="2026-02-16T10:00:00",
        source_file="test.xlsx",
        objectives=[
            Objective(okr_id="OKR 1", name="Trusted Controls", statement="Test",
                      owner="Jason", team="ISP", year="2026", status="On Track",
                      pct_complete=0.15),
            Objective(okr_id="OKR 2", name="Resilient Systems", statement="Test",
                      owner="Jason", team="ISP", year="2026", status="On Track",
                      pct_complete=0.0),
        ],
        key_results=[
            KeyResult(kr_id="KR 1.1", okr_id="OKR 1", name="Provisioning time",
                      status="Not Started", pct_complete=0.1, owner="Shawn",
                      team="IAM", target="<10 min"),
            KeyResult(kr_id="KR 2.1", okr_id="OKR 2", name="Mean time to contain",
                      status="On Track", pct_complete=0.2, owner="Michael",
                      team="SecOps", target="<8 hours"),
        ],
        initiatives=[
            Initiative(initiative_id="ISP-003", kr_ids="KR 1.1", okr_id="OKR 1",
                       name="RBAC Automation", pct_complete=0.05, status="On Track",
                       owner="Shawn", team="IAM", investment_tier="1",
                       maturity_type="Grow", investment_dollars=380000),
            Initiative(initiative_id="ISP-010", kr_ids="KR 2.1", okr_id="OKR 2",
                       name="WAF Implementation", pct_complete=0.0, status="At Risk",
                       owner="Jonas", team="Product Security", investment_tier="2",
                       blocker="Vendor selection delayed"),
        ],
    )


def test_save_and_load(store, sample_snapshot):
    store.save(sample_snapshot)
    loaded = store.load_latest()
    assert loaded is not None
    assert loaded.timestamp == sample_snapshot.timestamp
    assert len(loaded.objectives) == 2
    assert len(loaded.initiatives) == 2


def test_load_latest_no_data(store):
    assert store.load_latest() is None


def test_query_by_okr(store, sample_snapshot):
    store.save(sample_snapshot)
    results = store.query(okr_id="OKR 1")
    assert len(results["objectives"]) == 1
    assert len(results["key_results"]) == 1
    assert len(results["initiatives"]) == 1


def test_query_by_team(store, sample_snapshot):
    store.save(sample_snapshot)
    results = store.query(team="IAM")
    assert len(results["initiatives"]) == 1
    assert results["initiatives"][0]["name"] == "RBAC Automation"


def test_query_by_status(store, sample_snapshot):
    store.save(sample_snapshot)
    results = store.query(status="At Risk")
    assert len(results["initiatives"]) == 1
    assert results["initiatives"][0]["initiative_id"] == "ISP-010"


def test_query_blocked(store, sample_snapshot):
    store.save(sample_snapshot)
    results = store.query(blocked_only=True)
    assert len(results["initiatives"]) == 1
    assert results["initiatives"][0]["blocker"] == "Vendor selection delayed"


def test_query_text_search(store, sample_snapshot):
    store.save(sample_snapshot)
    results = store.query(text="RBAC")
    assert len(results["initiatives"]) == 1


def test_executive_summary(store, sample_snapshot):
    store.save(sample_snapshot)
    summary = store.executive_summary()
    assert summary["total_objectives"] == 2
    assert summary["total_key_results"] == 2
    assert summary["total_initiatives"] == 2
    assert summary["on_track"] == 1  # 1 initiative on track
    assert summary["at_risk"] == 1
    assert summary["total_investment"] == 380000
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_okr_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'okr.store'`

**Step 3: Write implementation**

Create `okr/store.py`:

```python
"""JSON-based snapshot store for OKR data."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from okr.models import Initiative, KeyResult, Objective, OKRSnapshot


class OKRStore:
    """Persists OKR snapshots as JSON and provides query methods."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_path = self.data_dir / "latest_snapshot.json"

    def save(self, snapshot: OKRSnapshot) -> Path:
        """Save a snapshot to disk."""
        data = asdict(snapshot)
        self._snapshot_path.write_text(json.dumps(data, indent=2, default=str))
        return self._snapshot_path

    def load_latest(self) -> Optional[OKRSnapshot]:
        """Load the most recent snapshot, or None if none exists."""
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

    def query(self, *, okr_id: str = "", team: str = "", status: str = "",
              blocked_only: bool = False, text: str = "") -> dict:
        """Query the latest snapshot with filters. Returns matching items."""
        snapshot = self.load_latest()
        if snapshot is None:
            return {"objectives": [], "key_results": [], "initiatives": [],
                    "message": "No OKR data loaded. Run refresh_okr_data first."}

        objs = [asdict(o) for o in snapshot.objectives]
        krs = [asdict(kr) for kr in snapshot.key_results]
        inits = [asdict(i) for i in snapshot.initiatives]

        if okr_id:
            objs = [o for o in objs if o["okr_id"] == okr_id]
            krs = [kr for kr in krs if kr["okr_id"] == okr_id]
            inits = [i for i in inits if i["okr_id"] == okr_id]

        if team:
            t = team.lower()
            krs = [kr for kr in krs if t in kr["team"].lower()]
            inits = [i for i in inits if t in i["team"].lower()]

        if status:
            s = status.lower()
            krs = [kr for kr in krs if s in kr["status"].lower()]
            inits = [i for i in inits if s in i["status"].lower()]

        if blocked_only:
            inits = [i for i in inits if i["blocker"]]

        if text:
            q = text.lower()
            objs = [o for o in objs if q in json.dumps(o).lower()]
            krs = [kr for kr in krs if q in json.dumps(kr).lower()]
            inits = [i for i in inits if q in json.dumps(i).lower()]

        return {"objectives": objs, "key_results": krs, "initiatives": inits}

    def executive_summary(self) -> dict:
        """Return high-level metrics from the latest snapshot."""
        snapshot = self.load_latest()
        if snapshot is None:
            return {"error": "No OKR data loaded. Run refresh_okr_data first."}

        init_statuses = [i.status.lower() for i in snapshot.initiatives]
        total_investment = sum(i.investment_dollars for i in snapshot.initiatives)

        return {
            "timestamp": snapshot.timestamp,
            "total_objectives": len(snapshot.objectives),
            "total_key_results": len(snapshot.key_results),
            "total_initiatives": len(snapshot.initiatives),
            "on_track": sum(1 for s in init_statuses if "on track" in s),
            "at_risk": sum(1 for s in init_statuses if "at risk" in s),
            "blocked": sum(1 for i in snapshot.initiatives if i.blocker),
            "not_started": sum(1 for s in init_statuses if "not started" in s),
            "total_investment": total_investment,
            "objectives_summary": [
                {"okr_id": o.okr_id, "name": o.name, "status": o.status,
                 "pct_complete": o.pct_complete}
                for o in snapshot.objectives
            ],
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_okr_store.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add okr/store.py tests/test_okr_store.py
git commit -m "feat(okr): add JSON snapshot store with query and summary"
```

---

## Task 5: MCP Tools — refresh_okr_data and query_okr_status

**Files:**
- Modify: `config.py` — add `OKR_DATA_DIR` and `OKR_SPREADSHEET_DEFAULT`
- Modify: `mcp_server.py` — add OKRStore to lifespan and two new tools
- Test: `tests/test_mcp_server.py` — add tests for the new tools

**Step 1: Add config constants**

In `config.py`, add:

```python
OKR_DATA_DIR = DATA_DIR / "okr"
OKR_SPREADSHEET_DEFAULT = OKR_DATA_DIR / "2026_ISP_OKR_Master_Final.xlsx"
```

**Step 2: Add OKRStore to mcp_server.py lifespan**

In `mcp_server.py`, add import at top:

```python
from okr.store import OKRStore
```

In `app_lifespan()`, after existing stores, add:

```python
okr_store = OKRStore(app_config.OKR_DATA_DIR)
```

Add to `_state.update({...})`:

```python
"okr_store": okr_store,
```

**Step 3: Add the two MCP tools**

Add to `mcp_server.py` after existing tools:

```python
# --- OKR Tools ---


@mcp.tool()
async def refresh_okr_data(source_path: str = "") -> str:
    """Parse the ISP OKR Excel spreadsheet and store a fresh snapshot.

    Downloads are expected at data/okr/2026_ISP_OKR_Master_Final.xlsx.
    Call this after downloading a new version of the spreadsheet.

    Args:
        source_path: Path to .xlsx file. Leave empty to use the default location.
    """
    from okr.parser import parse_okr_spreadsheet

    okr_store = _state["okr_store"]
    path = Path(source_path) if source_path else app_config.OKR_SPREADSHEET_DEFAULT

    if not path.exists():
        return json.dumps({
            "error": f"Spreadsheet not found at {path}. Download it first.",
            "hint": "Use the SharePoint link stored in memory (key: 2026_okr_sharepoint)."
        })

    snapshot = parse_okr_spreadsheet(path)
    okr_store.save(snapshot)

    summary = snapshot.summary()
    return json.dumps({
        "status": "refreshed",
        "parsed": summary,
        "message": f"Loaded {summary['objectives']} objectives, "
                   f"{summary['key_results']} key results, "
                   f"{summary['initiatives']} initiatives."
    })


@mcp.tool()
async def query_okr_status(
    query: str = "",
    okr_id: str = "",
    team: str = "",
    status: str = "",
    blocked_only: bool = False,
    summary_only: bool = False,
) -> str:
    """Query the latest OKR data. Use after refresh_okr_data has been called.

    Args:
        query: Free-text search across all OKR data (initiative names, descriptions, etc.)
        okr_id: Filter by OKR (e.g. "OKR 1", "OKR 2", "OKR 3")
        team: Filter by team (e.g. "IAM", "SecOps", "Product Security", "Privacy & GRC")
        status: Filter by status (e.g. "On Track", "At Risk", "Blocked", "Not Started")
        blocked_only: If true, only return initiatives with blockers
        summary_only: If true, return executive summary instead of detailed results
    """
    okr_store = _state["okr_store"]

    if summary_only:
        return json.dumps(okr_store.executive_summary())

    results = okr_store.query(
        okr_id=okr_id, team=team, status=status,
        blocked_only=blocked_only, text=query,
    )
    return json.dumps(results)
```

**Step 4: Write tests for the MCP tools**

Add to `tests/test_mcp_server.py` (or create a new `tests/test_mcp_okr.py`):

```python
"""Tests for OKR MCP tools."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

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
    assert summary["total_objectives"] == 1
    assert summary["total_initiatives"] == 1
    assert summary["total_investment"] == 380000


def test_query_by_team(okr_store):
    results = okr_store.query(team="IAM")
    assert len(results["initiatives"]) == 1


def test_query_text_search(okr_store):
    results = okr_store.query(text="RBAC")
    assert len(results["initiatives"]) == 1
```

**Step 5: Run all tests**

Run: `pytest tests/test_mcp_okr.py tests/test_okr_store.py tests/test_okr_models.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add config.py mcp_server.py okr/store.py tests/test_mcp_okr.py
git commit -m "feat(okr): add refresh_okr_data and query_okr_status MCP tools"
```

---

## Task 6: Agent Config — okr_tracker

**Files:**
- Create: `agent_configs/okr_tracker.yaml`

**Step 1: Create agent config**

Create `agent_configs/okr_tracker.yaml`:

```yaml
name: okr_tracker
description: >-
  Tracks ISP OKR progress from the master Excel spreadsheet. Parses objectives,
  key results, and initiatives into structured snapshots. Answers questions about
  OKR status, team workload, blocked items, investment allocation, and progress
  trends. Supports the executive leadership presentation with data-driven summaries.
system_prompt: >-
  You are an OKR tracking specialist for the ISP (Information Security & Privacy) team.
  You help track, analyze, and report on 2026 ISP OKRs which cover three strategic
  objectives: (1) Trusted Security & Privacy Controls, (2) Resilient Business Systems,
  and (3) Fast Risk Feedback.

  Your data comes from the ISP OKR Master spreadsheet stored locally. When asked about
  OKR status, always check the latest snapshot first. If the data seems stale (older
  than 1 week), recommend refreshing by downloading the latest spreadsheet.

  You can answer questions like:
  - What's the overall OKR status?
  - Which initiatives are blocked or at risk?
  - How is a specific team progressing?
  - What's the investment breakdown?
  - Help draft executive leadership presentation content

  Always ground answers in the actual data from the spreadsheet. Use specific numbers,
  percentages, and initiative IDs when reporting.
capabilities:
  - memory_read
  - memory_write
  - document_search
temperature: 0.3
max_tokens: 4096
```

**Step 2: Verify it loads**

Run: `python3 -c "from agents.registry import AgentRegistry; r = AgentRegistry(Path('agent_configs')); print(r.get_agent('okr_tracker').name)" 2>/dev/null || python3 -c "from pathlib import Path; from agents.registry import AgentRegistry; r = AgentRegistry(Path('agent_configs')); print(r.get_agent('okr_tracker').name)"`
Expected: `okr_tracker`

**Step 3: Commit**

```bash
git add agent_configs/okr_tracker.yaml
git commit -m "feat(okr): add okr_tracker agent config"
```

---

## Task 7: Wire pyproject.toml Package Discovery

**Files:**
- Modify: `pyproject.toml:29` — add `okr*` to package includes

**Step 1: Update package discovery**

In `pyproject.toml`, add `"okr*"` to the include list:

```toml
[tool.setuptools.packages.find]
include = ["memory*", "agents*", "documents*", "chief*", "tools*", "utils*", "apple_calendar*", "apple_notifications*", "apple_reminders*", "apple_mail*", "apple_messages*", "okr*"]
```

**Step 2: Reinstall**

Run: `pip install -e ".[dev]"`

**Step 3: Verify full test suite**

Run: `pytest tests/test_okr_models.py tests/test_okr_parser.py tests/test_okr_store.py tests/test_mcp_okr.py -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add okr package to setuptools discovery"
```

---

## Task 8: Initial Data Load — Parse and Store

This is an operational task, not a code task. Run after all code is committed.

**Step 1: Start MCP server or run parser directly**

Run: `python3 -c "
from pathlib import Path
from okr.parser import parse_okr_spreadsheet
from okr.store import OKRStore

snapshot = parse_okr_spreadsheet(Path('data/okr/2026_ISP_OKR_Master_Final.xlsx'))
store = OKRStore(Path('data/okr'))
store.save(snapshot)
s = snapshot.summary()
print(f'Loaded: {s[\"objectives\"]} objectives, {s[\"key_results\"]} key results, {s[\"initiatives\"]} initiatives')
print(f'Snapshot saved to data/okr/latest_snapshot.json')
"`

Expected: `Loaded: 3 objectives, 38 key results, 57 initiatives`

**Step 2: Verify query works**

Run: `python3 -c "
from pathlib import Path
from okr.store import OKRStore
import json

store = OKRStore(Path('data/okr'))
print('=== Executive Summary ===')
print(json.dumps(store.executive_summary(), indent=2))
print()
print('=== Blocked Items ===')
print(json.dumps(store.query(blocked_only=True), indent=2))
print()
print('=== At Risk ===')
print(json.dumps(store.query(status='At Risk'), indent=2))
"`

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Add openpyxl dependency | `pyproject.toml` |
| 2 | OKR data models | `okr/__init__.py`, `okr/models.py`, `tests/test_okr_models.py` |
| 3 | Excel parser | `okr/parser.py`, `tests/test_okr_parser.py` |
| 4 | JSON snapshot store | `okr/store.py`, `tests/test_okr_store.py` |
| 5 | MCP tools | `config.py`, `mcp_server.py`, `tests/test_mcp_okr.py` |
| 6 | Agent config | `agent_configs/okr_tracker.yaml` |
| 7 | Package wiring | `pyproject.toml` |
| 8 | Initial data load | Operational — run parser on downloaded file |

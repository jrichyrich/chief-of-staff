"""OKR tools for MCP server."""

import json
from pathlib import Path

import config as app_config


def register(mcp, state):
    """Register OKR tools with the MCP server."""

    @mcp.tool()
    async def refresh_okr_data(source_path: str = "") -> str:
        """Parse the ISP OKR Excel spreadsheet and store a fresh snapshot.

        Downloads are expected at data/okr/2026_ISP_OKR_Master_Final.xlsx.
        Call this after downloading a new version of the spreadsheet.

        Args:
            source_path: Path to .xlsx file. Leave empty to use the default location.
        """
        from okr.parser import parse_okr_spreadsheet

        okr_store = state.okr_store
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
        okr_store = state.okr_store

        if summary_only:
            return json.dumps(okr_store.executive_summary())

        results = okr_store.query(
            okr_id=okr_id, team=team, status=status,
            blocked_only=blocked_only, text=query,
        )
        return json.dumps(results)

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.refresh_okr_data = refresh_okr_data
    module.query_okr_status = query_okr_status

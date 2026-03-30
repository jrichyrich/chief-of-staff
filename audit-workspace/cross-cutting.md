# Cross-Cutting Scan Results

## TODO/FIXME/HACK Markers
- Only 1 real TODO in source: `delivery/service.py:62` — `raise NotImplementedError` (abstract method)
- `session/manager.py:31` uses TODO as a regex pattern for detecting action items in user messages (not a code TODO)
- All other TODO references are in test data strings — clean.

**Assessment**: Clean. No unfinished work markers in production code except the expected abstract method.

## Empty Pass Bodies (41 instances)
Grouped by concern:

### Exception swallowing (HIGH concern)
- `webhook/dispatcher.py:202` — pass in exception handler
- `connectors/graph_client.py:182,192,199,523` — 4 bare except/pass blocks in Graph API client
- `memory/store.py:454,462,471,479` — 4 bare passes in memory store
- `memory/agent_memory_store.py:88` — pass in exception handler
- `memory/fact_store.py:246,370` — 2 passes in fact store
- `memory/scheduler_store.py:126` — pass in scheduler store
- `scheduler/engine.py:241,341` — 2 passes in scheduler engine
- `agents/factory.py:57` — pass in agent factory
- `agents/triage.py:69` — pass in triage
- `agents/base.py:738,885` — 2 passes in base agent
- `chief/imessage_executor.py:71` — pass in executor
- `browser/teams_poster.py:64` — pass
- `browser/navigator.py:77` — pass
- `browser/ab_navigator.py:152,344` — 2 passes
- `browser/sharepoint_download.py:364` — pass
- `browser/agent_browser.py:64` — pass
- `browser/manager.py:70` — pass
- `orchestration/playbook_executor.py:32` — pass (looks like abstract class)
- `orchestration/synthesis.py:85` — pass
- `apple_mail/mail.py:419` — pass
- `proactive/engine.py:148` — pass
- `mcp_tools/usage_tracker.py:124` — pass
- `mcp_tools/session_tools.py:150` — pass
- `mcp_tools/resources.py:62,73,91,102,115` — 5 passes in resource handlers

**Assessment**: 41 empty pass blocks, most in exception handlers. These are silent failure points — errors get swallowed without logging. The Graph API client (4 instances) and memory stores (8 instances) are the highest risk since they're core data paths.

## Hardcoded Secrets
- **None found** in source code. Clean.
- Secrets managed via macOS Keychain (`vault/keychain.py`)

## Hardcoded URLs (Expected/Acceptable)
- Microsoft Graph API endpoints: `https://graph.microsoft.com/v1.0` — correct, standard
- Microsoft login authority: `https://login.microsoftonline.com/{tenant}` — correct
- Okta URL: `https://mychg.okta.com` — org-specific but acceptable in constants
- SharePoint URL patterns in `config.py` and `browser/sharepoint_download.py` — org-specific
- Teams URLs: `https://teams.microsoft.com`, `https://teams.cloud.microsoft/` — standard
- Local CDP ports: `http://127.0.0.1:{cdp_port}/json` — localhost, fine

**Assessment**: No leaked secrets. Org-specific URLs are in constants/config, which is acceptable.

## Dependency Analysis
Dependencies from `pyproject.toml`:
- `anthropic>=0.42.0` — Anthropic SDK
- `chromadb>=0.5.0` — vector DB
- `openpyxl>=3.1.0` — Excel parsing
- `pyyaml>=6.0` — YAML configs
- `mcp[cli]>=1.26,<2` — MCP framework
- `pyobjc-framework-EventKit>=10.0` — Apple Calendar/Reminders (macOS only)
- `pypdf>=5.0.0` — PDF parsing
- `python-docx>=1.1.0` — DOCX parsing
- `playwright>=1.40.0` — browser automation
- `rich>=13.0` — terminal formatting

Optional:
- `msal>=1.28.0` — Microsoft auth
- Dev: pytest, pytest-asyncio, pytest-mock, pytest-cov, httpx

**Assessment**: Dependencies are reasonable and well-scoped. No known CVEs flagged. Some version ranges are very open (e.g., `>=0.42.0` for anthropic).

## Test vs Source Ratio
- **Source**: 31,847 lines
- **Tests**: 43,771 lines (137 test files)
- **Ratio**: 1.37x tests-to-source

**Assessment**: Excellent test coverage ratio. Tests significantly exceed source code, indicating strong test discipline.

## Key Interface Exports
Not enumerated in detail (75K lines), but the primary public interface is:
- 25+ `mcp_tools/*.py` modules each exporting a `register(mcp, state)` function
- `BaseExpertAgent` class as the agent execution API
- `MemoryStore` as the persistence API
- `config.py` as the configuration surface

## Summary of Cross-Cutting Concerns

| Area | Status | Notes |
|------|--------|-------|
| TODO/FIXME markers | ✅ Clean | 1 expected NotImplementedError |
| Empty pass blocks | ⚠️ 41 instances | Silent error swallowing in core paths |
| Hardcoded secrets | ✅ Clean | Keychain-based |
| Hardcoded URLs | ✅ Acceptable | Org-specific in constants |
| Dependencies | ✅ Reasonable | Open version ranges |
| Test ratio | ✅ Excellent | 1.37x tests-to-source |

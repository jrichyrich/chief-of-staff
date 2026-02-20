# Setup Guide

Step-by-step instructions for installing and configuring Chief of Staff (Jarvis).

## Prerequisites

- **Python 3.11+** -- required by the project (`requires-python = ">=3.11"` in pyproject.toml)
- **macOS** -- required for Apple integrations (Calendar, Reminders, Mail, Messages via EventKit and AppleScript)
- **Homebrew** -- for installing system dependencies (`jq`, `sqlite3`)
- **Anthropic API key** -- powers all Claude-based agent reasoning
- **Claude CLI** (optional) -- needed for the inbox monitor, iMessage daemon, and Microsoft 365 bridge (`claude` command in PATH)

## Installation

### 1. Clone the repository

```bash
git clone <repo-url> chief_of_staff
cd chief_of_staff
```

### 2. Install in development mode

```bash
pip install -e ".[dev]"
```

This installs the project with all runtime and test dependencies:

| Category | Packages |
|----------|----------|
| Runtime | `anthropic`, `chromadb`, `openpyxl`, `pyyaml`, `mcp[cli]`, `pyobjc-framework-EventKit` (macOS), `pypdf`, `python-docx` |
| Dev | `pytest`, `pytest-asyncio`, `pytest-mock`, `pytest-cov`, `httpx` |

### 3. Install system dependencies

```bash
brew install jq sqlite3
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values. See the [Environment Variables](#environment-variables) section below.

## Environment Variables

All settings are read from environment variables. The `.env.example` file documents every option.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | -- | Anthropic API key for Claude access |
| `JARVIS_PROJECT_DIR` | No | Parent of `scripts/` | Project root directory |
| `JARVIS_DATA_DIR` | No | `$JARVIS_PROJECT_DIR/data` | Runtime data directory (SQLite DBs, logs) |
| `JARVIS_DEFAULT_EMAIL_TO` | No | -- | Default recipient for generated email drafts |
| `JARVIS_IMESSAGE_SELF` | No | -- | Your phone number for iMessage self-identification |
| `CLAUDE_BIN` | No | `claude` | Path to the Claude CLI binary |
| `CLAUDE_MCP_CONFIG` | No | -- | Path to MCP config file for Claude CLI subprocess calls |
| `M365_BRIDGE_MODEL` | No | `sonnet` | Claude model used by the M365 bridge subprocess |
| `M365_BRIDGE_TIMEOUT_SECONDS` | No | `90` | Timeout for M365 bridge operations |
| `M365_BRIDGE_DETECT_TIMEOUT_SECONDS` | No | `5` | Timeout for detecting whether the M365 connector is available |
| `CALENDAR_REQUIRE_DUAL_READ` | No | `true` | When true, calendar reads query both Apple and M365 providers |
| `JARVIS_ONEDRIVE_BASE` | No | -- | OneDrive path for backup script (e.g. `$HOME/Library/CloudStorage/OneDrive-YourOrg`) |

The inbox monitor and iMessage daemon have additional env vars documented in [docs/inbox-monitor-setup.md](inbox-monitor-setup.md).

## macOS Permissions

Jarvis uses several macOS APIs that require explicit user consent. Grant these in **System Settings > Privacy & Security**:

### Calendar and Reminders (EventKit)

The first time the MCP server accesses Calendar or Reminders, macOS will prompt for permission. Click **Allow** when prompted. If you denied access previously:

1. Open **System Settings > Privacy & Security > Calendars** (or **Reminders**)
2. Find your terminal app or Python and toggle it **on**

### Full Disk Access (iMessage reader)

The iMessage reader binary needs to read `~/Library/Messages/chat.db`, which macOS protects:

1. Open **System Settings > Privacy & Security > Full Disk Access**
2. Click the **+** button
3. Press `Cmd+Shift+G` and navigate to `<project>/scripts/imessage-reader`
4. Toggle it **on**

If you rebuild the binary from source, you must re-grant Full Disk Access since the code signature changes.

### Contacts (optional)

If any agent workflows query Contacts, grant access when prompted.

## Running the MCP Server

### Command line

```bash
jarvis-mcp
```

This starts the FastMCP server on stdio transport. It is not meant to be run directly in a terminal for interactive use -- it communicates via JSON-RPC over stdin/stdout.

### Claude Code integration

Add to your project `.mcp.json`:

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "python3.11",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/chief_of_staff",
      "env": {
        "PYTHONPATH": "/path/to/chief_of_staff"
      }
    }
  }
}
```

Replace `/path/to/chief_of_staff` with the actual path to your clone.

### Claude Desktop integration (DXT)

Build a DXT package for Claude Desktop:

```bash
mcpb pack . jarvis.mcpb
```

This uses the `manifest.json` to produce a `.dxt` file you can install in Claude Desktop (requires Claude Desktop >= 0.10.0).

## LaunchAgent Setup

Four macOS LaunchAgents automate background tasks. Install them all at once:

```bash
./scripts/install-plists.sh
```

The script replaces `__PROJECT_DIR__` placeholders in the plist templates with your actual project path, copies them to `~/Library/LaunchAgents/`, and loads them.

### What each plist does

| LaunchAgent | Purpose |
|-------------|---------|
| `com.chg.inbox-monitor` | Polls iMessages every 15 minutes for `jarvis:` commands and processes them via Claude CLI |
| `com.chg.jarvis-backup` | Periodic backup of runtime data |
| `com.chg.alert-evaluator` | Evaluates alert rules (overdue delegations, stale decisions, upcoming deadlines) |
| `com.chg.imessage-daemon` | Continuously ingests iMessage events into a SQLite queue and dispatches to the inbox monitor |

### Verify LaunchAgents are running

```bash
launchctl list | grep com.chg
```

### Uninstall

To unload and remove all LaunchAgents:

```bash
./scripts/install-plists.sh --uninstall
```

## Microsoft 365 Integration

The M365 integration works through a bridge that spawns a Claude CLI subprocess with the Microsoft 365 MCP connector attached.

### Prerequisites

1. **Claude CLI** installed and authenticated
2. **Microsoft 365 MCP connector** connected in your Claude configuration

### Configuration

Set these environment variables in your `.env`:

```bash
CLAUDE_BIN=claude                  # Path to Claude CLI binary
CLAUDE_MCP_CONFIG=                 # Optional: path to MCP config with M365 connector
M365_BRIDGE_MODEL=sonnet           # Claude model for bridge calls
M365_BRIDGE_TIMEOUT_SECONDS=90     # Operation timeout
M365_BRIDGE_DETECT_TIMEOUT_SECONDS=5  # Connector detection timeout
```

### How the bridge works

1. On startup, `ClaudeM365Bridge` calls `claude mcp list` to detect if the Microsoft 365 connector is available
2. When a calendar operation targets M365 (e.g., Outlook calendar), the bridge spawns `claude -p` with the appropriate prompt
3. The unified calendar service (`connectors/calendar_unified.py`) routes operations to either the Apple or M365 provider based on event ownership tracking in `data/calendar-routing.db`
4. Set `CALENDAR_REQUIRE_DUAL_READ=true` (the default) to query both providers on read operations

If the M365 connector is not detected at startup, M365 calendar operations are silently skipped and only Apple Calendar is used.

## Verification

### Run the test suite

```bash
pytest
```

All tests should pass (825 expected). Tests mock all external APIs -- no Anthropic key or macOS permissions needed.

### Start the MCP server

```bash
jarvis-mcp
```

The server should initialize without errors (log output goes to stderr).

### Test from Claude Code

With the `.mcp.json` configured, open Claude Code in the project directory and try:

```
Jarvis, what do you know about me?
```

This should invoke the `query_memory` tool via the MCP server.

## Troubleshooting

### EventKit permissions denied

**Symptom**: Calendar or Reminders tools return permission errors.

**Fix**: Open **System Settings > Privacy & Security > Calendars** (or **Reminders**) and ensure your terminal/Python has access enabled. You may need to restart the MCP server after granting permissions.

### iMessage "Full Disk Access denied"

**Symptom**: `imessage-reader` cannot read the Messages database.

**Fix**: Grant Full Disk Access to the binary (see [macOS Permissions](#macos-permissions) above). Test with:

```bash
./scripts/imessage-reader --minutes 1
```

### M365 connector not detected

**Symptom**: Calendar operations only show Apple Calendar events, no Outlook events.

**Fix**:
1. Verify the Claude CLI is installed: `claude --version`
2. Check that the M365 connector is connected: `claude mcp list`
3. Ensure `CLAUDE_BIN` points to the correct binary
4. If using a custom MCP config, set `CLAUDE_MCP_CONFIG` to the config file path

### "claude: command not found" in LaunchAgents

**Symptom**: LaunchAgent logs show `claude: command not found`.

**Fix**: The LaunchAgent PATH is set to `/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin`. If your `claude` binary is elsewhere, update the PATH in the plist's `EnvironmentVariables` section, or set `CLAUDE_BIN` to the full path.

### Package naming warning

Never create a Python package named `calendar/` in this project. It shadows Python's stdlib `calendar` module, which breaks the import chain `http.cookiejar` -> `httpx` -> `anthropic`. The project uses `apple_calendar/` for this reason.

### ChromaDB errors on first run

If `chromadb` fails to initialize, ensure the `data/` directory exists:

```bash
mkdir -p data/chroma
```

The MCP server lifespan handler creates this automatically, but manual creation may be needed if running individual modules directly.

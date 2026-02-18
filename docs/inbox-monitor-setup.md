# Inbox Monitor Setup Guide

The inbox monitor polls your iMessage (Messages.app) for messages prefixed with `jarvis:` and processes them automatically using Claude Code in headless mode. Send yourself an iMessage with a `jarvis:` command, and it gets picked up and executed within minutes.

## How It Works

1. A macOS LaunchAgent runs `scripts/inbox-monitor.sh` every 15 minutes
2. The script queries `~/Library/Messages/chat.db` via the `imessage-reader` binary
3. It finds messages matching the `jarvis:` prefix that were sent by you (`is_from_me = 1`) within the lookback window
4. Each new message is processed by invoking `claude -p` with the extracted instruction
5. Processed message GUIDs are saved to `data/inbox-processed.json` to prevent duplicates
6. All actions are logged to `data/inbox-log.md`
7. On each run, connector availability is detected via `claude mcp list`.
8. Each message gets a deterministic route decision (policy profile + preferred/fallback provider), with Microsoft 365-first for Teams/Outlook tasks and local Jarvis fallback.
9. Pass 2 structured output now includes `provider_used` and `fallback_used`, and impossible provider claims are rejected and logged.
10. Routing decisions and outcomes are appended to `data/inbox-routing-audit.jsonl`.
11. High-risk write/destructive requests are held behind a hard approval gate, queued with an approval ID and TTL, and executed only after an explicit `approve`.
12. Optional daemon mode (`scripts/imessage-daemon.py`) continuously ingests iMessage events into a SQLite queue and dispatches queued work to `inbox-monitor.sh`.

## Prerequisites

- **Claude Code CLI** installed and authenticated (`claude` command available in PATH)
- **jq** installed: `brew install jq`
- **Full Disk Access** for `scripts/imessage-reader` — required to read the iMessage database. To grant it:
  1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
  2. Click the **+** button
  3. Press `Cmd+Shift+G`, navigate to the project's `scripts/imessage-reader`
  4. Toggle it **on** in the list
- **MCP connectors configured in your Claude host setup** (default mode).
  `inbox-monitor.sh` does not force `--mcp-config` unless you explicitly pass one, so host-connected connectors (including Microsoft 365) are used automatically.
- **Optional**: project `.mcp.json` if you want to override with `--project-mcp-config` or `--mcp-config`.

## Installation

### Optional: run the iMessage daemon (recommended)

The daemon keeps ingestion state in SQLite and dispatches quickly, instead of waiting on a coarse polling interval.

```bash
# Run one daemon cycle for verification
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/imessage-daemon.py --once

# Run continuously in foreground
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/imessage-daemon.py
```

Install as LaunchAgent:

```bash
cp /Users/jasricha/Documents/GitHub/chief_of_staff/scripts/com.chg.imessage-daemon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.chg.imessage-daemon.plist
launchctl list | grep imessage-daemon
```

Daemon artifacts:
- `data/imessage-worker.db` — ingestion and processing queue state
- `data/imessage-daemon.log` — daemon log output
- `data/imessage-daemon.lock` — single-instance lock file

### 1. Verify prerequisites

```bash
# Check claude CLI
claude --version

# Check jq
jq --version

# Verify the imessage-reader binary can access the database
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/imessage-reader --minutes 1

# Test the script manually
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh
```

### 2. Install the LaunchAgent (recommended)

```bash
# Copy the plist to LaunchAgents
cp /Users/jasricha/Documents/GitHub/chief_of_staff/scripts/com.chg.inbox-monitor.plist ~/Library/LaunchAgents/

# Load and start the agent
launchctl load ~/Library/LaunchAgents/com.chg.inbox-monitor.plist

# Verify it's running
launchctl list | grep inbox-monitor
```

The LaunchAgent runs every 900 seconds (15 minutes) and starts automatically on login.

### 3. Verify it's working

```bash
# Watch the log
tail -f /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-log.md

# Check the launch output log
tail -f /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-cron.log
```

## Building from Source

A pre-built `imessage-reader` binary is included in the repo. If you need to rebuild it (e.g., after modifying the source):

```bash
cd /Users/jasricha/Documents/GitHub/chief_of_staff
cc -O2 -o scripts/imessage-reader scripts/imessage-reader.c -lsqlite3
codesign --force --sign - --identifier "com.chiefofstaff.imessage-reader" scripts/imessage-reader
```

**Note:** Recompiling changes the binary's code signature. You must re-grant Full Disk Access after rebuilding.

If macOS blocks the binary on first run (Gatekeeper quarantine), remove the quarantine attribute:

```bash
xattr -d com.apple.quarantine scripts/imessage-reader
```

## Usage

Open Messages.app and send an iMessage to yourself with the prefix `jarvis:`. Examples:

| Message | Action |
|---------|--------|
| `jarvis: remember my dentist is Dr. Smith at 555-1234` | Stores a personal fact |
| `jarvis: todo review Q3 budget proposal by Friday` | Creates a work todo |
| `jarvis: note sync with design team went well, agreed on v2 wireframes` | Stores a work note |
| `jarvis: agenda standup: discuss deploy timeline, review blockers` | Stores meeting agenda item |
| `jarvis: search project architecture decisions` | Searches ingested documents |
| `jarvis: lookup my upcoming meetings` | Queries stored memory facts |
| `jarvis: approve apr-20260216093000-abc123ef` | Executes a previously queued high-risk request |
| `jarvis: reject apr-20260216093000-abc123ef` | Rejects a queued high-risk request |

## Configuration

### Environment variables

Use env vars to avoid hardcoded paths/settings:

- `JARVIS_PROJECT_DIR` — project root (default: parent directory of `scripts/`)
- `JARVIS_DATA_DIR` — data directory (default: `${JARVIS_PROJECT_DIR}/data`)
- `INBOX_MONITOR_PROCESSED_FILE` — processed IDs JSON file path
- `INBOX_MONITOR_LOG_FILE` — monitor log file path
- `INBOX_MONITOR_MCP_CONFIG` — explicit MCP config path (optional override)
- `JARVIS_DEFAULT_EMAIL_TO` — address for generated email drafts (optional)
- `INBOX_MONITOR_ROUTING_AUDIT_FILE` — JSONL file for per-message connector routing audit events
- `INBOX_MONITOR_PENDING_APPROVALS_FILE` — pending hard-approval queue JSON file
- `INBOX_MONITOR_APPROVAL_AUDIT_FILE` — JSONL audit for requested/approved/rejected/executed approvals
- `INBOX_MONITOR_APPROVAL_TTL_MINUTES` — expiration window for pending approvals (default: `60`)
- `IMESSAGE_DAEMON_STATE_DB` — daemon SQLite state DB path (default: `${JARVIS_DATA_DIR}/imessage-worker.db`)
- `IMESSAGE_DAEMON_LOG_FILE` — daemon log path (default: `${JARVIS_DATA_DIR}/imessage-daemon.log`)
- `IMESSAGE_DAEMON_LOCK_FILE` — daemon lock file (default: `${JARVIS_DATA_DIR}/imessage-daemon.lock`)
- `IMESSAGE_DAEMON_POLL_INTERVAL_SECONDS` — ingest/dispatch cycle interval (default: `5`)
- `IMESSAGE_DAEMON_BOOTSTRAP_LOOKBACK_MINUTES` — initial lookback when no watermark exists (default: `30`)
- `IMESSAGE_DAEMON_DISPATCH_BATCH_SIZE` — queued jobs handed off per cycle (default: `25`)

If `JARVIS_DEFAULT_EMAIL_TO` is unset, email draft delivery is skipped (the run continues).

### Adjusting the polling interval

Edit the LaunchAgent plist (`~/Library/LaunchAgents/com.chg.inbox-monitor.plist`):

```xml
<key>StartInterval</key>
<integer>900</integer>  <!-- 900 = 15 min, 300 = 5 min, 1800 = 30 min -->
```

Then reload:

```bash
launchctl unload ~/Library/LaunchAgents/com.chg.inbox-monitor.plist
launchctl load ~/Library/LaunchAgents/com.chg.inbox-monitor.plist
```

### Adjusting the lookback window

Set the lookback slightly larger than your polling interval to avoid missing messages:

```bash
# In the plist ProgramArguments, add --interval:
<array>
    <string>/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh</string>
    <string>--interval</string>
    <string>20</string>
</array>
```

## Checking the Log

```bash
# View recent log entries
tail -30 /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-log.md

# Search for errors
grep "ERROR" /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-log.md

# View processed message tracker
cat /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-processed.json | jq .
```

## Testing Manually

```bash
# Run the monitor once
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh

# Run with a longer lookback (e.g., last 60 minutes)
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh --interval 60

# Force project-local MCP config override
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh --project-mcp-config

# Set explicit email draft delivery target
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh --email-to "you@example.com"

# Print detected connector availability and exit
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh --print-connector-status

# Override hard-approval TTL
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh --approval-ttl-minutes 120

# Run one daemon cycle
/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/imessage-daemon.py --once

# Check what was processed
cat /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-processed.json | jq .
tail -20 /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-log.md

# Inspect connector routing audit records
tail -20 /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-routing-audit.jsonl | jq .

# Inspect approval queue and audit
cat /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-pending-approvals.json | jq .
tail -20 /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-approvals-audit.jsonl | jq .

# Inspect daemon state and logs
sqlite3 /Users/jasricha/Documents/GitHub/chief_of_staff/data/imessage-worker.db '.tables'
tail -20 /Users/jasricha/Documents/GitHub/chief_of_staff/data/imessage-daemon.log
```

## Troubleshooting

### "Full Disk Access denied" / Cannot read iMessage database

The `imessage-reader` binary needs to read `~/Library/Messages/chat.db`, which macOS protects. Grant Full Disk Access:

1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
2. Click **+**, press `Cmd+Shift+G`, and navigate to the project's `scripts/imessage-reader`
3. Toggle it **on**
4. Test: `/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/imessage-reader --minutes 1`

If you rebuilt the binary from source, you must re-grant FDA since the code signature changed.

### "Database locked"

Messages.app uses WAL (Write-Ahead Logging) mode for `chat.db`. Read queries from the monitor script do not conflict with Messages.app writes, so this error is rare. If it occurs:

1. Verify Messages.app is not in the middle of a sync (wait a moment and retry)
2. The script will exit on failure — the next scheduled run will pick up the messages

### "claude: command not found"

The `claude` CLI is not in PATH. The LaunchAgent plist sets PATH to `/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin`. If claude is installed elsewhere:

```bash
# Find where claude is installed
which claude

# Update the PATH in the plist EnvironmentVariables section
```

### "jq: command not found"

Install jq: `brew install jq`. Already covered by the plist PATH including `/opt/homebrew/bin`.

### No messages being found

1. Make sure you sent the message **to yourself** in Messages.app (iMessage to your own phone number or email)
2. Verify the message starts with `jarvis:` (case-insensitive)
3. Check that the lookback window covers when the message was sent
4. Test the query manually: `/Users/jasricha/Documents/GitHub/chief_of_staff/scripts/imessage-reader --minutes 60 | jq .`

### Messages processed twice

This should not happen due to dedup via `data/inbox-processed.json`. If it does:
1. Check that the processed file is not being corrupted (valid JSON)
2. Verify the LaunchAgent is not running overlapping instances

### Processed IDs file growing too large

The script automatically prunes to the last 500 IDs. If you need to reset:

```bash
echo '{"processed_ids": [], "last_run": null}' > /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-processed.json
```

### Stopping the monitor

```bash
# Unload the LaunchAgent
launchctl unload ~/Library/LaunchAgents/com.chg.inbox-monitor.plist

# Or remove it entirely
rm ~/Library/LaunchAgents/com.chg.inbox-monitor.plist
```

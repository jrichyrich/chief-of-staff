# Inbox Monitor Setup Guide

The inbox monitor polls your iMessage (Messages.app) for messages prefixed with `jarvis:` and processes them automatically using Claude Code in headless mode. Send yourself an iMessage with a `jarvis:` command, and it gets picked up and executed within minutes.

## How It Works

1. A macOS LaunchAgent runs `scripts/inbox-monitor.sh` every 15 minutes
2. The script queries `~/Library/Messages/chat.db` via the `imessage-reader` binary
3. It finds messages matching the `jarvis:` prefix that were sent by you (`is_from_me = 1`) within the lookback window
4. Each new message is processed by invoking `claude -p` with the extracted instruction
5. Processed message GUIDs are saved to `data/inbox-processed.json` to prevent duplicates
6. All actions are logged to `data/inbox-log.md`

## Prerequisites

- **Claude Code CLI** installed and authenticated (`claude` command available in PATH)
- **jq** installed: `brew install jq`
- **Full Disk Access** for `scripts/imessage-reader` — required to read the iMessage database. To grant it:
  1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
  2. Click the **+** button
  3. Press `Cmd+Shift+G`, navigate to the project's `scripts/imessage-reader`
  4. Toggle it **on** in the list
- **Chief of Staff MCP server** configured in `.mcp.json` (already set up in this repo)

## Installation

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

## Configuration

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

# Check what was processed
cat /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-processed.json | jq .
tail -20 /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-log.md
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

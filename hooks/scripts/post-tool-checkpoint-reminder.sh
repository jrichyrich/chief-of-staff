#!/bin/bash
# PostToolUse hook: tracks tool call count and suggests checkpoint when threshold reached.
# Reads tool_name from stdin JSON. Uses a counter file in /tmp to track calls.
# When count >= CHECKPOINT_THRESHOLD and no checkpoint recorded recently, injects
# a systemMessage reminding Claude to run checkpoint_session.

COUNTER_FILE="/tmp/jarvis_tool_call_count"
CHECKPOINT_FILE="/tmp/jarvis_last_checkpoint"
CHECKPOINT_THRESHOLD=50
CHECKPOINT_COOLDOWN_SECONDS=1800  # 30 minutes

# Read stdin (PostToolUse input JSON)
read -r INPUT 2>/dev/null || true

# If this was a checkpoint_session call, record the timestamp for cooldown
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
if [ "$TOOL_NAME" = "mcp__jarvis__checkpoint_session" ] || [ "$TOOL_NAME" = "mcp__chief-of-staff__checkpoint_session" ]; then
    date +%s > "$CHECKPOINT_FILE"
    echo "0" > "$COUNTER_FILE"
    echo "{}"
    exit 0
fi

# Increment counter
if [ -f "$COUNTER_FILE" ]; then
    COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo "0")
    COUNT=$((COUNT + 1))
else
    COUNT=1
fi
echo "$COUNT" > "$COUNTER_FILE"

# Check if we should suggest a checkpoint
if [ "$COUNT" -ge "$CHECKPOINT_THRESHOLD" ]; then
    SHOULD_SUGGEST=true

    # Check cooldown
    if [ -f "$CHECKPOINT_FILE" ]; then
        LAST_CP=$(cat "$CHECKPOINT_FILE" 2>/dev/null || echo "0")
        NOW=$(date +%s)
        ELAPSED=$((NOW - LAST_CP))
        if [ "$ELAPSED" -lt "$CHECKPOINT_COOLDOWN_SECONDS" ]; then
            SHOULD_SUGGEST=false
        fi
    fi

    if [ "$SHOULD_SUGGEST" = true ]; then
        # Mark that we suggested (reset counter to avoid spamming)
        echo "0" > "$COUNTER_FILE"
        cat << EOF
{"systemMessage": "Session health: ${COUNT} tool calls with no recent checkpoint. Consider running checkpoint_session(auto_checkpoint=True) to preserve important context before potential compaction."}
EOF
        exit 0
    fi
fi

# No suggestion needed — output empty JSON
echo "{}"

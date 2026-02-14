#!/usr/bin/env bash
#
# inbox-monitor.sh — Polls iMessage for "jarvis:" commands and processes them.
#
# Usage:
#   ./scripts/inbox-monitor.sh              # Run once (default 20-minute lookback)
#   ./scripts/inbox-monitor.sh --interval 30 # Custom lookback window in minutes
#
# Cron example (every 15 minutes):
#   */15 * * * * /Users/jasricha/Documents/GitHub/chief_of_staff/scripts/inbox-monitor.sh >> /Users/jasricha/Documents/GitHub/chief_of_staff/data/inbox-cron.log 2>&1
#
# Requirements:
#   - claude CLI installed and authenticated (https://docs.anthropic.com/en/docs/claude-code)
#   - jq installed (brew install jq)
#   - Full Disk Access granted for scripts/imessage-reader (System Settings > Privacy & Security > Full Disk Access)

set -euo pipefail

# Prevent nested Claude Code session errors when invoked from inside Claude Code
unset CLAUDECODE 2>/dev/null || true

# ── Configuration ──────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="/Users/jasricha/Documents/GitHub/chief_of_staff"
MCP_CONFIG="${PROJECT_DIR}/.mcp.json"
DATA_DIR="${PROJECT_DIR}/data"
PROCESSED_FILE="${DATA_DIR}/inbox-processed.json"
LOG_FILE="${DATA_DIR}/inbox-log.md"
LOOKBACK_MINUTES=20
MAX_RETRIES=2

# ── Parse arguments ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval)
            LOOKBACK_MINUTES="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: inbox-monitor.sh [--interval MINUTES]"
            echo "  --interval  Lookback window in minutes (default: 20)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────────────────────
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    local msg="$1"
    echo "[$(timestamp)] ${msg}" >> "${LOG_FILE}"
}

log_to_stderr() {
    echo "[$(timestamp)] $1" >&2
}

# ── Preflight checks ──────────────────────────────────────────────────────────
if ! command -v claude &>/dev/null; then
    log_to_stderr "ERROR: 'claude' CLI not found. Install from https://docs.anthropic.com/en/docs/claude-code"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    log_to_stderr "ERROR: 'jq' not found. Install with: brew install jq"
    exit 1
fi

# Full Disk Access check — required to read the iMessage database
if ! "${SCRIPT_DIR}/imessage-reader" --minutes 1 &>/dev/null; then
    log_to_stderr "ERROR: Cannot read iMessage database."
    log_to_stderr "Grant Full Disk Access to the imessage-reader binary:"
    log_to_stderr "  System Settings > Privacy & Security > Full Disk Access"
    log_to_stderr "  Add ${SCRIPT_DIR}/imessage-reader"
    exit 1
fi

# Ensure data directory exists
mkdir -p "${DATA_DIR}"

# Initialize processed file if missing
if [[ ! -f "${PROCESSED_FILE}" ]]; then
    echo '{"processed_ids": [], "last_run": null}' > "${PROCESSED_FILE}"
    log "Initialized ${PROCESSED_FILE}"
fi

# Initialize log file if missing
if [[ ! -f "${LOG_FILE}" ]]; then
    echo "# Inbox Monitor Log" > "${LOG_FILE}"
    echo "" >> "${LOG_FILE}"
    log "Log file created"
fi

# ── Load previously processed GUIDs ─────────────────────────────────────────
PROCESSED_GUIDS=$(jq -r '.processed_ids // []' "${PROCESSED_FILE}")

# ── Query iMessage database ──────────────────────────────────────────────────
log "Starting inbox check (lookback: ${LOOKBACK_MINUTES} min)"

RAW_MESSAGES=$("${SCRIPT_DIR}/imessage-reader" --minutes "${LOOKBACK_MINUTES}" 2>/dev/null) || {
    log "ERROR: Failed to query iMessage database"
    log_to_stderr "ERROR: Failed to query iMessage database"
    exit 1
}

TOTAL_FOUND=$(echo "${RAW_MESSAGES}" | jq 'length')
log "Found ${TOTAL_FOUND} jarvis: messages in last ${LOOKBACK_MINUTES} minutes"

if [[ "${TOTAL_FOUND}" -eq 0 ]]; then
    # Update last_run timestamp
    UPDATED=$(jq --arg now "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        '.last_run = $now' "${PROCESSED_FILE}")
    echo "${UPDATED}" > "${PROCESSED_FILE}"
    log "No messages to process"
    log "--- Run complete ---"
    exit 0
fi

# ── Filter out already-processed GUIDs ────────────────────────────────────────
NEW_MESSAGES=$(echo "${RAW_MESSAGES}" | jq --argjson processed "${PROCESSED_GUIDS}" \
    '[.[] | select(.guid as $g | $processed | index($g) | not)]')

NEW_COUNT=$(echo "${NEW_MESSAGES}" | jq 'length')
SKIPPED=$((TOTAL_FOUND - NEW_COUNT))

log "New: ${NEW_COUNT}, Skipped (already processed): ${SKIPPED}"

if [[ "${NEW_COUNT}" -eq 0 ]]; then
    # Update last_run timestamp
    UPDATED=$(jq --arg now "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        '.last_run = $now' "${PROCESSED_FILE}")
    echo "${UPDATED}" > "${PROCESSED_FILE}"
    log "All messages already processed"
    log "--- Run complete ---"
    exit 0
fi

# ── Helpers: YAML prompt extraction ──────────────────────────────────────────
# Extract system_prompt from an agent YAML file.
# Handles both block-scalar (|) and quoted multiline ("...\") formats.
extract_system_prompt() {
    local yaml_file="$1"
    python3 -c "
import re, sys
text = open(sys.argv[1]).read()
# Block scalar: system_prompt: |\n  indented lines...
m = re.search(r'^system_prompt: \|\n((?:  .*\n?)+)', text, re.MULTILINE)
if m:
    print(re.sub(r'^  ', '', m.group(1), flags=re.MULTILINE).rstrip())
    sys.exit(0)
# Quoted: system_prompt: \"...\" (possibly multiline with backslash continuations)
m = re.search(r\"^system_prompt: ['\\\"](.+?)(?:['\\\"])\s*$\", text, re.MULTILINE | re.DOTALL)
if m:
    s = m.group(1)
    s = re.sub(r'\\\\\n\s*\\\\ ', ' ', s)  # join continuation lines
    s = s.replace('\\\\n', '\n')
    print(s.strip())
    sys.exit(0)
# Single-line: system_prompt: bare text
m = re.search(r'^system_prompt: (.+)$', text, re.MULTILINE)
if m:
    print(m.group(1).strip().strip('\"').strip(\"'\"))
" "${yaml_file}" 2>/dev/null
}

# ── Helpers: invoke claude with retries ──────────────────────────────────────
invoke_claude() {
    local prompt="$1"
    local result=""
    local attempt=0
    local ok=false

    while [[ ${attempt} -le ${MAX_RETRIES} ]]; do
        attempt=$((attempt + 1))
        result=$(claude -p "${prompt}" --output-format json --mcp-config "${MCP_CONFIG}" 2>/dev/null) && {
            ok=true
            break
        }
        if [[ ${attempt} -le ${MAX_RETRIES} ]]; then
            log "    Claude invocation failed (attempt ${attempt}/$((MAX_RETRIES + 1))), retrying in 5s..."
            sleep 5
        fi
    done

    if [[ "${ok}" != "true" ]]; then
        return 1
    fi
    echo "${result}"
}

# ── Helpers: invoke claude with structured JSON output (for Pass 2) ────────
PASS2_SCHEMA='{"type":"object","properties":{"action_taken":{"type":"string"},"success":{"type":"boolean"},"error":{"type":["string","null"]}},"required":["action_taken","success"]}'

invoke_claude_structured() {
    local prompt="$1"
    local result=""
    local attempt=0
    local ok=false

    while [[ ${attempt} -le ${MAX_RETRIES} ]]; do
        attempt=$((attempt + 1))
        result=$(claude -p "${prompt}" --output-format json --json-schema "${PASS2_SCHEMA}" --mcp-config "${MCP_CONFIG}" --no-session-persistence --disable-slash-commands --model sonnet 2>/dev/null) && {
            ok=true
            break
        }
        if [[ ${attempt} -le ${MAX_RETRIES} ]]; then
            log "    Claude invocation failed (attempt ${attempt}/$((MAX_RETRIES + 1))), retrying in 5s..."
            sleep 5
        fi
    done

    if [[ "${ok}" != "true" ]]; then
        return 1
    fi
    echo "${result}"
}

# ── Helpers: extract JSON from Claude response ──────────────────────────────
# Extracts the FIRST valid JSON object from text. Handles:
#   1. Raw JSON on its own line
#   2. JSON with trailing prose
#   3. Markdown-fenced JSON (```json ... ```)
#   4. JSON embedded in prose text
#   5. Nested JSON (curly braces inside string values)
extract_json() {
    local response_text="$1"
    python3 -c '
import json, re, sys

text = sys.stdin.read()

# Strip markdown fences first and prepend that content so it is tried first
fenced = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
if fenced:
    text = fenced.group(1).strip() + "\n" + text

def find_first_json_object(s):
    """Walk the string character by character, tracking brace depth and
    respecting JSON string boundaries (including escaped quotes), to
    find the first balanced { ... } that parses as valid JSON."""
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "{":
            start = i
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                c = s[j]
                if escape:
                    escape = False
                elif c == "\\":
                    if in_string:
                        escape = True
                elif c == "\"":
                    in_string = not in_string
                elif not in_string:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = s[start:j+1]
                            try:
                                json.loads(candidate)
                                return candidate
                            except (json.JSONDecodeError, ValueError):
                                break
                j += 1
        i += 1
    return ""

result = find_first_json_object(text)
print(result)
' <<< "${response_text}"
}

# ── Load triage prompt once ──────────────────────────────────────────────────
TRIAGE_FILE="${PROJECT_DIR}/agent_configs/inbox_triage.yaml"
TRIAGE_PROMPT=""
if [[ -f "${TRIAGE_FILE}" ]]; then
    TRIAGE_PROMPT=$(extract_system_prompt "${TRIAGE_FILE}")
fi
if [[ -z "${TRIAGE_PROMPT}" ]]; then
    log "WARNING: Could not read inbox_triage.yaml"
    exit 1
fi

# ── Inline handler prompt for simple tool actions ────────────────────────────
INLINE_PROMPT="You are Jarvis, a personal assistant. Process this instruction using available MCP tools (store_fact, query_memory, search_documents, store_location, list_locations).

For REMEMBER/STORE: use store_fact(category, key, value). Categories: personal, preference, work, relationship.
For LOCATION: use store_location(name, address, notes).
For TODO: use store_fact(category=\"work\", key=\"todo_<slug>\", value=<text>).
For NOTE: use store_fact(category=\"work\", key=\"note_<slug>\", value=<text>).
For SEARCH: use query_memory(query) first, then search_documents(query) if needed.

Return ONLY a JSON object:
{\"action_taken\": \"<what you did>\", \"success\": true}

On error:
{\"action_taken\": \"<what you attempted>\", \"success\": false, \"error\": \"<description>\"}"

# ── Process each new message ──────────────────────────────────────────────────
PROCESSED_COUNT=0
ERROR_COUNT=0
NEW_GUIDS=()

for row in $(echo "${NEW_MESSAGES}" | jq -r '.[] | @base64'); do
    _jq() {
        echo "${row}" | base64 --decode | jq -r "${1}"
    }

    MSG_GUID=$(_jq '.guid')
    MSG_TEXT=$(_jq '.text')
    MSG_DATE=$(_jq '.date_local')

    # Extract the instruction after "jarvis:" (case-insensitive prefix strip)
    INSTRUCTION=$(echo "${MSG_TEXT}" | sed 's/^[Jj][Aa][Rr][Vv][Ii][Ss]:[[:space:]]*//')

    if [[ -z "${INSTRUCTION}" ]]; then
        log "  Skipping empty instruction from message ${MSG_GUID}"
        continue
    fi

    log "  Processing [${MSG_GUID}] (${MSG_DATE}): ${INSTRUCTION:0:100}"

    # ── Pass 1: Classify the message ─────────────────────────────────────────
    log "    Pass 1: Classifying..."

    CLASSIFY_SCHEMA='{"type":"object","properties":{"category":{"type":"string","enum":["REMEMBER","LOCATION","TODO","NOTE","COMMUNICATE","PLANNING","AGENDA","SECURITY","INCIDENTS","APPROVALS","ACTION_ITEMS","SEARCH","MISSING"]},"agent":{"type":["string","null"]},"instruction":{"type":"string"},"missing_agent_suggestion":{"type":["string","null"]}},"required":["category","agent","instruction"]}'

    CLASSIFY_RESULT=""
    CLASSIFY_ATTEMPT=0
    CLASSIFY_OK=false
    while [[ ${CLASSIFY_ATTEMPT} -le ${MAX_RETRIES} ]]; do
        CLASSIFY_ATTEMPT=$((CLASSIFY_ATTEMPT + 1))
        CLASSIFY_RESULT=$(claude -p "${TRIAGE_PROMPT}

Classify this message:
${INSTRUCTION}" --output-format json --json-schema "${CLASSIFY_SCHEMA}" --mcp-config "${MCP_CONFIG}" --append-system-prompt "You MUST respond with ONLY a JSON object matching the schema. No other text." --model sonnet --no-session-persistence --disable-slash-commands 2>/dev/null) && {
            CLASSIFY_OK=true
            break
        }
        if [[ ${CLASSIFY_ATTEMPT} -le ${MAX_RETRIES} ]]; then
            log "    Classification failed (attempt ${CLASSIFY_ATTEMPT}/$((MAX_RETRIES + 1))), retrying in 5s..."
            sleep 5
        fi
    done

    if [[ "${CLASSIFY_OK}" != "true" ]]; then
        log "  ERROR: Classification failed for [${MSG_GUID}] after $((MAX_RETRIES + 1)) attempts"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        NEW_GUIDS+=("${MSG_GUID}")
        continue
    fi

    # Parse classification response — with --json-schema, structured output is in .structured_output
    CLASSIFY_JSON=$(echo "${CLASSIFY_RESULT}" | jq -r '.structured_output // empty' 2>/dev/null)
    # Fallback to .result if structured_output is missing
    if [[ -z "${CLASSIFY_JSON}" ]] || [[ "${CLASSIFY_JSON}" == "null" ]]; then
        CLASSIFY_TEXT=$(echo "${CLASSIFY_RESULT}" | jq -r '.result // empty' 2>/dev/null)
        if [[ -z "${CLASSIFY_TEXT}" ]]; then
            CLASSIFY_TEXT="${CLASSIFY_RESULT}"
        fi
        CLASSIFY_JSON=$(extract_json "${CLASSIFY_TEXT}")
    fi
    if [[ -z "${CLASSIFY_JSON}" ]] || ! echo "${CLASSIFY_JSON}" | jq . &>/dev/null; then
        log "    WARNING: Could not parse classification JSON"
        log "    Raw (truncated): ${CLASSIFY_TEXT:0:300}"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        NEW_GUIDS+=("${MSG_GUID}")
        continue
    fi

    CATEGORY=$(echo "${CLASSIFY_JSON}" | jq -r '.category // "MISSING"')
    AGENT_NAME=$(echo "${CLASSIFY_JSON}" | jq -r '.agent // "null"')
    AGENT_INSTRUCTION=$(echo "${CLASSIFY_JSON}" | jq -r '.instruction // empty')
    MISSING_SUGGESTION=$(echo "${CLASSIFY_JSON}" | jq -r '.missing_agent_suggestion // "null"')

    log "    Classified: category=${CATEGORY}, agent=${AGENT_NAME}"

    # ── Handle MISSING: log the gap ──────────────────────────────────────────
    if [[ "${CATEGORY}" == "MISSING" && "${MISSING_SUGGESTION}" != "null" ]]; then
        log "    Missing agent suggestion: ${MISSING_SUGGESTION}"
        # Store the missing agent suggestion in memory via Claude
        invoke_claude "Store this fact using store_fact with category=\"work\", key=\"missing_agent_$(date +%s)\", value=\"${MISSING_SUGGESTION} (requested: ${INSTRUCTION:0:80})\". Return JSON: {\"action_taken\": \"stored missing agent suggestion\", \"success\": true}" >/dev/null 2>&1 || true
    fi

    # ── Pass 2: Dispatch to the right agent or handle inline ─────────────────
    if [[ "${AGENT_NAME}" != "null" && -n "${AGENT_NAME}" ]]; then
        # Route to a named agent
        AGENT_YAML="${PROJECT_DIR}/agent_configs/${AGENT_NAME}.yaml"
        if [[ -f "${AGENT_YAML}" ]]; then
            AGENT_PROMPT=$(extract_system_prompt "${AGENT_YAML}")
            if [[ -n "${AGENT_PROMPT}" ]]; then
                log "    Pass 2: Dispatching to agent '${AGENT_NAME}'..."
                EXEC_RESULT=$(invoke_claude_structured "${AGENT_PROMPT}

Process this request:
${AGENT_INSTRUCTION:-$INSTRUCTION}") || {
                    log "    ERROR: Agent '${AGENT_NAME}' failed for [${MSG_GUID}]"
                    ERROR_COUNT=$((ERROR_COUNT + 1))
                    NEW_GUIDS+=("${MSG_GUID}")
                    continue
                }
            else
                log "    WARNING: Could not extract prompt from ${AGENT_YAML}, falling back to inline"
                EXEC_RESULT=$(invoke_claude_structured "${INLINE_PROMPT}

${AGENT_INSTRUCTION:-$INSTRUCTION}") || {
                    log "    ERROR: Inline handler failed for [${MSG_GUID}]"
                    ERROR_COUNT=$((ERROR_COUNT + 1))
                    NEW_GUIDS+=("${MSG_GUID}")
                    continue
                }
            fi
        else
            log "    WARNING: Agent YAML not found: ${AGENT_YAML}, falling back to inline"
            EXEC_RESULT=$(invoke_claude_structured "${INLINE_PROMPT}

${AGENT_INSTRUCTION:-$INSTRUCTION}") || {
                log "    ERROR: Inline handler failed for [${MSG_GUID}]"
                ERROR_COUNT=$((ERROR_COUNT + 1))
                NEW_GUIDS+=("${MSG_GUID}")
                continue
            }
        fi
    else
        # Handle inline (REMEMBER, TODO, NOTE, SEARCH, MISSING)
        log "    Pass 2: Handling inline (${CATEGORY})..."
        EXEC_RESULT=$(invoke_claude_structured "${INLINE_PROMPT}

${AGENT_INSTRUCTION:-$INSTRUCTION}") || {
            log "    ERROR: Inline handler failed for [${MSG_GUID}]"
            ERROR_COUNT=$((ERROR_COUNT + 1))
            NEW_GUIDS+=("${MSG_GUID}")
            continue
        }
    fi

    # ── Parse execution result ───────────────────────────────────────────────
    EXEC_JSON=$(echo "${EXEC_RESULT}" | jq -r '.structured_output // empty' 2>/dev/null)
    if [[ -z "${EXEC_JSON}" ]] || [[ "${EXEC_JSON}" == "null" ]]; then
        EXEC_TEXT=$(echo "${EXEC_RESULT}" | jq -r '.result // empty' 2>/dev/null)
        if [[ -z "${EXEC_TEXT}" ]]; then
            EXEC_TEXT="${EXEC_RESULT}"
        fi
        EXEC_JSON=$(extract_json "${EXEC_TEXT}")
    fi
    if [[ -n "${EXEC_JSON}" ]] && echo "${EXEC_JSON}" | jq . &>/dev/null; then
        ACTION=$(echo "${EXEC_JSON}" | jq -r '.action_taken // "unknown"')
        SUCCESS=$(echo "${EXEC_JSON}" | jq -r '.success // false')
        ERROR_MSG=$(echo "${EXEC_JSON}" | jq -r '.error // empty')

        log "    Result: category=${CATEGORY}, agent=${AGENT_NAME}, action=\"${ACTION}\", success=${SUCCESS}"
        if [[ -n "${ERROR_MSG}" ]]; then
            log "    Error: ${ERROR_MSG}"
            ERROR_COUNT=$((ERROR_COUNT + 1))
        fi
    else
        log "    WARNING: Could not parse execution JSON from agent '${AGENT_NAME:-inline}'"
        log "    Raw (truncated): ${EXEC_TEXT:0:300}"
    fi

    # ── Pass 3: Deliver output and notify ─────────────────────────────────
    # Skip if the agent was already "communications" (it handled delivery itself)
    # or if Pass 2 failed
    if [[ "${CATEGORY}" != "COMMUNICATE" && "${SUCCESS}" == "true" ]]; then
        DELIVERY_BODY="${ACTION}"

        # For richer output, try to extract the full result text
        FULL_RESULT=$(echo "${EXEC_RESULT}" | jq -r '.result // empty' 2>/dev/null)
        if [[ -n "${FULL_RESULT}" && "${FULL_RESULT}" != "null" ]]; then
            DELIVERY_BODY="${FULL_RESULT}"
        fi

        # 3a. Deliver via email or iMessage if instruction implies it
        DELIVERY_MODE=""
        if echo "${INSTRUCTION}" | grep -iqE '\b(email|draft|draft email|send email)\b'; then
            DELIVERY_MODE="email"
        elif echo "${INSTRUCTION}" | grep -iqE '\b(text|imessage|send text|send message)\b'; then
            DELIVERY_MODE="imessage"
        fi

        if [[ -n "${DELIVERY_MODE}" ]]; then
            log "    Pass 3a: Delivering via ${DELIVERY_MODE}..."
            if [[ "${DELIVERY_MODE}" == "email" ]]; then
                DELIVERY_SUBJECT="Jarvis: ${CATEGORY} — ${AGENT_NAME:-inline}"
                DELIVERY_OUTPUT=$("${SCRIPT_DIR}/communicate.sh" email-draft --to "jasricha@microsoft.com" --subject "${DELIVERY_SUBJECT}" --body "${DELIVERY_BODY}" 2>/dev/null) || true
            else
                DELIVERY_OUTPUT=$("${SCRIPT_DIR}/communicate.sh" imessage --to "self" --body "${DELIVERY_BODY}" 2>/dev/null) || true
            fi

            if [[ -n "${DELIVERY_OUTPUT}" ]]; then
                DELIVERY_STATUS=$(echo "${DELIVERY_OUTPUT}" | jq -r '.status // "unknown"' 2>/dev/null)
                log "    Pass 3a result: ${DELIVERY_MODE} status=${DELIVERY_STATUS}"
            fi
        fi

        # 3b. Always send a Reminder notification (syncs to iPhone via iCloud)
        log "    Pass 3b: Sending Reminder notification..."
        REMINDER_TITLE="Jarvis: ${CATEGORY} — ${AGENT_NAME:-inline}"
        # Truncate body for reminder if extremely long (keep first 4000 chars)
        REMINDER_BODY="${DELIVERY_BODY:0:4000}"
        REMINDER_OUTPUT=$("${SCRIPT_DIR}/communicate.sh" reminder --subject "${REMINDER_TITLE}" --body "${REMINDER_BODY}" 2>/dev/null) || true
        if [[ -n "${REMINDER_OUTPUT}" ]]; then
            REMINDER_STATUS=$(echo "${REMINDER_OUTPUT}" | jq -r '.status // "unknown"' 2>/dev/null)
            log "    Pass 3b result: reminder status=${REMINDER_STATUS}"
        fi
    fi

    PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
    NEW_GUIDS+=("${MSG_GUID}")
done

# ── Update processed GUIDs ────────────────────────────────────────────────────
if [[ ${#NEW_GUIDS[@]} -gt 0 ]]; then
    # Build JSON array of new GUIDs
    GUID_JSON=$(printf '%s\n' "${NEW_GUIDS[@]}" | jq -R . | jq -s .)

    UPDATED=$(jq --arg now "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --argjson new_ids "${GUID_JSON}" \
        '{
            processed_ids: ((.processed_ids // []) + $new_ids | unique),
            last_run: $now
        }' "${PROCESSED_FILE}")

    echo "${UPDATED}" > "${PROCESSED_FILE}"
else
    UPDATED=$(jq --arg now "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        '.last_run = $now' "${PROCESSED_FILE}")
    echo "${UPDATED}" > "${PROCESSED_FILE}"
fi

# ── Prune old processed GUIDs (keep last 500) ────────────────────────────────
ID_COUNT=$(jq '.processed_ids | length' "${PROCESSED_FILE}")
if [[ "${ID_COUNT}" -gt 500 ]]; then
    PRUNED=$(jq '.processed_ids = (.processed_ids | .[-500:])' "${PROCESSED_FILE}")
    echo "${PRUNED}" > "${PROCESSED_FILE}"
    log "Pruned processed GUIDs from ${ID_COUNT} to 500"
fi

log "Check complete: found=${TOTAL_FOUND}, processed=${PROCESSED_COUNT}, skipped=${SKIPPED}, errors=${ERROR_COUNT}"
log "--- Run complete ---"

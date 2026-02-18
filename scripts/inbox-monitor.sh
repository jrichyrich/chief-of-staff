#!/usr/bin/env bash
#
# inbox-monitor.sh — Polls iMessage for "jarvis:" commands and processes them.
#
# Usage:
#   ./scripts/inbox-monitor.sh              # Run once (default 20-minute lookback)
#   ./scripts/inbox-monitor.sh --interval 30 # Custom lookback window in minutes
#   ./scripts/inbox-monitor.sh --mcp-config /path/to/config.json # Optional MCP override
#   ./scripts/inbox-monitor.sh --email-to you@example.com # Optional email draft target
#   ./scripts/inbox-monitor.sh --print-connector-status # Show detected connector status and exit
#
# Cron example (every 15 minutes):
#   */15 * * * * $JARVIS_PROJECT_DIR/scripts/inbox-monitor.sh >> $JARVIS_PROJECT_DIR/data/inbox-cron.log 2>&1
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
PROJECT_DIR="${JARVIS_PROJECT_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
MCP_CONFIG="${INBOX_MONITOR_MCP_CONFIG:-}"
DATA_DIR="${JARVIS_DATA_DIR:-${PROJECT_DIR}/data}"
PROCESSED_FILE="${INBOX_MONITOR_PROCESSED_FILE:-${DATA_DIR}/inbox-processed.json}"
LOG_FILE="${INBOX_MONITOR_LOG_FILE:-${DATA_DIR}/inbox-log.md}"
DEFAULT_EMAIL_TO="${JARVIS_DEFAULT_EMAIL_TO:-}"
LOOKBACK_MINUTES=20
MAX_RETRIES=2
CLAUDE_MCP_ARGS=()
PRINT_CONNECTOR_STATUS=false
MCP_LIST_OUTPUT=""
HAS_M365_CONNECTOR=false
HAS_LOCAL_JARVIS_CONNECTOR=false
ROUTING_AUDIT_FILE="${INBOX_MONITOR_ROUTING_AUDIT_FILE:-${DATA_DIR}/inbox-routing-audit.jsonl}"
PENDING_APPROVALS_FILE="${INBOX_MONITOR_PENDING_APPROVALS_FILE:-${DATA_DIR}/inbox-pending-approvals.json}"
APPROVAL_AUDIT_FILE="${INBOX_MONITOR_APPROVAL_AUDIT_FILE:-${DATA_DIR}/inbox-approvals-audit.jsonl}"
APPROVAL_TTL_MINUTES="${INBOX_MONITOR_APPROVAL_TTL_MINUTES:-60}"
ROUTE_POLICY_VERSION="2026-02-16"
ROUTE_PROFILE="LOCAL_DEFAULT"
ROUTE_PREFERRED_PROVIDER="none"
ROUTE_FALLBACK_PROVIDER="none"
ROUTE_REASON="uninitialized"
ROUTING_VALIDATION_ERROR=""
APPROVAL_REASON=""
CONNECTOR_POLICY_PROMPT=""
ALLOWED_SENDERS_FILE="${INBOX_MONITOR_ALLOWED_SENDERS:-${DATA_DIR}/inbox-allowed-senders.txt}"
ALLOWED_SENDERS_ENV="${JARVIS_ALLOWED_SENDERS:-}"

# ── Parse arguments ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval)
            LOOKBACK_MINUTES="$2"
            shift 2
            ;;
        --mcp-config)
            MCP_CONFIG="$2"
            shift 2
            ;;
        --project-mcp-config)
            MCP_CONFIG="${PROJECT_DIR}/.mcp.json"
            shift
            ;;
        --email-to)
            DEFAULT_EMAIL_TO="$2"
            shift 2
            ;;
        --print-connector-status)
            PRINT_CONNECTOR_STATUS=true
            shift
            ;;
        --approval-ttl-minutes)
            APPROVAL_TTL_MINUTES="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: inbox-monitor.sh [--interval MINUTES] [--mcp-config PATH] [--project-mcp-config] [--email-to ADDRESS] [--print-connector-status] [--approval-ttl-minutes MINUTES]"
            echo "  --interval  Lookback window in minutes (default: 20)"
            echo "  --mcp-config  Optional MCP config file for claude CLI"
            echo "  --project-mcp-config  Use ${PROJECT_DIR}/.mcp.json"
            echo "  --email-to  Email address used for generated draft delivery"
            echo "  --print-connector-status  Print detected MCP connector availability and exit"
            echo "  --approval-ttl-minutes  Hard-approval TTL in minutes (default: 60)"
            echo ""
            echo "Default behavior: no --mcp-config is passed, so Claude uses host-level connected connectors."
            echo "Default email draft target: JARVIS_DEFAULT_EMAIL_TO env var (unset means skip email draft delivery)."
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

bool_to_status() {
    if [[ "$1" == "true" ]]; then
        echo "connected"
    else
        echo "not connected"
    fi
}

detect_connector_state() {
    if [[ ${#CLAUDE_MCP_ARGS[@]} -gt 0 ]]; then
        MCP_LIST_OUTPUT="$(claude mcp list "${CLAUDE_MCP_ARGS[@]}" 2>/dev/null || true)"
    else
        MCP_LIST_OUTPUT="$(claude mcp list 2>/dev/null || true)"
    fi
    if [[ -z "${MCP_LIST_OUTPUT}" ]]; then
        log_to_stderr "WARNING: Could not read MCP connector list (claude mcp list)."
        HAS_M365_CONNECTOR=false
        HAS_LOCAL_JARVIS_CONNECTOR=false
        return
    fi

    if echo "${MCP_LIST_OUTPUT}" | grep -Eiq "microsoft[[:space:]]*365:.*connected"; then
        HAS_M365_CONNECTOR=true
    else
        HAS_M365_CONNECTOR=false
    fi

    if echo "${MCP_LIST_OUTPUT}" | grep -Eiq "(chief-of-staff|jarvis):.*connected"; then
        HAS_LOCAL_JARVIS_CONNECTOR=true
    else
        HAS_LOCAL_JARVIS_CONNECTOR=false
    fi
}

sanitize_instruction() {
    local raw="$1"
    local max_length="${2:-2000}"
    # Strip control characters except space/tab/newline
    local cleaned
    cleaned=$(printf '%s' "$raw" | tr -d '\000-\010\013\014\016-\037\177')
    # Truncate
    if [[ ${#cleaned} -gt $max_length ]]; then
        cleaned="${cleaned:0:$max_length}..."
    fi
    printf '%s' "$cleaned"
}

is_sender_allowed() {
    local sender="$1"
    # If no allowlist configured, deny all (fail-closed)
    local has_allowlist=false

    # Check environment variable
    if [[ -n "${ALLOWED_SENDERS_ENV}" ]]; then
        has_allowlist=true
        IFS=',' read -ra senders <<< "${ALLOWED_SENDERS_ENV}"
        for allowed in "${senders[@]}"; do
            allowed="$(echo "${allowed}" | tr -d '[:space:]')"
            if [[ "${sender}" == "${allowed}" ]]; then
                return 0
            fi
        done
    fi

    # Check file
    if [[ -f "${ALLOWED_SENDERS_FILE}" ]]; then
        has_allowlist=true
        while IFS= read -r allowed || [[ -n "$allowed" ]]; do
            allowed="$(echo "${allowed}" | tr -d '[:space:]')"
            [[ -z "${allowed}" || "${allowed}" == \#* ]] && continue
            if [[ "${sender}" == "${allowed}" ]]; then
                return 0
            fi
        done < "${ALLOWED_SENDERS_FILE}"
    fi

    # If no allowlist is configured at all, log a warning but allow (backwards compat)
    if [[ "${has_allowlist}" == "false" ]]; then
        log_to_stderr "WARNING: No sender allowlist configured. Set JARVIS_ALLOWED_SENDERS or create ${ALLOWED_SENDERS_FILE}"
        return 0
    fi

    return 1
}

contains_any_keyword() {
    local haystack="$1"
    shift
    local keyword=""
    for keyword in "$@"; do
        if [[ "${haystack}" == *"${keyword}"* ]]; then
            return 0
        fi
    done
    return 1
}

decide_connector_route() {
    local instruction="$1"
    local category="$2"
    local instruction_lc=""
    local wants_m365=false
    local wants_local=false
    local wants_combined=false
    local prefers_summary=false

    instruction_lc="$(echo "${instruction}" | tr '[:upper:]' '[:lower:]')"

    if contains_any_keyword "${instruction_lc}" \
        "microsoft 365" "office 365" "teams" "outlook" "exchange" "sharepoint" "onedrive"; then
        wants_m365=true
    fi

    if contains_any_keyword "${instruction_lc}" \
        "apple mail" "mail.app" "apple calendar" "ical" "local mail" "local calendar"; then
        wants_local=true
    fi

    if contains_any_keyword "${instruction_lc}" \
        "across both" "combined" "all sources" "full picture" "overall status" "cross-platform"; then
        wants_combined=true
    fi

    if [[ "${category}" == "COMMUNICATE" || "${category}" == "PLANNING" ]]; then
        if contains_any_keyword "${instruction_lc}" "status" "summary" "brief" "digest"; then
            prefers_summary=true
        fi
    fi

    if [[ "${wants_combined}" == "true" && "${HAS_M365_CONNECTOR}" == "true" && "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" ]]; then
        ROUTE_PROFILE="COMBINED"
        ROUTE_PREFERRED_PROVIDER="both"
        ROUTE_FALLBACK_PROVIDER="none"
        ROUTE_REASON="explicit_combined_request"
        return
    fi

    if [[ "${wants_m365}" == "true" ]]; then
        ROUTE_PROFILE="M365_FIRST"
        ROUTE_REASON="m365_domain_request"
        if [[ "${HAS_M365_CONNECTOR}" == "true" ]]; then
            ROUTE_PREFERRED_PROVIDER="microsoft_365"
            if [[ "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" ]]; then
                ROUTE_FALLBACK_PROVIDER="local_jarvis"
            else
                ROUTE_FALLBACK_PROVIDER="none"
            fi
        elif [[ "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" ]]; then
            ROUTE_PREFERRED_PROVIDER="local_jarvis"
            ROUTE_FALLBACK_PROVIDER="none"
            ROUTE_REASON="m365_unavailable_using_local"
        else
            ROUTE_PREFERRED_PROVIDER="none"
            ROUTE_FALLBACK_PROVIDER="none"
            ROUTE_REASON="no_connector_available"
        fi
        return
    fi

    if [[ "${wants_local}" == "true" ]]; then
        ROUTE_PROFILE="LOCAL_FIRST"
        ROUTE_REASON="local_domain_request"
        if [[ "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" ]]; then
            ROUTE_PREFERRED_PROVIDER="local_jarvis"
            if [[ "${HAS_M365_CONNECTOR}" == "true" ]]; then
                ROUTE_FALLBACK_PROVIDER="microsoft_365"
            else
                ROUTE_FALLBACK_PROVIDER="none"
            fi
        elif [[ "${HAS_M365_CONNECTOR}" == "true" ]]; then
            ROUTE_PREFERRED_PROVIDER="microsoft_365"
            ROUTE_FALLBACK_PROVIDER="none"
            ROUTE_REASON="local_unavailable_using_m365"
        else
            ROUTE_PREFERRED_PROVIDER="none"
            ROUTE_FALLBACK_PROVIDER="none"
            ROUTE_REASON="no_connector_available"
        fi
        return
    fi

    if [[ "${prefers_summary}" == "true" && "${HAS_M365_CONNECTOR}" == "true" && "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" ]]; then
        ROUTE_PROFILE="COMBINED"
        ROUTE_PREFERRED_PROVIDER="both"
        ROUTE_FALLBACK_PROVIDER="none"
        ROUTE_REASON="broad_summary_request"
        return
    fi

    ROUTE_PROFILE="LOCAL_DEFAULT"
    ROUTE_REASON="default_route"
    if [[ "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" ]]; then
        ROUTE_PREFERRED_PROVIDER="local_jarvis"
        if [[ "${HAS_M365_CONNECTOR}" == "true" ]]; then
            ROUTE_FALLBACK_PROVIDER="microsoft_365"
        else
            ROUTE_FALLBACK_PROVIDER="none"
        fi
    elif [[ "${HAS_M365_CONNECTOR}" == "true" ]]; then
        ROUTE_PREFERRED_PROVIDER="microsoft_365"
        ROUTE_FALLBACK_PROVIDER="none"
        ROUTE_REASON="local_unavailable_using_m365"
    else
        ROUTE_PREFERRED_PROVIDER="none"
        ROUTE_FALLBACK_PROVIDER="none"
        ROUTE_REASON="no_connector_available"
    fi
}

build_connector_policy_prompt() {
    local m365_status=""
    local local_status=""
    m365_status="$(bool_to_status "${HAS_M365_CONNECTOR}")"
    local_status="$(bool_to_status "${HAS_LOCAL_JARVIS_CONNECTOR}")"

    CONNECTOR_POLICY_PROMPT="Connector status for this run:
- Microsoft 365 MCP (Teams/Outlook): ${m365_status}
- Local Jarvis MCP (Apple Mail/Calendar): ${local_status}

Global routing policy v${ROUTE_POLICY_VERSION} (MUST follow):
1) Teams, Outlook email, and Outlook/Exchange calendar tasks use Microsoft 365 first when connected.
2) If Microsoft 365 is unavailable or fails, fall back to local Jarvis (Apple Mail/Calendar) when available.
3) If a request explicitly asks for combined or broad status and both connectors are connected, use both and deduplicate.
4) Never claim results from a connector that is not connected."
}

build_message_connector_policy_prompt() {
    local instruction="$1"
    local category="$2"
    local m365_status=""
    local local_status=""

    decide_connector_route "${instruction}" "${category}"
    m365_status="$(bool_to_status "${HAS_M365_CONNECTOR}")"
    local_status="$(bool_to_status "${HAS_LOCAL_JARVIS_CONNECTOR}")"

    CONNECTOR_POLICY_PROMPT="Connector status for this run:
- Microsoft 365 MCP (Teams/Outlook): ${m365_status}
- Local Jarvis MCP (Apple Mail/Calendar): ${local_status}

Request-specific route decision (policy v${ROUTE_POLICY_VERSION}):
- category: ${category}
- profile: ${ROUTE_PROFILE}
- preferred_provider: ${ROUTE_PREFERRED_PROVIDER}
- fallback_provider: ${ROUTE_FALLBACK_PROVIDER}
- reason: ${ROUTE_REASON}

Execution contract (MUST follow):
1) Use preferred_provider first.
2) If preferred_provider fails and fallback_provider is not none, set fallback_used=true and use fallback_provider.
3) Return provider_used as one of: microsoft_365, local_jarvis, both, none.
4) Return fallback_used as true or false.
5) In action_taken, mention provider_used and whether fallback happened.
6) Never claim data from an unavailable connector."
}

validate_execution_provider() {
    local provider_used="$1"
    local fallback_used="$2"
    ROUTING_VALIDATION_ERROR=""

    case "${provider_used}" in
        microsoft_365|local_jarvis|both|none)
            ;;
        *)
            ROUTING_VALIDATION_ERROR="invalid provider_used value: ${provider_used}"
            return 1
            ;;
    esac

    if [[ "${provider_used}" == "microsoft_365" || "${provider_used}" == "both" ]]; then
        if [[ "${HAS_M365_CONNECTOR}" != "true" ]]; then
            ROUTING_VALIDATION_ERROR="provider_used included microsoft_365, but Microsoft 365 connector is not connected"
            return 1
        fi
    fi

    if [[ "${provider_used}" == "local_jarvis" || "${provider_used}" == "both" ]]; then
        if [[ "${HAS_LOCAL_JARVIS_CONNECTOR}" != "true" ]]; then
            ROUTING_VALIDATION_ERROR="provider_used included local_jarvis, but local Jarvis connector is not connected"
            return 1
        fi
    fi

    if [[ "${ROUTE_PROFILE}" == "M365_FIRST" && "${HAS_M365_CONNECTOR}" == "true" && "${provider_used}" == "local_jarvis" && "${fallback_used}" != "true" ]]; then
        ROUTING_VALIDATION_ERROR="m365-first route required fallback_used=true before local_jarvis provider is allowed"
        return 1
    fi

    if [[ "${ROUTE_PROFILE}" == "COMBINED" && "${HAS_M365_CONNECTOR}" == "true" && "${HAS_LOCAL_JARVIS_CONNECTOR}" == "true" && "${provider_used}" != "both" && "${fallback_used}" != "true" ]]; then
        ROUTING_VALIDATION_ERROR="combined route required provider_used=both (or fallback_used=true if one side failed)"
        return 1
    fi

    if [[ "${ROUTE_PREFERRED_PROVIDER}" == "none" && "${provider_used}" != "none" ]]; then
        ROUTING_VALIDATION_ERROR="no connectors available; provider_used must be none"
        return 1
    fi

    return 0
}

append_routing_audit() {
    local guid="$1"
    local category="$2"
    local instruction="$3"
    local success="$4"
    local provider_used="$5"
    local fallback_used="$6"
    local error_msg="$7"

    jq -nc \
        --arg ts "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --arg guid "${guid}" \
        --arg category "${category}" \
        --arg instruction "${instruction:0:200}" \
        --arg policy_version "${ROUTE_POLICY_VERSION}" \
        --arg profile "${ROUTE_PROFILE}" \
        --arg preferred "${ROUTE_PREFERRED_PROVIDER}" \
        --arg fallback "${ROUTE_FALLBACK_PROVIDER}" \
        --arg route_reason "${ROUTE_REASON}" \
        --arg provider_used "${provider_used}" \
        --arg error "${error_msg}" \
        --argjson success "${success}" \
        --argjson fallback_used "${fallback_used}" \
        --argjson m365_connected "${HAS_M365_CONNECTOR}" \
        --argjson local_connected "${HAS_LOCAL_JARVIS_CONNECTOR}" \
        '{
            timestamp_utc: $ts,
            guid: $guid,
            category: $category,
            instruction_excerpt: $instruction,
            policy_version: $policy_version,
            route_profile: $profile,
            preferred_provider: $preferred,
            fallback_provider: $fallback,
            route_reason: $route_reason,
            connector_state: {
                microsoft_365_connected: $m365_connected,
                local_jarvis_connected: $local_connected
            },
            execution: {
                success: $success,
                provider_used: $provider_used,
                fallback_used: $fallback_used,
                error: (if $error == "" then null else $error end)
            }
        }' >> "${ROUTING_AUDIT_FILE}" || true
}

iso_utc_from_epoch() {
    local epoch="$1"
    date -u -r "${epoch}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || python3 -c 'import datetime,sys; print(datetime.datetime.utcfromtimestamp(int(sys.argv[1])).strftime("%Y-%m-%dT%H:%M:%SZ"))' "${epoch}"
}

append_approval_audit() {
    local action="$1"
    local request_id="$2"
    local status="$3"
    local reason="$4"
    local guid="$5"
    local instruction="$6"
    local category="$7"
    local agent="$8"

    jq -nc \
        --arg ts "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --arg action "${action}" \
        --arg request_id "${request_id}" \
        --arg status "${status}" \
        --arg reason "${reason}" \
        --arg guid "${guid}" \
        --arg instruction "${instruction:0:200}" \
        --arg category "${category}" \
        --arg agent "${agent}" \
        '{
            timestamp_utc: $ts,
            action: $action,
            request_id: $request_id,
            status: $status,
            reason: (if $reason == "" then null else $reason end),
            guid: $guid,
            instruction_excerpt: $instruction,
            category: $category,
            agent: (if $agent == "" || $agent == "null" then null else $agent end)
        }' >> "${APPROVAL_AUDIT_FILE}" || true
}

remove_pending_approval() {
    local request_id="$1"
    local updated=""
    updated=$(jq --arg id "${request_id}" '.pending = [(.pending // [])[] | select(.id != $id)]' "${PENDING_APPROVALS_FILE}" 2>/dev/null || true)
    if [[ -n "${updated}" ]]; then
        echo "${updated}" > "${PENDING_APPROVALS_FILE}"
    fi
}

load_pending_approval() {
    local request_id="$1"
    jq -c --arg id "${request_id}" '(.pending // [])[] | select(.id == $id)' "${PENDING_APPROVALS_FILE}" 2>/dev/null | head -n1 || true
}

prune_expired_approvals() {
    local now_epoch=""
    local expired=""
    local entry=""
    now_epoch="$(date -u +%s)"

    expired=$(jq -c --argjson now "${now_epoch}" '(.pending // [])[] | select((.expires_at_epoch // 0) <= $now)' "${PENDING_APPROVALS_FILE}" 2>/dev/null || true)
    if [[ -n "${expired}" ]]; then
        while IFS= read -r entry; do
            [[ -z "${entry}" ]] && continue
            append_approval_audit \
                "expired" \
                "$(echo "${entry}" | jq -r '.id // "unknown"')" \
                "expired" \
                "ttl_elapsed" \
                "$(echo "${entry}" | jq -r '.origin_guid // "unknown"')" \
                "$(echo "${entry}" | jq -r '.instruction // ""')" \
                "$(echo "${entry}" | jq -r '.category // "unknown"')" \
                "$(echo "${entry}" | jq -r '.agent // "null"')"
        done <<< "${expired}"

        jq --argjson now "${now_epoch}" '.pending = [(.pending // [])[] | select((.expires_at_epoch // 0) > $now)]' "${PENDING_APPROVALS_FILE}" > "${PENDING_APPROVALS_FILE}.tmp" \
            && mv "${PENDING_APPROVALS_FILE}.tmp" "${PENDING_APPROVALS_FILE}"
    fi
}

requires_hard_approval() {
    local instruction="$1"
    local category="$2"
    local instruction_lc=""
    APPROVAL_REASON=""
    instruction_lc="$(echo "${instruction}" | tr '[:upper:]' '[:lower:]')"

    if [[ "${category}" == "COMMUNICATE" ]]; then
        APPROVAL_REASON="communications_send_or_draft"
        return 0
    fi

    if contains_any_keyword "${instruction_lc}" \
        "send email" "email " "send text" "imessage" "send message" "message " "notify "; then
        APPROVAL_REASON="outbound_communication"
        return 0
    fi

    if contains_any_keyword "${instruction_lc}" \
        "calendar" "meeting" "event" "schedule" "reschedule" "cancel meeting" "update event" "delete event"; then
        if contains_any_keyword "${instruction_lc}" \
            "create " "add " "update " "edit " "delete " "remove " "cancel " "move " "reschedule "; then
            APPROVAL_REASON="calendar_write"
            return 0
        fi
    fi

    if contains_any_keyword "${instruction_lc}" \
        "delete fact" "remove fact" "update fact" "delete note" "remove note" "update note" \
        "delete todo" "remove todo" "update todo" "forget this" "erase memory"; then
        APPROVAL_REASON="memory_destructive_change"
        return 0
    fi

    if contains_any_keyword "${instruction_lc}" "delegate " "assign " "handoff " "hand off "; then
        APPROVAL_REASON="delegation_or_assignment"
        return 0
    fi

    return 1
}

create_pending_approval() {
    local guid="$1"
    local instruction="$2"
    local category="$3"
    local agent="$4"
    local agent_instruction="$5"
    local request_id=""
    local id_suffix=""
    local now_epoch=""
    local expires_epoch=""
    local created_at=""
    local expires_at=""
    local updated=""

    id_suffix="$(printf '%s' "${guid}" | shasum | awk '{print substr($1,1,8)}')"
    request_id="apr-$(date -u '+%Y%m%d%H%M%S')-${id_suffix}"
    now_epoch="$(date -u +%s)"
    expires_epoch=$((now_epoch + (APPROVAL_TTL_MINUTES * 60)))
    created_at="$(iso_utc_from_epoch "${now_epoch}")"
    expires_at="$(iso_utc_from_epoch "${expires_epoch}")"

    updated=$(jq \
        --arg id "${request_id}" \
        --arg guid "${guid}" \
        --arg instruction "${instruction}" \
        --arg category "${category}" \
        --arg agent "${agent}" \
        --arg agent_instruction "${agent_instruction}" \
        --arg approval_reason "${APPROVAL_REASON}" \
        --arg route_profile "${ROUTE_PROFILE}" \
        --arg preferred_provider "${ROUTE_PREFERRED_PROVIDER}" \
        --arg fallback_provider "${ROUTE_FALLBACK_PROVIDER}" \
        --arg route_reason "${ROUTE_REASON}" \
        --arg created_at "${created_at}" \
        --arg expires_at "${expires_at}" \
        --argjson created_at_epoch "${now_epoch}" \
        --argjson expires_at_epoch "${expires_epoch}" \
        '.pending = (.pending // []) + [{
            id: $id,
            status: "pending",
            origin_guid: $guid,
            instruction: $instruction,
            category: $category,
            agent: (if $agent == "" || $agent == "null" then null else $agent end),
            agent_instruction: (if $agent_instruction == "" then null else $agent_instruction end),
            approval_reason: $approval_reason,
            route_profile: $route_profile,
            preferred_provider: $preferred_provider,
            fallback_provider: $fallback_provider,
            route_reason: $route_reason,
            created_at: $created_at,
            created_at_epoch: $created_at_epoch,
            expires_at: $expires_at,
            expires_at_epoch: $expires_at_epoch
        }]' "${PENDING_APPROVALS_FILE}" 2>/dev/null || true)
    if [[ -n "${updated}" ]]; then
        echo "${updated}" > "${PENDING_APPROVALS_FILE}"
        echo "${request_id}"
        return 0
    fi
    return 1
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

if [[ -n "${MCP_CONFIG}" ]]; then
    if [[ ! -f "${MCP_CONFIG}" ]]; then
        log_to_stderr "ERROR: MCP config file not found: ${MCP_CONFIG}"
        exit 1
    fi
    CLAUDE_MCP_ARGS=(--mcp-config "${MCP_CONFIG}")
    log_to_stderr "Using explicit MCP config: ${MCP_CONFIG}"
else
    log_to_stderr "Using Claude host-level MCP connectors (no explicit --mcp-config override)"
fi

detect_connector_state
build_connector_policy_prompt
log_to_stderr "Connector status: Microsoft 365=${HAS_M365_CONNECTOR}, local_jarvis=${HAS_LOCAL_JARVIS_CONNECTOR}"

if [[ "${PRINT_CONNECTOR_STATUS}" == "true" ]]; then
    cat <<EOF
{
  "route_policy_version": "${ROUTE_POLICY_VERSION}",
  "microsoft_365_connected": ${HAS_M365_CONNECTOR},
  "local_jarvis_connected": ${HAS_LOCAL_JARVIS_CONNECTOR}
}
EOF
    exit 0
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

# Initialize routing audit file if missing
if [[ ! -f "${ROUTING_AUDIT_FILE}" ]]; then
    touch "${ROUTING_AUDIT_FILE}"
fi

# Initialize approval state/audit files if missing
if [[ ! -f "${PENDING_APPROVALS_FILE}" ]]; then
    echo '{"pending": []}' > "${PENDING_APPROVALS_FILE}"
fi
if [[ ! -f "${APPROVAL_AUDIT_FILE}" ]]; then
    touch "${APPROVAL_AUDIT_FILE}"
fi

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

prune_expired_approvals

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
        result=$(claude -p "${prompt}" --output-format json "${CLAUDE_MCP_ARGS[@]}" 2>/dev/null) && {
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
PASS2_SCHEMA='{"type":"object","properties":{"action_taken":{"type":"string"},"success":{"type":"boolean"},"provider_used":{"type":"string","enum":["microsoft_365","local_jarvis","both","none"]},"fallback_used":{"type":"boolean"},"error":{"type":["string","null"]}},"required":["action_taken","success","provider_used","fallback_used"]}'

invoke_claude_structured() {
    local prompt="$1"
    local result=""
    local attempt=0
    local ok=false

    while [[ ${attempt} -le ${MAX_RETRIES} ]]; do
        attempt=$((attempt + 1))
        result=$(claude -p "${prompt}" --output-format json --json-schema "${PASS2_SCHEMA}" "${CLAUDE_MCP_ARGS[@]}" --no-session-persistence --disable-slash-commands --model sonnet 2>/dev/null) && {
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

You MUST follow the connector routing policy provided in context.

For REMEMBER/STORE: use store_fact(category, key, value). Categories: personal, preference, work, relationship.
For LOCATION: use store_location(name, address, notes).
For TODO: use store_fact(category=\"work\", key=\"todo_<slug>\", value=<text>).
For NOTE: use store_fact(category=\"work\", key=\"note_<slug>\", value=<text>).
For SEARCH: use query_memory(query) first, then search_documents(query) if needed.

Return ONLY a JSON object:
{\"action_taken\": \"<what you did>\", \"success\": true, \"provider_used\": \"local_jarvis\", \"fallback_used\": false}

On error:
{\"action_taken\": \"<what you attempted>\", \"success\": false, \"provider_used\": \"none\", \"fallback_used\": false, \"error\": \"<description>\"}"

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
    MSG_SENDER=$(_jq '.sender // ""')

    # ── Sender allowlist check ────────────────────────────────────────────
    if [[ -n "${MSG_SENDER}" ]] && ! is_sender_allowed "${MSG_SENDER}"; then
        log "  BLOCKED: Unauthorized sender '${MSG_SENDER}' for message ${MSG_GUID}"
        NEW_GUIDS+=("${MSG_GUID}")
        continue
    fi

    # Extract the instruction after "jarvis:" (case-insensitive prefix strip)
    INSTRUCTION=$(echo "${MSG_TEXT}" | sed 's/^[Jj][Aa][Rr][Vv][Ii][Ss]:[[:space:]]*//')
    INSTRUCTION=$(sanitize_instruction "${INSTRUCTION}")

    if [[ -z "${INSTRUCTION}" ]]; then
        log "  Skipping empty instruction from message ${MSG_GUID}"
        continue
    fi

    log "  Processing [${MSG_GUID}] (${MSG_DATE}): ${INSTRUCTION:0:100}"

    FORCE_PASS3_DELIVERY=false
    SKIP_PASS2_EXECUTION=false
    IS_APPROVED_REPLAY=false
    APPROVAL_REQUEST_ID=""
    ACTION="unknown"
    SUCCESS=false
    ERROR_MSG=""
    PROVIDER_USED="none"
    FALLBACK_USED=false
    EXEC_RESULT=""
    CATEGORY="MISSING"
    AGENT_NAME="null"
    AGENT_INSTRUCTION=""
    REQUEST_INSTRUCTION="${INSTRUCTION}"
    MISSING_SUGGESTION="null"

    # ── Approval command handling (approve/reject) ───────────────────────────
    FIRST_TOKEN="$(echo "${INSTRUCTION}" | awk '{print tolower($1)}')"
    SECOND_TOKEN="$(echo "${INSTRUCTION}" | awk '{print $2}')"
    if [[ ("${FIRST_TOKEN}" == "approve" || "${FIRST_TOKEN}" == "reject") && -n "${SECOND_TOKEN}" ]]; then
        PENDING_REQUEST="$(load_pending_approval "${SECOND_TOKEN}")"
        if [[ -z "${PENDING_REQUEST}" ]]; then
            SKIP_PASS2_EXECUTION=true
            FORCE_PASS3_DELIVERY=true
            CATEGORY="APPROVALS"
            AGENT_NAME="approval_gate"
            ACTION="Approval request '${SECOND_TOKEN}' was not found (it may already be approved/rejected/expired)."
            SUCCESS=true
            ERROR_MSG="approval_request_not_found"
            log "    ERROR: ${ERROR_MSG} id=${SECOND_TOKEN}"
        elif [[ "${FIRST_TOKEN}" == "reject" ]]; then
            REJECT_REASON="$(echo "${INSTRUCTION}" | sed -E 's/^[Rr][Ee][Jj][Ee][Cc][Tt][[:space:]]+[^[:space:]]+[[:space:]]*//')"
            remove_pending_approval "${SECOND_TOKEN}"
            append_approval_audit "rejected" "${SECOND_TOKEN}" "rejected" "${REJECT_REASON}" "${MSG_GUID}" "$(echo "${PENDING_REQUEST}" | jq -r '.instruction // ""')" "$(echo "${PENDING_REQUEST}" | jq -r '.category // "unknown"')" "$(echo "${PENDING_REQUEST}" | jq -r '.agent // "null"')"
            SKIP_PASS2_EXECUTION=true
            FORCE_PASS3_DELIVERY=true
            CATEGORY="APPROVALS"
            AGENT_NAME="approval_gate"
            ACTION="Approval ${SECOND_TOKEN} rejected. No external action was executed."
            SUCCESS=true
            ERROR_MSG=""
            log "    Approval rejected: id=${SECOND_TOKEN}"
        else
            APPROVAL_REQUEST_ID="${SECOND_TOKEN}"
            remove_pending_approval "${APPROVAL_REQUEST_ID}"
            append_approval_audit "approved" "${APPROVAL_REQUEST_ID}" "approved" "" "${MSG_GUID}" "$(echo "${PENDING_REQUEST}" | jq -r '.instruction // ""')" "$(echo "${PENDING_REQUEST}" | jq -r '.category // "unknown"')" "$(echo "${PENDING_REQUEST}" | jq -r '.agent // "null"')"
            IS_APPROVED_REPLAY=true
            INSTRUCTION="$(echo "${PENDING_REQUEST}" | jq -r '.instruction // empty')"
            CATEGORY="$(echo "${PENDING_REQUEST}" | jq -r '.category // "MISSING"')"
            AGENT_NAME="$(echo "${PENDING_REQUEST}" | jq -r '.agent // "null"')"
            AGENT_INSTRUCTION="$(echo "${PENDING_REQUEST}" | jq -r '.agent_instruction // empty')"
            REQUEST_INSTRUCTION="${AGENT_INSTRUCTION:-$INSTRUCTION}"
            log "    Approval granted: id=${APPROVAL_REQUEST_ID}, replaying instruction"
        fi
    fi

    # ── Pass 1: Classify the message ─────────────────────────────────────────
    if [[ "${IS_APPROVED_REPLAY}" != "true" && "${SKIP_PASS2_EXECUTION}" != "true" ]]; then
        log "    Pass 1: Classifying..."

        CLASSIFY_SCHEMA='{"type":"object","properties":{"category":{"type":"string","enum":["REMEMBER","LOCATION","TODO","NOTE","COMMUNICATE","PLANNING","AGENDA","SECURITY","INCIDENTS","APPROVALS","ACTION_ITEMS","SEARCH","MISSING"]},"agent":{"type":["string","null"]},"instruction":{"type":"string"},"missing_agent_suggestion":{"type":["string","null"]}},"required":["category","agent","instruction"]}'

        CLASSIFY_RESULT=""
        CLASSIFY_ATTEMPT=0
        CLASSIFY_OK=false
        while [[ ${CLASSIFY_ATTEMPT} -le ${MAX_RETRIES} ]]; do
            CLASSIFY_ATTEMPT=$((CLASSIFY_ATTEMPT + 1))
            CLASSIFY_RESULT=$(claude -p "${TRIAGE_PROMPT}

Classify this message:
${INSTRUCTION}" --output-format json --json-schema "${CLASSIFY_SCHEMA}" "${CLAUDE_MCP_ARGS[@]}" --append-system-prompt "You MUST respond with ONLY a JSON object matching the schema. No other text." --model sonnet --no-session-persistence --disable-slash-commands 2>/dev/null) && {
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
        REQUEST_INSTRUCTION="${AGENT_INSTRUCTION:-$INSTRUCTION}"

        log "    Classified: category=${CATEGORY}, agent=${AGENT_NAME}"

        # ── Handle MISSING: log the gap ──────────────────────────────────────
        if [[ "${CATEGORY}" == "MISSING" && "${MISSING_SUGGESTION}" != "null" ]]; then
            log "    Missing agent suggestion: ${MISSING_SUGGESTION}"
            # Store the missing agent suggestion in memory via Claude
            invoke_claude "Store this fact using store_fact with category=\"work\", key=\"missing_agent_$(date +%s)\", value=\"${MISSING_SUGGESTION} (requested: ${INSTRUCTION:0:80})\". Return JSON: {\"action_taken\": \"stored missing agent suggestion\", \"success\": true}" >/dev/null 2>&1 || true
        fi
    elif [[ "${IS_APPROVED_REPLAY}" == "true" ]]; then
        log "    Pass 1: Using approved request classification: category=${CATEGORY}, agent=${AGENT_NAME}"
    fi

    if [[ "${SKIP_PASS2_EXECUTION}" != "true" ]]; then
        build_message_connector_policy_prompt "${REQUEST_INSTRUCTION}" "${CATEGORY}"
        log "    Route: profile=${ROUTE_PROFILE}, preferred=${ROUTE_PREFERRED_PROVIDER}, fallback=${ROUTE_FALLBACK_PROVIDER}, reason=${ROUTE_REASON}"

        if [[ "${IS_APPROVED_REPLAY}" != "true" ]] && requires_hard_approval "${REQUEST_INSTRUCTION}" "${CATEGORY}"; then
            PENDING_ID="$(create_pending_approval "${MSG_GUID}" "${INSTRUCTION}" "${CATEGORY}" "${AGENT_NAME}" "${AGENT_INSTRUCTION}" || true)"
            if [[ -n "${PENDING_ID}" ]]; then
                PENDING_JSON="$(load_pending_approval "${PENDING_ID}")"
                APPROVAL_EXPIRY="$(echo "${PENDING_JSON}" | jq -r '.expires_at // "unknown"')"
                append_approval_audit "requested" "${PENDING_ID}" "pending" "${APPROVAL_REASON}" "${MSG_GUID}" "${INSTRUCTION}" "${CATEGORY}" "${AGENT_NAME}"
                ACTION="Approval required for this request (${APPROVAL_REASON}). Reply with: jarvis: approve ${PENDING_ID}. Expires at ${APPROVAL_EXPIRY}. To cancel: jarvis: reject ${PENDING_ID}."
                SUCCESS=true
                PROVIDER_USED="none"
                FALLBACK_USED=false
                ERROR_MSG=""
                CATEGORY="APPROVALS"
                AGENT_NAME="approval_gate"
                FORCE_PASS3_DELIVERY=true
                SKIP_PASS2_EXECUTION=true
                log "    Hard approval required: id=${PENDING_ID}, reason=${APPROVAL_REASON}, expires=${APPROVAL_EXPIRY}"
            else
                ACTION="Approval queue unavailable; request was not executed."
                SUCCESS=false
                ERROR_MSG="approval_queue_write_failed"
                PROVIDER_USED="none"
                FALLBACK_USED=false
                CATEGORY="APPROVALS"
                AGENT_NAME="approval_gate"
                FORCE_PASS3_DELIVERY=true
                SKIP_PASS2_EXECUTION=true
                ERROR_COUNT=$((ERROR_COUNT + 1))
                log "    ERROR: ${ERROR_MSG}"
            fi
        fi
    fi

    if [[ "${SKIP_PASS2_EXECUTION}" != "true" ]]; then
        # ── Pass 2: Dispatch to the right agent or handle inline ─────────────
        if [[ "${AGENT_NAME}" != "null" && -n "${AGENT_NAME}" ]]; then
            # Route to a named agent
            AGENT_YAML="${PROJECT_DIR}/agent_configs/${AGENT_NAME}.yaml"
            if [[ -f "${AGENT_YAML}" ]]; then
                AGENT_PROMPT=$(extract_system_prompt "${AGENT_YAML}")
                if [[ -n "${AGENT_PROMPT}" ]]; then
                    log "    Pass 2: Dispatching to agent '${AGENT_NAME}'..."
                    EXEC_RESULT=$(invoke_claude_structured "${CONNECTOR_POLICY_PROMPT}

${AGENT_PROMPT}

Process this request:
${REQUEST_INSTRUCTION}") || {
                        log "    ERROR: Agent '${AGENT_NAME}' failed for [${MSG_GUID}]"
                        ERROR_COUNT=$((ERROR_COUNT + 1))
                        NEW_GUIDS+=("${MSG_GUID}")
                        continue
                    }
                else
                    log "    WARNING: Could not extract prompt from ${AGENT_YAML}, falling back to inline"
                    EXEC_RESULT=$(invoke_claude_structured "${CONNECTOR_POLICY_PROMPT}

${INLINE_PROMPT}

${REQUEST_INSTRUCTION}") || {
                        log "    ERROR: Inline handler failed for [${MSG_GUID}]"
                        ERROR_COUNT=$((ERROR_COUNT + 1))
                        NEW_GUIDS+=("${MSG_GUID}")
                        continue
                    }
                fi
            else
                log "    WARNING: Agent YAML not found: ${AGENT_YAML}, falling back to inline"
                EXEC_RESULT=$(invoke_claude_structured "${CONNECTOR_POLICY_PROMPT}

${INLINE_PROMPT}

${REQUEST_INSTRUCTION}") || {
                    log "    ERROR: Inline handler failed for [${MSG_GUID}]"
                    ERROR_COUNT=$((ERROR_COUNT + 1))
                    NEW_GUIDS+=("${MSG_GUID}")
                    continue
                }
            fi
        else
            # Handle inline (REMEMBER, TODO, NOTE, SEARCH, MISSING)
            log "    Pass 2: Handling inline (${CATEGORY})..."
            EXEC_RESULT=$(invoke_claude_structured "${CONNECTOR_POLICY_PROMPT}

${INLINE_PROMPT}

${REQUEST_INSTRUCTION}") || {
                log "    ERROR: Inline handler failed for [${MSG_GUID}]"
                ERROR_COUNT=$((ERROR_COUNT + 1))
                NEW_GUIDS+=("${MSG_GUID}")
                continue
            }
        fi

        # ── Parse execution result ───────────────────────────────────────────
        ACTION="unknown"
        SUCCESS=false
        ERROR_MSG=""
        PROVIDER_USED="none"
        FALLBACK_USED=false
        EXEC_TEXT=""
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
            PROVIDER_USED=$(echo "${EXEC_JSON}" | jq -r '.provider_used // "none"')
            FALLBACK_USED=$(echo "${EXEC_JSON}" | jq -r '.fallback_used // false')
            ERROR_MSG=$(echo "${EXEC_JSON}" | jq -r '.error // empty')

            if ! validate_execution_provider "${PROVIDER_USED}" "${FALLBACK_USED}"; then
                SUCCESS=false
                if [[ -n "${ERROR_MSG}" ]]; then
                    ERROR_MSG="${ERROR_MSG}; routing_validation: ${ROUTING_VALIDATION_ERROR}"
                else
                    ERROR_MSG="routing_validation: ${ROUTING_VALIDATION_ERROR}"
                fi
                log "    ERROR: ${ERROR_MSG}"
            fi

            log "    Result: category=${CATEGORY}, agent=${AGENT_NAME}, provider=${PROVIDER_USED}, fallback=${FALLBACK_USED}, action=\"${ACTION}\", success=${SUCCESS}"
            if [[ -n "${ERROR_MSG}" ]]; then
                log "    Error: ${ERROR_MSG}"
                ERROR_COUNT=$((ERROR_COUNT + 1))
            fi
        else
            log "    WARNING: Could not parse execution JSON from agent '${AGENT_NAME:-inline}'"
            log "    Raw (truncated): ${EXEC_TEXT:0:300}"
            ERROR_MSG="execution_json_parse_error"
            ERROR_COUNT=$((ERROR_COUNT + 1))
        fi

        if [[ "${IS_APPROVED_REPLAY}" == "true" ]]; then
            EXECUTION_STATUS="failed"
            if [[ "${SUCCESS}" == "true" ]]; then
                EXECUTION_STATUS="executed"
            fi
            append_approval_audit "executed" "${APPROVAL_REQUEST_ID}" "${EXECUTION_STATUS}" "${ERROR_MSG}" "${MSG_GUID}" "${REQUEST_INSTRUCTION}" "${CATEGORY}" "${AGENT_NAME}"
        fi
    fi

    append_routing_audit "${MSG_GUID}" "${CATEGORY}" "${REQUEST_INSTRUCTION}" "${SUCCESS}" "${PROVIDER_USED}" "${FALLBACK_USED}" "${ERROR_MSG}"

    # ── Pass 3: Deliver output and notify ─────────────────────────────────
    # Skip if the agent was already "communications" (it handled delivery itself)
    # or if Pass 2 failed
    if [[ ("${CATEGORY}" != "COMMUNICATE" || "${FORCE_PASS3_DELIVERY}" == "true") && "${SUCCESS}" == "true" ]]; then
        DELIVERY_BODY="${ACTION}"

        # For richer output, try to extract the full result text
        FULL_RESULT=$(echo "${EXEC_RESULT}" | jq -r '.result // empty' 2>/dev/null)
        if [[ -n "${FULL_RESULT}" && "${FULL_RESULT}" != "null" ]]; then
            DELIVERY_BODY="${FULL_RESULT}"
        fi

        # 3a. Deliver via email or iMessage if instruction implies it
        DELIVERY_MODE=""
        if [[ "${FORCE_PASS3_DELIVERY}" != "true" ]]; then
            if echo "${INSTRUCTION}" | grep -iqE '\b(email|draft|draft email|send email)\b'; then
                DELIVERY_MODE="email"
            elif echo "${INSTRUCTION}" | grep -iqE '\b(text|imessage|send text|send message)\b'; then
                DELIVERY_MODE="imessage"
            fi
        fi

        if [[ -n "${DELIVERY_MODE}" ]]; then
            log "    Pass 3a: Delivering via ${DELIVERY_MODE}..."
            if [[ "${DELIVERY_MODE}" == "email" ]]; then
                if [[ -z "${DEFAULT_EMAIL_TO}" ]]; then
                    log "    Pass 3a skipped: no email target configured (set --email-to or JARVIS_DEFAULT_EMAIL_TO)"
                    DELIVERY_OUTPUT=""
                else
                    DELIVERY_SUBJECT="Jarvis: ${CATEGORY} — ${AGENT_NAME:-inline}"
                    DELIVERY_OUTPUT=$("${SCRIPT_DIR}/communicate.sh" email-draft --to "${DEFAULT_EMAIL_TO}" --subject "${DELIVERY_SUBJECT}" --body "${DELIVERY_BODY}" 2>/dev/null) || true
                fi
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

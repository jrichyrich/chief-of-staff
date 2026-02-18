#!/usr/bin/env bash
set -euo pipefail

ACTION=""
TO=""
CHAT_ID=""
SUBJECT=""
BODY=""

usage() {
    cat <<'USAGE'
Usage: communicate.sh <action> [--to "recipient" | --chat-id "chat_identifier"] --body "text" [options]

Actions:
  email-draft    Create a draft email in Microsoft Outlook
  imessage       Send an iMessage via Messages.app
  reminder       Create an iCloud Reminder (syncs to iPhone with alert)

Options:
  --to "recipient"        Email address, phone number, or "self" (required for email; optional for imessage if --chat-id is provided)
  --chat-id "id"          iMessage chat identifier for thread-aware sends (imessage only)
  --body "text"           Message body (required)
  --subject "subject"     Email subject / reminder title (email-draft, reminder)
  --help                  Show this help message

Environment:
  JARVIS_IMESSAGE_SELF    Phone or email for "self" iMessage target
USAGE
    exit 0
}

json_error() {
    local channel="$1" error="$2"
    jq -nc --arg channel "$channel" --arg status "error" --arg error "$error" \
        '{"channel": $channel, "status": $status, "error": $error}'
}

escape_applescript() {
    local text="$1"
    text="${text//\\/\\\\}"
    text="${text//\"/\\\"}"
    text="${text//$'\n'/\\n}"
    text="${text//$'\r'/\\r}"
    text="${text//$'\t'/\\t}"
    printf '%s' "$text"
}

# Parse subcommand
if [[ $# -eq 0 ]]; then
    usage
fi

case "$1" in
    email-draft|imessage|reminder)
        ACTION="$1"
        shift
        ;;
    --help)
        usage
        ;;
    *)
        json_error "unknown" "Unknown action: $1. Use email-draft, imessage, or reminder."
        exit 1
        ;;
esac

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --to)      TO="$2";      shift 2 ;;
        --chat-id) CHAT_ID="$2"; shift 2 ;;
        --subject) SUBJECT="$2"; shift 2 ;;
        --body)    BODY="$2";    shift 2 ;;
        --help)    usage ;;
        *)
            json_error "$ACTION" "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Validate required args
if [[ -z "$TO" && "$ACTION" != "reminder" && "$ACTION" != "imessage" ]]; then
    json_error "$ACTION" "--to is required"
    exit 1
fi

if [[ "$ACTION" == "imessage" && -z "$TO" && -z "$CHAT_ID" ]]; then
    json_error "$ACTION" "--to or --chat-id is required for imessage"
    exit 1
fi

if [[ -z "$BODY" ]]; then
    json_error "$ACTION" "--body is required"
    exit 1
fi

case "$ACTION" in
    email-draft)
        escaped_body="$(escape_applescript "$BODY")"
        escaped_subject="$(escape_applescript "$SUBJECT")"
        escaped_to="$(escape_applescript "$TO")"

        applescript=$(cat <<APPLESCRIPT
tell application "Microsoft Outlook"
    set newMsg to make new outgoing message with properties {subject:"${escaped_subject}", content:"${escaped_body}"}
    make new recipient at newMsg with properties {email address:{address:"${escaped_to}"}}
    open newMsg
    activate
end tell
APPLESCRIPT
)

        if osascript -e "$applescript" 2>/dev/null; then
            jq -nc --arg channel "email" --arg status "draft_created" --arg subject "$SUBJECT" \
                '{"channel": $channel, "status": $status, "subject": $subject}'
        else
            json_error "email" "Failed to create email draft in Outlook"
            exit 1
        fi
        ;;

    imessage)
        escaped_body="$(escape_applescript "$BODY")"
        if [[ -n "$CHAT_ID" ]]; then
            escaped_chat_id="$(escape_applescript "$CHAT_ID")"
            applescript=$(cat <<APPLESCRIPT
tell application "Messages"
    set targetChat to first chat whose id is "${escaped_chat_id}"
    send "${escaped_body}" to targetChat
end tell
APPLESCRIPT
)
        else
            # Resolve "self" target
            if [[ "$TO" == "self" ]]; then
                TO="${JARVIS_IMESSAGE_SELF:-}"
                if [[ -z "$TO" ]]; then
                    json_error "imessage" "JARVIS_IMESSAGE_SELF not set and --to is \"self\""
                    exit 1
                fi
            fi
            escaped_to="$(escape_applescript "$TO")"
            applescript=$(cat <<APPLESCRIPT
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "${escaped_to}" of targetService
    send "${escaped_body}" to targetBuddy
end tell
APPLESCRIPT
)
        fi

        if osascript -e "$applescript" 2>/dev/null; then
            if [[ -n "$CHAT_ID" ]]; then
                jq -nc --arg channel "imessage" --arg status "sent" --arg chat_identifier "$CHAT_ID" \
                    '{"channel": $channel, "status": $status, "chat_identifier": $chat_identifier}'
            else
                jq -nc --arg channel "imessage" --arg status "sent" --arg to "$TO" \
                    '{"channel": $channel, "status": $status, "to": $to}'
            fi
        else
            json_error "imessage" "Failed to send iMessage"
            exit 1
        fi
        ;;

    reminder)
        escaped_body="$(escape_applescript "$BODY")"
        reminder_title="${SUBJECT:-Jarvis}"
        escaped_title="$(escape_applescript "$reminder_title")"

        applescript=$(cat <<APPLESCRIPT
tell application "Reminders"
    if not (exists list "Jarvis") then
        make new list with properties {name:"Jarvis"}
    end if
    tell list "Jarvis"
        make new reminder with properties {name:"${escaped_title}", body:"${escaped_body}", due date:(current date), priority:1}
    end tell
end tell
APPLESCRIPT
)

        if osascript -e "$applescript" >/dev/null 2>&1; then
            jq -nc --arg channel "reminder" --arg status "created" --arg title "$reminder_title" \
                '{"channel": $channel, "status": $status, "title": $title}'
        else
            json_error "reminder" "Failed to create reminder"
            exit 1
        fi
        ;;
esac

#!/usr/bin/env bash
set -euo pipefail

ACTION=""
TO=""
SUBJECT=""
BODY=""

usage() {
    cat <<'USAGE'
Usage: communicate.sh <action> --to "recipient" --body "text" [options]

Actions:
  email-draft    Create a draft email in Microsoft Outlook
  imessage       Send an iMessage via Messages.app
  reminder       Create an iCloud Reminder (syncs to iPhone with alert)

Options:
  --to "recipient"        Email address, phone number, or "self" (required for email/imessage; ignored for reminder)
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
    printf '{"channel": "%s", "status": "error", "error": "%s"}\n' "$channel" "$error"
}

escape_applescript() {
    local text="$1"
    text="${text//\\/\\\\}"
    text="${text//\"/\\\"}"
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
if [[ -z "$TO" && "$ACTION" != "reminder" ]]; then
    json_error "$ACTION" "--to is required"
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
            escaped_subj_json="${SUBJECT//\"/\\\"}"
            printf '{"channel": "email", "status": "draft_created", "subject": "%s"}\n' "$escaped_subj_json"
        else
            json_error "email" "Failed to create email draft in Outlook"
            exit 1
        fi
        ;;

    imessage)
        # Resolve "self" target
        if [[ "$TO" == "self" ]]; then
            TO="${JARVIS_IMESSAGE_SELF:-}"
            if [[ -z "$TO" ]]; then
                json_error "imessage" "JARVIS_IMESSAGE_SELF not set and --to is \"self\""
                exit 1
            fi
        fi

        escaped_body="$(escape_applescript "$BODY")"
        escaped_to="$(escape_applescript "$TO")"

        applescript=$(cat <<APPLESCRIPT
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "${escaped_to}" of targetService
    send "${escaped_body}" to targetBuddy
end tell
APPLESCRIPT
)

        if osascript -e "$applescript" 2>/dev/null; then
            escaped_to_json="${TO//\"/\\\"}"
            printf '{"channel": "imessage", "status": "sent", "to": "%s"}\n' "$escaped_to_json"
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
            escaped_title_json="${reminder_title//\"/\\\"}"
            printf '{"channel": "reminder", "status": "created", "title": "%s"}\n' "$escaped_title_json"
        else
            json_error "reminder" "Failed to create reminder"
            exit 1
        fi
        ;;
esac

import json
import logging
import subprocess
from datetime import datetime

from connectors.claude_m365_bridge import ClaudeM365Bridge


def test_connector_connected_detection_true():
    def fake_runner(args, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(args, 0, stdout="microsoft 365: connected\n", stderr="")

    bridge = ClaudeM365Bridge(runner=fake_runner)
    assert bridge.is_connector_connected() is True


def test_connector_connected_detection_false():
    def fake_runner(args, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(args, 0, stdout="microsoft 365: disconnected\n", stderr="")

    bridge = ClaudeM365Bridge(runner=fake_runner)
    assert bridge.is_connector_connected() is False


def test_list_calendars_reads_structured_output():
    payload = {
        "structured_output": {
            "results": [{"name": "Work", "calendar_id": "cal-1", "source_account": "Microsoft 365"}]
        }
    }

    def fake_runner(args, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    bridge = ClaudeM365Bridge(runner=fake_runner)
    rows = bridge.list_calendars()
    assert len(rows) == 1
    assert rows[0]["name"] == "Work"


def test_get_events_parses_json_from_result_text():
    payload = {
        "result": "Here you go:\n{\"results\":[{\"title\":\"Standup\",\"uid\":\"x1\"}]}"
    }

    def fake_runner(args, capture_output, text, timeout, check):
        if args[:3] == ["claude", "mcp", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="microsoft 365: connected\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    bridge = ClaudeM365Bridge(runner=fake_runner)
    rows = bridge.get_events(
        start_dt=datetime(2026, 2, 1),
        end_dt=datetime(2026, 2, 2),
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Standup"


def test_get_events_error_includes_timing():
    """When get_events fails, error dict contains elapsed_ms and operation keys."""
    def fake_runner(args, capture_output, text, timeout, check):
        if args[:3] == ["claude", "mcp", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="microsoft 365: connected\n", stderr="")
        # Return a failing subprocess result to trigger error path
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="API timeout")

    bridge = ClaudeM365Bridge(runner=fake_runner)
    rows = bridge.get_events(
        start_dt=datetime(2026, 2, 1),
        end_dt=datetime(2026, 2, 2),
    )
    # Should be an error dict (list with one error entry)
    assert len(rows) == 1
    error_dict = rows[0]
    assert "error" in error_dict
    assert "elapsed_ms" in error_dict
    assert error_dict["operation"] == "get_events"
    assert isinstance(error_dict["elapsed_ms"], int)


def _make_bridge_with_events(events, total_count=None):
    """Helper to create a bridge that returns preset events."""
    result = {"results": events}
    if total_count is not None:
        result["total_event_count"] = total_count
    payload = {"structured_output": result}

    def fake_runner(args, capture_output, text, timeout, check):
        if args[:3] == ["claude", "mcp", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="microsoft 365: connected\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    return ClaudeM365Bridge(runner=fake_runner)


def test_get_events_count_matches_no_warning():
    """No _bridge_warning when total_event_count matches results length."""
    events = [{"title": "Meeting", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00"}]
    bridge = _make_bridge_with_events(events, total_count=1)
    rows = bridge.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(rows) == 1
    assert "_bridge_warning" not in rows[0]


def test_get_events_count_mismatch_adds_warning():
    """_bridge_warning added when total_event_count exceeds results length."""
    events = [{"title": "Meeting", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00"}]
    bridge = _make_bridge_with_events(events, total_count=5)
    rows = bridge.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(rows) == 1
    assert "_bridge_warning" in rows[0]
    assert "5" in rows[0]["_bridge_warning"]


def test_get_events_no_total_count_no_crash():
    """Backward compat: no total_event_count field doesn't crash."""
    events = [{"title": "Meeting", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00"}]
    bridge = _make_bridge_with_events(events, total_count=None)
    rows = bridge.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(rows) == 1
    assert "_bridge_warning" not in rows[0]


def test_search_events_count_mismatch_adds_warning():
    """search_events also tags _bridge_warning on count mismatch."""
    events = [{"title": "Standup", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T09:30:00-06:00"}]
    bridge = _make_bridge_with_events(events, total_count=3)
    rows = bridge.search_events("Standup", datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(rows) == 1
    assert "_bridge_warning" in rows[0]


def test_search_events_count_matches_no_warning():
    """search_events: no warning when count matches."""
    events = [{"title": "Standup", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T09:30:00-06:00"}]
    bridge = _make_bridge_with_events(events, total_count=1)
    rows = bridge.search_events("Standup", datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(rows) == 1
    assert "_bridge_warning" not in rows[0]


# ---------------------------------------------------------------------------
# Critical 1: System prompt hardening against prompt injection
# ---------------------------------------------------------------------------


def test_invoke_structured_includes_system_prompt():
    """CLI args must include --append-system-prompt with data-boundary instructions."""
    captured_args = {}

    def spy_runner(args, capture_output, text, timeout, check):
        captured_args["args"] = args
        payload = {"structured_output": {"results": []}}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    bridge = ClaudeM365Bridge(runner=spy_runner)
    bridge.list_calendars()

    args = captured_args["args"]
    assert "--append-system-prompt" in args, "Must pass --append-system-prompt to Claude CLI"
    # The system prompt should be the argument following --append-system-prompt
    idx = args.index("--append-system-prompt")
    system_prompt = args[idx + 1]
    assert "data" in system_prompt.lower(), "System prompt must mention data boundaries"
    assert "instruction" in system_prompt.lower() or "instruct" in system_prompt.lower(), (
        "System prompt must distinguish data from instructions"
    )


def test_system_prompt_references_user_tags():
    """System prompt must explicitly reference <user_*> tags as data-only."""
    captured_args = {}

    def spy_runner(args, capture_output, text, timeout, check):
        captured_args["args"] = args
        payload = {"structured_output": {"results": [], "total_event_count": 0}}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    bridge = ClaudeM365Bridge(runner=spy_runner)
    bridge.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))

    args = captured_args["args"]
    idx = args.index("--append-system-prompt")
    system_prompt = args[idx + 1]
    assert "user_" in system_prompt.lower() or "<user" in system_prompt.lower(), (
        "System prompt must reference user_* tags as data-only markers"
    )


# ---------------------------------------------------------------------------
# Critical 2: Output validation — filter out-of-range events
# ---------------------------------------------------------------------------


def test_get_events_filters_out_of_range_events():
    """Events outside the requested date range must be filtered out."""
    events = [
        {"title": "In range", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00", "uid": "e1"},
        {"title": "Before range", "start": "2026-03-08T09:00:00-06:00", "end": "2026-03-08T10:00:00-06:00", "uid": "e2"},
        {"title": "After range", "start": "2026-03-15T09:00:00-06:00", "end": "2026-03-15T10:00:00-06:00", "uid": "e3"},
    ]
    bridge = _make_bridge_with_events(events, total_count=3)
    rows = bridge.get_events(datetime(2026, 3, 9), datetime(2026, 3, 12))
    titles = [r["title"] for r in rows]
    assert "In range" in titles
    assert "Before range" not in titles, "Events before requested range must be filtered"
    assert "After range" not in titles, "Events after requested range must be filtered"


def test_search_events_filters_out_of_range_events():
    """search_events must also filter events outside the requested range."""
    events = [
        {"title": "Match in range", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00", "uid": "e1"},
        {"title": "Match out of range", "start": "2026-03-20T09:00:00-06:00", "end": "2026-03-20T10:00:00-06:00", "uid": "e2"},
    ]
    bridge = _make_bridge_with_events(events, total_count=2)
    rows = bridge.search_events("Match", datetime(2026, 3, 9), datetime(2026, 3, 12))
    assert len(rows) == 1
    assert rows[0]["title"] == "Match in range"


def test_get_events_keeps_events_with_unparseable_dates():
    """Events with unparseable start/end should be kept (not silently dropped)."""
    events = [
        {"title": "Good", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00", "uid": "e1"},
        {"title": "Bad dates", "start": "not-a-date", "end": "also-not", "uid": "e2"},
    ]
    bridge = _make_bridge_with_events(events, total_count=2)
    rows = bridge.get_events(datetime(2026, 3, 9), datetime(2026, 3, 12))
    titles = [r["title"] for r in rows]
    assert "Good" in titles
    assert "Bad dates" in titles, "Events with unparseable dates should be kept, not dropped"


def test_invoke_structured_logs_warning_on_fallback_parse(caplog):
    """When _parse_first_json_object fallback fires, a warning must be logged."""
    # Return data that only parses via fallback (no structured_output, result is text with embedded JSON)
    payload = {
        "result": "Here is your data: {\"results\": [{\"title\": \"Test\", \"start\": \"2026-03-10T09:00:00\", \"end\": \"2026-03-10T10:00:00\"}], \"total_event_count\": 1}"
    }

    def fake_runner(args, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    bridge = ClaudeM365Bridge(runner=fake_runner)
    with caplog.at_level(logging.WARNING, logger="connectors.claude_m365_bridge"):
        bridge.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))

    fallback_warnings = [r for r in caplog.records if "fallback" in r.message.lower()]
    assert len(fallback_warnings) >= 1, "Must log a warning when fallback JSON parsing is used"


def test_get_events_rejects_absurd_total_event_count():
    """An unreasonably large total_event_count should produce a warning."""
    events = [{"title": "Meeting", "start": "2026-03-10T09:00:00-06:00", "end": "2026-03-10T10:00:00-06:00"}]
    bridge = _make_bridge_with_events(events, total_count=999999)
    rows = bridge.get_events(datetime(2026, 3, 10), datetime(2026, 3, 11))
    assert len(rows) == 1
    # Should still have the bridge warning for mismatch
    assert "_bridge_warning" in rows[0]
    # And an additional flag about suspicious count
    assert rows[0].get("_bridge_suspicious_count") is True, (
        "Absurdly large total_event_count should be flagged as suspicious"
    )

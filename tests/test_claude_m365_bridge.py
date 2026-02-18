import json
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

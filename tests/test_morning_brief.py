"""Tests for scheduler/morning_brief.py."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from scheduler.morning_brief import run_morning_brief, _parse_config


class TestParseConfig:
    def test_empty_string(self):
        assert _parse_config("") == {}

    def test_none_like(self):
        assert _parse_config("  ") == {}

    def test_valid_json(self):
        assert _parse_config('{"model": "opus"}') == {"model": "opus"}

    def test_invalid_json(self):
        assert _parse_config("not json") == {}

    def test_non_dict(self):
        assert _parse_config('["a", "b"]') == {}


class TestRunMorningBrief:
    @patch("scheduler.morning_brief.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="## Schedule\n- 9:00 AM: Standup\n\n## Action Items\n- None",
            stderr="",
        )

        result = json.loads(run_morning_brief())

        assert result["status"] == "ok"
        assert result["handler"] == "morning_brief"
        assert "Schedule" in result["brief"]
        assert "Standup" in result["brief"]

        # Verify CLI args
        call_args = mock_run.call_args
        args = call_args[0][0]
        assert "-p" in args
        assert "--output-format" in args
        assert "text" in args
        assert "--no-session-persistence" in args
        assert "--mcp-config" in args
        assert "--dangerously-skip-permissions" in args

    @patch("scheduler.morning_brief.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=180)

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "timed out" in result["error"]

    @patch("scheduler.morning_brief.subprocess.run")
    def test_binary_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("claude not found")

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @patch("scheduler.morning_brief.subprocess.run")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="", stderr="API key invalid",
        )

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "exit code 1" in result["error"]
        assert "API key invalid" in result["error"]

    @patch("scheduler.morning_brief.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="", stderr="",
        )

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "empty output" in result["error"]

    @patch("scheduler.morning_brief.subprocess.run")
    def test_custom_config(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief content here",
            stderr="",
        )

        config = json.dumps({
            "model": "opus",
            "timeout": 300,
            "prompt_extra": "Focus on calendar conflicts.",
        })
        result = json.loads(run_morning_brief(config))

        assert result["status"] == "ok"

        call_args = mock_run.call_args
        args = call_args[0][0]
        assert "--model" in args
        model_idx = args.index("--model")
        assert args[model_idx + 1] == "opus"

        # Verify timeout was passed
        assert call_args[1]["timeout"] == 300

    @patch("scheduler.morning_brief.subprocess.run")
    def test_prompt_extra_appended(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief content",
            stderr="",
        )

        config = json.dumps({"prompt_extra": "Also check Jira."})
        run_morning_brief(config)

        call_args = mock_run.call_args
        args = call_args[0][0]
        prompt_idx = args.index("-p")
        prompt = args[prompt_idx + 1]
        assert "Also check Jira." in prompt


class TestEngineIntegration:
    def test_morning_brief_handler_registered(self):
        """Verify the morning_brief handler is wired into execute_handler."""
        from scheduler.engine import execute_handler

        with patch("scheduler.morning_brief.run_morning_brief") as mock_brief:
            mock_brief.return_value = json.dumps({"status": "ok", "handler": "morning_brief", "brief": "test"})
            result = execute_handler("morning_brief", '{"model": "sonnet"}')

        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        mock_brief.assert_called_once_with('{"model": "sonnet"}')

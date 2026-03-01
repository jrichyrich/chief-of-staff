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
    @patch("scheduler.morning_brief.run_with_cleanup")
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

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=180)

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "timed out" in result["error"]

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_binary_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("claude not found")

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="", stderr="API key invalid",
        )

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "exit code 1" in result["error"]
        assert "API key invalid" in result["error"]

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_empty_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="", stderr="",
        )

        result = json.loads(run_morning_brief())

        assert result["status"] == "error"
        assert "empty output" in result["error"]

    @patch("scheduler.morning_brief.run_with_cleanup")
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

    @patch("scheduler.morning_brief.run_with_cleanup")
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


class TestMcpConfigHandling:
    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_mcp_config_missing(self, mock_run, tmp_path):
        """Returns error when .mcp.json doesn't exist."""
        config = json.dumps({"project_dir": str(tmp_path)})
        result = json.loads(run_morning_brief(config))

        assert result["status"] == "error"
        assert "MCP config not found" in result["error"]
        mock_run.assert_not_called()

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_mcp_config_override(self, mock_run, tmp_path):
        """Uses mcp_config_override from handler_config."""
        custom_mcp = tmp_path / "custom.mcp.json"
        custom_mcp.write_text("{}")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief via custom config",
            stderr="",
        )

        config = json.dumps({"mcp_config_override": str(custom_mcp)})
        result = json.loads(run_morning_brief(config))

        assert result["status"] == "ok"
        assert "Brief via custom config" in result["brief"]

        # Verify the custom MCP config path was used in the CLI args
        call_args = mock_run.call_args
        args = call_args[0][0]
        mcp_idx = args.index("--mcp-config")
        assert args[mcp_idx + 1] == str(custom_mcp)

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_mcp_config_override_empty_falls_back(self, mock_run, tmp_path):
        """Empty mcp_config_override falls back to project_dir/.mcp.json."""
        # Create .mcp.json in the project dir
        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text("{}")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief content",
            stderr="",
        )

        config = json.dumps({
            "project_dir": str(tmp_path),
            "mcp_config_override": "",
        })
        result = json.loads(run_morning_brief(config))

        assert result["status"] == "ok"

        call_args = mock_run.call_args
        args = call_args[0][0]
        mcp_idx = args.index("--mcp-config")
        assert args[mcp_idx + 1] == str(mcp_file)


class TestRunWithCleanupUsed:
    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_uses_run_with_cleanup(self, mock_run, tmp_path):
        """Verify run_with_cleanup is used instead of subprocess.run."""
        # Create .mcp.json so the pre-check passes
        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text("{}")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief output",
            stderr="",
        )

        config = json.dumps({"project_dir": str(tmp_path)})
        run_morning_brief(config)

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 180  # default timeout
        assert call_kwargs["text"] is True


class TestEnvHandling:
    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_env_claudecode_stripped(self, mock_run, tmp_path, monkeypatch):
        """CLAUDECODE env var is removed from subprocess env."""
        monkeypatch.setenv("CLAUDECODE", "true")

        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text("{}")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief output",
            stderr="",
        )

        config = json.dumps({"project_dir": str(tmp_path)})
        run_morning_brief(config)

        call_kwargs = mock_run.call_args[1]
        env = call_kwargs["env"]
        assert "CLAUDECODE" not in env

    @patch("scheduler.morning_brief.run_with_cleanup")
    def test_env_path_includes_homebrew(self, mock_run, tmp_path):
        """PATH in subprocess env includes /opt/homebrew/bin."""
        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text("{}")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Brief output",
            stderr="",
        )

        config = json.dumps({"project_dir": str(tmp_path)})
        run_morning_brief(config)

        call_kwargs = mock_run.call_args[1]
        env = call_kwargs["env"]
        assert "/opt/homebrew/bin" in env.get("PATH", "")


class TestConfigDefaults:
    def test_default_model_from_config(self):
        """Default model comes from config module."""
        from config import MORNING_BRIEF_DEFAULT_MODEL
        from scheduler.morning_brief import _DEFAULT_MODEL
        assert _DEFAULT_MODEL == MORNING_BRIEF_DEFAULT_MODEL

    def test_default_timeout_from_config(self):
        """Default timeout comes from config module."""
        from config import MORNING_BRIEF_DEFAULT_TIMEOUT
        from scheduler.morning_brief import _DEFAULT_TIMEOUT
        assert _DEFAULT_TIMEOUT == MORNING_BRIEF_DEFAULT_TIMEOUT


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

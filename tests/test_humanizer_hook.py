# tests/test_humanizer_hook.py
"""Tests for the humanizer hook integration."""

import pytest
import yaml

import mcp_server  # noqa: F401

from hooks.registry import HookRegistry, build_tool_context, extract_transformed_args
from humanizer.hook import humanize_hook


class TestHumanizeHook:
    def test_transforms_send_email_body(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "test@test.com", "subject": "Test", "body": "Additionally, we utilize this tool."},
        )
        result = humanize_hook(ctx)
        assert result is not None
        assert "tool_args" in result
        assert "Additionally" not in result["tool_args"]["body"]
        assert "utilize" not in result["tool_args"]["body"]

    def test_transforms_reply_to_email_body(self):
        ctx = build_tool_context(
            tool_name="reply_to_email",
            tool_args={"message_id": "123", "body": "Great question! The tool serves as a gateway."},
        )
        result = humanize_hook(ctx)
        assert "Great question!" not in result["tool_args"]["body"]
        assert "serves as" not in result["tool_args"]["body"]

    def test_transforms_send_imessage_reply_body(self):
        ctx = build_tool_context(
            tool_name="send_imessage_reply",
            tool_args={"to": "+1234", "body": "In order to fix this \u2014 we need to update."},
        )
        result = humanize_hook(ctx)
        assert "\u2014" not in result["tool_args"]["body"]
        assert "In order to" not in result["tool_args"]["body"]

    def test_ignores_non_outbound_tools(self):
        ctx = build_tool_context(
            tool_name="query_memory",
            tool_args={"query": "Additionally, we utilize this tool."},
        )
        result = humanize_hook(ctx)
        assert result is None

    def test_preserves_other_args(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "a@b.com", "subject": "Hi", "body": "Additionally, yes.", "cc": "c@d.com"},
        )
        result = humanize_hook(ctx)
        assert result["tool_args"]["to"] == "a@b.com"
        assert result["tool_args"]["cc"] == "c@d.com"
        assert result["tool_args"]["subject"] == "Hi"

    def test_transforms_subject_too(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "a@b.com", "subject": "A Comprehensive Overview", "body": "Hello."},
        )
        result = humanize_hook(ctx)
        assert "comprehensive" not in result["tool_args"]["subject"].lower()

    def test_handles_missing_body_gracefully(self):
        ctx = build_tool_context(
            tool_name="send_email",
            tool_args={"to": "a@b.com", "subject": "Test"},
        )
        result = humanize_hook(ctx)
        # Should not crash, just return None or unchanged
        assert result is None or "tool_args" in result


class TestHumanizeHookIntegration:
    def test_registered_via_hook_registry(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", humanize_hook, name="humanizer", priority=10)

        ctx = {
            "tool_name": "send_email",
            "tool_args": {"to": "x@y.com", "body": "Additionally, we utilize this."},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        results = reg.fire_hooks("before_tool_call", ctx)
        transformed = extract_transformed_args(results)
        assert transformed is not None
        assert "Additionally" not in transformed["body"]
        assert "utilize" not in transformed["body"]

"""Handler execution functions for scheduled tasks.

Each _run_*_handler() function executes a specific handler type and returns
a JSON result string. The execute_handler() dispatch function routes by type.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Commands that are never allowed in custom handlers
_DANGEROUS_COMMANDS = frozenset({
    "rm", "rmdir", "del", "format", "mkfs", "dd", "shred",
    "shutdown", "reboot", "halt", "poweroff",
    "chmod", "chown", "chgrp",
    "kill", "killall", "pkill",
    "sudo", "su", "doas",
})

# Maximum timeout for custom subprocess execution (seconds)
_CUSTOM_HANDLER_TIMEOUT = 30


def _parse_json_config(config_str: str) -> dict:
    """Safely parse a JSON config string."""
    if not config_str or not config_str.strip():
        return {}
    try:
        value = json.loads(config_str)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _validate_custom_command(command_str: str) -> str:
    """Validate and sanitize a custom handler command. Returns the command or raises ValueError."""
    if not command_str or not command_str.strip():
        raise ValueError("Custom handler command cannot be empty")

    # Parse the command to check for dangerous patterns
    parts = command_str.strip().split()
    base_cmd = Path(parts[0]).name.lower()

    if base_cmd in _DANGEROUS_COMMANDS:
        raise ValueError(f"Command '{base_cmd}' is not allowed in custom handlers")

    # Check for shell metacharacters that could enable injection
    dangerous_chars = set(";|&`$(){}!")
    if dangerous_chars & set(command_str):
        raise ValueError("Shell metacharacters are not allowed in custom handler commands")

    return command_str.strip()


def _run_alert_eval_handler() -> str:
    """Run the alert evaluator handler."""
    try:
        from scheduler.alert_evaluator import evaluate_alerts
        evaluate_alerts()
        return json.dumps({"status": "ok", "handler": "alert_eval"})
    except Exception as e:
        logger.error("Alert eval handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "alert_eval", "error": str(e)})


def _run_custom_handler(handler_config: str) -> str:
    """Run a custom subprocess handler."""
    config = _parse_json_config(handler_config)
    command = config.get("command", "")

    try:
        validated_command = _validate_custom_command(command)
    except ValueError as e:
        return json.dumps({"status": "error", "handler": "custom", "error": str(e)})

    parts = validated_command.split()

    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=_CUSTOM_HANDLER_TIMEOUT,
            shell=False,
        )
        return json.dumps({
            "status": "ok" if result.returncode == 0 else "error",
            "handler": "custom",
            "returncode": result.returncode,
            "stdout": result.stdout[:1000],
            "stderr": result.stderr[:500],
        })
    except subprocess.TimeoutExpired:
        logger.error("Custom handler timed out: %s", validated_command)
        return json.dumps({"status": "error", "handler": "custom", "error": "timeout"})
    except FileNotFoundError:
        logger.error("Custom handler command not found: %s", parts[0])
        return json.dumps({"status": "error", "handler": "custom", "error": f"command not found: {parts[0]}"})
    except Exception as e:
        logger.error("Custom handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "custom", "error": str(e)})


def _run_webhook_poll_handler(memory_store) -> str:
    """Run the webhook poll handler to ingest queued webhook events."""
    try:
        from webhook.ingest import ingest_events
        from config import WEBHOOK_INBOX_DIR

        inbox_dir = Path(WEBHOOK_INBOX_DIR)
        if not inbox_dir.exists():
            return json.dumps({
                "status": "ok",
                "handler": "webhook_poll",
                "message": "Inbox directory does not exist yet, nothing to ingest",
            })

        result = ingest_events(memory_store, inbox_dir)
        return json.dumps({"status": "ok", "handler": "webhook_poll", **result})
    except Exception as e:
        logger.error("Webhook poll handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "webhook_poll", "error": str(e)})


def _run_skill_analysis_handler(memory_store) -> str:
    """Run the skill pattern analysis handler."""
    try:
        from skills.pattern_detector import PatternDetector
        from memory.models import SkillSuggestion

        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns()
        for pattern in patterns:
            suggestion = SkillSuggestion(
                description=pattern["description"],
                suggested_name=pattern["tool_name"].replace(" ", "_") + "_specialist",
                suggested_capabilities=pattern["tool_name"],
                confidence=pattern["confidence"],
            )
            memory_store.store_skill_suggestion(suggestion)
        return json.dumps({"status": "ok", "handler": "skill_analysis", "patterns_found": len(patterns)})
    except Exception as e:
        logger.error("Skill analysis handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "skill_analysis", "error": str(e)})


def _run_proactive_push_handler(memory_store) -> str:
    """Run the proactive push notification handler."""
    try:
        from config import PROACTIVE_PUSH_ENABLED, PROACTIVE_PUSH_THRESHOLD
        from proactive.engine import ProactiveSuggestionEngine

        if not PROACTIVE_PUSH_ENABLED:
            return json.dumps({"status": "skipped", "handler": "proactive_push", "message": "Push notifications disabled"})

        engine = ProactiveSuggestionEngine(memory_store)
        result = engine.check_all(push_enabled=True, push_threshold=PROACTIVE_PUSH_THRESHOLD)
        return json.dumps({
            "status": "ok",
            "handler": "proactive_push",
            "suggestions_count": len(result["suggestions"]),
            "pushed_count": len(result.get("pushed", [])),
        })
    except Exception as e:
        logger.error("Proactive push handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "proactive_push", "error": str(e)})


def _run_morning_brief_handler(handler_config: str) -> str:
    """Run the morning brief handler (spawns Claude CLI)."""
    try:
        from scheduler.morning_brief import run_morning_brief
        return run_morning_brief(handler_config)
    except Exception as e:
        logger.error("Morning brief handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "morning_brief", "error": str(e)})


def _run_skill_auto_exec_handler(memory_store, agent_registry=None) -> str:
    """Run the skill auto-execution handler."""
    try:
        from config import SKILL_AUTO_EXECUTE_ENABLED
        from skills.pattern_detector import PatternDetector

        if not SKILL_AUTO_EXECUTE_ENABLED:
            return json.dumps({"status": "skipped", "handler": "skill_auto_exec", "message": "Skill auto-execute disabled"})

        detector = PatternDetector(memory_store)
        created = detector.auto_execute(memory_store, agent_registry)
        return json.dumps({
            "status": "ok",
            "handler": "skill_auto_exec",
            "agents_created": len(created),
            "agent_names": created,
        })
    except Exception as e:
        logger.error("Skill auto-exec handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "skill_auto_exec", "error": str(e)})


def _run_webhook_dispatch_handler(memory_store, agent_registry=None, document_store=None) -> str:
    """Run the webhook dispatch handler to process pending events via matched agents."""
    try:
        from config import WEBHOOK_AUTO_DISPATCH_ENABLED

        if not WEBHOOK_AUTO_DISPATCH_ENABLED:
            return json.dumps({"status": "skipped", "handler": "webhook_dispatch", "message": "Webhook auto-dispatch disabled"})

        import asyncio
        from webhook.ingest import dispatch_pending_events

        # dispatch_pending_events is async; handle both standalone and daemon contexts.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Inside daemon's async context — run in a thread to avoid nested event loop.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    dispatch_pending_events(memory_store, agent_registry, document_store),
                )
                result = future.result(timeout=300)
        else:
            result = asyncio.run(
                dispatch_pending_events(memory_store, agent_registry, document_store)
            )

        return json.dumps({"status": "ok", "handler": "webhook_dispatch", **result})
    except Exception as e:
        logger.error("Webhook dispatch handler failed: %s", e)
        return json.dumps({"status": "error", "handler": "webhook_dispatch", "error": str(e)})


def execute_handler(handler_type: str, handler_config: str, memory_store=None, agent_registry=None, document_store=None) -> str:
    """Execute a task handler and return a JSON result string."""
    # Import here to avoid module-level circular dependency
    from memory.models import HandlerType

    if handler_type == HandlerType.alert_eval:
        return _run_alert_eval_handler()
    elif handler_type == HandlerType.webhook_poll:
        return _run_webhook_poll_handler(memory_store)
    elif handler_type == HandlerType.skill_analysis:
        return _run_skill_analysis_handler(memory_store)
    elif handler_type == HandlerType.proactive_push:
        return _run_proactive_push_handler(memory_store)
    elif handler_type == HandlerType.skill_auto_exec:
        return _run_skill_auto_exec_handler(memory_store, agent_registry)
    elif handler_type == HandlerType.webhook_dispatch:
        return _run_webhook_dispatch_handler(memory_store, agent_registry, document_store)
    elif handler_type == HandlerType.morning_brief:
        return _run_morning_brief_handler(handler_config)
    elif handler_type == HandlerType.custom:
        return _run_custom_handler(handler_config)
    else:
        return json.dumps({
            "status": "skipped",
            "handler": handler_type,
            "message": f"Handler type '{handler_type}' is not yet implemented",
        })

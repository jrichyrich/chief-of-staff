"""HookRegistry — manages Python-level hooks for tool/session lifecycle events.

Event types:
    before_tool_call  — fired before a tool executes
    after_tool_call   — fired after a tool executes (includes result)
    session_start     — fired when the MCP server starts
    session_end       — fired when the MCP server shuts down

Each hook callback receives a context dict and may return an arbitrary value.
Hooks are error-isolated: one hook raising does not prevent subsequent hooks from running.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger("jarvis-mcp.hooks")

EVENT_TYPES = frozenset({
    "before_tool_call",
    "after_tool_call",
    "session_start",
    "session_end",
})


class HookRegistry:
    """Registry for Python-level lifecycle hooks."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[dict[str, Any]]] = {et: [] for et in EVENT_TYPES}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_hook(
        self,
        event_type: str,
        callback: Callable[[dict], Any],
        *,
        name: str = "",
        priority: int = 100,
        enabled: bool = True,
    ) -> None:
        """Register a hook callback for an event type.

        Args:
            event_type: One of EVENT_TYPES.
            callback: Callable receiving a context dict. May be sync or async.
            name: Optional human-readable name (used in logs).
            priority: Lower numbers run first. Default 100.
            enabled: If False, the hook is registered but will not fire.
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event type '{event_type}'. Must be one of: {sorted(EVENT_TYPES)}"
            )
        entry = {
            "name": name or getattr(callback, "__name__", "anonymous"),
            "callback": callback,
            "priority": priority,
            "enabled": enabled,
        }
        self._hooks[event_type].append(entry)
        # Keep hooks sorted by priority (stable sort preserves insertion order for ties)
        self._hooks[event_type].sort(key=lambda h: h["priority"])

    def fire_hooks(self, event_type: str, context: dict) -> list[Any]:
        """Fire all enabled hooks for *event_type*, returning their results.

        Each hook receives a **copy** of *context* so mutations don't leak between hooks.
        If a hook raises, the exception is logged and ``None`` is appended to results.
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event type '{event_type}'. Must be one of: {sorted(EVENT_TYPES)}"
            )
        results: list[Any] = []
        for entry in self._hooks[event_type]:
            if not entry["enabled"]:
                continue
            try:
                result = entry["callback"](dict(context))
                results.append(result)
            except Exception:
                logger.exception("Hook '%s' failed for event '%s'", entry["name"], event_type)
                results.append(None)
        return results

    def get_hooks(self, event_type: str) -> list[dict[str, Any]]:
        """Return the list of hook entries for *event_type* (mainly for introspection/tests)."""
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Unknown event type '{event_type}'. Must be one of: {sorted(EVENT_TYPES)}"
            )
        return list(self._hooks[event_type])

    def clear(self) -> None:
        """Remove all registered hooks."""
        for et in EVENT_TYPES:
            self._hooks[et].clear()

    # ------------------------------------------------------------------
    # YAML config loading
    # ------------------------------------------------------------------

    def load_configs(self, config_dir: str | Path) -> int:
        """Load hook YAML configs from *config_dir*. Returns count of hooks loaded.

        Each YAML file should contain a list of hook definitions:

            - event_type: before_tool_call
              name: my_hook
              handler: hooks.builtin.audit_log_hook
              priority: 50
              enabled: true
        """
        config_dir = Path(config_dir)
        if not config_dir.is_dir():
            logger.warning("Hook config directory does not exist: %s", config_dir)
            return 0

        loaded = 0
        for yaml_file in sorted(config_dir.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    entries = yaml.safe_load(f)
                if not isinstance(entries, list):
                    logger.warning("Hook config %s: expected a list, got %s", yaml_file, type(entries).__name__)
                    continue
                for entry in entries:
                    event_type = entry.get("event_type", "")
                    handler_path = entry.get("handler", "")
                    if not event_type or not handler_path:
                        logger.warning("Hook config %s: skipping entry missing event_type or handler", yaml_file)
                        continue
                    callback = _import_handler(handler_path)
                    if callback is None:
                        logger.warning("Hook config %s: could not import handler '%s'", yaml_file, handler_path)
                        continue
                    self.register_hook(
                        event_type=event_type,
                        callback=callback,
                        name=entry.get("name", ""),
                        priority=entry.get("priority", 100),
                        enabled=entry.get("enabled", True),
                    )
                    loaded += 1
            except Exception:
                logger.exception("Error loading hook config %s", yaml_file)
        return loaded


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _import_handler(dotted_path: str) -> Callable | None:
    """Import a callable from a dotted module path like 'hooks.builtin.audit_log_hook'."""
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        return None
    module_path, attr_name = parts
    try:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name, None)
    except (ImportError, AttributeError):
        return None


def build_tool_context(
    tool_name: str,
    tool_args: dict,
    agent_name: str = "",
    result: Any = None,
) -> dict:
    """Build a standard context dict for tool-related hook events."""
    ctx: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "agent_name": agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if result is not None:
        ctx["result"] = result
    return ctx

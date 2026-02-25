"""Session Brain tools for the Chief of Staff MCP server."""

import json
import logging
import sys

logger = logging.getLogger("jarvis-mcp")

_state_ref = None


def _get_brain():
    if _state_ref and _state_ref.session_brain:
        return _state_ref.session_brain
    return None


def register(mcp, state):
    global _state_ref
    _state_ref = state

    @mcp.tool()
    async def get_session_brain() -> str:
        """Get the current Session Brain -- persistent cross-session context.

        Returns the full brain state: active workstreams, open action items,
        recent decisions, key people context, and session handoff notes.
        """
        brain = _get_brain()
        if brain is None:
            return json.dumps({"error": "Session brain not initialized"})
        brain.load()
        return json.dumps(brain.to_dict())

    @mcp.tool()
    async def update_session_brain(action: str, data: str) -> str:
        """Update the Session Brain with new information.

        Args:
            action: One of: add_workstream, update_workstream, add_action_item,
                    complete_action_item, add_decision, add_person, add_handoff_note
            data: JSON string with action-specific fields:
                - add_workstream: {"name", "status", "context"}
                - add_action_item: {"text", "source"?}
                - complete_action_item: {"text"}
                - add_decision: {"summary"}
                - add_person: {"name", "context"}
                - add_handoff_note: {"note"}
        """
        brain = _get_brain()
        if brain is None:
            return json.dumps({"error": "Session brain not initialized"})

        try:
            params = json.loads(data)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in data: {e}"})

        actions = {
            "add_workstream": lambda p: brain.add_workstream(p["name"], p["status"], p["context"]),
            "update_workstream": lambda p: brain.update_workstream(p["name"], status=p["status"], context=p["context"]),
            "add_action_item": lambda p: brain.add_action_item(p["text"], source=p.get("source", "")),
            "complete_action_item": lambda p: brain.complete_action_item(p["text"]),
            "add_decision": lambda p: brain.add_decision(p["summary"]),
            "add_person": lambda p: brain.add_person(p["name"], p["context"]),
            "add_handoff_note": lambda p: brain.add_handoff_note(p["note"]),
        }

        handler = actions.get(action)
        if handler is None:
            return json.dumps({"error": f"Unknown action: {action}. Valid: {list(actions.keys())}"})

        try:
            handler(params)
            brain.save()
            return json.dumps({"status": "updated", "action": action})
        except (KeyError, TypeError) as e:
            return json.dumps({"error": f"Missing required field: {e}"})

    module = sys.modules[__name__]
    module.get_session_brain = get_session_brain
    module.update_session_brain = update_session_brain

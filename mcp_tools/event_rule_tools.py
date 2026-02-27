"""Event rule tools for the Chief of Staff MCP server.

Manages event rules that link webhook events to expert agent activation.
"""

import json
import logging

from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register event rule tools with the FastMCP server."""

    @mcp.tool()
    async def create_event_rule(
        name: str,
        event_source: str,
        event_type_pattern: str,
        agent_name: str,
        description: str = "",
        agent_input_template: str = "",
        delivery_channel: str = "",
        delivery_config: str = "",
        enabled: bool = True,
        priority: int = 100,
    ) -> str:
        """Create an event rule that triggers an agent when a matching webhook event arrives.

        Args:
            name: Unique name for this rule (required)
            event_source: Source to match (e.g. "github", "jira") (required)
            event_type_pattern: Glob pattern for event types (e.g. "alert.*", "incident.critical") (required)
            agent_name: Name of the expert agent to activate (required)
            description: Human-readable description of what this rule does
            agent_input_template: Template for agent input with $event_type, $source, $payload, $timestamp vars
            delivery_channel: Delivery channel for results (email, imessage, notification)
            delivery_config: JSON config for the delivery channel
            enabled: Whether the rule is active (default: True)
            priority: Priority for rule ordering (lower = higher priority, default: 100)
        """
        memory_store = state.memory_store
        # Validate agent exists
        agent_registry = state.agent_registry
        if agent_registry and not agent_registry.agent_exists(agent_name):
            return json.dumps({"error": f"Agent '{agent_name}' not found in registry"})

        try:
            rule = _retry_on_transient(
                memory_store.create_event_rule,
                name=name,
                event_source=event_source,
                event_type_pattern=event_type_pattern,
                agent_name=agent_name,
                description=description,
                agent_input_template=agent_input_template,
                delivery_channel=delivery_channel or None,
                delivery_config=delivery_config or None,
                enabled=enabled,
                priority=priority,
            )
            return json.dumps(rule)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def update_event_rule(
        rule_id: int,
        name: str = "",
        event_source: str = "",
        event_type_pattern: str = "",
        agent_name: str = "",
        description: str = "",
        agent_input_template: str = "",
        delivery_channel: str = "",
        delivery_config: str = "",
        enabled: bool = True,
        priority: int = -1,
    ) -> str:
        """Update an existing event rule.

        Args:
            rule_id: The ID of the event rule to update (required)
            name: New name for the rule
            event_source: New event source filter
            event_type_pattern: New glob pattern for event types
            agent_name: New agent to activate
            description: New description
            agent_input_template: New input template
            delivery_channel: New delivery channel
            delivery_config: New delivery config (JSON string)
            enabled: Whether the rule is active
            priority: New priority value (-1 means no change)
        """
        memory_store = state.memory_store
        kwargs = {}
        if name:
            kwargs["name"] = name
        if event_source:
            kwargs["event_source"] = event_source
        if event_type_pattern:
            kwargs["event_type_pattern"] = event_type_pattern
        if agent_name:
            kwargs["agent_name"] = agent_name
        if description:
            kwargs["description"] = description
        if agent_input_template:
            kwargs["agent_input_template"] = agent_input_template
        if delivery_channel:
            kwargs["delivery_channel"] = delivery_channel
        if delivery_config:
            kwargs["delivery_config"] = delivery_config
        # enabled is always passed since it's a bool with a default
        kwargs["enabled"] = enabled
        if priority >= 0:
            kwargs["priority"] = priority

        try:
            result = _retry_on_transient(
                memory_store.update_event_rule, rule_id, **kwargs
            )
            if result is None:
                return json.dumps({"error": f"Event rule {rule_id} not found"})
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def delete_event_rule(rule_id: int) -> str:
        """Delete an event rule by ID.

        Args:
            rule_id: The ID of the event rule to delete
        """
        memory_store = state.memory_store
        result = _retry_on_transient(memory_store.delete_event_rule, rule_id)
        return json.dumps(result)

    @mcp.tool()
    async def list_event_rules(enabled_only: bool = True) -> str:
        """List event rules.

        Args:
            enabled_only: If True, only return enabled rules (default: True)
        """
        memory_store = state.memory_store
        rules = _retry_on_transient(
            memory_store.list_event_rules, enabled_only=enabled_only
        )
        return json.dumps({"rules": rules, "count": len(rules)})

    @mcp.tool()
    async def process_webhook_event_with_agents(event_id: int) -> str:
        """Manually trigger agent dispatch for a specific webhook event.

        Finds matching event rules and dispatches the event to the corresponding agents.

        Args:
            event_id: The ID of the webhook event to process
        """
        memory_store = state.memory_store
        event = _retry_on_transient(memory_store.get_webhook_event, event_id)
        if event is None:
            return json.dumps({"error": f"Webhook event {event_id} not found"})

        from config import MAX_CONCURRENT_AGENT_DISPATCHES
        from webhook.dispatcher import EventDispatcher
        dispatcher = EventDispatcher(
            agent_registry=state.agent_registry,
            memory_store=memory_store,
            document_store=state.document_store,
            parallel=True,
            max_concurrent=MAX_CONCURRENT_AGENT_DISPATCHES,
        )
        results = await dispatcher.dispatch(event)

        # Update event status based on results
        if results:
            all_success = all(r["status"] == "success" for r in results)
            new_status = "processed" if all_success else "failed"
        else:
            new_status = "processed"  # No matching rules is not an error
        _retry_on_transient(
            memory_store.update_webhook_event_status, event_id, new_status
        )

        return json.dumps({
            "event_id": event_id,
            "rules_matched": len(results),
            "dispatches": results,
            "event_status": new_status,
        })

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.create_event_rule = create_event_rule
    module.update_event_rule = update_event_rule
    module.delete_event_rule = delete_event_rule
    module.list_event_rules = list_event_rules
    module.process_webhook_event_with_agents = process_webhook_event_with_agents

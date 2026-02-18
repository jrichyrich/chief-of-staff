"""Decision log, delegation tracking, and alert tools for the Chief of Staff MCP server."""

import json

from tools import lifecycle as lifecycle_tools


def register(mcp, state):
    """Register lifecycle tools with the FastMCP server."""

    # --- Decision Log Tools ---

    @mcp.tool()
    async def create_decision(
        title: str,
        description: str = "",
        context: str = "",
        decided_by: str = "",
        owner: str = "",
        status: str = "pending_execution",
        follow_up_date: str = "",
        tags: str = "",
        source: str = "",
    ) -> str:
        """Log a decision for tracking and follow-up.

        Args:
            title: Short title of the decision (required)
            description: Detailed description of what was decided
            context: Background context or rationale
            decided_by: Who made the decision
            owner: Who is responsible for execution
            status: Decision status (default: pending_execution)
            follow_up_date: Date to follow up (YYYY-MM-DD)
            tags: Comma-separated tags for categorization
            source: Where the decision was made (e.g. meeting name, email)
        """
        memory_store = state.memory_store
        result = lifecycle_tools.create_decision(
            memory_store,
            title=title,
            description=description,
            context=context,
            decided_by=decided_by,
            owner=owner,
            status=status,
            follow_up_date=follow_up_date,
            tags=tags,
            source=source,
        )
        return json.dumps(result)

    @mcp.tool()
    async def search_decisions(query: str = "", status: str = "") -> str:
        """Search decisions by text and/or filter by status.

        Args:
            query: Text to search in title, description, and tags
            status: Filter by decision status (e.g. pending_execution, executed, deferred)
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.search_decisions(memory_store, query=query, status=status))

    @mcp.tool()
    async def update_decision(decision_id: int, status: str = "", notes: str = "") -> str:
        """Update a decision's status or add notes.

        Args:
            decision_id: The ID of the decision to update
            status: New status value
            notes: Additional notes to append to the description
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.update_decision(memory_store, decision_id=decision_id, status=status, notes=notes))

    @mcp.tool()
    async def list_pending_decisions() -> str:
        """List all decisions with status 'pending_execution'."""
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.list_pending_decisions(memory_store))

    @mcp.tool()
    async def delete_decision(decision_id: int) -> str:
        """Delete a decision by ID.

        Args:
            decision_id: The ID of the decision to delete
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.delete_decision(memory_store, decision_id=decision_id))

    # --- Delegation Tracker Tools ---

    @mcp.tool()
    async def create_delegation(
        task: str,
        delegated_to: str,
        description: str = "",
        due_date: str = "",
        priority: str = "medium",
        source: str = "",
    ) -> str:
        """Create a new delegation to track a task assigned to someone.

        Args:
            task: Short description of the delegated task (required)
            delegated_to: Who the task is delegated to (required)
            description: Detailed description of expectations
            due_date: Due date (YYYY-MM-DD)
            priority: Priority level (low, medium, high, critical)
            source: Where the delegation originated
        """
        memory_store = state.memory_store
        result = lifecycle_tools.create_delegation(
            memory_store,
            task=task,
            delegated_to=delegated_to,
            description=description,
            due_date=due_date,
            priority=priority,
            source=source,
        )
        return json.dumps(result)

    @mcp.tool()
    async def list_delegations(status: str = "", delegated_to: str = "") -> str:
        """List delegations with optional filters.

        Args:
            status: Filter by status (active, completed, cancelled)
            delegated_to: Filter by who the task is delegated to
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.list_delegations(memory_store, status=status, delegated_to=delegated_to))

    @mcp.tool()
    async def update_delegation(delegation_id: int, status: str = "", notes: str = "") -> str:
        """Update a delegation's status or add notes.

        Args:
            delegation_id: The ID of the delegation to update
            status: New status value (active, completed, cancelled)
            notes: Additional notes
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.update_delegation(memory_store, delegation_id=delegation_id, status=status, notes=notes))

    @mcp.tool()
    async def check_overdue_delegations() -> str:
        """Return all active delegations that are past their due date."""
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.check_overdue_delegations(memory_store))

    @mcp.tool()
    async def delete_delegation(delegation_id: int) -> str:
        """Delete a delegation by ID.

        Args:
            delegation_id: The ID of the delegation to delete
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.delete_delegation(memory_store, delegation_id=delegation_id))

    # --- Alert Tools ---

    @mcp.tool()
    async def create_alert_rule(
        name: str,
        alert_type: str,
        description: str = "",
        condition: str = "",
        enabled: bool = True,
    ) -> str:
        """Create or update an alert rule.

        Args:
            name: Unique name for the alert rule (required)
            alert_type: Type of alert: overdue_delegation, pending_decision, upcoming_deadline (required)
            description: Human-readable description of what this alert checks
            condition: Machine-readable condition expression
            enabled: Whether the rule is active (default: True)
        """
        memory_store = state.memory_store
        return json.dumps(
            lifecycle_tools.create_alert_rule(
                memory_store,
                name=name,
                alert_type=alert_type,
                description=description,
                condition=condition,
                enabled=enabled,
            )
        )

    @mcp.tool()
    async def list_alert_rules(enabled_only: bool = False) -> str:
        """List all alert rules.

        Args:
            enabled_only: If True, only return enabled rules
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.list_alert_rules(memory_store, enabled_only=enabled_only))

    @mcp.tool()
    async def check_alerts() -> str:
        """Run alert checks: overdue delegations, stale pending decisions (>7 days), and upcoming deadlines (within 3 days)."""
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.check_alerts(memory_store))

    @mcp.tool()
    async def dismiss_alert(rule_id: int) -> str:
        """Disable an alert rule so it no longer triggers.

        Args:
            rule_id: The ID of the alert rule to disable
        """
        memory_store = state.memory_store
        return json.dumps(lifecycle_tools.dismiss_alert(memory_store, rule_id=rule_id))

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.create_decision = create_decision
    module.search_decisions = search_decisions
    module.update_decision = update_decision
    module.list_pending_decisions = list_pending_decisions
    module.delete_decision = delete_decision
    module.create_delegation = create_delegation
    module.list_delegations = list_delegations
    module.update_delegation = update_delegation
    module.check_overdue_delegations = check_overdue_delegations
    module.delete_delegation = delete_delegation
    module.create_alert_rule = create_alert_rule
    module.list_alert_rules = list_alert_rules
    module.check_alerts = check_alerts
    module.dismiss_alert = dismiss_alert

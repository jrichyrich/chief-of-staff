"""Playbook tools for the Chief of Staff MCP server."""

import json
import logging
import sys
from pathlib import Path

import config as app_config

logger = logging.getLogger("jarvis-mcp")


def _get_loader_dir() -> Path:
    return app_config.PLAYBOOKS_DIR


def register(mcp, state):
    """Register playbook tools with the FastMCP server."""

    @mcp.tool()
    async def list_playbooks() -> str:
        """List all available team playbooks.

        Playbooks define parallel workstreams that fan out across multiple
        data sources and agents, then synthesize results.
        """
        from playbooks.loader import PlaybookLoader
        loader = PlaybookLoader(_get_loader_dir())
        names = loader.list_playbooks()
        descriptions = {}
        for name in names:
            pb = loader.get_playbook(name)
            if pb:
                descriptions[name] = pb.description
        return json.dumps({
            "playbooks": names,
            "descriptions": descriptions,
            "count": len(names),
        })

    @mcp.tool()
    async def get_playbook(name: str) -> str:
        """Get details of a specific playbook including its workstreams and inputs.

        Args:
            name: The playbook name (e.g. "meeting_prep", "expert_research")
        """
        from playbooks.loader import PlaybookLoader
        loader = PlaybookLoader(_get_loader_dir())
        pb = loader.get_playbook(name)
        if pb is None:
            return json.dumps({"error": f"Playbook '{name}' not found"})
        return json.dumps({
            "name": pb.name,
            "description": pb.description,
            "inputs": pb.inputs,
            "workstreams": [
                {"name": ws.name, "prompt": ws.prompt, "condition": ws.condition}
                for ws in pb.workstreams
            ],
            "synthesis_prompt": pb.synthesis_prompt,
            "delivery_default": pb.delivery_default,
            "delivery_options": pb.delivery_options,
        })

    @mcp.tool()
    async def execute_playbook(
        name: str,
        inputs: str = "{}",
        context: str = "{}",
        delivery: str = "",
    ) -> str:
        """Execute a playbook: dispatch workstreams in parallel, synthesize results.

        Loads the named playbook, substitutes input variables, runs all active
        workstreams concurrently via expert agents, then synthesizes results
        using a Haiku merge pass.

        Args:
            name: Playbook name (e.g. "daily_briefing", "meeting_prep")
            inputs: JSON string of input values (e.g. '{"topic": "Q4 review"}')
            context: JSON string of context for condition evaluation (e.g. '{"depth": "thorough"}')
            delivery: Override delivery channel ("email", "inline", etc.). Empty = playbook default.
        """
        from playbooks.loader import PlaybookLoader
        from orchestration.playbook_executor import execute_playbook as _execute

        loader = PlaybookLoader(_get_loader_dir())
        pb = loader.get_playbook(name)
        if pb is None:
            return json.dumps({"error": f"Playbook '{name}' not found"})

        # Parse inputs and context
        try:
            input_values = json.loads(inputs) if isinstance(inputs, str) else inputs
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid inputs JSON: {inputs}"})

        try:
            ctx = json.loads(context) if isinstance(context, str) else context
        except json.JSONDecodeError:
            ctx = {}

        # Check for missing required inputs (warn but proceed)
        missing = [i for i in pb.inputs if i not in input_values]

        # Resolve input variables
        resolved = pb.resolve_inputs(input_values)

        # Execute
        result = await _execute(
            playbook=resolved,
            agent_registry=state.agent_registry,
            state=state,
            context=ctx if ctx else None,
        )

        if missing:
            result["warning"] = f"Missing inputs (used as literals): {', '.join(missing)}"

        # Delivery override
        channel = delivery or resolved.delivery_default
        if channel and channel != "inline" and result.get("synthesized_summary"):
            try:
                from delivery.service import deliver_result
                delivery_result = deliver_result(
                    channel=channel,
                    config={},
                    result_text=result["synthesized_summary"],
                    task_name=f"playbook_{name}",
                )
                result["delivery"] = delivery_result
            except Exception as e:
                result["delivery"] = {"status": "error", "error": str(e)}

        return json.dumps(result)

    module = sys.modules[__name__]
    module.list_playbooks = list_playbooks
    module.get_playbook = get_playbook
    module.execute_playbook = execute_playbook

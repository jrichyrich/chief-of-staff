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

    module = sys.modules[__name__]
    module.list_playbooks = list_playbooks
    module.get_playbook = get_playbook

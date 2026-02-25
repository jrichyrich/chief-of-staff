"""Channel routing tools for the Chief of Staff MCP server."""

import json
import logging
import sys

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register channel routing tools with the FastMCP server."""

    @mcp.tool()
    async def route_message(
        recipient_type: str,
        urgency: str = "informational",
        sensitive: bool = False,
        first_contact: bool = False,
        override: str = "",
    ) -> str:
        """Determine the safety tier and delivery channel for an outbound message.

        Use this before sending any message to determine whether it should be
        auto-sent, confirmed first, or left as a draft for the user.

        Args:
            recipient_type: "self", "internal", or "external"
            urgency: "urgent", "informational", "formal", "informal", "ephemeral"
            sensitive: True if topic involves legal, HR, security, financial, etc.
            first_contact: True if this is the first message to this recipient
            override: Explicit tier override: "auto", "confirm", or "draft_only"
        """
        from channels.routing import (
            determine_safety_tier,
            is_work_hours,
            select_channel,
        )

        tier = determine_safety_tier(
            recipient_type=recipient_type,
            sensitive=sensitive,
            first_contact=first_contact,
            override=override or None,
        )
        channel = select_channel(
            recipient_type=recipient_type,
            urgency=urgency,
            work_hours=is_work_hours(),
        )

        return json.dumps({
            "safety_tier": tier.name.lower(),
            "channel": channel,
            "recipient_type": recipient_type,
            "urgency": urgency,
            "work_hours": is_work_hours(),
        })

    module = sys.modules[__name__]
    module.route_message = route_message

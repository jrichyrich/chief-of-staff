"""Execute iMessage instructions via Claude API with Jarvis tool schemas."""

from __future__ import annotations

import logging
from typing import Any

from config import DEFAULT_MODEL, MODEL_TIERS

logger = logging.getLogger(__name__)

# System prompt for iMessage command processing
SYSTEM_PROMPT = (
    "You are Jarvis, an AI chief of staff assistant. You received an iMessage "
    "instruction from your user. Execute the request using the tools available "
    "to you and respond with a concise result suitable for an iMessage reply "
    "(keep under 500 characters when possible).\n\n"
    "If the instruction is unclear or you cannot complete it, explain what you "
    "need in a brief reply."
)

MAX_TOOL_ROUNDS = 10  # Lower than interactive to limit async costs


class IMessageExecutor:
    """Executes an iMessage instruction via Claude API tool-use loop."""

    def __init__(
        self,
        client: Any = None,
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_handlers: dict[str, Any] | None = None,
    ):
        self.client = client
        self.model = model or MODEL_TIERS.get("sonnet", DEFAULT_MODEL)
        self.tools = tools or []
        self.tool_handlers = tool_handlers or {}

    async def execute(self, instruction: str) -> str:
        """Send instruction to Claude, run tool-use loop, return text result."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]

        for _ in range(MAX_TOOL_ROUNDS):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 2048,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            }
            if self.tools:
                kwargs["tools"] = self.tools

            response = await self.client.messages.create(**kwargs)

            if response.stop_reason != "tool_use":
                # Extract text from response
                texts = [b.text for b in response.content if b.type == "text"]
                return "\n".join(texts) if texts else "(no response)"

            # Handle tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    handler = self.tool_handlers.get(block.name)
                    if handler:
                        try:
                            result = await handler(**block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(result),
                            })
                        except Exception as e:
                            logger.error("Tool %s failed: %s", block.name, e)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Error: {e}",
                                "is_error": True,
                            })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Tool '{block.name}' not available in async mode.",
                            "is_error": True,
                        })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        return "(max tool rounds exceeded — partial result)"

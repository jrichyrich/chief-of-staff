"""Event-driven agent dispatcher for webhook events.

When a webhook event arrives and matches an event rule, the dispatcher
loads the corresponding agent, formats the input from the rule's template,
executes the agent, and optionally delivers the result.

One agent failure never blocks other rule dispatches.
"""

from __future__ import annotations

import json
import logging
import time
from string import Template
from typing import Optional

from agents.triage import classify_and_resolve

logger = logging.getLogger("jarvis-event-dispatcher")


class EventDispatcher:
    """Dispatches webhook events to matching expert agents."""

    def __init__(
        self,
        agent_registry,
        memory_store,
        document_store=None,
        delivery_fn=None,
    ):
        """
        Args:
            agent_registry: AgentRegistry instance for loading agent configs.
            memory_store: MemoryStore instance for matching rules and updating events.
            document_store: DocumentStore instance passed to agents.
            delivery_fn: Optional callable(channel, config, result_text, task_name) -> dict.
                         Defaults to scheduler.delivery.deliver_result if not provided.
        """
        self.agent_registry = agent_registry
        self.memory_store = memory_store
        self.document_store = document_store
        self._delivery_fn = delivery_fn

    def _get_delivery_fn(self):
        if self._delivery_fn is not None:
            return self._delivery_fn
        from scheduler.delivery import deliver_result
        return deliver_result

    async def dispatch(self, webhook_event) -> list[dict]:
        """Dispatch a webhook event to all matching event rules.

        Args:
            webhook_event: A WebhookEvent (or dict-like) with source, event_type, payload, id.

        Returns:
            List of dispatch result dicts, one per matched rule.
        """
        source = webhook_event.source if hasattr(webhook_event, "source") else webhook_event["source"]
        event_type = webhook_event.event_type if hasattr(webhook_event, "event_type") else webhook_event["event_type"]
        payload = webhook_event.payload if hasattr(webhook_event, "payload") else webhook_event.get("payload", "")
        event_id = webhook_event.id if hasattr(webhook_event, "id") else webhook_event.get("id")
        received_at = ""
        if hasattr(webhook_event, "received_at"):
            received_at = webhook_event.received_at or ""

        matched_rules = self.memory_store.match_event_rules(source, event_type)
        if not matched_rules:
            logger.info("No matching event rules for source=%s type=%s", source, event_type)
            return []

        results = []
        for rule in matched_rules:
            result = await self._dispatch_single(rule, source, event_type, payload, received_at)
            results.append(result)

        return results

    async def _dispatch_single(
        self,
        rule: dict,
        source: str,
        event_type: str,
        payload: str,
        timestamp: str,
    ) -> dict:
        """Execute a single rule dispatch. Catches all exceptions."""
        agent_name = rule["agent_name"]
        rule_name = rule["name"]
        start = time.monotonic()

        try:
            # Load agent config
            agent_config = self.agent_registry.get_agent(agent_name)
            if agent_config is None:
                return {
                    "rule_name": rule_name,
                    "agent_name": agent_name,
                    "status": "error",
                    "result_text": f"Agent '{agent_name}' not found in registry",
                    "duration_seconds": round(time.monotonic() - start, 3),
                    "delivery_status": None,
                }

            # Format the agent input
            agent_input = self._format_input(
                rule.get("agent_input_template", ""),
                source,
                event_type,
                payload,
                timestamp,
            )

            # Triage: classify complexity and potentially downgrade model
            try:
                effective_config = classify_and_resolve(agent_config, agent_input)
            except Exception:
                effective_config = agent_config

            # Execute the agent
            from agents.base import BaseExpertAgent
            agent = BaseExpertAgent(
                config=effective_config,
                memory_store=self.memory_store,
                document_store=self.document_store,
            )
            result_text = await agent.execute(agent_input)

            duration = round(time.monotonic() - start, 3)

            # Deliver result if delivery channel configured
            delivery_status = None
            delivery_channel = rule.get("delivery_channel")
            if delivery_channel:
                delivery_config_raw = rule.get("delivery_config")
                delivery_config = {}
                if delivery_config_raw:
                    try:
                        delivery_config = json.loads(delivery_config_raw) if isinstance(delivery_config_raw, str) else delivery_config_raw
                    except (json.JSONDecodeError, TypeError):
                        pass
                try:
                    deliver = self._get_delivery_fn()
                    delivery_status = deliver(
                        delivery_channel,
                        delivery_config,
                        result_text,
                        task_name=rule_name,
                    )
                except Exception as e:
                    logger.error("Delivery failed for rule '%s': %s", rule_name, e)
                    delivery_status = {"status": "error", "error": str(e)}

            logger.info(
                "Dispatched rule='%s' agent='%s' status=success duration=%.3fs",
                rule_name, agent_name, duration,
            )

            return {
                "rule_name": rule_name,
                "agent_name": agent_name,
                "status": "success",
                "result_text": result_text,
                "duration_seconds": duration,
                "delivery_status": delivery_status,
            }

        except Exception as e:
            duration = round(time.monotonic() - start, 3)
            logger.error(
                "Dispatch failed for rule='%s' agent='%s': %s",
                rule_name, agent_name, e,
            )
            return {
                "rule_name": rule_name,
                "agent_name": agent_name,
                "status": "error",
                "result_text": str(e),
                "duration_seconds": duration,
                "delivery_status": None,
            }

    @staticmethod
    def _format_input(
        template_str: str,
        source: str,
        event_type: str,
        payload: str,
        timestamp: str,
    ) -> str:
        """Format the agent input using string.Template substitution.

        Template variables: $event_type, $source, $payload, $timestamp
        Falls back to a default prompt if template is empty.
        """
        if not template_str:
            template_str = (
                "A webhook event was received.\n"
                "Source: $source\n"
                "Event type: $event_type\n"
                "Timestamp: $timestamp\n"
                "Payload:\n$payload"
            )
        return Template(template_str).safe_substitute(
            event_type=event_type,
            source=source,
            payload=payload,
            timestamp=timestamp,
        )

"""dispatch_agents — parallel multi-agent orchestrator MCP tool."""

import asyncio
import json
import logging
import time

logger = logging.getLogger("jarvis-dispatch")


def register(mcp, state):
    """Register dispatch tools with the MCP server."""

    @mcp.tool()
    async def dispatch_agents(
        task: str,
        agent_names: str = "",
        capability_match: str = "",
        max_concurrent: int = 0,
        use_triage: bool = True,
        synthesize: bool = False,
    ) -> str:
        """Dispatch multiple expert agents in parallel on a task and return consolidated results.

        Selects agents by name, capability, or auto-detection, runs them concurrently
        with asyncio.gather, and returns all results. One agent failure never blocks others.

        Args:
            task: The task or query for the agents to work on (required, max 5000 chars)
            agent_names: Comma-separated agent names to dispatch (e.g. "researcher,analyst").
                        If empty and capability_match is empty, auto-selects agents.
            capability_match: Comma-separated capability names to filter agents by.
                            Only agents with ALL listed capabilities are selected.
                            (e.g. "memory_read,document_search")
            max_concurrent: Max concurrent agent executions (0 = use config default).
            use_triage: If True, classify task complexity per agent and potentially
                       downgrade model tier for simple tasks (default True).
            synthesize: If True and DISPATCH_SYNTHESIS_ENABLED config is set, run a
                       Haiku merge pass to synthesize multi-agent results into a
                       coherent summary (default False).
        """
        import config as app_config
        from agents.registry import AgentConfig

        # --- Validation ---
        if not task or not task.strip():
            return json.dumps({"error": "Task is required and cannot be empty"})

        task = task[:5000]  # Hard cap on input length

        agent_registry = state.agent_registry
        if agent_registry is None:
            return json.dumps({"error": "Agent registry not available"})

        # --- Agent selection ---
        selected_configs: list[AgentConfig] = []
        skipped: list[str] = []

        if agent_names:
            # Mode A: Explicit agent names
            names = [n.strip() for n in agent_names.split(",") if n.strip()]
            for name in names:
                try:
                    config = agent_registry.get_agent(name)
                except ValueError:
                    skipped.append(name)
                    logger.warning("dispatch_agents: invalid agent name '%s', skipping", name)
                    continue
                if config is None:
                    skipped.append(name)
                    logger.warning("dispatch_agents: agent '%s' not found, skipping", name)
                else:
                    selected_configs.append(config)

        elif capability_match:
            # Mode B: Capability matching
            requested_caps = {c.strip() for c in capability_match.split(",") if c.strip()}
            for config in agent_registry.list_agents():
                agent_caps = set(config.capabilities)
                if requested_caps.issubset(agent_caps):
                    selected_configs.append(config)
            if not selected_configs:
                return json.dumps({
                    "error": f"No agents found matching capabilities: {', '.join(sorted(requested_caps))}",
                })

        else:
            # Mode C: Auto-select (agents with non-empty capabilities, sorted by name)
            for config in agent_registry.list_agents():
                if config.capabilities:
                    selected_configs.append(config)
            selected_configs.sort(key=lambda c: c.name)
            selected_configs = selected_configs[:5]  # Auto-select capped at 5

        if not selected_configs:
            return json.dumps({
                "error": "No valid agents to dispatch",
                "agents_skipped": skipped,
                "dispatches": [],
            })

        # --- Apply hard cap ---
        max_agents = getattr(app_config, "DISPATCH_AGENTS_MAX_AGENTS", 10)
        if len(selected_configs) > max_agents:
            logger.warning(
                "dispatch_agents: %d agents selected, capping at %d",
                len(selected_configs), max_agents,
            )
            selected_configs = selected_configs[:max_agents]

        dispatched_names = [c.name for c in selected_configs]
        max_result_len = getattr(app_config, "DISPATCH_AGENTS_MAX_RESULT_LENGTH", 5000)

        # --- Single agent dispatch helper ---
        async def _dispatch_single(config: AgentConfig) -> dict:
            start = time.monotonic()
            try:
                effective_config = config
                if use_triage:
                    try:
                        from agents.triage import classify_and_resolve
                        effective_config = await asyncio.to_thread(
                            classify_and_resolve, config, task
                        )
                    except Exception as e:
                        logger.debug("dispatch_agents: triage failed for '%s': %s", config.name, e)
                        effective_config = config

                from agents.base import BaseExpertAgent
                agent = BaseExpertAgent(
                    config=effective_config,
                    memory_store=state.memory_store,
                    document_store=state.document_store,
                    calendar_store=getattr(state, "calendar_store", None),
                    reminder_store=getattr(state, "reminder_store", None),
                    mail_store=getattr(state, "mail_store", None),
                    hook_registry=getattr(state, "hook_registry", None),
                    agent_browser=getattr(state, "agent_browser", None),
                )
                result_text = await agent.execute(task)
                duration = round(time.monotonic() - start, 3)

                # Truncate long results
                display_text = str(result_text)
                if len(display_text) > max_result_len:
                    display_text = display_text[:max_result_len] + "... [truncated]"

                # Reflect agent-reported status if available (AgentResult)
                agent_status = "success"
                if hasattr(result_text, "is_error") and result_text.is_error:
                    agent_status = getattr(result_text, "status", "error")

                return {
                    "agent_name": config.name,
                    "status": agent_status,
                    "result": display_text,
                    "duration_seconds": duration,
                    "model_used": effective_config.model,
                }
            except Exception as e:
                duration = round(time.monotonic() - start, 3)
                error_type = type(e).__name__
                logger.error("dispatch_agents: agent '%s' failed: %s", config.name, e)
                return {
                    "agent_name": config.name,
                    "status": "error",
                    "result": f"Agent execution failed ({error_type})",
                    "duration_seconds": duration,
                    "model_used": config.model,
                }

        # --- Parallel dispatch ---
        total_start = time.monotonic()

        config_max = getattr(app_config, "MAX_CONCURRENT_AGENT_DISPATCHES", 5)
        conc_limit = max_concurrent if max_concurrent > 0 else config_max
        conc_limit = min(conc_limit, config_max)  # Never exceed config ceiling

        wall_clock_timeout = getattr(app_config, "DISPATCH_AGENTS_WALL_CLOCK_TIMEOUT", 300)

        if len(selected_configs) > 1 and conc_limit > 0:
            semaphore = asyncio.Semaphore(conc_limit)

            async def _limited(config):
                async with semaphore:
                    return await _dispatch_single(config)

            gather_coro = asyncio.gather(
                *[_limited(c) for c in selected_configs],
                return_exceptions=True,
            )
        else:
            gather_coro = asyncio.gather(
                *[_dispatch_single(c) for c in selected_configs],
                return_exceptions=True,
            )

        try:
            raw_results = await asyncio.wait_for(gather_coro, timeout=wall_clock_timeout)
        except asyncio.TimeoutError:
            total_duration = round(time.monotonic() - total_start, 3)
            return json.dumps({
                "error": f"Dispatch timed out after {wall_clock_timeout}s",
                "task": task[:200],
                "agents_dispatched": dispatched_names,
                "agents_skipped": skipped,
                "dispatches": [],
                "total_duration_seconds": total_duration,
            })

        # Post-process: convert bare exceptions from return_exceptions=True into error dicts
        dispatches = []
        for i, result in enumerate(raw_results):
            if isinstance(result, BaseException):
                error_type = type(result).__name__
                dispatches.append({
                    "agent_name": selected_configs[i].name,
                    "status": "error",
                    "result": f"Agent execution failed ({error_type})",
                    "duration_seconds": 0,
                    "model_used": selected_configs[i].model,
                })
            else:
                dispatches.append(result)

        total_duration = round(time.monotonic() - total_start, 3)

        success_count = sum(1 for d in dispatches if d["status"] == "success")
        error_count = sum(1 for d in dispatches if d["status"] == "error")

        # --- Optional synthesis ---
        synthesized = None
        if synthesize and getattr(app_config, "DISPATCH_SYNTHESIS_ENABLED", False):
            if success_count >= 1:
                try:
                    from orchestration.synthesis import synthesize_results
                    synthesized = await synthesize_results(
                        task=task,
                        dispatches=dispatches,
                    )
                except Exception as e:
                    logger.warning("dispatch_agents: synthesis failed: %s", e)

        result_dict = {
            "task": task[:200],
            "agents_dispatched": dispatched_names,
            "agents_skipped": skipped,
            "dispatches": dispatches,
            "total_duration_seconds": total_duration,
            "summary": f"Dispatched {len(dispatches)} agents: {success_count} succeeded, {error_count} failed.",
        }
        if synthesized is not None:
            result_dict["synthesized_summary"] = synthesized

        return json.dumps(result_dict)

    # Expose at module level for testing
    import sys
    module = sys.modules[__name__]
    module.dispatch_agents = dispatch_agents

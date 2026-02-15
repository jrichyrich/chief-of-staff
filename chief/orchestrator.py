# chief/orchestrator.py
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import anthropic

logger = logging.getLogger("chief-of-staff")

MAX_TOOL_ROUNDS = 25

import config as app_config
from agents.base import BaseExpertAgent
from agents.registry import AgentConfig, AgentRegistry
from chief.dispatcher import AgentDispatcher
from documents.store import DocumentStore
from memory.models import Decision, Delegation
from memory.store import MemoryStore
from tools.definitions import get_chief_tools
from tools.executor import execute_query_memory, execute_store_memory, execute_search_documents
from utils.retry import retry_api_call

CHIEF_SYSTEM_PROMPT = """You are the Chief of Staff, an AI orchestrator that manages a team of expert agents.

Your responsibilities:
1. Understand user requests and decide the best way to handle them
2. Check shared memory for relevant context about the user
3. Delegate tasks to expert agents when specialized knowledge is needed
4. Create new expert agents when no existing agent has the right expertise
5. Dispatch multiple agents in parallel when a task benefits from multiple perspectives
6. Synthesize results from multiple agents into coherent responses
7. Store important facts and details in shared memory for future reference

Always check memory first for context. When you learn new facts about the user (name, preferences, etc.), store them.

Effort scaling — match agent dispatch to task complexity:
- Simple factual lookups or single-domain questions: handle directly or dispatch 1 agent
- Comparisons or multi-faceted questions: dispatch 2-4 agents in parallel
- Complex multi-source research or comprehensive analysis: dispatch 5+ agents

Task delegation — each agent task must include:
- A clear, specific objective (not vague "research this")
- Expected output format or structure
- Relevant context from the conversation so far

Result synthesis — after receiving agent results:
- Identify overlaps, conflicts, and gaps across responses
- Cite which agent provided which information when relevant
- Present a unified, coherent synthesis rather than listing agent outputs verbatim"""


class ChiefOfStaff:
    def __init__(
        self,
        memory_store: MemoryStore,
        document_store: DocumentStore,
        agent_registry: AgentRegistry,
        calendar_store=None,
        reminder_store=None,
        notifier=None,
        mail_store=None,
    ):
        self.memory_store = memory_store
        self.document_store = document_store
        self.agent_registry = agent_registry
        self.calendar_store = calendar_store
        self.reminder_store = reminder_store
        self.notifier = notifier
        self.mail_store = mail_store
        self.dispatcher = AgentDispatcher(timeout_seconds=app_config.AGENT_TIMEOUT_SECONDS)
        self.client = anthropic.AsyncAnthropic(api_key=app_config.ANTHROPIC_API_KEY)
        self.conversation_history: list[dict] = []
        self.session_id = str(uuid.uuid4())[:8]

    async def process(self, user_message: str) -> str:
        logger.info("Processing user message (session=%s)", self.session_id)
        self.conversation_history.append({"role": "user", "content": user_message})
        messages = list(self.conversation_history)
        tools = get_chief_tools()

        for _round in range(MAX_TOOL_ROUNDS):
            response = await self._call_api(messages, tools)

            if response.stop_reason == "tool_use":
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        logger.info("Tool call: %s (round %d)", block.name, _round + 1)
                        result = await self._handle_tool_call_async(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Extract final text response
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

            logger.info("Final response after %d round(s) (session=%s)", _round + 1, self.session_id)
            # Persist intermediate tool call/result messages and the final
            # response with full content blocks so subsequent turns have
            # complete context (tool_use blocks, tool_results, and text).
            new_messages = messages[len(self.conversation_history):]
            self.conversation_history.extend(new_messages)
            self.conversation_history.append({"role": "assistant", "content": response.content})
            return text

        logger.warning("Reached max tool rounds (%d) without final response (session=%s)", MAX_TOOL_ROUNDS, self.session_id)
        fallback = "[Reached maximum tool rounds without a final response]"
        self.conversation_history.append({"role": "assistant", "content": fallback})
        return fallback

    @retry_api_call
    async def _call_api(self, messages: list, tools: list) -> Any:
        return await self.client.messages.create(
            model=app_config.CHIEF_MODEL,
            max_tokens=4096,
            system=CHIEF_SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

    async def _handle_tool_call_async(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name in ("dispatch_agent", "dispatch_parallel"):
            return await self._handle_async_tool(tool_name, tool_input)
        if tool_name == "create_agent":
            return self._handle_create_agent(tool_input)
        return self.handle_tool_call(tool_name, tool_input)

    def handle_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "query_memory":
            return execute_query_memory(
                self.memory_store, tool_input["query"], tool_input.get("category")
            )

        elif tool_name == "store_memory":
            return execute_store_memory(
                self.memory_store,
                tool_input["category"],
                tool_input["key"],
                tool_input["value"],
                source="chief_of_staff",
            )

        elif tool_name == "search_documents":
            return execute_search_documents(
                self.document_store, tool_input["query"], tool_input.get("top_k", 5)
            )

        elif tool_name == "list_agents":
            agents = self.agent_registry.list_agents()
            return [{"name": a.name, "description": a.description} for a in agents]

        elif tool_name == "log_decision":
            decision = Decision(
                title=tool_input["title"],
                description=tool_input.get("description", ""),
                context=tool_input.get("context", ""),
                decided_by=tool_input.get("decided_by", ""),
                owner=tool_input.get("owner", ""),
                status=tool_input.get("status", "pending_execution"),
                follow_up_date=tool_input.get("follow_up_date") or None,
                tags=tool_input.get("tags", ""),
                source=tool_input.get("source", ""),
            )
            stored = self.memory_store.store_decision(decision)
            return {"status": "logged", "id": stored.id, "title": stored.title}

        elif tool_name == "add_delegation":
            delegation = Delegation(
                task=tool_input["task"],
                delegated_to=tool_input["delegated_to"],
                description=tool_input.get("description", ""),
                due_date=tool_input.get("due_date") or None,
                priority=tool_input.get("priority", "medium"),
                source=tool_input.get("source", ""),
            )
            stored = self.memory_store.store_delegation(delegation)
            return {"status": "created", "id": stored.id, "task": stored.task}

        elif tool_name == "check_alerts":
            from datetime import date, timedelta
            alerts = {"overdue_delegations": [], "stale_decisions": [], "upcoming_deadlines": []}
            overdue = self.memory_store.list_overdue_delegations()
            for d in overdue:
                alerts["overdue_delegations"].append({"id": d.id, "task": d.task, "delegated_to": d.delegated_to, "due_date": d.due_date})
            pending = self.memory_store.list_decisions_by_status("pending_execution")
            cutoff = (date.today() - timedelta(days=7)).isoformat()
            for d in pending:
                if d.created_at and d.created_at[:10] < cutoff:
                    alerts["stale_decisions"].append({"id": d.id, "title": d.title, "created_at": d.created_at})
            today = date.today()
            soon = (today + timedelta(days=3)).isoformat()
            today_str = today.isoformat()
            active = self.memory_store.list_delegations(status="active")
            for d in active:
                if d.due_date and today_str <= d.due_date <= soon:
                    alerts["upcoming_deadlines"].append({"id": d.id, "task": d.task, "delegated_to": d.delegated_to, "due_date": d.due_date})
            total = sum(len(v) for v in alerts.values())
            return {"total_alerts": total, "alerts": alerts}

        elif tool_name == "list_calendars":
            if self.calendar_store is None:
                return {"error": "Calendar not available (macOS only)"}
            return self.calendar_store.list_calendars()

        elif tool_name == "get_calendar_events":
            if self.calendar_store is None:
                return {"error": "Calendar not available (macOS only)"}
            start_dt = datetime.fromisoformat(tool_input["start_date"])
            end_dt = datetime.fromisoformat(tool_input["end_date"])
            calendar_names = None
            if tool_input.get("calendar_name"):
                calendar_names = [tool_input["calendar_name"]]
            return self.calendar_store.get_events(start_dt, end_dt, calendar_names)

        elif tool_name == "create_calendar_event":
            if self.calendar_store is None:
                return {"error": "Calendar not available (macOS only)"}
            start_dt = datetime.fromisoformat(tool_input["start_date"])
            end_dt = datetime.fromisoformat(tool_input["end_date"])
            return self.calendar_store.create_event(
                title=tool_input["title"],
                start_dt=start_dt,
                end_dt=end_dt,
                calendar_name=tool_input.get("calendar_name"),
                location=tool_input.get("location"),
                notes=tool_input.get("notes"),
                is_all_day=tool_input.get("is_all_day", False),
            )

        elif tool_name == "list_reminder_lists":
            if self.reminder_store is None:
                return {"error": "Reminders not available (macOS only)"}
            return self.reminder_store.list_reminder_lists()

        elif tool_name == "get_reminders":
            if self.reminder_store is None:
                return {"error": "Reminders not available (macOS only)"}
            return self.reminder_store.get_reminders(
                list_name=tool_input.get("list_name"),
                completed=tool_input.get("completed"),
            )

        elif tool_name == "create_reminder":
            if self.reminder_store is None:
                return {"error": "Reminders not available (macOS only)"}
            return self.reminder_store.create_reminder(
                title=tool_input["title"],
                list_name=tool_input.get("list_name"),
                due_date=tool_input.get("due_date"),
                priority=tool_input.get("priority"),
                notes=tool_input.get("notes"),
            )

        elif tool_name == "complete_reminder":
            if self.reminder_store is None:
                return {"error": "Reminders not available (macOS only)"}
            return self.reminder_store.complete_reminder(tool_input["reminder_id"])

        elif tool_name == "search_reminders":
            if self.reminder_store is None:
                return {"error": "Reminders not available (macOS only)"}
            return self.reminder_store.search_reminders(
                query=tool_input["query"],
                include_completed=tool_input.get("include_completed", False),
            )

        elif tool_name == "send_notification":
            if self.notifier is None:
                return {"error": "Notifications not available (macOS only)"}
            return self.notifier.send(
                title=tool_input["title"],
                message=tool_input["message"],
                subtitle=tool_input.get("subtitle"),
                sound=tool_input.get("sound", "default"),
            )

        elif tool_name == "list_mailboxes":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.list_mailboxes()

        elif tool_name == "get_mail_messages":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.get_messages(
                mailbox=tool_input.get("mailbox", "INBOX"),
                account=tool_input.get("account", ""),
                limit=tool_input.get("limit", 25),
            )

        elif tool_name == "get_mail_message":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.get_message(tool_input["message_id"])

        elif tool_name == "search_mail":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.search_messages(
                query=tool_input["query"],
                mailbox=tool_input.get("mailbox", "INBOX"),
                account=tool_input.get("account", ""),
                limit=tool_input.get("limit", 25),
            )

        elif tool_name == "get_unread_count":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            mailbox = tool_input.get("mailbox", "INBOX")
            account = tool_input.get("account", "")
            mailboxes = self.mail_store.list_mailboxes()
            for mb in mailboxes:
                if isinstance(mb, dict) and mb.get("name") == mailbox:
                    if account and mb.get("account") != account:
                        continue
                    return {"mailbox": mailbox, "unread_count": mb.get("unread_count", 0)}
            return {"mailbox": mailbox, "unread_count": 0}

        elif tool_name == "mark_mail_read":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.mark_read(
                message_id=tool_input["message_id"],
                read=tool_input.get("read", True),
            )

        elif tool_name == "mark_mail_flagged":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.mark_flagged(
                message_id=tool_input["message_id"],
                flagged=tool_input.get("flagged", True),
            )

        elif tool_name == "move_mail_message":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            return self.mail_store.move_message(
                message_id=tool_input["message_id"],
                target_mailbox=tool_input["target_mailbox"],
                target_account=tool_input.get("target_account", ""),
            )

        elif tool_name == "send_email":
            if self.mail_store is None:
                return {"error": "Mail not available (macOS only)"}
            to_list = [a.strip() for a in tool_input["to"].split(",") if a.strip()]
            cc_list = [a.strip() for a in tool_input.get("cc", "").split(",") if a.strip()] or None
            bcc_list = [a.strip() for a in tool_input.get("bcc", "").split(",") if a.strip()] or None
            return self.mail_store.send_message(
                to=to_list,
                subject=tool_input["subject"],
                body=tool_input["body"],
                cc=cc_list,
                bcc=bcc_list,
                confirm_send=tool_input.get("confirm_send", False),
            )

        return {"error": f"Unknown tool: {tool_name}"}

    def _handle_create_agent(self, tool_input: dict) -> Any:
        config = AgentConfig(
            name=tool_input["name"],
            description=tool_input["description"],
            system_prompt=tool_input["system_prompt"],
            capabilities=tool_input.get("capabilities", ["memory_read"]),
        )
        self.agent_registry.save_agent(config)
        return {"status": "created", "name": config.name, "description": config.description}

    def _get_last_user_message(self) -> str | None:
        """Return the most recent user text message from conversation history."""
        for msg in reversed(self.conversation_history):
            if msg["role"] == "user" and isinstance(msg["content"], str):
                return msg["content"]
        return None

    def _enrich_task(self, task: str) -> str:
        """Prepend the user's original request to give agents fuller context."""
        user_msg = self._get_last_user_message()
        if user_msg:
            return f"User's original request: {user_msg}\n\nYour specific task: {task}"
        return task

    async def _handle_async_tool(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "dispatch_agent":
            agent_name = tool_input["agent_name"]
            task = self._enrich_task(tool_input["task"])
            config = self.agent_registry.get_agent(agent_name)
            if config is None:
                logger.warning("Agent '%s' not found for dispatch", agent_name)
                return {"error": f"Agent '{agent_name}' not found"}
            logger.info("Dispatching agent: %s", agent_name)
            agent = BaseExpertAgent(config, self.memory_store, self.document_store, client=self.client, calendar_store=self.calendar_store, reminder_store=self.reminder_store, notifier=self.notifier, mail_store=self.mail_store)
            results = await self.dispatcher.dispatch([(agent_name, agent, task)])
            r = results[0]
            if r.error:
                return {"error": r.error}
            return {"agent": agent_name, "response": r.result}

        elif tool_name == "dispatch_parallel":
            tasks_to_dispatch = []
            missing_agents = []
            for item in tool_input["tasks"]:
                name = item["agent_name"]
                config = self.agent_registry.get_agent(name)
                if config is None:
                    logger.warning("Agent '%s' not found, skipping in parallel dispatch", name)
                    missing_agents.append(name)
                    continue
                agent = BaseExpertAgent(config, self.memory_store, self.document_store, client=self.client, calendar_store=self.calendar_store, reminder_store=self.reminder_store, notifier=self.notifier, mail_store=self.mail_store)
                enriched_task = self._enrich_task(item["task"])
                tasks_to_dispatch.append((name, agent, enriched_task))

            if not tasks_to_dispatch:
                return {"error": "No valid agents found for dispatch"}

            agent_names = [t[0] for t in tasks_to_dispatch]
            logger.info("Dispatching %d agent(s) in parallel: %s", len(agent_names), ", ".join(agent_names))

            results = await self.dispatcher.dispatch(tasks_to_dispatch)
            output = [
                {"agent": r.agent_name, "response": r.result, "error": r.error}
                for r in results
            ]
            for name in missing_agents:
                output.append({"agent": name, "error": f"Agent '{name}' not found"})
            return output

        return {"error": f"Unknown async tool: {tool_name}"}

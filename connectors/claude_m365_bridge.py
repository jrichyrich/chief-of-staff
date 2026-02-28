from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from datetime import datetime
from typing import Callable, Optional


class ClaudeM365Bridge:
    """Bridge that invokes Claude CLI to execute Microsoft 365 MCP operations."""

    @staticmethod
    def _sanitize_for_prompt(text: str, max_length: int = 500) -> str:
        """Sanitize user input before embedding in a Claude prompt."""
        if text is None:
            return ""
        # Strip control characters (keep only printable + space)
        sanitized = "".join(c for c in str(text) if c.isprintable() or c == " ")
        # Truncate
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."
        return sanitized

    def __init__(
        self,
        claude_bin: str = "claude",
        mcp_config: str = "",
        model: str = "sonnet",
        timeout_seconds: int = 90,
        detect_timeout_seconds: int = 5,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ):
        self.claude_bin = claude_bin
        self.mcp_config = mcp_config
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.detect_timeout_seconds = detect_timeout_seconds
        self._runner = runner or subprocess.run

    def is_connector_connected(self) -> bool:
        args = [self.claude_bin, "mcp", "list"]
        if self.mcp_config:
            args.extend(["--mcp-config", self.mcp_config])
        proc = self._run(args, timeout=self.detect_timeout_seconds)
        if proc is None or proc.returncode != 0:
            return False
        output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        return bool(re.search(r"microsoft\s*365:.*\bconnected\b", output, flags=re.IGNORECASE))

    def list_calendars(self) -> list[dict]:
        schema = {
            "type": "object",
            "properties": {"results": {"type": "array", "items": {"type": "object"}}},
            "required": ["results"],
        }
        prompt = (
            "Use only Microsoft 365 MCP connector tools to list Outlook/Exchange calendars. "
            "Return calendar rows with useful fields such as name, calendar_id, source_account, type, and color "
            "when available."
        )
        data = self._invoke_structured(prompt, schema)
        if data.get("error"):
            return [data]
        return [dict(row) for row in data.get("results", []) if isinstance(row, dict)]

    def get_events(
        self,
        start_dt: datetime,
        end_dt: datetime,
        calendar_names: Optional[list[str]] = None,
    ) -> list[dict]:
        schema = {
            "type": "object",
            "properties": {"results": {"type": "array", "items": {"type": "object"}}},
            "required": ["results"],
        }
        filter_clause = (
            "Limit to these calendars when possible: "
            f"<user_calendar_names>{', '.join(self._sanitize_for_prompt(n) for n in calendar_names)}</user_calendar_names>. "
            if calendar_names
            else ""
        )
        prompt = (
            "Use only Microsoft 365 MCP connector tools to get calendar events. "
            f"Time range start={start_dt.isoformat()} end={end_dt.isoformat()}. "
            f"{filter_clause}"
            "Return results with fields like uid/native_id, title, start, end, calendar/calendar_id, source_account."
        )
        data = self._invoke_structured(prompt, schema)
        if data.get("error"):
            return [data]
        return [dict(row) for row in data.get("results", []) if isinstance(row, dict)]

    def search_events(self, query: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
        schema = {
            "type": "object",
            "properties": {"results": {"type": "array", "items": {"type": "object"}}},
            "required": ["results"],
        }
        prompt = (
            "Use only Microsoft 365 MCP connector tools to search Outlook/Exchange calendar events by title text. "
            f"query=<user_query>{self._sanitize_for_prompt(query)}</user_query>, "
            f"start={start_dt.isoformat()}, end={end_dt.isoformat()}. "
            "Return results with fields like uid/native_id, title, start, end, calendar/calendar_id, source_account."
        )
        data = self._invoke_structured(prompt, schema)
        if data.get("error"):
            return [data]
        return [dict(row) for row in data.get("results", []) if isinstance(row, dict)]

    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        calendar_name: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        is_all_day: bool = False,
    ) -> dict:
        schema = {
            "type": "object",
            "properties": {"result": {"type": "object"}},
            "required": ["result"],
        }
        prompt = (
            "Use only Microsoft 365 MCP connector tools to create a calendar event in Outlook/Exchange. "
            f"title=<user_title>{self._sanitize_for_prompt(title)}</user_title>, "
            f"start={start_dt.isoformat()}, end={end_dt.isoformat()}, "
            f"calendar_name=<user_calendar_name>{self._sanitize_for_prompt(calendar_name)}</user_calendar_name>, "
            f"location=<user_location>{self._sanitize_for_prompt(location)}</user_location>, "
            f"notes=<user_notes>{self._sanitize_for_prompt(notes, max_length=1000)}</user_notes>, "
            f"is_all_day={is_all_day}. "
            "Return created event fields as an object in result."
        )
        data = self._invoke_structured(prompt, schema)
        if data.get("error"):
            return data
        result = data.get("result", {})
        return dict(result) if isinstance(result, dict) else {"error": "Invalid create_event response from Claude bridge"}

    def update_event(self, event_uid: str, calendar_name: Optional[str] = None, **kwargs) -> dict:
        schema = {
            "type": "object",
            "properties": {"result": {"type": "object"}},
            "required": ["result"],
        }
        safe_kwargs = dict(kwargs)
        if isinstance(safe_kwargs.get("start_dt"), datetime):
            safe_kwargs["start_dt"] = safe_kwargs["start_dt"].isoformat()
        if isinstance(safe_kwargs.get("end_dt"), datetime):
            safe_kwargs["end_dt"] = safe_kwargs["end_dt"].isoformat()
        # Sanitize user-supplied string values in kwargs
        sanitized_kwargs = {}
        for k, v in safe_kwargs.items():
            sanitized_kwargs[k] = self._sanitize_for_prompt(v) if isinstance(v, str) else v
        prompt = (
            "Use only Microsoft 365 MCP connector tools to update an existing Outlook/Exchange calendar event. "
            f"event_uid=<user_event_uid>{self._sanitize_for_prompt(event_uid)}</user_event_uid>, "
            f"calendar_name=<user_calendar_name>{self._sanitize_for_prompt(calendar_name)}</user_calendar_name>, "
            f"updates=<user_updates>{json.dumps(sanitized_kwargs)}</user_updates>. "
            "Return updated event fields as an object in result."
        )
        data = self._invoke_structured(prompt, schema)
        if data.get("error"):
            return data
        result = data.get("result", {})
        return dict(result) if isinstance(result, dict) else {"error": "Invalid update_event response from Claude bridge"}

    def delete_event(self, event_uid: str, calendar_name: Optional[str] = None) -> dict:
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "event_uid": {"type": "string"},
                "error": {"type": ["string", "null"]},
            },
            "required": ["status"],
        }
        prompt = (
            "Use only Microsoft 365 MCP connector tools to delete an Outlook/Exchange calendar event. "
            f"event_uid=<user_event_uid>{self._sanitize_for_prompt(event_uid)}</user_event_uid>, "
            f"calendar_name=<user_calendar_name>{self._sanitize_for_prompt(calendar_name)}</user_calendar_name>. "
            "Return status and event_uid."
        )
        data = self._invoke_structured(prompt, schema)
        if data.get("error"):
            return data
        return dict(data)

    def _invoke_structured(self, prompt: str, schema: dict) -> dict:
        args = [
            self.claude_bin,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--no-session-persistence",
            "--disable-slash-commands",
            "--model",
            self.model,
        ]
        if self.mcp_config:
            args.extend(["--mcp-config", self.mcp_config])

        proc = self._run(args, timeout=self.timeout_seconds)
        if proc is None:
            return {"error": "Failed to invoke Claude CLI"}
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return {"error": f"Claude bridge command failed: {err or 'unknown error'}"}

        payload = self._parse_output_json(proc.stdout or "")
        if payload is None:
            return {"error": "Claude bridge returned invalid JSON"}

        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            return structured
        if isinstance(structured, str) and structured.strip():
            parsed = self._parse_first_json_object(structured)
            if parsed is not None:
                return parsed

        raw_result = payload.get("result")
        if isinstance(raw_result, dict):
            return raw_result
        if isinstance(raw_result, str) and raw_result.strip():
            parsed = self._parse_first_json_object(raw_result)
            if parsed is not None:
                return parsed

        parsed = self._parse_first_json_object(proc.stdout or "")
        if parsed is not None:
            return parsed

        return {"error": "Claude bridge could not parse structured output"}

    def _run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess | None:
        try:
            if self._runner is not subprocess.run:
                # Custom runner (e.g. test mock) — use as-is
                return self._runner(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            # Default runner: use Popen with process group cleanup on timeout
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
                return None
        except FileNotFoundError:
            return None
        except Exception:
            return None

    @staticmethod
    def _parse_output_json(text: str) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _parse_first_json_object(text: str) -> dict | None:
        s = text or ""
        n = len(s)
        i = 0
        while i < n:
            if s[i] != "{":
                i += 1
                continue
            start = i
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                c = s[j]
                if escape:
                    escape = False
                elif c == "\\" and in_string:
                    escape = True
                elif c == '"':
                    in_string = not in_string
                elif not in_string:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = s[start:j + 1]
                            try:
                                parsed = json.loads(candidate)
                                return parsed if isinstance(parsed, dict) else None
                            except json.JSONDecodeError:
                                break
                j += 1
            i += 1
        return None

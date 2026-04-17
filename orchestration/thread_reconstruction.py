"""Email + Teams thread reconstruction.

Groups individual messages returned by Graph-style search endpoints into
coherent conversation threads so downstream brief-generation operates on
'what was the exchange about' rather than 'here are N floating messages'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd):\s*", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    prev = None
    s = subject or ""
    while prev != s:
        prev = s
        s = _SUBJECT_PREFIX_RE.sub("", s)
    return s.strip().lower()


def _extract_sender(msg: dict[str, Any]) -> tuple[str, str]:
    """Return (email, name) for an email message dict."""
    fr = msg.get("from") or {}
    ea = fr.get("emailAddress") or {}
    return ea.get("address", ""), ea.get("name", "")


@dataclass
class EmailThread:
    conversation_id: str
    subject: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def participants(self) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        for m in self.messages:
            email, name = _extract_sender(m)
            if email and email not in seen:
                seen[email] = name
        return [{"email": e, "name": n} for e, n in seen.items()]

    @property
    def latest(self) -> dict[str, Any]:
        return self.messages[-1] if self.messages else {}

    @property
    def latest_received(self) -> str:
        return self.latest.get("receivedDateTime", "")

    @property
    def latest_sender_email(self) -> str:
        return _extract_sender(self.latest)[0]

    @property
    def latest_preview(self) -> str:
        return self.latest.get("bodyPreview", "")


def reconstruct_email_threads(messages: list[dict[str, Any]]) -> list[EmailThread]:
    """Group email messages into threads keyed by conversationId (or normalized subject)."""
    if not messages:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in messages:
        key = m.get("conversationId") or _normalize_subject(m.get("subject", ""))
        if not key:
            key = m.get("id", "")
        groups.setdefault(key, []).append(m)

    threads: list[EmailThread] = []
    for key, items in groups.items():
        items.sort(key=lambda x: x.get("receivedDateTime", ""))
        subject = items[-1].get("subject", "")
        threads.append(EmailThread(conversation_id=key, subject=subject, messages=items))
    threads.sort(key=lambda t: t.latest_received, reverse=True)
    return threads


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return _HTML_TAG_RE.sub("", html or "").strip()


@dataclass
class TeamsThread:
    chat_id: str
    chat_type: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def latest(self) -> dict[str, Any]:
        return self.messages[-1] if self.messages else {}

    @property
    def latest_preview(self) -> str:
        body = self.latest.get("body") or {}
        return _strip_html(body.get("content", ""))

    @property
    def latest_created(self) -> str:
        return self.latest.get("createdDateTime", "")

    @property
    def latest_sender_name(self) -> str:
        return ((self.latest.get("from") or {}).get("user") or {}).get("displayName", "")

    @property
    def participants(self) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        for m in self.messages:
            user = (m.get("from") or {}).get("user") or {}
            uid = user.get("id", "")
            name = user.get("displayName", "")
            if uid and uid not in seen:
                seen[uid] = name
        return [{"id": u, "name": n} for u, n in seen.items()]


def reconstruct_teams_threads(messages: list[dict[str, Any]]) -> list[TeamsThread]:
    """Group Teams chat messages by chatId and order by createdDateTime."""
    if not messages:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    chat_types: dict[str, str] = {}
    for m in messages:
        cid = m.get("chatId") or m.get("channelIdentity", {}).get("channelId") or m.get("id", "")
        groups.setdefault(cid, []).append(m)
        chat_types[cid] = m.get("chatType", chat_types.get(cid, "unknown"))

    threads: list[TeamsThread] = []
    for cid, items in groups.items():
        items.sort(key=lambda x: x.get("createdDateTime", ""))
        threads.append(TeamsThread(chat_id=cid, chat_type=chat_types[cid], messages=items))
    threads.sort(key=lambda t: t.latest_created, reverse=True)
    return threads

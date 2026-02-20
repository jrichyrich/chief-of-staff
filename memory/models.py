# memory/models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Fact:
    category: str
    key: str
    value: str
    confidence: float = 1.0
    source: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Location:
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class ContextEntry:
    topic: str
    summary: str
    session_id: Optional[str] = None
    agent: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class Decision:
    title: str
    description: str = ""
    context: str = ""
    alternatives_considered: str = ""
    decided_by: str = ""
    owner: str = ""
    status: str = "pending_execution"
    follow_up_date: Optional[str] = None
    tags: str = ""
    source: str = ""
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Delegation:
    task: str
    delegated_to: str
    description: str = ""
    delegated_by: str = ""
    due_date: Optional[str] = None
    priority: str = "medium"
    status: str = "active"
    source: str = ""
    notes: str = ""
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class AlertRule:
    name: str
    description: str = ""
    alert_type: str = ""
    condition: str = ""
    enabled: bool = True
    last_triggered_at: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class WebhookEvent:
    source: str
    event_type: str
    payload: str = ""
    status: str = "pending"
    id: Optional[int] = None
    received_at: Optional[str] = None
    processed_at: Optional[str] = None


@dataclass
class ScheduledTask:
    name: str
    schedule_type: str  # interval, cron, once
    schedule_config: str = ""  # JSON string
    handler_type: str = ""  # alert_eval, backup, webhook_poll, custom
    handler_config: str = ""  # JSON string
    description: str = ""
    enabled: bool = True
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_result: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SkillUsage:
    tool_name: str
    query_pattern: str
    count: int = 1
    last_used: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class SkillSuggestion:
    description: str
    suggested_name: str = ""
    suggested_capabilities: str = ""
    confidence: float = 0.0
    status: str = "pending"
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class AgentMemory:
    agent_name: str = ""
    memory_type: str = ""  # "insight", "preference", "context"
    key: str = ""
    value: str = ""
    confidence: float = 1.0
    namespace: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

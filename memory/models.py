# memory/models.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# StrEnum shim (compatible with Python 3.10+)
# ---------------------------------------------------------------------------

class StrEnum(str, Enum):
    """String enum compatible with Python 3.10+."""

    def __str__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)

    def __hash__(self):
        return hash(self.value)


# ---------------------------------------------------------------------------
# Status / type enums
# ---------------------------------------------------------------------------

class WebhookStatus(StrEnum):
    pending = "pending"
    processed = "processed"
    failed = "failed"


class DecisionStatus(StrEnum):
    pending_execution = "pending_execution"
    executed = "executed"
    deferred = "deferred"
    reversed = "reversed"


class DelegationStatus(StrEnum):
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class DelegationPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class HandlerType(StrEnum):
    alert_eval = "alert_eval"
    webhook_poll = "webhook_poll"
    skill_analysis = "skill_analysis"
    proactive_push = "proactive_push"
    skill_auto_exec = "skill_auto_exec"
    webhook_dispatch = "webhook_dispatch"
    morning_brief = "morning_brief"
    custom = "custom"


class DeliveryChannel(StrEnum):
    email = "email"
    imessage = "imessage"
    notification = "notification"
    teams = "teams"


class SkillSuggestionStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class ScheduleType(StrEnum):
    interval = "interval"
    cron = "cron"
    once = "once"


class FactCategory(StrEnum):
    personal = "personal"
    preference = "preference"
    work = "work"
    relationship = "relationship"
    backlog = "backlog"


class AgentMemoryType(StrEnum):
    insight = "insight"
    preference = "preference"
    context = "context"


class IdentityProvider(StrEnum):
    imessage = "imessage"
    email = "email"
    m365_teams = "m365_teams"
    m365_email = "m365_email"
    slack = "slack"
    jira = "jira"
    confluence = "confluence"


class AlertType(StrEnum):
    overdue_delegation = "overdue_delegation"
    pending_decision = "pending_decision"
    upcoming_deadline = "upcoming_deadline"


@dataclass
class Fact:
    category: str
    key: str
    value: str
    confidence: float = 1.0
    source: Optional[str] = None
    pinned: bool = False
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
    status: DecisionStatus = DecisionStatus.pending_execution
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
    priority: DelegationPriority = DelegationPriority.medium
    status: DelegationStatus = DelegationStatus.active
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
    status: WebhookStatus = WebhookStatus.pending
    id: Optional[int] = None
    received_at: Optional[str] = None
    processed_at: Optional[str] = None


@dataclass
class ScheduledTask:
    name: str
    schedule_type: ScheduleType  # interval, cron, once
    schedule_config: str = ""  # JSON string
    handler_type: HandlerType = HandlerType.custom
    handler_config: str = ""  # JSON string
    description: str = ""
    enabled: bool = True
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_result: Optional[str] = None
    delivery_channel: Optional[DeliveryChannel] = None
    delivery_config: Optional[dict] = None  # channel-specific JSON config
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
    status: SkillSuggestionStatus = SkillSuggestionStatus.pending
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class Identity:
    canonical_name: str
    provider: str
    provider_id: str
    display_name: str = ""
    email: str = ""
    metadata: str = ""  # JSON string
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class EventRule:
    name: str
    event_source: str
    event_type_pattern: str
    agent_name: str
    description: str = ""
    agent_input_template: str = ""
    delivery_channel: Optional[str] = None
    delivery_config: Optional[str] = None  # JSON string
    enabled: bool = True
    priority: int = 100
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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

"""Configuration for proactive session context loading."""

from dataclasses import dataclass, field


@dataclass
class ContextLoaderConfig:
    """Controls which sources are fetched and timing parameters."""

    enabled: bool = True
    per_source_timeout_seconds: int = 10
    ttl_minutes: int = 15
    sources: dict[str, bool] = field(default_factory=lambda: {
        "calendar": True,
        "mail": True,
        "delegations": True,
        "decisions": True,
        "reminders": True,
        "brain": True,
    })

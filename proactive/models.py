from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Suggestion:
    category: str       # "skill", "webhook", "delegation", "decision", "deadline"
    priority: str       # "high", "medium", "low"
    title: str
    description: str
    action: str         # suggested MCP tool to call
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

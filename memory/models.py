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

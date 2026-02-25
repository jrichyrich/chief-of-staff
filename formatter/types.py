"""TypedDicts for structured input data to formatter functions."""

from typing import TypedDict


class CalendarEntry(TypedDict, total=False):
    time: str
    event: str
    location: str
    status: str
    key: bool


class ActionItem(TypedDict, total=False):
    priority: str  # urgent, high, medium, low, fyi
    text: str


class Conflict(TypedDict, total=False):
    time: str
    a: str
    b: str


class EmailHighlight(TypedDict, total=False):
    sender: str
    subject: str
    tag: str


class StatusField(TypedDict, total=False):
    label: str
    value: str
    status: str  # green, yellow, red


class PanelData(TypedDict, total=False):
    title: str
    content: str

"""Outbound channel routing with safety tiers.

Determines how messages should be delivered based on:
- Recipient type (self, internal, external)
- Content sensitivity
- First-contact status
- Urgency level
- Work hours
"""

import re
from datetime import datetime
from enum import IntEnum
from typing import Optional

__all__ = [
    "SafetyTier",
    "determine_safety_tier",
    "select_channel",
    "is_work_hours",
    "is_sensitive_topic",
]


# ---------------------------------------------------------------------------
# Safety Tier Model
# ---------------------------------------------------------------------------


class SafetyTier(IntEnum):
    """Message delivery safety tiers (higher value = more restrictive).

    - AUTO_SEND (1): Send immediately without confirmation (e.g. notes to self)
    - CONFIRM (2): Show draft and require explicit confirmation before sending
    - DRAFT_ONLY (3): Create draft only; user must manually review and send
    """

    AUTO_SEND = 1
    CONFIRM = 2
    DRAFT_ONLY = 3


# Mapping from recipient type to baseline tier
_RECIPIENT_BASELINE: dict[str, SafetyTier] = {
    "self": SafetyTier.AUTO_SEND,
    "internal": SafetyTier.CONFIRM,
    "external": SafetyTier.DRAFT_ONLY,
}

# Valid override string values
_OVERRIDE_MAP: dict[str, SafetyTier] = {
    "auto": SafetyTier.AUTO_SEND,
    "confirm": SafetyTier.CONFIRM,
    "draft_only": SafetyTier.DRAFT_ONLY,
}

# Valid recipient types
_VALID_RECIPIENT_TYPES = frozenset(_RECIPIENT_BASELINE.keys())


# ---------------------------------------------------------------------------
# Sensitive topic detection
# ---------------------------------------------------------------------------

# Keywords that indicate sensitive/HR/legal content (matched as whole words,
# case-insensitive).  Kept as a compiled regex for performance.
_SENSITIVE_KEYWORDS = [
    "salary",
    "compensation",
    "confidential",
    "termination",
    "terminated",
    "performance review",
    "legal",
    "nda",
    "pii",
    "pip",
    "disciplin",        # matches discipline, disciplinary
    "severance",
    "lawsuit",
    "harassment",
    "whistleblow",
    "insider",
    "merger",
    "acquisition",
    "layoff",
    "reduction in force",
    "rif",
]

# Build a single compiled pattern: match any keyword as a word boundary match
_SENSITIVE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _SENSITIVE_KEYWORDS) + r")",
    re.IGNORECASE,
)


def is_sensitive_topic(content: str) -> bool:
    """Detect whether message content contains sensitive topics.

    Uses keyword matching (case-insensitive, word-boundary aware) to flag
    messages that may require higher safety tiers.

    Args:
        content: The message body text to scan.

    Returns:
        True if any sensitive keyword is found in the content.
    """
    if not content:
        return False
    return bool(_SENSITIVE_PATTERN.search(content))


# ---------------------------------------------------------------------------
# Work hours detection
# ---------------------------------------------------------------------------

# Default work hours: Monday-Friday, 9:00-17:59 (i.e. 9 <= hour < 18)
_WORK_START_HOUR = 9
_WORK_END_HOUR = 18  # exclusive


def is_work_hours(dt: Optional[datetime] = None) -> bool:
    """Check whether the given datetime falls within standard work hours.

    Work hours are defined as Monday-Friday, 09:00-17:59 local time.

    Args:
        dt: The datetime to check. Defaults to ``datetime.now()`` if not provided.

    Returns:
        True if the datetime is within work hours.
    """
    if dt is None:
        dt = datetime.now()
    # weekday(): Monday=0 .. Sunday=6
    if dt.weekday() >= 5:
        return False
    return _WORK_START_HOUR <= dt.hour < _WORK_END_HOUR


# ---------------------------------------------------------------------------
# Safety tier determination
# ---------------------------------------------------------------------------


def determine_safety_tier(
    recipient_type: str,
    sensitive: bool = False,
    first_contact: bool = False,
    override: Optional[str] = None,
) -> SafetyTier:
    """Determine the safety tier for an outbound message.

    Logic:
    1. If ``override`` is provided, return the corresponding tier immediately.
    2. Start with the baseline tier for the recipient type.
    3. If ``sensitive`` is True, bump up one tier (capped at DRAFT_ONLY).
    4. If ``first_contact`` is True and recipient is not "self", set to DRAFT_ONLY.

    Args:
        recipient_type: One of "self", "internal", "external".
        sensitive: Whether the message content is sensitive.
        first_contact: Whether this is the first message to this recipient.
        override: Force a specific tier: "auto", "confirm", or "draft_only".

    Returns:
        The determined SafetyTier.

    Raises:
        ValueError: If ``recipient_type`` or ``override`` is invalid.
    """
    # Validate override first
    if override is not None:
        if override not in _OVERRIDE_MAP:
            raise ValueError(
                f"Invalid override: {override!r}. "
                f"Must be one of: {sorted(_OVERRIDE_MAP)}"
            )
        return _OVERRIDE_MAP[override]

    # Validate recipient type
    if recipient_type not in _VALID_RECIPIENT_TYPES:
        raise ValueError(
            f"Invalid recipient_type: {recipient_type!r}. "
            f"Must be one of: {sorted(_VALID_RECIPIENT_TYPES)}"
        )

    tier = _RECIPIENT_BASELINE[recipient_type]

    # Sensitive content bumps tier up by one (unless already at max)
    if sensitive:
        tier = SafetyTier(min(tier + 1, SafetyTier.DRAFT_ONLY))

    # First contact bumps non-self to DRAFT_ONLY
    if first_contact and recipient_type != "self":
        tier = SafetyTier(max(tier, SafetyTier.DRAFT_ONLY))

    return tier


# ---------------------------------------------------------------------------
# Channel selection
# ---------------------------------------------------------------------------


def select_channel(
    recipient_type: str,
    urgency: str,
    work_hours: Optional[bool] = None,
) -> str:
    """Select the best outbound channel for a message.

    Channel selection matrix:

    **Self:**
    - urgent -> imessage
    - informational -> email
    - ephemeral -> notification
    - (other) -> email

    **Internal (work hours):**
    - informal -> teams
    - formal -> email
    - urgent -> teams
    - (other) -> email

    **Internal (off hours):**
    - urgent -> imessage
    - (other) -> queued (deferred until work hours)

    **External:**
    - (always) -> email

    Args:
        recipient_type: One of "self", "internal", "external".
        urgency: Message urgency/style: "urgent", "informational", "ephemeral",
                 "informal", "formal".
        work_hours: Whether it is currently work hours. If None, auto-detected
                    via ``is_work_hours()``.

    Returns:
        Channel name string: "imessage", "email", "notification", "teams", or "queued".

    Raises:
        ValueError: If ``recipient_type`` is invalid.
    """
    if recipient_type not in _VALID_RECIPIENT_TYPES:
        raise ValueError(
            f"Invalid recipient_type: {recipient_type!r}. "
            f"Must be one of: {sorted(_VALID_RECIPIENT_TYPES)}"
        )

    # External always goes through email
    if recipient_type == "external":
        return "email"

    # Self: route by urgency
    if recipient_type == "self":
        if urgency == "urgent":
            return "imessage"
        if urgency == "ephemeral":
            return "notification"
        # informational, formal, informal, or anything else -> email
        return "email"

    # Internal: depends on work hours
    if work_hours is None:
        work_hours = is_work_hours()

    if work_hours:
        if urgency in ("informal", "urgent"):
            return "teams"
        # formal, informational, ephemeral, or anything else -> email
        return "email"
    else:
        # Off hours
        if urgency == "urgent":
            return "imessage"
        return "queued"

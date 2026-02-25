"""Tests for channels/routing.py — outbound channel routing with safety tiers."""

from datetime import datetime

import pytest

from channels.routing import (
    SafetyTier,
    determine_safety_tier,
    is_sensitive_topic,
    is_work_hours,
    select_channel,
)


# --- SafetyTier enum ---


class TestSafetyTierEnum:
    def test_auto_send_value(self):
        assert SafetyTier.AUTO_SEND.value == 1

    def test_confirm_value(self):
        assert SafetyTier.CONFIRM.value == 2

    def test_draft_only_value(self):
        assert SafetyTier.DRAFT_ONLY.value == 3

    def test_ordering(self):
        """Higher value = more restrictive."""
        assert SafetyTier.AUTO_SEND.value < SafetyTier.CONFIRM.value
        assert SafetyTier.CONFIRM.value < SafetyTier.DRAFT_ONLY.value


# --- determine_safety_tier ---


class TestDetermineSafetyTier:
    """Safety tier determination based on recipient, sensitivity, and contact history."""

    def test_self_recipient_returns_auto_send(self):
        """Messages to self should auto-send (Tier 1)."""
        tier = determine_safety_tier(recipient_type="self")
        assert tier == SafetyTier.AUTO_SEND

    def test_internal_recipient_returns_confirm(self):
        """Messages to known internal contacts should require confirmation (Tier 2)."""
        tier = determine_safety_tier(recipient_type="internal")
        assert tier == SafetyTier.CONFIRM

    def test_external_recipient_returns_draft_only(self):
        """Messages to external contacts should be draft-only (Tier 3)."""
        tier = determine_safety_tier(recipient_type="external")
        assert tier == SafetyTier.DRAFT_ONLY

    def test_sensitive_topic_bumps_self_to_confirm(self):
        """Sensitive content should bump self from Tier 1 to Tier 2."""
        tier = determine_safety_tier(recipient_type="self", sensitive=True)
        assert tier == SafetyTier.CONFIRM

    def test_sensitive_topic_bumps_internal_to_draft_only(self):
        """Sensitive content should bump internal from Tier 2 to Tier 3."""
        tier = determine_safety_tier(recipient_type="internal", sensitive=True)
        assert tier == SafetyTier.DRAFT_ONLY

    def test_sensitive_external_stays_draft_only(self):
        """External is already Tier 3, sensitive can't go higher."""
        tier = determine_safety_tier(recipient_type="external", sensitive=True)
        assert tier == SafetyTier.DRAFT_ONLY

    def test_first_contact_bumps_to_draft_only(self):
        """First contact with anyone should always be draft-only."""
        tier = determine_safety_tier(recipient_type="internal", first_contact=True)
        assert tier == SafetyTier.DRAFT_ONLY

    def test_first_contact_self_stays_auto_send(self):
        """First contact flag is irrelevant for self — you always know yourself."""
        tier = determine_safety_tier(recipient_type="self", first_contact=True)
        assert tier == SafetyTier.AUTO_SEND

    def test_override_auto_forces_auto_send(self):
        """Override 'auto' should force AUTO_SEND regardless of other factors."""
        tier = determine_safety_tier(
            recipient_type="external", sensitive=True, override="auto"
        )
        assert tier == SafetyTier.AUTO_SEND

    def test_override_draft_only_forces_draft_only(self):
        """Override 'draft_only' should force DRAFT_ONLY regardless."""
        tier = determine_safety_tier(recipient_type="self", override="draft_only")
        assert tier == SafetyTier.DRAFT_ONLY

    def test_override_confirm_forces_confirm(self):
        """Override 'confirm' should force CONFIRM."""
        tier = determine_safety_tier(recipient_type="self", override="confirm")
        assert tier == SafetyTier.CONFIRM

    def test_invalid_recipient_type_raises(self):
        """Unknown recipient types should raise ValueError."""
        with pytest.raises(ValueError, match="recipient_type"):
            determine_safety_tier(recipient_type="unknown")

    def test_invalid_override_raises(self):
        """Unknown override values should raise ValueError."""
        with pytest.raises(ValueError, match="override"):
            determine_safety_tier(recipient_type="self", override="yolo")


# --- select_channel ---


class TestSelectChannel:
    """Channel selection based on recipient, urgency, and work hours."""

    # Self recipient
    def test_self_urgent_returns_imessage(self):
        result = select_channel(recipient_type="self", urgency="urgent")
        assert result == "imessage"

    def test_self_informational_returns_email(self):
        result = select_channel(recipient_type="self", urgency="informational")
        assert result == "email"

    def test_self_ephemeral_returns_notification(self):
        result = select_channel(recipient_type="self", urgency="ephemeral")
        assert result == "notification"

    # Internal recipient — work hours
    def test_internal_work_hours_informal_returns_teams(self):
        result = select_channel(
            recipient_type="internal", urgency="informal", work_hours=True
        )
        assert result == "teams"

    def test_internal_work_hours_formal_returns_email(self):
        result = select_channel(
            recipient_type="internal", urgency="formal", work_hours=True
        )
        assert result == "email"

    # Internal recipient — off hours
    def test_internal_off_hours_urgent_returns_imessage(self):
        result = select_channel(
            recipient_type="internal", urgency="urgent", work_hours=False
        )
        assert result == "imessage"

    def test_internal_off_hours_non_urgent_returns_queued(self):
        result = select_channel(
            recipient_type="internal", urgency="informational", work_hours=False
        )
        assert result == "queued"

    def test_internal_off_hours_informal_returns_queued(self):
        result = select_channel(
            recipient_type="internal", urgency="informal", work_hours=False
        )
        assert result == "queued"

    def test_internal_off_hours_formal_returns_queued(self):
        result = select_channel(
            recipient_type="internal", urgency="formal", work_hours=False
        )
        assert result == "queued"

    # External recipient
    def test_external_always_returns_email(self):
        """External messages always go via email regardless of urgency or hours."""
        for urgency in ("urgent", "informational", "ephemeral", "informal", "formal"):
            for work_hours in (True, False):
                result = select_channel(
                    recipient_type="external", urgency=urgency, work_hours=work_hours
                )
                assert result == "email", (
                    f"Expected email for external+{urgency}+work_hours={work_hours}"
                )

    # Default work_hours (auto-detect)
    def test_work_hours_defaults_to_auto_detect(self):
        """When work_hours is None, it should auto-detect based on current time."""
        # We just verify it doesn't raise — actual value depends on wall clock
        result = select_channel(recipient_type="internal", urgency="informal")
        assert result in ("teams", "queued")

    def test_invalid_recipient_type_raises(self):
        with pytest.raises(ValueError, match="recipient_type"):
            select_channel(recipient_type="alien", urgency="urgent")


# --- is_work_hours ---


class TestIsWorkHours:
    def test_weekday_9am_is_work_hours(self):
        # Monday at 9:00 AM
        dt = datetime(2026, 2, 23, 9, 0)  # Monday
        assert is_work_hours(dt) is True

    def test_weekday_5pm_is_work_hours(self):
        # Monday at 5:00 PM (17:00 — still within 9-18)
        dt = datetime(2026, 2, 23, 17, 0)
        assert is_work_hours(dt) is True

    def test_weekday_6pm_is_not_work_hours(self):
        # Monday at 6:00 PM (18:00 — boundary, not included)
        dt = datetime(2026, 2, 23, 18, 0)
        assert is_work_hours(dt) is False

    def test_weekday_8am_is_not_work_hours(self):
        # Monday at 8:00 AM (before 9)
        dt = datetime(2026, 2, 23, 8, 0)
        assert is_work_hours(dt) is False

    def test_saturday_noon_is_not_work_hours(self):
        dt = datetime(2026, 2, 28, 12, 0)  # Saturday
        assert is_work_hours(dt) is False

    def test_sunday_noon_is_not_work_hours(self):
        dt = datetime(2026, 3, 1, 12, 0)  # Sunday
        assert is_work_hours(dt) is False

    def test_no_argument_uses_current_time(self):
        """Calling with no argument should not raise."""
        result = is_work_hours()
        assert isinstance(result, bool)


# --- is_sensitive_topic ---


class TestIsSensitiveTopic:
    def test_salary_is_sensitive(self):
        assert is_sensitive_topic("Let's discuss your salary adjustment") is True

    def test_compensation_is_sensitive(self):
        assert is_sensitive_topic("Compensation review for Q2") is True

    def test_confidential_is_sensitive(self):
        assert is_sensitive_topic("This is CONFIDENTIAL information") is True

    def test_termination_is_sensitive(self):
        assert is_sensitive_topic("We need to discuss termination procedures") is True

    def test_performance_review_is_sensitive(self):
        assert is_sensitive_topic("Your performance review is scheduled") is True

    def test_legal_is_sensitive(self):
        assert is_sensitive_topic("The legal team has concerns") is True

    def test_nda_is_sensitive(self):
        assert is_sensitive_topic("Please sign the NDA before proceeding") is True

    def test_pii_is_sensitive(self):
        assert is_sensitive_topic("Contains PII that must be protected") is True

    def test_normal_message_not_sensitive(self):
        assert is_sensitive_topic("Let's grab lunch tomorrow") is False

    def test_empty_string_not_sensitive(self):
        assert is_sensitive_topic("") is False

    def test_case_insensitive(self):
        assert is_sensitive_topic("SALARY negotiations") is True
        assert is_sensitive_topic("salary negotiations") is True

    def test_pip_is_sensitive(self):
        assert is_sensitive_topic("Starting a PIP for the team member") is True

    def test_discipline_is_sensitive(self):
        assert is_sensitive_topic("Disciplinary action is required") is True

"""Tests for the humanizer rule-based text transformer."""

import pytest

import mcp_server  # noqa: F401 — trigger registration

from humanizer.rules import humanize, HumanizerRule, DEFAULT_RULES


class TestEmDashRemoval:
    def test_em_dash_replaced_with_comma(self):
        text = "The tool — which is powerful — works well"
        result = humanize(text)
        assert "\u2014" not in result
        assert "tool," in result or "tool " in result

    def test_double_hyphen_em_dash(self):
        text = "The tool -- which is great -- works"
        result = humanize(text)
        assert "--" not in result


class TestAIVocabulary:
    def test_additionally_becomes_also(self):
        result = humanize("Additionally, the system supports X.")
        assert "Additionally" not in result
        assert "Also" in result or "also" in result

    def test_utilize_becomes_use(self):
        result = humanize("We utilize this tool daily.")
        assert "utilize" not in result
        assert "use" in result

    def test_facilitate_becomes_help(self):
        result = humanize("This will facilitate the process.")
        assert "facilitate" not in result

    def test_leverage_becomes_use(self):
        result = humanize("We can leverage this capability.")
        assert "leverage" not in result
        assert "use" in result

    def test_comprehensive_removed_or_replaced(self):
        result = humanize("This is a comprehensive solution.")
        assert "comprehensive" not in result

    def test_robust_removed_or_replaced(self):
        result = humanize("This is a robust system.")
        assert "robust" not in result


class TestFillerPhrases:
    def test_in_order_to(self):
        result = humanize("In order to fix this, we need to update.")
        assert "In order to" not in result
        assert result.startswith("To fix")

    def test_due_to_the_fact_that(self):
        result = humanize("Due to the fact that it failed, we retried.")
        assert "Due to the fact that" not in result
        assert "Because" in result

    def test_it_is_worth_noting(self):
        result = humanize("It is worth noting that the system works.")
        assert "It is worth noting that" not in result

    def test_at_the_end_of_the_day(self):
        result = humanize("At the end of the day, we need results.")
        assert "At the end of the day," not in result


class TestSycophancy:
    def test_great_question(self):
        result = humanize("Great question! Here is the answer.")
        assert "Great question!" not in result

    def test_hope_this_helps(self):
        result = humanize("The answer is X. I hope this helps!")
        assert "I hope this helps" not in result

    def test_absolutely(self):
        result = humanize("Absolutely! We can do that.")
        assert result.strip().startswith("We can") or "Absolutely!" not in result


class TestCopulaAvoidance:
    def test_serves_as(self):
        result = humanize("This serves as the main entry point.")
        assert "serves as" not in result
        assert "is" in result

    def test_functions_as(self):
        result = humanize("This functions as a gateway.")
        assert "functions as" not in result

    def test_stands_as(self):
        result = humanize("This stands as a testament.")
        assert "stands as" not in result


class TestHedging:
    def test_could_potentially(self):
        result = humanize("This could potentially cause issues.")
        assert "could potentially" not in result

    def test_it_should_be_noted(self):
        result = humanize("It should be noted that this works.")
        assert "It should be noted that" not in result


class TestSignificanceInflation:
    def test_pivotal(self):
        result = humanize("This was a pivotal moment.")
        assert "pivotal" not in result

    def test_transformative(self):
        result = humanize("This is a transformative approach.")
        assert "transformative" not in result

    def test_groundbreaking(self):
        result = humanize("This is a groundbreaking discovery.")
        assert "groundbreaking" not in result


class TestRuleStructure:
    def test_default_rules_not_empty(self):
        assert len(DEFAULT_RULES) > 0

    def test_each_rule_has_required_fields(self):
        for rule in DEFAULT_RULES:
            assert isinstance(rule, HumanizerRule)
            assert rule.name
            assert rule.pattern
            assert rule.description

    def test_humanize_empty_string(self):
        assert humanize("") == ""

    def test_humanize_none_returns_empty(self):
        assert humanize(None) == ""

    def test_humanize_preserves_normal_text(self):
        text = "The server is running on port 8080."
        assert humanize(text) == text

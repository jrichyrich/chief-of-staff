"""Rule-based text humanizer for outbound communications."""

from humanizer.rules import humanize, HumanizerRule, DEFAULT_RULES
from humanizer.hook import humanize_hook

__all__ = ["humanize", "HumanizerRule", "DEFAULT_RULES", "humanize_hook"]

"""Rule-based text transformer that removes common AI writing patterns.

Based on Wikipedia's "Signs of AI writing" guide and the blader/humanizer
Claude Code skill. Each rule is a regex pattern with a replacement.
"""

import re
from dataclasses import dataclass
from typing import Union, Callable


@dataclass
class HumanizerRule:
    """A single text transformation rule."""
    name: str
    pattern: re.Pattern
    replacement: Union[str, Callable[[re.Match], str]]
    description: str


def _build_rules() -> list[HumanizerRule]:
    """Build the default set of humanizer rules."""
    rules = []

    # --- Em dash removal ---
    rules.append(HumanizerRule(
        name="em_dash",
        pattern=re.compile(r"\s*\u2014\s*"),
        replacement=", ",
        description="Replace em dashes with commas",
    ))
    rules.append(HumanizerRule(
        name="double_hyphen_em_dash",
        pattern=re.compile(r"\s*--\s*"),
        replacement=", ",
        description="Replace double-hyphen em dashes with commas",
    ))

    # --- AI vocabulary swaps ---
    vocab_swaps = [
        (r"\bAdditionally\b", "Also"),
        (r"\badditionally\b", "also"),
        (r"\butilize\b", "use"),
        (r"\bUtilize\b", "Use"),
        (r"\butilizing\b", "using"),
        (r"\bUtilizing\b", "Using"),
        (r"\bleverage\b", "use"),
        (r"\bLeverage\b", "Use"),
        (r"\bleveraging\b", "using"),
        (r"\bLeveraging\b", "Using"),
        (r"\bfacilitate\b", "help with"),
        (r"\bFacilitate\b", "Help with"),
        (r"\bfacilitating\b", "helping with"),
        (r"\bcomprehensive\b", "full"),
        (r"\bComprehensive\b", "Full"),
        (r"\brobust\b", "solid"),
        (r"\bRobust\b", "Solid"),
        (r"\bseamless\b", "smooth"),
        (r"\bSeamless\b", "Smooth"),
        (r"\bseamlessly\b", "smoothly"),
        (r"\bstreamline\b", "simplify"),
        (r"\bStreamline\b", "Simplify"),
        (r"\bstreamlining\b", "simplifying"),
        (r"\bdelve\b", "look into"),
        (r"\bDelve\b", "Look into"),
        (r"\bdelving\b", "looking into"),
        (r"\bpivotal\b", "important"),
        (r"\bPivotal\b", "Important"),
        (r"\btransformative\b", "significant"),
        (r"\bTransformative\b", "Significant"),
        (r"\bgroundbreaking\b", "notable"),
        (r"\bGroundbreaking\b", "Notable"),
        (r"\bparadigm\b", "approach"),
        (r"\bParadigm\b", "Approach"),
        (r"\bsynergy\b", "collaboration"),
        (r"\btestament\b", "sign"),
        (r"\bTestament\b", "Sign"),
        (r"\blandscape\b", "space"),
        (r"\bLandscape\b", "Space"),
        (r"\bshowcasing\b", "showing"),
        (r"\bShowcasing\b", "Showing"),
        (r"\bshowcase\b", "show"),
        (r"\bShowcase\b", "Show"),
        (r"\bunderscoring\b", "highlighting"),
        (r"\bunderscore\b", "highlight"),
    ]
    for pattern_str, repl in vocab_swaps:
        name = pattern_str.strip(r"\b").lower()
        rules.append(HumanizerRule(
            name=f"vocab_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Replace '{name}' with '{repl}'",
        ))

    # --- Filler phrases ---
    filler_swaps = [
        (r"In order to\b", "To"),
        (r"in order to\b", "to"),
        (r"Due to the fact that\b", "Because"),
        (r"due to the fact that\b", "because"),
        (r"It is worth noting that ", ""),
        (r"it is worth noting that ", ""),
        (r"It should be noted that ", ""),
        (r"it should be noted that ", ""),
        (r"At the end of the day, ", ""),
        (r"at the end of the day, ", ""),
        (r"It goes without saying that ", ""),
        (r"Needless to say, ", ""),
        (r"needless to say, ", ""),
    ]
    for pattern_str, repl in filler_swaps:
        name = pattern_str[:30].strip().lower().replace(" ", "_")
        rules.append(HumanizerRule(
            name=f"filler_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Remove filler phrase",
        ))

    # --- Sycophantic patterns ---
    syco_patterns = [
        (r"Great question!\s*", ""),
        (r"That's a great question!\s*", ""),
        (r"Excellent question!\s*", ""),
        (r"I hope this helps!?\s*", ""),
        (r"Let me know if you have any (?:other )?questions!?\s*", ""),
        (r"Absolutely!\s*", ""),
        (r"You're absolutely right!\s*", ""),
    ]
    for pattern_str, repl in syco_patterns:
        name = pattern_str[:25].strip().lower().replace(" ", "_").replace(r"\s*", "")
        rules.append(HumanizerRule(
            name=f"syco_{name}",
            pattern=re.compile(pattern_str, re.IGNORECASE),
            replacement=repl,
            description="Remove sycophantic pattern",
        ))

    # --- Copula avoidance ---
    copula_swaps = [
        (r"\bserves as\b", "is"),
        (r"\bServes as\b", "Is"),
        (r"\bfunctions as\b", "is"),
        (r"\bFunctions as\b", "Is"),
        (r"\bstands as\b", "is"),
        (r"\bStands as\b", "Is"),
        (r"\bacts as\b", "is"),
        (r"\bActs as\b", "Is"),
    ]
    for pattern_str, repl in copula_swaps:
        name = pattern_str.strip(r"\b").lower().replace(" ", "_")
        rules.append(HumanizerRule(
            name=f"copula_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Replace '{name}' with '{repl}'",
        ))

    # --- Hedging ---
    hedge_patterns = [
        (r"\bcould potentially\b", "could"),
        (r"\bCould potentially\b", "Could"),
        (r"\bmight potentially\b", "might"),
        (r"\bcould possibly\b", "could"),
    ]
    for pattern_str, repl in hedge_patterns:
        name = pattern_str.strip(r"\b").lower().replace(" ", "_")
        rules.append(HumanizerRule(
            name=f"hedge_{name}",
            pattern=re.compile(pattern_str),
            replacement=repl,
            description=f"Reduce hedging: '{name}' to '{repl}'",
        ))

    return rules


DEFAULT_RULES: list[HumanizerRule] = _build_rules()


def humanize(text: str | None, rules: list[HumanizerRule] | None = None) -> str:
    """Apply humanizer rules to text, returning the cleaned version.

    Args:
        text: Input text to humanize. None returns empty string.
        rules: Optional custom rule list. Defaults to DEFAULT_RULES.

    Returns:
        Cleaned text with AI patterns removed.
    """
    if not text:
        return ""

    if rules is None:
        rules = DEFAULT_RULES

    result = text
    for rule in rules:
        result = rule.pattern.sub(rule.replacement, result)

    # Clean up double spaces left by removals
    result = re.sub(r"  +", " ", result)
    # Clean up space before punctuation
    result = re.sub(r" ([.,;:!?])", r"\1", result)
    # Clean up leading space on lines
    result = re.sub(r"(?m)^ +", "", result)

    return result.strip()

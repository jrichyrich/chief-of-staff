# agents/loop_detector.py
"""Detects repetitive tool-call patterns in agent execution loops."""
import hashlib
import json
from collections import Counter


class LoopDetector:
    """Tracks tool calls and detects repetitive patterns.

    Patterns detected:
    - Same (tool_name, args) repeated >= warn_threshold or break_threshold times
    - A-B-A-B alternation (two distinct calls repeating in sequence)
    """

    def __init__(self, warn_threshold: int = 3, break_threshold: int = 5):
        self.warn_threshold = warn_threshold
        self.break_threshold = break_threshold
        self._counts: Counter = Counter()
        self._history: list[str] = []

    def _make_key(self, tool_name: str, tool_args: dict) -> str:
        normalized = json.dumps(tool_args, sort_keys=True, default=str)
        args_hash = hashlib.md5(normalized.encode()).hexdigest()
        return f"{tool_name}:{args_hash}"

    def record(self, tool_name: str, tool_args: dict) -> str:
        """Record a tool call and return 'ok', 'warning', or 'break'."""
        key = self._make_key(tool_name, tool_args)
        self._counts[key] += 1
        self._history.append(key)

        count = self._counts[key]
        if count >= self.break_threshold:
            return "break"
        if count >= self.warn_threshold:
            return "warning"

        # Check A-B-A-B alternation (need at least 4 entries)
        if len(self._history) >= 4:
            h = self._history
            if (h[-1] == h[-3] and h[-2] == h[-4] and h[-1] != h[-2]):
                return "warning"

        return "ok"

    def reset(self) -> None:
        """Clear all tracked state."""
        self._counts.clear()
        self._history.clear()

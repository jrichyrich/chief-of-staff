"""Teams navigation using the agent-browser CLI.

Replaces CSS-selector-based navigation (browser/navigator.py) with
accessibility-tree snapshots and keyboard shortcuts via the
agent-browser daemon.

Uses keyboard shortcuts for navigation (reliable) and snapshot parsing
for element identification (resilient to DOM changes).
"""

import asyncio
import logging
import re
from typing import Optional

from browser.agent_browser import AgentBrowser, AgentBrowserError

logger = logging.getLogger(__name__)

# Teams keyboard shortcuts (macOS)
SHORTCUT_NEW_MESSAGE = "Control+Shift+KeyN"
SHORTCUT_SEARCH = "Meta+e"

# Patterns that look like date-separator headings in the chat area
_DATE_WORDS = re.compile(
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|january|february|march|april|may|june|july|august"
    r"|september|october|november|december"
    r"|today|yesterday|\d{4})",
    re.IGNORECASE,
)


class ABNavigator:
    """Navigate within Teams using agent-browser snapshots.

    Uses keyboard shortcuts for navigation and accessibility-tree
    snapshots for element identification, making it resilient to
    Teams DOM changes.
    """

    def __init__(self, ab: Optional[AgentBrowser] = None) -> None:
        self._ab = ab or AgentBrowser()

    @staticmethod
    def _extract_ref(result: dict) -> Optional[str]:
        """Extract a @ref ID from an agent-browser result."""
        text = result.get("text", "")
        match = re.search(r"@e\d+", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_refs_with_text(snapshot_text: str) -> list[tuple[str, str]]:
        """Parse snapshot text into (ref, description) pairs.

        Handles two formats:
        - Real agent-browser: ``- heading "Chat" [ref=e17] [level=1]``
        - Legacy/test:        ``@e17 heading 'Chat'``
        """
        pairs = []
        for line in snapshot_text.strip().split("\n"):
            line = line.strip()
            # Real agent-browser format: [ref=eN] inline
            ref_match = re.search(r"\[ref=(e\d+)\]", line)
            if ref_match:
                pairs.append(("@" + ref_match.group(1), line))
                continue
            # Legacy @eN prefix format
            prefix_match = re.match(r"(@e\d+)\s+(.*)", line)
            if prefix_match:
                pairs.append((prefix_match.group(1), prefix_match.group(2)))
        return pairs

    async def _find_ref_in_snapshot(self, *keywords: str) -> Optional[str]:
        """Take a snapshot and find the first element matching all keywords.

        Returns the @ref ID or None.
        """
        snap = await self._ab.snapshot()
        snap_text = snap.get("text", "")
        for ref, desc in self._extract_refs_with_text(snap_text):
            desc_lower = desc.lower()
            if all(kw.lower() in desc_lower for kw in keywords):
                return ref
        return None

    @staticmethod
    def _is_date_heading(name: str) -> bool:
        """Return True if *name* looks like a date separator, not a chat title."""
        return bool(_DATE_WORDS.search(name))

    async def detect_channel_name(self) -> str:
        """Detect the active conversation name from the page snapshot.

        Teams shows the conversation name as a level-2 heading for
        channels/group chats.  For 1:1 chats the name often only appears
        as a ``treeitem "Chat PersonName"`` in the sidebar.
        """
        try:
            result = await self._ab.snapshot()
            text = result.get("text", "")
            skip = {"Chat", "Teams", "Microsoft Teams", "Chat participants"}

            pairs = self._extract_refs_with_text(text)

            # Pass 1: level-2 headings (channels and group chats)
            for ref, desc in pairs:
                desc_lower = desc.lower()
                if "heading" in desc_lower and "[level=2]" in desc:
                    name_match = re.search(r"""['"]([^'"]+)['"]""", desc)
                    if name_match:
                        name = name_match.group(1)
                        if name not in skip and not self._is_date_heading(name):
                            return name

            # Pass 2: any heading that isn't level-1
            for ref, desc in pairs:
                desc_lower = desc.lower()
                if "heading" in desc_lower and "[level=1]" not in desc:
                    name_match = re.search(r"""['"]([^'"]+)['"]""", desc)
                    if name_match:
                        name = name_match.group(1)
                        if (name not in skip
                                and "by " not in name.lower()
                                and not self._is_date_heading(name)):
                            return name

            # Pass 3: 1:1 chats — treeitem "Chat <Name>" or
            # "Chat <Name> (You)" in the sidebar.  Prefer items with
            # [selected] or [focused] attributes; fall back to first match.
            first_chat_name: Optional[str] = None
            for ref, desc in pairs:
                if "treeitem" not in desc.lower():
                    continue
                chat_match = re.search(
                    r"""['"]Chat\s+(.+?)(?:\s*\([^)]*\))?\s*['"]""", desc
                )
                if not chat_match:
                    continue
                name = chat_match.group(1).strip()
                if not name or name in skip:
                    continue
                # Prefer selected/focused treeitem
                if "[selected" in desc.lower() or "[focused" in desc.lower():
                    return name
                if first_chat_name is None:
                    first_chat_name = name
            if first_chat_name:
                return first_chat_name

        except AgentBrowserError:
            pass
        return "(unknown)"

    async def create_group_chat(self, recipients: list[str]) -> dict:
        """Create a new group chat by pressing New Message shortcut and adding recipients.

        Returns:
            dict with "status": "navigated" and "detected_channel" on success,
            or "status": "error" with "error" detail on failure.
        """
        try:
            # 1. Press Ctrl+Shift+N to open new message
            await self._ab.press(SHORTCUT_NEW_MESSAGE)
            await asyncio.sleep(2)

            # 2. Add each recipient via the To field
            failed = []
            for name in recipients:
                name = name.strip()
                if not name:
                    continue
                ok = await self._add_recipient(name)
                if not ok:
                    failed.append(name)

            # 3. Detect channel name — fall back to recipient list for new groups
            await asyncio.sleep(1)
            detected = await self.detect_channel_name()
            if detected == "(unknown)":
                added = [n.strip() for n in recipients if n.strip() and n.strip() not in failed]
                if added:
                    detected = ", ".join(added)

            result = {"status": "navigated", "detected_channel": detected}
            if failed:
                result["warnings"] = f"Could not find: {', '.join(failed)}"
            return result

        except AgentBrowserError as exc:
            return {"status": "error", "error": str(exc)}

    async def _add_recipient(self, name: str) -> bool:
        """Type a recipient name into the To field and select the match."""
        try:
            # Find the To textbox via snapshot
            ref = await self._find_ref_in_snapshot("textbox", "to:")
            if ref is None:
                # Fallback: look for the placeholder text
                ref = await self._find_ref_in_snapshot("textbox", "enter name")
            if ref is None:
                logger.warning("Could not find To field for recipient '%s'", name)
                return False

            # Type the name
            await self._ab.fill(ref, name)
            await asyncio.sleep(2)

            # Get snapshot and find matching suggestion
            snap = await self._ab.snapshot()
            snap_text = snap.get("text", "")
            name_lower = name.lower()

            for sref, desc in self._extract_refs_with_text(snap_text):
                if "option" in desc.lower():
                    if name_lower in desc.lower():
                        await self._ab.click(sref)
                        await asyncio.sleep(1)
                        return True

            # Fallback: click first option
            for sref, desc in self._extract_refs_with_text(snap_text):
                if "option" in desc.lower():
                    logger.info("No exact match for '%s', clicking first suggestion", name)
                    await self._ab.click(sref)
                    await asyncio.sleep(1)
                    return True

            logger.warning("No suggestions found for '%s'", name)
            return False

        except AgentBrowserError as exc:
            logger.warning("Error adding recipient '%s': %s", name, exc)
            return False

    async def search_and_navigate(self, target: str) -> dict:
        """Search for a person/channel and navigate to it.

        Uses Cmd+E keyboard shortcut to activate the search bar.

        Returns:
            dict with "status": "navigated" and "detected_channel" on success,
            or "status": "error" with "error" detail on failure.
        """
        try:
            # 1. Activate search via keyboard shortcut
            await self._ab.press(SHORTCUT_SEARCH)
            await asyncio.sleep(1)

            # 2. Find the active search input via snapshot and type
            ref = await self._find_ref_in_snapshot("combobox", "search")
            if ref is None:
                ref = await self._find_ref_in_snapshot("combobox")
            if ref is None:
                return {"status": "error", "error": "Search bar not found"}

            await self._ab.fill(ref, target)
            await asyncio.sleep(2)

            # 3. Find matching search result
            snap = await self._ab.snapshot()
            snap_text = snap.get("text", "")
            target_lower = target.lower()

            best_ref = None
            for sref, desc in self._extract_refs_with_text(snap_text):
                if "option" in desc.lower():
                    if target_lower in desc.lower():
                        best_ref = sref
                        break

            if best_ref is None:
                for sref, desc in self._extract_refs_with_text(snap_text):
                    if "option" in desc.lower():
                        best_ref = sref
                        break

            if best_ref is None:
                await self._ab.press("Escape")
                return {
                    "status": "error",
                    "error": f"No search results found for '{target}'",
                }

            await self._ab.click(best_ref)
            await asyncio.sleep(2)

            detected = await self.detect_channel_name()
            return {"status": "navigated", "detected_channel": detected}

        except AgentBrowserError as exc:
            return {"status": "error", "error": str(exc)}

    async def find_compose_box(self) -> Optional[str]:
        """Find the compose/reply textbox and return its ref ID."""
        try:
            ref = await self._find_ref_in_snapshot("textbox", "message")
            if ref:
                return ref
            ref = await self._find_ref_in_snapshot("textbox", "reply")
            if ref:
                return ref
            ref = await self._find_ref_in_snapshot("textbox", "type")
            return ref
        except AgentBrowserError:
            pass
        return None

"""Teams navigation using the agent-browser CLI.

Replaces CSS-selector-based navigation (browser/navigator.py) with
accessibility-tree snapshots and semantic element finding via the
agent-browser daemon.
"""

import asyncio
import logging
import re
from typing import Optional

from browser.agent_browser import AgentBrowser, AgentBrowserError

logger = logging.getLogger(__name__)


class ABNavigator:
    """Navigate within Teams using agent-browser snapshots.

    Uses semantic locators (role, text, label, placeholder) instead of
    CSS selectors, making it resilient to Teams DOM changes.
    """

    def __init__(self, ab: Optional[AgentBrowser] = None) -> None:
        self._ab = ab or AgentBrowser()

    async def _find_and_click(self, locator: str, value: str, text: str | None = None) -> str:
        """Find an element and click it. Returns the ref ID."""
        result = await self._ab.find(locator, value, text)
        ref = self._extract_ref(result)
        if ref is None:
            raise AgentBrowserError(f"Could not find {locator}={value} text={text}")
        await self._ab.click(ref)
        return ref

    @staticmethod
    def _extract_ref(result: dict) -> Optional[str]:
        """Extract a @ref ID from an agent-browser result."""
        text = result.get("text", "")
        match = re.search(r"@e\d+", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_refs_with_text(snapshot_text: str) -> list[tuple[str, str]]:
        """Parse snapshot text into (ref, description) pairs."""
        pairs = []
        for line in snapshot_text.strip().split("\n"):
            line = line.strip()
            match = re.match(r"(@e\d+)\s+(.*)", line)
            if match:
                pairs.append((match.group(1), match.group(2)))
        return pairs

    async def detect_channel_name(self) -> str:
        """Detect the active conversation name from the page snapshot."""
        try:
            result = await self._ab.snapshot()
            text = result.get("text", "")
            for ref, desc in self._extract_refs_with_text(text):
                if "heading" in desc.lower():
                    name_match = re.search(r"'([^']+)'", desc)
                    if name_match:
                        name = name_match.group(1)
                        if name not in ("Chat", "Teams", "Microsoft Teams"):
                            return name
        except AgentBrowserError:
            pass
        return "(unknown)"

    async def create_group_chat(self, recipients: list[str]) -> dict:
        """Create a new group chat by clicking New Chat and adding recipients.

        Returns:
            dict with "status": "navigated" and "detected_channel" on success,
            or "status": "error" with "error" detail on failure.
        """
        try:
            # 1. Click Chat tab
            await self._find_and_click("role", "button", "Chat")
            await asyncio.sleep(2)

            # 2. Click New Chat / New Message button
            try:
                await self._find_and_click("role", "button", "New chat")
            except AgentBrowserError:
                await self._find_and_click("role", "button", "New message")
            await asyncio.sleep(2)

            # 3. Add each recipient via the To field
            failed = []
            for name in recipients:
                name = name.strip()
                if not name:
                    continue
                ok = await self._add_recipient(name)
                if not ok:
                    failed.append(name)

            # 4. Detect channel name
            await asyncio.sleep(1)
            detected = await self.detect_channel_name()

            result = {"status": "navigated", "detected_channel": detected}
            if failed:
                result["warnings"] = f"Could not find: {', '.join(failed)}"
            return result

        except AgentBrowserError as exc:
            return {"status": "error", "error": str(exc)}

    async def _add_recipient(self, name: str) -> bool:
        """Type a recipient name into the To field and select the match."""
        try:
            # Find the To/people-picker input
            try:
                result = await self._ab.find("placeholder", "Enter name")
            except AgentBrowserError:
                result = await self._ab.find("role", "combobox")

            ref = self._extract_ref(result)
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
                if "option" in desc.lower() or "listitem" in desc.lower():
                    if name_lower in desc.lower():
                        await self._ab.click(sref)
                        await asyncio.sleep(1)
                        return True

            # Fallback: click first option-like element
            for sref, desc in self._extract_refs_with_text(snap_text):
                if "option" in desc.lower() or "listitem" in desc.lower():
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

        Returns:
            dict with "status": "navigated" and "detected_channel" on success,
            or "status": "error" with "error" detail on failure.
        """
        try:
            # 1. Find and click the search bar
            try:
                result = await self._ab.find("placeholder", "Search")
            except AgentBrowserError:
                result = await self._ab.find("role", "searchbox")

            ref = self._extract_ref(result)
            if ref is None:
                return {"status": "error", "error": "Search bar not found"}

            await self._ab.click(ref)
            await asyncio.sleep(0.5)

            # 2. Type the search query
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
            snap = await self._ab.snapshot()
            snap_text = snap.get("text", "")
            for ref, desc in self._extract_refs_with_text(snap_text):
                if "textbox" in desc.lower() and any(
                    kw in desc.lower() for kw in ("message", "reply", "type")
                ):
                    return ref
        except AgentBrowserError:
            pass
        return None

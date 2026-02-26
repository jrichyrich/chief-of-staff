"""Teams in-app navigation via the search bar."""

import asyncio
import logging

from browser.constants import (
    CHAT_LIST_ITEM_SELECTOR,
    CHAT_TAB_SELECTORS,
    CHANNEL_NAME_SELECTORS,
    COMPOSE_SELECTORS,
    FILTER_INPUT_SELECTORS,
    FILTER_SHOW_BTN_SELECTORS,
    NEW_CHAT_SELECTORS,
    POST_TIMEOUT_MS,
    RECIPIENT_SUGGESTION_SELECTOR,
    TO_FIELD_SELECTORS,
)

logger = logging.getLogger(__name__)

# CSS selectors for the Teams search bar, tried in order.
# Confirmed via scripts/teams_search_explore.py
SEARCH_SELECTORS = (
    'input[placeholder*="Search"]',
    'input[aria-label*="Search"]',
    '[data-tid="search-input"]',
    '[data-tid="app-search-input"]',
)

# Selector for actual search result items (TOPHITS), not category filters.
# The dropdown has PRIMARYDOMAIN* items (filter shortcuts like "Messages",
# "Files") and TOPHITS* items (actual people/channel results).
# Confirmed via live DOM exploration 2026-02-23.
SEARCH_RESULT_SELECTOR = 'div[role="option"][data-tid*="TOPHITS"]'


class TeamsNavigator:
    """Navigate within the Teams SPA using the search bar."""

    @staticmethod
    async def _find_element(page, selectors, timeout_ms: int = 10_000):
        """Try each selector with retries. Returns first matching locator or None."""
        elapsed = 0
        interval_ms = 1_000
        while True:
            for selector in selectors:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    return locator
            elapsed += interval_ms
            if elapsed >= timeout_ms:
                return None
            await asyncio.sleep(interval_ms / 1_000)

    @staticmethod
    async def _detect_channel_name(page) -> str:
        """Detect active channel/conversation name from DOM."""
        for selector in CHANNEL_NAME_SELECTORS:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    text = await locator.first.inner_text()
                    text = text.strip()
                    if text:
                        return text
            except Exception:
                continue

        try:
            title = await page.title()
            if title and title not in ("Microsoft Teams", ""):
                for suffix in (" | Microsoft Teams", " - Microsoft Teams"):
                    if title.endswith(suffix):
                        title = title[: -len(suffix)]
                return title.strip() or "(unknown)"
        except Exception:
            pass

        return "(unknown)"

    @staticmethod
    async def _find_matching_result(locator, target: str):
        """Find the search result whose text contains *target*.

        Returns the matching element locator, or ``None`` if no match.
        """
        target_lower = target.lower()
        count = await locator.count()
        for i in range(count):
            try:
                text = await locator.nth(i).inner_text()
                if target_lower in text.lower():
                    return locator.nth(i)
            except Exception:
                continue
        return None

    @staticmethod
    def _name_fallbacks(target: str) -> list[str]:
        """Generate shorter name variants for search fallback.

        For "Jonas de Oliveira" returns ["Jonas Oliveira", "Jonas"].
        For "Jonas Oliveira" returns ["Jonas"].
        For "Jonas" returns [].
        """
        words = target.split()
        if len(words) <= 1:
            return []
        fallbacks = []
        if len(words) > 2:
            fallbacks.append(f"{words[0]} {words[-1]}")
        fallbacks.append(words[0])
        return fallbacks

    async def _open_sidebar_filter(self, page):
        """Open the sidebar filter text box if not already visible.

        Returns the filter input locator, or ``None`` if it can't be opened.
        """
        # Check if filter input is already visible
        f_input = await self._find_element(page, FILTER_INPUT_SELECTORS, timeout_ms=2_000)
        if f_input is not None:
            return f_input

        # Click the "Show filter text box" button
        show_btn = await self._find_element(page, FILTER_SHOW_BTN_SELECTORS, timeout_ms=3_000)
        if show_btn is None:
            return None
        await show_btn.first.click()
        await asyncio.sleep(1)

        return await self._find_element(page, FILTER_INPUT_SELECTORS, timeout_ms=3_000)

    @staticmethod
    def _match_chat_item(item_text: str, participants: list[str]) -> int:
        """Score how well a chat item matches the requested participants.

        Returns a score (higher is better). 0 means no match.
        For multiple participants, prefer items whose text contains
        multiple participant names (group chats) over single-name matches.

        Scoring:
        - Full name match = 2 points per participant
        - First name match = 1 point per participant
        - Bonus: +10 if more than one participant matched (prefers group chats)
        """
        text_lower = item_text.lower()
        matched_count = 0
        score = 0
        for name in participants:
            if name.lower() in text_lower:
                score += 2
                matched_count += 1
            elif name.split()[0].lower() in text_lower:
                score += 1
                matched_count += 1
        # Bonus for group chat matches (multiple participants found)
        if matched_count > 1:
            score += 10
        return score

    async def find_existing_chat(self, page, participants: list[str]) -> dict:
        """Find an existing chat by participant names using the sidebar filter.

        Opens the Chat tab, uses the filter text box to narrow the sidebar,
        then finds and clicks a matching chat item.

        Returns a dict with:
        - ``"status": "navigated"`` and ``"detected_channel"`` on success
        - ``"status": "not_found"`` if no matching chat exists
        - ``"status": "error"`` with ``"error"`` detail on failure
        """
        # 1. Navigate to Chat tab
        chat_tab = await self._find_element(page, CHAT_TAB_SELECTORS, timeout_ms=5_000)
        if chat_tab is None:
            return {
                "status": "error",
                "error": "Chat tab not found. Is Teams loaded?",
            }
        await chat_tab.first.click()
        await asyncio.sleep(2)

        # 2. Open the sidebar filter
        f_input = await self._open_sidebar_filter(page)
        if f_input is None:
            return {
                "status": "error",
                "error": "Could not open sidebar filter text box.",
            }

        # 3. Type the first participant's name to narrow results
        search_name = participants[0].split()[0]  # Use first name for broader match
        await f_input.first.click()
        await f_input.first.fill(search_name)
        await asyncio.sleep(2)

        # 4. Find level-2 treeitems (actual chats, not section headers)
        items = page.locator(CHAT_LIST_ITEM_SELECTOR)
        count = await items.count()

        if count == 0:
            # Clear filter before returning
            await f_input.first.fill("")
            return {"status": "not_found"}

        # 5. Score each item and find best match
        best_idx = -1
        best_score = 0
        for i in range(count):
            try:
                text = await items.nth(i).inner_text()
                score = self._match_chat_item(text, participants)
                if score > best_score:
                    best_score = score
                    best_idx = i
            except Exception:
                continue

        if best_idx < 0 or best_score == 0:
            await f_input.first.fill("")
            return {"status": "not_found"}

        # 6. Click the matching chat item
        logger.info("Found matching chat at index %d (score=%d)", best_idx, best_score)
        await items.nth(best_idx).click()
        await asyncio.sleep(2)

        # 7. Clear the filter
        # Re-find input since DOM may have changed after click
        f_input_after = await self._find_element(page, FILTER_INPUT_SELECTORS, timeout_ms=2_000)
        if f_input_after is not None:
            await f_input_after.first.fill("")

        # 8. Wait for compose box to confirm navigation
        compose = await self._find_element(
            page, COMPOSE_SELECTORS, timeout_ms=POST_TIMEOUT_MS
        )
        if compose is None:
            return {
                "status": "error",
                "error": "Navigated to chat but compose box not found.",
            }

        detected = await self._detect_channel_name(page)
        return {
            "status": "navigated",
            "detected_channel": detected,
        }

    async def _add_recipient(self, page, to_field, name: str) -> bool:
        """Type a recipient name into the To: field and select the match.

        Returns True if a suggestion was found and clicked, False otherwise.
        """
        await to_field.click()
        await to_field.fill(name)
        await asyncio.sleep(2)  # Wait for suggestions to load

        suggestions = page.locator(RECIPIENT_SUGGESTION_SELECTOR)
        elapsed = 0
        while await suggestions.count() == 0 and elapsed < 8_000:
            await asyncio.sleep(1)
            elapsed += 1_000

        count = await suggestions.count()
        if count == 0:
            logger.warning("No suggestions found for recipient '%s'", name)
            return False

        # Find best match by name
        name_lower = name.lower()
        for i in range(count):
            try:
                text = await suggestions.nth(i).inner_text()
                if name_lower in text.lower():
                    logger.info("Selecting recipient: %s", text.strip()[:60])
                    await suggestions.nth(i).click()
                    await asyncio.sleep(1)
                    return True
            except Exception:
                continue

        # Fallback: click first suggestion
        logger.info("No exact match for '%s', selecting first suggestion", name)
        await suggestions.first.click()
        await asyncio.sleep(1)
        return True

    async def create_group_chat(self, page, recipients: list[str]) -> dict:
        """Create a new group chat with the given recipients.

        Navigates to the Chat tab, clicks "New message", adds each
        recipient via the people picker, and waits for the compose box.

        Returns a dict with:
        - ``"status": "navigated"`` and ``"detected_channel"`` on success
        - ``"status": "error"`` with ``"error"`` detail on failure
        """
        # 1. Navigate to Chat tab
        chat_tab = await self._find_element(page, CHAT_TAB_SELECTORS, timeout_ms=5_000)
        if chat_tab is None:
            return {
                "status": "error",
                "error": "Chat tab not found. Is Teams loaded?",
            }
        await chat_tab.first.click()
        await asyncio.sleep(2)

        # 2. Click "New message" button
        new_chat_btn = await self._find_element(page, NEW_CHAT_SELECTORS, timeout_ms=5_000)
        if new_chat_btn is None:
            return {
                "status": "error",
                "error": "New message button not found in chat pane.",
            }
        await new_chat_btn.first.click()
        await asyncio.sleep(2)

        # 3. Find the To: field
        to_field = await self._find_element(page, TO_FIELD_SELECTORS, timeout_ms=5_000)
        if to_field is None:
            return {
                "status": "error",
                "error": "To: recipient field not found. Could not create group chat.",
            }

        # 4. Add each recipient
        failed = []
        for name in recipients:
            name = name.strip()
            if not name:
                continue
            ok = await self._add_recipient(page, to_field.first, name)
            if not ok:
                failed.append(name)
            # Re-find the To: field (DOM may update after each selection)
            to_field = await self._find_element(page, TO_FIELD_SELECTORS, timeout_ms=3_000)
            if to_field is None:
                break

        if failed:
            logger.warning("Could not find suggestions for: %s", ", ".join(failed))

        # 5. Wait for compose box
        compose = await self._find_element(
            page, COMPOSE_SELECTORS, timeout_ms=POST_TIMEOUT_MS
        )
        if compose is None:
            return {
                "status": "error",
                "error": "Compose box not found after adding recipients.",
            }

        detected = await self._detect_channel_name(page)
        result = {
            "status": "navigated",
            "detected_channel": detected,
        }
        if failed:
            result["warnings"] = f"Could not find: {', '.join(failed)}"
        return result

    async def search_and_navigate(self, page, target: str) -> dict:
        """Search for *target* in Teams and navigate to it.

        Returns a dict with:
        - ``"status": "navigated"`` and ``"detected_channel"`` on success
        - ``"status": "error"`` with ``"error"`` detail on failure
        """
        # Find the search bar
        search_bar = await self._find_element(page, SEARCH_SELECTORS, timeout_ms=10_000)
        if search_bar is None:
            # Auto-recover: reload page and retry once
            logger.info("Search bar not found, reloading page and retrying")
            try:
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(3)
            except Exception as exc:
                logger.warning("Page reload failed during recovery: %s", exc)
            search_bar = await self._find_element(page, SEARCH_SELECTORS, timeout_ms=10_000)
            if search_bar is None:
                return {
                    "status": "error",
                    "error": "Could not find Teams search bar. Is Teams loaded?",
                }

        # Click search bar
        await search_bar.click()
        await asyncio.sleep(0.5)

        queries = [target] + self._name_fallbacks(target)
        result_items = None
        match = None

        for query in queries:
            await page.keyboard.press("Meta+a")  # Select all existing text
            await page.keyboard.type(query, delay=50)
            await asyncio.sleep(2)  # Wait for search results

            # Find search results (TOPHITS only)
            result_items = await self._find_element(
                page, (SEARCH_RESULT_SELECTOR,), timeout_ms=10_000
            )
            if result_items is None:
                logger.info("No results for '%s', trying next fallback", query)
                continue

            # Match against the ORIGINAL full target name
            match = await self._find_matching_result(result_items, target)
            if match is not None:
                break
            # If TOPHITS exist but none match the full name, still use them
            logger.info("Results found for '%s' but no text match for '%s'", query, target)
            break

        if result_items is None:
            await page.keyboard.press("Escape")
            return {
                "status": "error",
                "error": f"No search results found for '{target}'.",
            }

        if match is None:
            logger.info("No exact match for '%s', clicking first result", target)
            match = result_items.first

        await match.click()
        await asyncio.sleep(2)  # Wait for navigation

        # Wait for compose box to confirm we're in a conversation
        compose = await self._find_element(
            page, COMPOSE_SELECTORS, timeout_ms=POST_TIMEOUT_MS
        )
        if compose is None:
            return {
                "status": "error",
                "error": (
                    f"Navigated to '{target}' but compose box not found. "
                    "May have landed on a non-conversation page."
                ),
            }

        detected = await self._detect_channel_name(page)
        return {
            "status": "navigated",
            "detected_channel": detected,
        }

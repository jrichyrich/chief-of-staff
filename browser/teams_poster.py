"""Playwright-based Microsoft Teams message poster.

Uses a persistent browser managed by TeamsBrowserManager and navigates
to channels/people by name via TeamsNavigator.

Two-phase posting flow:
1. ``prepare_message`` -- connects to running browser, navigates to
   target, detects active channel, returns confirmation info.
2. ``send_prepared_message`` -- types the message and presses Enter.
3. ``cancel_prepared_message`` -- disconnects without sending.
"""

import asyncio
import logging
from typing import Optional

from browser.constants import COMPOSE_SELECTORS, POST_TIMEOUT_MS
from browser.manager import TeamsBrowserManager
from browser.navigator import TeamsNavigator

logger = logging.getLogger(__name__)


class PlaywrightTeamsPoster:
    """Post messages to Microsoft Teams via a persistent browser.

    Two-phase flow:
    1. :meth:`prepare_message` connects to the running browser,
       navigates to the target, and returns confirmation info.
    2. :meth:`send_prepared_message` types and sends the message.
    3. :meth:`cancel_prepared_message` disconnects without sending.
    """

    def __init__(
        self,
        manager: Optional[TeamsBrowserManager] = None,
        navigator: Optional[TeamsNavigator] = None,
    ):
        self._manager = manager or TeamsBrowserManager()
        self._navigator = navigator or TeamsNavigator()
        self._pw = None
        self._page = None
        self._compose = None
        self._pending_message: Optional[str] = None

    @property
    def has_pending_message(self) -> bool:
        """Return True if there is a prepared message waiting to send."""
        return self._pending_message is not None and self._page is not None

    async def _disconnect(self) -> None:
        """Disconnect from browser (does NOT close the browser)."""
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = None
        self._page = None
        self._compose = None
        self._pending_message = None

    @staticmethod
    async def _find_compose_box(page, timeout_ms: int = POST_TIMEOUT_MS):
        """Try each selector in :data:`COMPOSE_SELECTORS` with retries.

        The Teams SPA takes several seconds to render after navigation.
        Retries every 2s up to *timeout_ms* before giving up.
        Returns the first locator that matches, or ``None``.
        """
        elapsed = 0
        interval_ms = 2_000
        while elapsed < timeout_ms:
            for selector in COMPOSE_SELECTORS:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    return locator
            await asyncio.sleep(interval_ms / 1_000)
            elapsed += interval_ms
        return None

    async def prepare_message(self, target: str, message: str) -> dict:
        """Phase 1: connect to browser, navigate to target, return confirmation.

        Args:
            target: Channel name or person name to search for in Teams.
            message: The message text to post.

        Returns a dict with ``"status"`` of ``"confirm_required"`` on
        success (with ``"detected_channel"``, ``"message"``, and ``"target"``),
        or ``"error"`` on failure.
        """
        if not self._manager.is_alive():
            return {
                "status": "error",
                "error": "Browser is not running. Call open_teams_browser first.",
            }

        # Clean up any leftover state from a previous prepare
        if self.has_pending_message:
            await self._disconnect()

        try:
            self._pw, browser = await self._manager.connect()
            ctx = browser.contexts[0]
            self._page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            nav_result = await self._navigator.search_and_navigate(self._page, target)
            if nav_result["status"] != "navigated":
                await self._disconnect()
                return nav_result

            self._compose = await self._find_compose_box(self._page)
            if self._compose is None:
                await self._disconnect()
                return {
                    "status": "error",
                    "error": "Could not find compose box after navigation.",
                }

            detected = nav_result["detected_channel"]
            self._pending_message = message

            return {
                "status": "confirm_required",
                "detected_channel": detected,
                "message": message,
                "target": target,
            }

        except Exception as exc:
            logger.exception("Failed to prepare Teams message")
            await self._disconnect()
            return {"status": "error", "error": str(exc)}

    async def send_prepared_message(self) -> dict:
        """Phase 2: type the pending message into the compose box and send.

        Must be called after :meth:`prepare_message` returned
        ``"confirm_required"``.  Disconnects from the browser after sending.
        """
        if not self.has_pending_message:
            return {
                "status": "error",
                "error": "No pending message. Call prepare_message first.",
            }

        try:
            # Re-detect the channel in case user navigated during confirmation
            detected = await TeamsNavigator._detect_channel_name(self._page)

            await self._compose.click()
            await self._compose.fill(self._pending_message)
            await self._page.keyboard.press("Enter")

            # Allow a moment for the message to dispatch
            await self._page.wait_for_timeout(1_000)

            result = {
                "status": "sent",
                "detected_channel": detected,
                "message": self._pending_message,
            }

        except Exception as exc:
            logger.exception("Failed to send prepared Teams message")
            result = {"status": "error", "error": str(exc)}

        finally:
            await self._disconnect()

        return result

    async def cancel_prepared_message(self) -> dict:
        """Cancel a prepared message and disconnect without sending."""
        had_pending = self.has_pending_message
        await self._disconnect()
        if had_pending:
            return {"status": "cancelled"}
        return {"status": "error", "error": "No pending message to cancel."}

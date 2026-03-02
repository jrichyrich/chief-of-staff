"""Agent-browser-based Teams message poster.

Drop-in replacement for PlaywrightTeamsPoster. Uses AgentBrowser CLI
instead of raw Playwright for resilient Teams interaction.

Two-phase posting flow (same interface as PlaywrightTeamsPoster):
1. prepare_message — navigate to target, return confirmation
2. send_prepared_message — type and send
3. cancel_prepared_message — abort without sending
"""

import logging
from typing import Optional, Union

from browser.agent_browser import AgentBrowser, AgentBrowserError
from browser.ab_navigator import ABNavigator

logger = logging.getLogger(__name__)


class ABTeamsPoster:
    """Post Teams messages via the agent-browser CLI."""

    def __init__(
        self,
        ab: Optional[AgentBrowser] = None,
        navigator: Optional[ABNavigator] = None,
    ) -> None:
        self._ab = ab or AgentBrowser()
        self._navigator = navigator or ABNavigator(self._ab)
        self._compose_ref: Optional[str] = None
        self._pending_message: Optional[str] = None

    @property
    def has_pending_message(self) -> bool:
        return self._pending_message is not None and self._compose_ref is not None

    def _clear_pending(self) -> None:
        self._compose_ref = None
        self._pending_message = None

    async def prepare_message(self, target: Union[str, list[str]], message: str) -> dict:
        """Navigate to target and prepare message for sending.

        For list targets, always creates a new group chat.
        For string targets, searches and navigates.

        Returns dict with "status": "confirm_required" on success.
        """
        if self.has_pending_message:
            self._clear_pending()

        try:
            if isinstance(target, list):
                nav_result = await self._navigator.create_group_chat(target)
            else:
                nav_result = await self._navigator.search_and_navigate(target)

            if nav_result["status"] != "navigated":
                return nav_result

            # Find compose box
            compose_ref = await self._navigator.find_compose_box()
            if compose_ref is None:
                return {
                    "status": "error",
                    "error": "Compose box not found after navigation.",
                }

            self._compose_ref = compose_ref
            self._pending_message = message

            return {
                "status": "confirm_required",
                "detected_channel": nav_result.get("detected_channel", "(unknown)"),
                "message": message,
                "target": target,
            }

        except AgentBrowserError as exc:
            self._clear_pending()
            return {"status": "error", "error": str(exc)}

    async def send_prepared_message(self) -> dict:
        """Type and send the pending message."""
        if not self.has_pending_message:
            return {"status": "error", "error": "No pending message. Call prepare_message first."}

        try:
            detected = await self._navigator.detect_channel_name()

            await self._ab.fill(self._compose_ref, self._pending_message)

            # Try clicking Send button via snapshot, fall back to Enter
            send_ref = await self._navigator._find_ref_in_snapshot("button", "send")
            if send_ref:
                await self._ab.click(send_ref)
            else:
                await self._ab.press("Enter")

            msg = self._pending_message
            self._clear_pending()
            return {"status": "sent", "detected_channel": detected, "message": msg}

        except AgentBrowserError as exc:
            self._clear_pending()
            return {"status": "error", "error": str(exc)}

    async def send_message(self, target: Union[str, list[str]], message: str) -> dict:
        """One-shot: prepare + send."""
        result = await self.prepare_message(target, message)
        if result["status"] != "confirm_required":
            return result
        return await self.send_prepared_message()

    async def cancel_prepared_message(self) -> dict:
        """Cancel without sending."""
        had_pending = self.has_pending_message
        self._clear_pending()
        if had_pending:
            return {"status": "cancelled"}
        return {"status": "error", "error": "No pending message to cancel."}

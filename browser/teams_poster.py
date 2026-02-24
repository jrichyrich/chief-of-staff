"""Playwright-based Microsoft Teams message poster.

Uses a headed Chromium browser with persistent session storage to post
messages to Teams channels. Handles Microsoft/Okta SSO login detection
and waits for the user to complete authentication when needed.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Default path for persisted browser session (storage state JSON).
SESSION_PATH = Path("data/playwright/teams_session.json")

# Timeout (ms) for waiting for user to complete SSO authentication.
AUTH_TIMEOUT_MS = 120_000

# Timeout (ms) for finding the compose box and posting a message.
POST_TIMEOUT_MS = 30_000

# URL substrings that indicate an SSO / login page.
LOGIN_PATTERNS = (
    "login.microsoftonline.com",
    ".okta.com",
    "login.microsoft.com",
)

# CSS selectors to locate the Teams compose / reply box, tried in order.
COMPOSE_SELECTORS = (
    '[data-tid="ckeditor-replyConversation"]',
    'div[role="textbox"][aria-label*="message"]',
    'div[role="textbox"][aria-label*="Reply"]',
    'div[contenteditable="true"][data-tid]',
)


class PlaywrightTeamsPoster:
    """Post messages to Microsoft Teams channels via Playwright automation.

    The poster launches a headed Chromium instance, navigates to the given
    channel URL, waits for authentication if needed, finds the compose box,
    types the message, and presses Enter.  Browser session state is
    persisted to disk so subsequent calls skip login.
    """

    def __init__(self, session_path: Optional[Path] = None):
        self.session_path = session_path or SESSION_PATH

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _load_session(self) -> Optional[dict]:
        """Load stored browser session state from disk.

        Returns ``None`` if the file is missing, unreadable, or contains
        invalid JSON.
        """
        try:
            return json.loads(self.session_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _save_session_sync(self, state: dict) -> None:
        """Persist browser session state to disk, creating parent dirs."""
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(state))

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_login_page(url: str) -> bool:
        """Return True if *url* looks like a Microsoft / Okta login page."""
        for pattern in LOGIN_PATTERNS:
            if pattern in url:
                return True
        return False

    async def _wait_for_auth(self, page) -> bool:
        """Poll *page* URL every 1 s until it leaves the login page.

        Returns ``True`` if the user completed auth within
        :data:`AUTH_TIMEOUT_MS`, ``False`` on timeout.
        """
        elapsed = 0
        interval_ms = 1_000
        while elapsed < AUTH_TIMEOUT_MS:
            if not self._is_login_page(page.url):
                return True
            await asyncio.sleep(interval_ms / 1_000)
            elapsed += interval_ms
        return False

    # ------------------------------------------------------------------
    # Compose-box detection
    # ------------------------------------------------------------------

    @staticmethod
    async def _find_compose_box(page):
        """Try each selector in :data:`COMPOSE_SELECTORS` and return the
        first locator that matches at least one element, or ``None``.
        """
        for selector in COMPOSE_SELECTORS:
            locator = page.locator(selector)
            if await locator.count() > 0:
                return locator
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def post_message(self, channel_url: str, message: str) -> dict:
        """Post *message* to the Teams channel at *channel_url*.

        Returns a dict with ``"status"`` (``"sent"``, ``"auth_required"``,
        or ``"error"``) and optional ``"error"`` detail.
        """
        browser = None
        try:
            pw = await async_playwright().start()
            session = self._load_session()
            launch_kwargs = {"headless": False}
            browser = await pw.chromium.launch(**launch_kwargs)

            context_kwargs: dict = {}
            if session is not None:
                context_kwargs["storage_state"] = session
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            await page.goto(channel_url, wait_until="domcontentloaded")

            # Handle SSO login if redirected
            if self._is_login_page(page.url):
                logger.info("Login page detected — waiting for user auth")
                authed = await self._wait_for_auth(page)
                if not authed:
                    return {
                        "status": "auth_required",
                        "error": (
                            "Authentication timed out. Please re-run and "
                            "complete login within the browser window."
                        ),
                    }
                # Persist session after successful login
                state = await context.storage_state()
                self._save_session_sync(state)

            # Locate the compose box
            compose = await self._find_compose_box(page)
            if compose is None:
                return {
                    "status": "error",
                    "error": (
                        "Could not find compose box. The Teams UI may have "
                        "changed or the page did not load completely."
                    ),
                }

            # Type and send
            await compose.click()
            await compose.fill(message)
            await page.keyboard.press("Enter")

            # Allow a moment for the message to dispatch
            await page.wait_for_timeout(1_000)

            # Persist session for next time
            state = await context.storage_state()
            self._save_session_sync(state)

            return {"status": "sent", "channel_url": channel_url}

        except Exception as exc:
            logger.exception("Failed to post Teams message")
            return {"status": "error", "error": str(exc)}

        finally:
            if browser is not None:
                await browser.close()

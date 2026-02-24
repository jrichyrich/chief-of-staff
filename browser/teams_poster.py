"""Playwright-based Microsoft Teams message poster.

Uses a headed Chromium browser with persistent session storage to post
messages to Teams channels. Handles Microsoft/Okta SSO login detection
and waits for the user to complete authentication when needed.

Two-phase posting flow:
1. ``prepare_message`` — opens browser, navigates, detects active
   channel, and returns confirmation info **without** sending.
2. ``send_prepared_message`` — types the message and presses Enter.
3. ``cancel_prepared_message`` — closes the browser without sending.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

logger = logging.getLogger(__name__)

# Default path for persisted browser session (storage state JSON).
try:
    from config import DATA_DIR
    SESSION_PATH = DATA_DIR / "playwright" / "teams_session.json"
except ImportError:
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
    "login.srf",
)

# URL substrings that indicate we've landed on Teams.
TEAMS_PATTERNS = (
    "teams.microsoft.com",
    "teams.cloud.microsoft",
)

# CSS selectors to locate the Teams compose / reply box, tried in order.
COMPOSE_SELECTORS = (
    '[data-tid="ckeditor-replyConversation"]',
    'div[role="textbox"][aria-label*="message"]',
    'div[role="textbox"][aria-label*="Reply"]',
    'div[contenteditable="true"][data-tid]',
)

# CSS selectors to detect the active channel / conversation name.
CHANNEL_NAME_SELECTORS = (
    '[data-tid="chat-header-title"]',
    'h1[data-tid]',
    'h2[data-tid]',
    'span[data-tid="chat-header-channel-name"]',
    '[data-tid="thread-header"] h2',
    '[data-tid="channel-header"] span',
)

# Timeout (ms) for user to navigate to correct channel and confirm.
CONFIRM_TIMEOUT_MS = 300_000  # 5 minutes


class PlaywrightTeamsPoster:
    """Post messages to Microsoft Teams channels via Playwright automation.

    Uses a two-phase flow to prevent sending to the wrong channel:

    1. :meth:`prepare_message` opens the browser, navigates to Teams,
       detects the active channel, and returns confirmation info.
    2. :meth:`send_prepared_message` types the message and sends it.
    3. :meth:`cancel_prepared_message` closes the browser without sending.

    Browser session state is persisted to disk so subsequent calls skip login.
    """

    def __init__(self, session_path: Optional[Path] = None):
        self.session_path = session_path or SESSION_PATH
        # Pending state for two-phase posting
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._compose = None
        self._pending_message: Optional[str] = None

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
        self.session_path.write_text(json.dumps(state, indent=2))
        logger.info("Session saved to %s", self.session_path)

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

    @staticmethod
    def _is_teams_page(url: str) -> bool:
        """Return True if *url* is on a Teams domain."""
        return any(pattern in url for pattern in TEAMS_PATTERNS)

    async def _wait_for_auth(self, page) -> bool:
        """Poll *page* URL every 1 s until it leaves the login page.

        Returns ``True`` if the user completed auth within
        :data:`AUTH_TIMEOUT_MS`, ``False`` on timeout.
        """
        elapsed = 0
        interval_ms = 1_000
        while elapsed < AUTH_TIMEOUT_MS:
            if not self._is_login_page(page.url) and self._is_teams_page(page.url):
                return True
            await asyncio.sleep(interval_ms / 1_000)
            elapsed += interval_ms
        return False

    # ------------------------------------------------------------------
    # Compose-box detection
    # ------------------------------------------------------------------

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
                    logger.debug("Compose box found: %s", selector)
                    return locator
            logger.debug("Compose box not found yet, retrying in %ds...", interval_ms // 1000)
            await asyncio.sleep(interval_ms / 1_000)
            elapsed += interval_ms
        return None

    # ------------------------------------------------------------------
    # Channel name detection
    # ------------------------------------------------------------------

    @staticmethod
    async def _detect_channel_name(page) -> str:
        """Try to extract the active channel or conversation name from the DOM.

        Returns the detected name, or ``"(unknown)"`` if detection fails.
        """
        # Try known selectors first
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

        # Fall back to page title (Teams usually sets it to the channel name)
        try:
            title = await page.title()
            if title and title not in ("Microsoft Teams", ""):
                # Strip common suffixes like "| Microsoft Teams"
                for suffix in (" | Microsoft Teams", " - Microsoft Teams"):
                    if title.endswith(suffix):
                        title = title[: -len(suffix)]
                return title.strip() or "(unknown)"
        except Exception:
            pass

        return "(unknown)"

    # ------------------------------------------------------------------
    # Internal cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self) -> None:
        """Close browser and Playwright, reset pending state."""
        if self._context is not None:
            try:
                state = await self._context.storage_state()
                self._save_session_sync(state)
            except Exception:
                pass
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._compose = None
        self._pending_message = None

    @property
    def has_pending_message(self) -> bool:
        """Return True if there is a prepared message waiting to send."""
        return self._pending_message is not None and self._page is not None

    # ------------------------------------------------------------------
    # Public API — two-phase posting
    # ------------------------------------------------------------------

    async def prepare_message(self, channel_url: str, message: str) -> dict:
        """Phase 1: open browser, navigate, find compose box, detect channel.

        The browser stays open so the user can verify the active channel.
        Returns a dict with ``"status"`` of ``"confirm_required"`` on
        success (with ``"detected_channel"`` and ``"message"``), or
        ``"auth_required"`` / ``"error"`` on failure.
        """
        if async_playwright is None:
            return {
                "status": "error",
                "error": "playwright is not installed. Run: pip install playwright && playwright install chromium",
            }

        # Clean up any leftover state from a previous prepare
        if self.has_pending_message:
            await self._cleanup()

        try:
            self._pw = await async_playwright().start()
            session = self._load_session()
            self._browser = await self._pw.chromium.launch(headless=False)

            context_kwargs: dict = {}
            if session is not None:
                context_kwargs["storage_state"] = session
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()

            await self._page.goto(channel_url, wait_until="domcontentloaded",
                                  timeout=POST_TIMEOUT_MS)

            # Handle SSO login if redirected
            if self._is_login_page(self._page.url):
                logger.info("Login page detected — waiting for user auth")
                authed = await self._wait_for_auth(self._page)
                if not authed:
                    await self._cleanup()
                    return {
                        "status": "auth_required",
                        "error": (
                            "Authentication timed out. Please re-run and "
                            "complete login within the browser window."
                        ),
                    }
                # Persist session after successful login
                state = await self._context.storage_state()
                self._save_session_sync(state)

            # Locate the compose box
            self._compose = await self._find_compose_box(self._page)
            if self._compose is None:
                await self._cleanup()
                return {
                    "status": "error",
                    "error": (
                        "Could not find compose box. The Teams UI may have "
                        "changed or the page did not load completely."
                    ),
                }

            # Detect which channel/conversation is active
            detected = await self._detect_channel_name(self._page)
            self._pending_message = message

            return {
                "status": "confirm_required",
                "detected_channel": detected,
                "message": message,
                "channel_url": channel_url,
            }

        except Exception as exc:
            logger.exception("Failed to prepare Teams message")
            await self._cleanup()
            return {"status": "error", "error": str(exc)}

    async def send_prepared_message(self) -> dict:
        """Phase 2: type the pending message into the compose box and send.

        Must be called after :meth:`prepare_message` returned
        ``"confirm_required"``.  Closes the browser after sending.
        """
        if not self.has_pending_message:
            return {
                "status": "error",
                "error": "No pending message. Call prepare_message first.",
            }

        try:
            # Re-detect the channel in case user navigated during confirmation
            detected = await self._detect_channel_name(self._page)

            await self._compose.click()
            await self._compose.fill(self._pending_message)
            await self._page.keyboard.press("Enter")

            # Allow a moment for the message to dispatch
            await self._page.wait_for_timeout(1_000)

            message = self._pending_message
            result = {
                "status": "sent",
                "detected_channel": detected,
                "message": message,
            }

        except Exception as exc:
            logger.exception("Failed to send prepared Teams message")
            result = {"status": "error", "error": str(exc)}

        finally:
            await self._cleanup()

        return result

    async def cancel_prepared_message(self) -> dict:
        """Cancel a prepared message and close the browser without sending."""
        had_pending = self.has_pending_message
        await self._cleanup()
        if had_pending:
            return {"status": "cancelled"}
        return {"status": "error", "error": "No pending message to cancel."}

    # ------------------------------------------------------------------
    # Legacy one-shot API (kept for backward compatibility)
    # ------------------------------------------------------------------

    async def post_message(self, channel_url: str, message: str) -> dict:
        """One-shot post: prepare, auto-confirm, and send in one call.

        .. deprecated::
            Use :meth:`prepare_message` + :meth:`send_prepared_message`
            for the safer two-phase flow.
        """
        result = await self.prepare_message(channel_url, message)
        if result["status"] != "confirm_required":
            return result
        return await self.send_prepared_message()

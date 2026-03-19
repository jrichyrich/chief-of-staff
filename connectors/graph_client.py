"""Microsoft Graph API client using MSAL for auth and httpx for HTTP calls.

Provides async access to Teams chat and Outlook email endpoints with
device-code auth flow and silent token refresh.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency imports (same pattern as other connectors)
# ---------------------------------------------------------------------------

try:
    import msal  # type: ignore[import-untyped]
except ImportError:
    msal = None  # type: ignore[assignment]

try:
    from msal_extensions import (  # type: ignore[import-untyped]
        FilePersistence,
        PersistedTokenCache,
    )
except ImportError:
    FilePersistence = None  # type: ignore[assignment,misc]
    PersistedTokenCache = None  # type: ignore[assignment,misc]

try:
    from msal_extensions import KeychainPersistence  # type: ignore[import-untyped]
except (ImportError, AttributeError):
    KeychainPersistence = None  # type: ignore[assignment,misc]

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# Vault integration — WS1 may not be merged yet
try:
    from vault.keychain import get_secret  # type: ignore[import-untyped]
except ImportError:

    def get_secret(key: str) -> str | None:  # type: ignore[misc]
        """Fallback: read secrets from environment variables only."""
        return os.environ.get(key)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GraphAPIError(Exception):
    """Base error for non-transient Graph API failures."""


class GraphTransientError(GraphAPIError):
    """Raised on 429/5xx responses — triggers fallback to old backend."""


class GraphAuthError(GraphAPIError):
    """Raised when token refresh fails — triggers fallback in daemon mode."""


# ---------------------------------------------------------------------------
# GraphClient
# ---------------------------------------------------------------------------

_DEFAULT_SCOPES = [
    "Calendars.ReadWrite",
    "Channel.ReadBasic.All",
    "ChannelMessage.Send",
    "Chat.Create",
    "Chat.Read",
    "Chat.ReadWrite",
    "ChatMessage.Send",
    "Mail.Send",
    "Team.ReadBasic.All",
    "User.Read",
    "User.ReadBasic.All",
]

# Token age (seconds) at which we start warning about approaching expiry.
_TOKEN_AGE_WARNING_SECONDS = 60 * 60 * 24 * 60  # 60 days


class GraphClient:
    """Async Microsoft Graph API client with MSAL auth and httpx transport."""

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        client_id: str,
        tenant_id: str,
        scopes: list[str] | None = None,
        interactive: bool = True,
    ) -> None:
        if msal is None:
            raise ImportError(
                "msal is required for GraphClient — install with: pip install msal msal-extensions"
            )
        if httpx is None:
            raise ImportError(
                "httpx is required for GraphClient — install with: pip install httpx"
            )

        self._client_id = client_id
        self._tenant_id = tenant_id
        self._scopes = scopes or list(_DEFAULT_SCOPES)
        self._interactive = interactive

        # Build MSAL application(s) with persistent token cache.
        # Always create a PublicClientApplication so we can use cached
        # delegated tokens from prior interactive sessions.  When a
        # client_secret is available, also create a
        # ConfidentialClientApplication as a fallback for app-only
        # operations (no user context).
        cache = self._build_token_cache()
        authority = f"https://login.microsoftonline.com/{self._tenant_id}"
        client_secret = get_secret("m365_client_secret")

        # Public app — used for delegated auth (device code + silent refresh)
        self._public_app: Any = msal.PublicClientApplication(
            client_id=self._client_id,
            authority=authority,
            token_cache=cache,
        )

        # Confidential app — used for app-only client credentials fallback
        if client_secret:
            self._confidential_app: Any = msal.ConfidentialClientApplication(
                client_id=self._client_id,
                client_credential=client_secret,
                authority=authority,
                token_cache=cache,
            )
        else:
            self._confidential_app = None

        # Primary app used by most code paths — always the public app
        # so that /me endpoints work with cached delegated tokens.
        self._app: Any = self._public_app

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            verify=self._get_ssl_context(),
        )
        self._calendar_name_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # SSL / TLS
    # ------------------------------------------------------------------

    @staticmethod
    def _get_ssl_context():
        """Build an SSL context that works behind corporate proxies (e.g. Zscaler).

        Checks SSL_CERT_FILE, REQUESTS_CA_BUNDLE env vars, then falls back
        to the macOS System keychain export if available.
        """
        import ssl

        # Prefer Jarvis-managed bundle (includes system + corporate proxy CAs)
        jarvis_bundle = Path.home() / ".jarvis" / "ca-bundle.pem"
        if jarvis_bundle.is_file():
            try:
                ctx = ssl.create_default_context(cafile=str(jarvis_bundle))
                logger.debug("Using Jarvis CA bundle at %s", jarvis_bundle)
                return ctx
            except Exception:
                pass

        for env_var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            ca_file = os.environ.get(env_var)
            if ca_file and Path(ca_file).is_file():
                try:
                    ctx = ssl.create_default_context(cafile=ca_file)
                    logger.debug("Using CA bundle from %s=%s", env_var, ca_file)
                    return ctx
                except Exception:
                    pass

        # Fallback: try certifi if available
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except (ImportError, Exception):
            pass

        # Last resort: system default (works on most systems without proxy)
        return True

    # ------------------------------------------------------------------
    # Token cache
    # ------------------------------------------------------------------

    @staticmethod
    def _build_token_cache() -> Any:
        """Build an MSAL token cache backed by macOS Keychain or a fallback file."""
        if PersistedTokenCache is None:
            logger.debug("msal_extensions not available — using in-memory token cache")
            return msal.TokenCache() if msal else None

        # Prefer KeychainPersistence on macOS
        if sys.platform == "darwin" and KeychainPersistence is not None:
            try:
                from config import MSAL_KEYCHAIN_ACCOUNT, MSAL_KEYCHAIN_SERVICE

                persistence = KeychainPersistence(
                    signal_location=str(Path.home() / ".jarvis" / "token_cache.lock"),
                    service_name=MSAL_KEYCHAIN_SERVICE,
                    account_name=MSAL_KEYCHAIN_ACCOUNT,
                )
                logger.debug("Using macOS Keychain for MSAL token cache")
                return PersistedTokenCache(persistence)
            except Exception:
                logger.warning(
                    "KeychainPersistence setup failed — falling back to file cache",
                    exc_info=True,
                )

        # File-based fallback
        cache_dir = Path.home() / ".jarvis"
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        cache_path = cache_dir / "token_cache.bin"
        try:
            persistence = FilePersistence(str(cache_path))
            # Restrict token cache file permissions to owner only
            if cache_path.exists():
                cache_path.chmod(0o600)
            logger.debug("Using file-based MSAL token cache at %s", cache_path)
            return PersistedTokenCache(persistence)
        except Exception:
            logger.warning(
                "FilePersistence setup failed — using in-memory token cache",
                exc_info=True,
            )
            return msal.TokenCache() if msal else None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def ensure_authenticated(self) -> str:
        """Acquire a valid access token, refreshing silently or via device code.

        Returns the access token string.
        Raises ``GraphAuthError`` if authentication cannot be completed.
        """
        # 1. Try delegated token (public app) — supports /me endpoints.
        #    This works even in headless mode if a prior interactive session
        #    cached a user token that can be silently refreshed.
        accounts = self._public_app.get_accounts()
        if accounts:
            result = self._public_app.acquire_token_silent(
                scopes=self._scopes,
                account=accounts[0],
            )
            if result and "access_token" in result:
                self._check_token_age(result)
                return result["access_token"]

        # 2. Fall back to client credentials (app-only, no user context).
        #    Only works for endpoints that don't require /me.
        if not self._interactive and self._confidential_app:
            result = self._confidential_app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"],
            )
            if result and "access_token" in result:
                logger.warning(
                    "Using app-only token (client credentials). "
                    "/me endpoints will fail. Re-authenticate interactively "
                    "to restore delegated access."
                )
                return result["access_token"]

        if not self._interactive:
            raise GraphAuthError(
                "Token refresh failed and interactive auth is disabled (headless mode). "
                "Run: python scripts/bootstrap_secrets.py --reauth"
            )

        result = await self._device_code_flow()

        if "access_token" not in result:
            error_desc = result.get("error_description", result.get("error", "unknown error"))
            raise GraphAuthError(f"Device code flow failed: {error_desc}")

        return result["access_token"]

    async def _device_code_flow(self) -> dict:
        """Run MSAL device code flow (public clients only)."""
        flow = self._app.initiate_device_flow(scopes=self._scopes)
        if "user_code" not in flow:
            raise GraphAuthError(
                f"Device code flow initiation failed: {flow.get('error_description', 'unknown error')}"
            )

        logger.info(
            "Device code auth: visit %s and enter code %s",
            flow.get("verification_uri", "https://microsoft.com/devicelogin"),
            flow["user_code"],
        )
        print(
            f"\nTo sign in, visit {flow.get('verification_uri', 'https://microsoft.com/devicelogin')} "
            f"and enter code: {flow['user_code']}\n",
            file=sys.stderr,
        )

        return await asyncio.to_thread(
            self._app.acquire_token_by_device_flow, flow
        )

    async def get_authenticated_email(self) -> str | None:
        """Return the authenticated user's email from MSAL account cache.

        Returns None if no account is cached (not yet authenticated).
        """
        accounts = self._public_app.get_accounts()
        if accounts:
            return accounts[0].get("username")
        return None

    @staticmethod
    def _check_token_age(result: dict) -> None:
        """Log a warning if the token is approaching expiry."""
        # MSAL doesn't directly expose token issuance time in the result,
        # but we can check the id_token_claims for iat (issued at).
        claims = result.get("id_token_claims") or {}
        iat = claims.get("iat")
        if iat:
            age = time.time() - float(iat)
            if age > _TOKEN_AGE_WARNING_SECONDS:
                days = int(age / (60 * 60 * 24))
                logger.warning(
                    "MSAL token age is %d days — approaching 90-day expiry. "
                    "Run bootstrap_secrets.py to re-authenticate.",
                    days,
                )

    async def proactive_token_refresh(self) -> dict:
        """Proactively refresh the delegated token to prevent expiry.

        Returns a status dict with keys:
            status: "ok" | "warning" | "expired"
            message: Human-readable description
            account: The authenticated username (if available)
            days_until_expiry: Estimated days remaining (if determinable)

        This should be called periodically (e.g. daily) to keep the
        refresh token alive and warn before the 90-day window expires.
        """
        accounts = self._public_app.get_accounts()
        if not accounts:
            return {
                "status": "expired",
                "message": "No cached accounts. Interactive re-authentication required.",
                "account": None,
            }

        account = accounts[0]
        username = account.get("username", "unknown")

        result = self._public_app.acquire_token_silent(
            scopes=self._scopes,
            account=account,
        )

        if not result or "access_token" not in result:
            error = "unknown"
            if result:
                error = result.get("error_description", result.get("error", "unknown"))
            return {
                "status": "expired",
                "message": f"Silent refresh failed for {username}: {error}. "
                           "Interactive re-authentication required.",
                "account": username,
            }

        # Token refreshed successfully — check age
        claims = result.get("id_token_claims") or {}
        iat = claims.get("iat")
        days_remaining = None
        status = "ok"
        message = f"Token refreshed successfully for {username}."

        if iat:
            age_seconds = time.time() - float(iat)
            age_days = int(age_seconds / (60 * 60 * 24))
            # Refresh tokens typically last 90 days
            days_remaining = max(0, 90 - age_days)
            if days_remaining <= 14:
                status = "warning"
                message = (
                    f"Token for {username} expires in ~{days_remaining} days. "
                    "Re-authenticate soon to avoid disruption."
                )
            else:
                message = (
                    f"Token refreshed for {username}. "
                    f"~{days_remaining} days until re-authentication needed."
                )

        logger.info("Proactive token refresh: %s — %s", status, message)
        return {
            "status": status,
            "message": message,
            "account": username,
            "days_until_expiry": days_remaining,
        }

    # ------------------------------------------------------------------
    # HTTP request helper
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make an authenticated request to the Graph API.

        Handles 401 retry (token refresh), 429 retry (rate limit), and
        raises appropriate exceptions for error responses.
        """
        token = await self.ensure_authenticated()
        url = f"{self.GRAPH_BASE}{path}" if path.startswith("/") else f"{self.GRAPH_BASE}/{path}"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        max_429_retries = 3

        for attempt in range(max_429_retries + 1):
            response = await self._http.request(method, url, headers=headers, **kwargs)

            # Success
            if response.status_code in (200, 201, 202, 204):
                if response.status_code == 204 or not response.content:
                    return {"status": "success"}
                return response.json()

            # 401 — force token refresh and retry once
            if response.status_code == 401 and attempt == 0:
                logger.info("Graph API 401 — forcing token refresh and retrying")
                # Clear cached accounts so ensure_authenticated does a fresh acquire
                for acct in self._app.get_accounts():
                    self._app.remove_account(acct)
                token = await self.ensure_authenticated()
                headers["Authorization"] = f"Bearer {token}"
                continue

            # 429 — respect Retry-After
            if response.status_code == 429 and attempt < max_429_retries:
                try:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                except (ValueError, TypeError):
                    retry_after = 5
                logger.warning(
                    "Graph API 429 — retrying after %ds (attempt %d/%d)",
                    retry_after,
                    attempt + 1,
                    max_429_retries,
                )
                await asyncio.sleep(retry_after)
                continue

            # 429 exhausted
            if response.status_code == 429:
                raise GraphTransientError(
                    f"Graph API rate limited after {max_429_retries} retries"
                )

            # 5xx — transient, retry up to 2 times with exponential backoff
            if response.status_code >= 500:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(
                        "Graph API %d — retrying after %ds (attempt %d/2)",
                        response.status_code,
                        wait,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                body = self._extract_error_body(response)
                raise GraphTransientError(
                    f"Graph API {response.status_code}: {body}"
                )

            # Other 4xx — non-transient
            body = self._extract_error_body(response)
            raise GraphAPIError(
                f"Graph API {response.status_code}: {body}"
            )

        # Should not reach here, but just in case
        raise GraphAPIError("Unexpected request loop exit")  # pragma: no cover

    @staticmethod
    def _extract_error_body(response: Any) -> str:
        """Extract a concise error message from a Graph API error response.

        Attempts to parse the response as JSON and extract ``error.code`` and
        ``error.message``.  Falls back to the first 500 characters of the raw
        body when parsing fails.
        """
        try:
            data = response.json()
            err = data.get("error", {})
            code = err.get("code", "")
            message = err.get("message", "")
            if code or message:
                return f"{code}: {message}".strip(": ")
        except Exception:
            pass
        return (response.text or "")[:500]

    # ------------------------------------------------------------------
    # Teams methods
    # ------------------------------------------------------------------

    async def list_chats(self, limit: int = 50) -> list[dict]:
        """List the authenticated user's Teams chats."""
        data = await self._request("GET", f"/me/chats?$top={limit}&$expand=members")
        return data.get("value", [])

    async def get_chat_messages(self, chat_id: str, limit: int = 50) -> list[dict]:
        """Get recent messages from a Teams chat."""
        safe_id = urllib.parse.quote(chat_id, safe="")
        data = await self._request("GET", f"/me/chats/{safe_id}/messages?$top={limit}")
        return data.get("value", [])

    async def send_chat_message(
        self,
        chat_id: str,
        content: str,
        content_type: str = "text",
        mentions: list[dict] | None = None,
    ) -> dict:
        """Send a message to a Teams chat.

        Args:
            chat_id: The Teams chat ID.
            content: Message body text (plain text or HTML).
            content_type: ``"text"`` (default) or ``"html"``.
            mentions: Optional list of mention objects for @mentions.
                Each must have ``id``, ``mentionText``, and ``mentioned.user``
                with ``id``, ``displayName``, ``userIdentityType``.
        """
        safe_id = urllib.parse.quote(chat_id, safe="")
        body: dict[str, Any] = {
            "body": {"content": content, "contentType": content_type},
        }
        if mentions:
            body["mentions"] = mentions
        return await self._request(
            "POST",
            f"/me/chats/{safe_id}/messages",
            json=body,
        )

    async def reply_to_chat_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        content_type: str = "text",
        mentions: list[dict] | None = None,
    ) -> dict:
        """Reply to a specific message in a Teams chat (threading).

        Args:
            chat_id: The Teams chat ID.
            message_id: The ID of the message to reply to.
            content: Reply body (plain text or HTML).
            content_type: ``"text"`` (default) or ``"html"``.
            mentions: Optional list of mention objects for @mentions.
        """
        safe_chat = urllib.parse.quote(chat_id, safe="")
        safe_msg = urllib.parse.quote(message_id, safe="")
        body: dict[str, Any] = {
            "body": {"content": content, "contentType": content_type},
        }
        if mentions:
            body["mentions"] = mentions
        return await self._request(
            "POST",
            f"/chats/{safe_chat}/messages/{safe_msg}/replies",
            json=body,
        )

    async def find_chat_by_members(self, member_emails: list[str]) -> str | None:
        """Find a chat containing the given members.

        Returns the chat_id or None if no matching chat is found.
        """
        chats = await self.list_chats(limit=50)
        target = {e.lower() for e in member_emails}

        # Prefer oneOnOne chats — sort by member count ascending so 1:1 matches first
        chats.sort(key=lambda c: len(c.get("members", [])))

        for chat in chats:
            members = chat.get("members", [])
            chat_emails = set()
            for m in members:
                email = (m.get("email") or m.get("additionalData", {}).get("email") or "").lower()
                if email:
                    chat_emails.add(email)
            if target.issubset(chat_emails):
                return chat.get("id")

        return None

    async def resolve_user_email(self, display_name: str) -> str | None:
        """Resolve a display name to an email via Graph /users endpoint.

        Returns the user's email if exactly one match is found, None otherwise.
        """
        try:
            safe_name = display_name.replace("'", "''")
            data = await self._request(
                "GET",
                "/users",
                params={"$filter": f"displayName eq '{safe_name}'", "$select": "mail,userPrincipalName"},
            )
            users = data.get("value", [])
            if len(users) == 1:
                return users[0].get("mail") or users[0].get("userPrincipalName")
            return None
        except Exception:
            return None

    async def get_user_by_email(self, email: str) -> dict | None:
        """Look up an Azure AD user by email address.

        Returns a dict with ``id``, ``displayName``, and ``mail`` fields,
        or None if the user is not found.  The ``id`` is the Azure AD
        object ID needed for @mentions in Teams messages.
        """
        try:
            safe_email = email.replace("'", "''")
            data = await self._request(
                "GET",
                "/users",
                params={
                    "$filter": f"mail eq '{safe_email}' or userPrincipalName eq '{safe_email}'",
                    "$select": "id,displayName,mail,userPrincipalName",
                },
            )
            users = data.get("value", [])
            if len(users) >= 1:
                u = users[0]
                return {
                    "id": u.get("id"),
                    "displayName": u.get("displayName"),
                    "mail": u.get("mail") or u.get("userPrincipalName"),
                }
            return None
        except Exception:
            return None

    async def create_chat(
        self,
        member_emails: list[str],
        message: str | None = None,
    ) -> dict:
        """Create a new Teams chat with the given members.

        Uses oneOnOne for a single member, group for multiple.
        For group chats, the authenticated user is explicitly added as an owner
        (required by Graph API). For oneOnOne, Graph auto-includes the caller.
        """
        chat_type = "oneOnOne" if len(member_emails) == 1 else "group"

        members = [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{email}",
            }
            for email in member_emails
        ]

        # Group chats require the caller to be explicitly listed as a member
        if chat_type == "group":
            my_email = await self.get_authenticated_email()
            if my_email and my_email.lower() not in {e.lower() for e in member_emails}:
                members.insert(0, {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{my_email}",
                })

        body: dict[str, Any] = {
            "chatType": chat_type,
            "members": members,
        }

        result = await self._request("POST", "/chats", json=body)

        # Optionally send an initial message
        if message and result.get("id"):
            await self.send_chat_message(result["id"], message)

        return result

    async def update_chat_topic(self, chat_id: str, topic: str) -> dict:
        """Rename a group chat's topic/display name."""
        safe_id = urllib.parse.quote(chat_id, safe="")
        return await self._request(
            "PATCH",
            f"/chats/{safe_id}",
            json={"topic": topic},
        )

    async def list_chat_members(self, chat_id: str) -> list[dict]:
        """List members of a Teams chat."""
        safe_id = urllib.parse.quote(chat_id, safe="")
        data = await self._request("GET", f"/me/chats/{safe_id}/members")
        return data.get("value", [])

    async def add_chat_member(self, chat_id: str, user_email: str, roles: list[str] | None = None) -> dict:
        """Add a member to a group chat."""
        safe_id = urllib.parse.quote(chat_id, safe="")
        return await self._request(
            "POST",
            f"/me/chats/{safe_id}/members",
            json={
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": roles or ["guest"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{user_email}",
            },
        )

    async def remove_chat_member(self, chat_id: str, membership_id: str) -> dict:
        """Remove a member from a group chat by their membership ID."""
        safe_chat = urllib.parse.quote(chat_id, safe="")
        safe_member = urllib.parse.quote(membership_id, safe="")
        return await self._request(
            "DELETE",
            f"/me/chats/{safe_chat}/members/{safe_member}",
        )

    # ------------------------------------------------------------------
    # Email methods
    # ------------------------------------------------------------------

    async def send_mail(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        content_type: str = "Text",
    ) -> dict:
        """Send an email via Outlook."""
        to_recipients = [
            {"emailAddress": {"address": addr}} for addr in to
        ]
        cc_recipients = [
            {"emailAddress": {"address": addr}} for addr in (cc or [])
        ]
        bcc_recipients = [
            {"emailAddress": {"address": addr}} for addr in (bcc or [])
        ]

        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": content_type, "content": body},
            "toRecipients": to_recipients,
        }
        if cc_recipients:
            message["ccRecipients"] = cc_recipients
        if bcc_recipients:
            message["bccRecipients"] = bcc_recipients

        return await self._request(
            "POST",
            "/me/sendMail",
            json={"message": message, "saveToSentItems": True},
        )

    async def reply_mail(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Reply to an email message.

        When *reply_all* is True, uses the ``/replyAll`` endpoint.
        Optional *cc* and *bcc* lists add additional recipients.
        """
        safe_id = urllib.parse.quote(message_id, safe="")
        action = "replyAll" if reply_all else "reply"

        payload: dict[str, Any] = {"comment": body}

        # Graph API accepts a "message" object alongside the comment to add
        # extra recipients (cc/bcc) to the reply.
        extra_msg: dict[str, Any] = {}
        if cc:
            extra_msg["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in cc
            ]
        if bcc:
            extra_msg["bccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in bcc
            ]
        if extra_msg:
            payload["message"] = extra_msg

        return await self._request(
            "POST",
            f"/me/messages/{safe_id}/{action}",
            json=payload,
        )

    # ------------------------------------------------------------------
    # Calendar helpers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_event_datetime(
        dt_str: str, timezone: str, is_all_day: bool
    ) -> dict[str, str]:
        """Format a datetime string for Graph API event payload.

        Timed events: {"dateTime": "2026-04-15T09:00:00", "timeZone": "America/Denver"}
        All-day events: {"dateTime": "2026-04-15", "timeZone": "UTC"}
        """
        if is_all_day:
            return {"dateTime": dt_str[:10], "timeZone": "UTC"}
        return {"dateTime": dt_str, "timeZone": timezone}

    @staticmethod
    def _build_attendees_payload(
        attendees: list[dict] | None,
    ) -> list[dict] | None:
        """Convert simplified attendee list to Graph API format.

        Input:  [{"email": "a@b.com", "name": "A", "type": "required"}]
        Output: [{"emailAddress": {"address": "a@b.com", "name": "A"}, "type": "required"}]
        """
        if attendees is None:
            return None
        result = []
        for att in attendees:
            email = att["email"]
            name = att.get("name") or email.split("@")[0]
            att_type = att.get("type", "required")
            result.append({
                "emailAddress": {"address": email, "name": name},
                "type": att_type,
            })
        return result

    @staticmethod
    def _build_recurrence_payload(recurrence: dict | None) -> dict | None:
        """Convert simplified recurrence dict to Graph API format.

        Input:  {"type": "weekly", "interval": 1, "days_of_week": ["tuesday"], "end_date": "2026-12-31"}
        Output: {"pattern": {...}, "range": {...}}
        """
        if recurrence is None:
            return None

        rec_type = recurrence["type"]
        interval = recurrence.get("interval", 1)

        pattern: dict[str, Any] = {"type": rec_type, "interval": interval}
        if "days_of_week" in recurrence:
            pattern["daysOfWeek"] = recurrence["days_of_week"]
        if "day_of_month" in recurrence:
            pattern["dayOfMonth"] = recurrence["day_of_month"]
        if "month" in recurrence:
            pattern["month"] = recurrence["month"]

        if "end_date" in recurrence:
            rec_range = {
                "type": "endDate",
                "startDate": "",
                "endDate": recurrence["end_date"],
            }
        elif "occurrences" in recurrence:
            rec_range = {
                "type": "numbered",
                "startDate": "",
                "numberOfOccurrences": recurrence["occurrences"],
            }
        else:
            rec_range = {"type": "noEnd", "startDate": ""}

        return {"pattern": pattern, "range": rec_range}

    @staticmethod
    def _normalize_event(graph_event: dict) -> dict:
        """Normalize a Graph API event to internal format."""
        location = graph_event.get("location")
        body = graph_event.get("body")
        attendees_raw = graph_event.get("attendees") or []
        response_status = graph_event.get("responseStatus")

        return {
            "uid": graph_event.get("id", ""),
            "title": graph_event.get("subject", ""),
            "start": (graph_event.get("start") or {}).get("dateTime", ""),
            "end": (graph_event.get("end") or {}).get("dateTime", ""),
            "location": location.get("displayName") if isinstance(location, dict) else None,
            "notes": body.get("content") if isinstance(body, dict) else None,
            "is_all_day": graph_event.get("isAllDay", False),
            "showAs": graph_event.get("showAs", ""),
            "isCancelled": graph_event.get("isCancelled", False),
            "responseStatus": response_status.get("response", "") if isinstance(response_status, dict) else "",
            "attendees": [
                att["emailAddress"]["address"]
                for att in attendees_raw
                if isinstance(att, dict) and "emailAddress" in att
            ],
            "recurrence": graph_event.get("recurrence"),
        }

    # ------------------------------------------------------------------
    # Calendar CRUD
    # ------------------------------------------------------------------

    async def resolve_calendar_id(self, calendar_name: str) -> str | None:
        """Resolve a human-readable calendar name to a Graph API calendar ID.

        Uses a session-scoped cache. Returns None if no match found.
        """
        if not self._calendar_name_cache:
            calendars = await self._request("GET", "/me/calendars")
            for cal in calendars.get("value", []):
                name = cal.get("name", "")
                self._calendar_name_cache[name.lower()] = cal["id"]
        return self._calendar_name_cache.get(calendar_name.lower())

    async def create_calendar_event(
        self,
        subject: str,
        start: str,
        end: str,
        timezone: str = "America/Denver",
        attendees: list[dict] | None = None,
        recurrence: dict | None = None,
        calendar_id: str | None = None,
        location: str | None = None,
        body: str | None = None,
        is_all_day: bool = False,
        reminder_minutes: int | None = 15,
    ) -> dict:
        """Create a calendar event via Graph API.

        Sends standard Exchange meeting invites to all attendees.
        """
        payload: dict[str, Any] = {
            "subject": subject,
            "start": self._format_event_datetime(start, timezone, is_all_day),
            "end": self._format_event_datetime(end, timezone, is_all_day),
        }

        if location:
            payload["location"] = {"displayName": location}
        if body:
            payload["body"] = {"contentType": "text", "content": body}
        if is_all_day:
            payload["isAllDay"] = True
        if reminder_minutes is not None:
            payload["isReminderOn"] = True
            payload["reminderMinutesBeforeStart"] = reminder_minutes

        graph_attendees = self._build_attendees_payload(attendees)
        if graph_attendees:
            payload["attendees"] = graph_attendees

        graph_recurrence = self._build_recurrence_payload(recurrence)
        if graph_recurrence:
            graph_recurrence["range"]["startDate"] = start[:10]
            payload["recurrence"] = graph_recurrence

        endpoint = f"/me/calendars/{calendar_id}/events" if calendar_id else "/me/events"
        response = await self._request("POST", endpoint, json=payload)
        return self._normalize_event(response)

    async def update_calendar_event(self, event_id: str, **kwargs: Any) -> dict:
        """Update a calendar event via Graph API.

        Accepts any combination of: subject, start, end, timezone, location,
        body, is_all_day, attendees, recurrence, reminder_minutes.

        Note: attendees is a FULL REPLACEMENT — omitted attendees are removed
        and receive cancellation notices.
        """
        timezone = kwargs.pop("timezone", "America/Denver")
        is_all_day = kwargs.pop("is_all_day", None)

        payload: dict[str, Any] = {}

        if "subject" in kwargs:
            payload["subject"] = kwargs["subject"]
        if "start" in kwargs:
            payload["start"] = self._format_event_datetime(
                kwargs["start"], timezone, is_all_day or False
            )
        if "end" in kwargs:
            payload["end"] = self._format_event_datetime(
                kwargs["end"], timezone, is_all_day or False
            )
        if "location" in kwargs:
            payload["location"] = {"displayName": kwargs["location"]}
        if "body" in kwargs:
            payload["body"] = {"contentType": "text", "content": kwargs["body"]}
        if is_all_day is not None:
            payload["isAllDay"] = is_all_day
        if "reminder_minutes" in kwargs:
            payload["isReminderOn"] = True
            payload["reminderMinutesBeforeStart"] = kwargs["reminder_minutes"]

        if "attendees" in kwargs:
            graph_attendees = self._build_attendees_payload(kwargs["attendees"])
            if graph_attendees is not None:
                payload["attendees"] = graph_attendees

        if "recurrence" in kwargs:
            graph_recurrence = self._build_recurrence_payload(kwargs["recurrence"])
            if graph_recurrence:
                if "start" in kwargs:
                    graph_recurrence["range"]["startDate"] = kwargs["start"][:10]
                payload["recurrence"] = graph_recurrence

        response = await self._request("PATCH", f"/me/events/{event_id}", json=payload)
        return self._normalize_event(response)

    async def delete_calendar_event(self, event_id: str) -> dict:
        """Delete a calendar event via Graph API."""
        return await self._request("DELETE", f"/me/events/{event_id}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the httpx async client."""
        await self._http.aclose()

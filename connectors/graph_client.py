"""Microsoft Graph API client using MSAL for auth and httpx for HTTP calls.

Provides async access to Teams chat and Outlook email endpoints with
device-code auth flow and silent token refresh.
"""

from __future__ import annotations

import asyncio
import html
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

_DEFAULT_SCOPES = ["Chat.Read", "ChatMessage.Send", "Mail.Send", "User.Read"]

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

        # Build MSAL application with persistent token cache.
        # Interactive (CLI) → PublicClientApplication + device code flow.
        # Headless (daemon) → ConfidentialClientApplication + client credentials
        #   if a client_secret is available, else PublicClientApplication + silent only.
        cache = self._build_token_cache()
        authority = f"https://login.microsoftonline.com/{self._tenant_id}"
        client_secret = get_secret("m365_client_secret")
        if not interactive and client_secret:
            self._app: Any = msal.ConfidentialClientApplication(
                client_id=self._client_id,
                client_credential=client_secret,
                authority=authority,
                token_cache=cache,
            )
            self._is_confidential = True
        else:
            self._app: Any = msal.PublicClientApplication(
                client_id=self._client_id,
                authority=authority,
                token_cache=cache,
            )
            self._is_confidential = False

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            verify=self._get_ssl_context(),
        )

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
                persistence = KeychainPersistence(
                    signal_location=str(Path.home() / ".jarvis" / "token_cache.lock"),
                    service_name="jarvis",
                    account_name="msal_token_cache",
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
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(
                scopes=self._scopes,
                account=accounts[0],
            )
            if result and "access_token" in result:
                # Warn if token is getting old
                self._check_token_age(result)
                return result["access_token"]

        # Silent acquisition failed — try client credentials for confidential apps
        # in headless mode (app-only permissions only, no user context).
        if not self._interactive and self._is_confidential:
            result = self._app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            if result and "access_token" in result:
                return result["access_token"]

        if not self._interactive:
            raise GraphAuthError(
                "Token refresh failed and interactive auth is disabled (headless mode)"
            )

        if self._is_confidential:
            # Confidential clients use auth code flow with local redirect
            result = await self._auth_code_flow()
        else:
            # Public clients use device code flow
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

    async def _auth_code_flow(self) -> dict:
        """Run MSAL authorization code flow with local redirect (confidential clients).

        Starts a temporary local HTTP server on port 8400 to receive the OAuth
        redirect, then opens the browser for user consent.
        """
        import http.server
        import threading
        import urllib.parse
        import webbrowser

        auth_code_result: dict = {}
        server_ready = threading.Event()

        class _CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal auth_code_result
                qs = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(qs)
                if "code" in params:
                    auth_code_result["code"] = params["code"][0]
                    if "state" in params:
                        auth_code_result["state"] = params["state"][0]
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"<html><body><h2>Authentication successful.</h2>"
                                    b"<p>You can close this window.</p></body></html>")
                else:
                    error = params.get("error", ["unknown"])[0]
                    desc = params.get("error_description", [""])[0]
                    auth_code_result["error"] = error
                    auth_code_result["error_description"] = desc
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(f"<html><body><h2>Error: {html.escape(error)}</h2>"
                                    f"<p>{html.escape(desc)}</p></body></html>".encode())

            def log_message(self, format, *args):
                pass  # Suppress request logging

        redirect_uri = "http://localhost:8400"
        flow = self._app.initiate_auth_code_flow(
            scopes=self._scopes,
            redirect_uri=redirect_uri,
        )
        if "auth_uri" not in flow:
            raise GraphAuthError(
                f"Auth code flow initiation failed: {flow.get('error_description', 'unknown error')}"
            )

        # Start local server in background thread
        server = http.server.HTTPServer(("127.0.0.1", 8400), _CallbackHandler)
        server.timeout = 300  # 5 minute timeout

        def serve():
            server_ready.set()
            server.handle_request()  # Handle exactly one request

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        server_ready.wait()

        auth_uri = flow["auth_uri"]
        logger.info("Opening browser for auth code flow: %s", auth_uri)
        print(f"\nOpening browser for authentication...\nIf it doesn't open, visit: {auth_uri}\n", file=sys.stderr)
        webbrowser.open(auth_uri)

        # Wait for the callback
        try:
            thread.join(timeout=300)
        finally:
            server.server_close()

        if "error" in auth_code_result:
            raise GraphAuthError(
                f"Auth code flow failed: {auth_code_result.get('error_description', auth_code_result['error'])}"
            )
        if "code" not in auth_code_result:
            raise GraphAuthError("Auth code flow timed out — no callback received")

        # Exchange auth code for tokens
        result = self._app.acquire_token_by_auth_code_flow(
            flow,
            auth_code_result,
        )
        return result

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

    async def send_chat_message(self, chat_id: str, content: str) -> dict:
        """Send a message to a Teams chat."""
        safe_id = urllib.parse.quote(chat_id, safe="")
        return await self._request(
            "POST",
            f"/me/chats/{safe_id}/messages",
            json={"body": {"content": content, "contentType": "text"}},
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
                f"/users?$filter=displayName eq '{safe_name}'&$select=mail,userPrincipalName",
            )
            users = data.get("value", [])
            if len(users) == 1:
                return users[0].get("mail") or users[0].get("userPrincipalName")
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
        """
        chat_type = "oneOnOne" if len(member_emails) == 1 else "group"

        # The authenticated user is automatically included
        members = [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{email}",
            }
            for email in member_emails
        ]

        body: dict[str, Any] = {
            "chatType": chat_type,
            "members": members,
        }

        result = await self._request("POST", "/chats", json=body)

        # Optionally send an initial message
        if message and result.get("id"):
            await self.send_chat_message(result["id"], message)

        return result

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
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the httpx async client."""
        await self._http.aclose()

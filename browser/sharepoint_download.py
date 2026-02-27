"""Download files from SharePoint using the persistent Playwright browser.

Uses the same CDP-connected browser that Teams tools use (already
Okta-authenticated).

Strategy order:
1. ``download.aspx?UniqueId=`` — dedicated download endpoint (fastest)
2. Excel Online UI clicks via raw CDP — connects directly to the Excel
   iframe target and clicks File → Create a Copy → Download a Copy.
   The file lands in ~/Downloads and is moved to the destination.
"""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

try:
    from playwright._impl._errors import TimeoutError as PlaywrightTimeout
except ImportError:
    PlaywrightTimeout = None  # type: ignore[misc,assignment]

# Tuple of timeout exceptions — Playwright's TimeoutError does NOT inherit
# from the builtins.TimeoutError (it inherits from Exception directly).
_TIMEOUT_ERRORS: tuple = (TimeoutError, RuntimeError)
if PlaywrightTimeout is not None:
    _TIMEOUT_ERRORS = (TimeoutError, RuntimeError, PlaywrightTimeout)

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path.home() / "Downloads"


def _extract_unique_id(sharepoint_url: str) -> Optional[str]:
    """Extract the document UniqueId (GUID) from a SharePoint URL.

    Looks for ``sourcedoc=%7B<GUID>%7D`` in the query string.
    """
    match = re.search(
        r"sourcedoc=%7B([A-Fa-f0-9-]+)%7D", sharepoint_url, re.IGNORECASE
    )
    return match.group(1) if match else None


def _extract_site_base(sharepoint_url: str) -> Optional[str]:
    """Extract the SharePoint site base URL.

    Returns the host + site/personal path, e.g.:
    - ``https://host/sites/ISPTeam``
    - ``https://host-my/personal/user_domain_com``

    Handles sharing-link prefixes like ``/:x:/r/`` or ``/:p:/r/`` that
    appear before ``/sites/`` or ``/personal/``.
    """
    # Match /sites/Name or /personal/Name (OneDrive for Business)
    match = re.match(
        r"(https://[^/]+)/(?:[^/]+/)*?((?:sites|personal)/[^/]+)",
        sharepoint_url,
    )
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    match = re.match(r"(https://[^/]+)", sharepoint_url)
    return match.group(1) if match else None


def _extract_filename(sharepoint_url: str) -> Optional[str]:
    """Extract the filename from a SharePoint URL's ``file=`` parameter."""
    match = re.search(r"[?&]file=([^&]+)", sharepoint_url)
    return match.group(1) if match else None


def _make_download_url(sharepoint_url: str) -> str:
    """Convert a SharePoint view URL into a direct download URL.

    Prefers the ``download.aspx?UniqueId=`` endpoint.  Falls back to
    ``action=download`` substitution when the GUID cannot be extracted.
    """
    uid = _extract_unique_id(sharepoint_url)
    site_base = _extract_site_base(sharepoint_url)

    if uid and site_base:
        return f"{site_base}/_layouts/15/download.aspx?UniqueId=%7B{uid}%7D"

    if re.search(r"[?&]action=", sharepoint_url):
        return re.sub(r"([?&])action=\w+", r"\1action=download", sharepoint_url)
    sep = "&" if "?" in sharepoint_url else "?"
    return f"{sharepoint_url}{sep}action=download"


async def _save_download(download, destination: Path) -> dict:
    """Save a Playwright download to *destination* and return a result dict."""
    failure = await download.failure()
    if failure:
        raise RuntimeError(f"Download reported failure: {failure}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    await download.save_as(str(destination))

    size = destination.stat().st_size
    if size == 0:
        raise RuntimeError("Downloaded file is empty (0 bytes)")

    return {
        "status": "downloaded",
        "path": str(destination),
        "size_bytes": size,
    }


async def _try_direct_download(ctx, download_url: str, destination: Path,
                                timeout_ms: int) -> dict:
    """Strategy 1: navigate to download.aspx URL and intercept the download.

    Playwright raises ``"Download is starting"`` when a navigation triggers
    a file download instead of loading a page.  We catch that specific error
    and let ``expect_download`` collect the download event.
    """
    page = await ctx.new_page()
    try:
        async with page.expect_download(timeout=timeout_ms) as dl_info:
            try:
                await page.goto(download_url, wait_until="commit",
                                timeout=timeout_ms)
            except Exception as nav_err:
                if "Download is starting" not in str(nav_err):
                    raise
                # Expected — the navigation triggered a download
        download = await dl_info.value
        result = await _save_download(download, destination)
        result["method"] = "direct_url"
        return result
    finally:
        await page.close()


def _find_excel_iframe_ws(cdp_port: int = 9222) -> Optional[str]:
    """Find the Excel Online iframe's WebSocket debugger URL via CDP."""
    try:
        with urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=5) as resp:
            targets = json.loads(resp.read())
    except (URLError, OSError):
        return None

    for t in targets:
        url = t.get("url", "")
        if "excel.officeapps.live.com" in url and "xlviewer" in url:
            return t.get("webSocketDebuggerUrl")
    return None


async def _cdp_send(ws, msg_id_holder: list, method: str,
                    params: Optional[dict] = None) -> dict:
    """Send a CDP command over WebSocket and return the response."""
    import websockets  # noqa: delayed import

    msg_id_holder[0] += 1
    current_id = msg_id_holder[0]
    msg: dict = {"id": current_id, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))

    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        resp = json.loads(raw)
        if resp.get("id") == current_id:
            return resp


async def _try_ui_download(sharepoint_url: str, destination: Path,
                           timeout_ms: int, cdp_port: int = 9222) -> dict:
    """Strategy 2: click File → Create a Copy → Download a Copy via CDP.

    Connects directly to the Excel Online iframe's CDP target (which is
    cross-origin and inaccessible via Playwright's frame API) and performs
    the menu click sequence.  The file downloads to ~/Downloads and is then
    moved to *destination*.
    """
    import websockets

    ws_url = _find_excel_iframe_ws(cdp_port)
    if not ws_url:
        raise RuntimeError(
            "Excel Online iframe not found — the spreadsheet may not be open"
        )

    # Snapshot ~/Downloads before triggering the download
    filename = _extract_filename(sharepoint_url) or "download.xlsx"
    stem = Path(filename).stem
    before = set(DOWNLOADS_DIR.glob(f"{stem}*"))

    async with websockets.connect(ws_url) as ws:
        mid = [0]  # mutable counter

        await _cdp_send(ws, mid, "Runtime.enable")

        # Step 1: Click File menu
        logger.info("UI download: clicking File menu...")
        r = await _cdp_send(ws, mid, "Runtime.evaluate", {
            "expression": (
                "(() => {"
                "  const btn = document.getElementById('FileMenuFlyoutLauncher');"
                "  if (!btn) return 'FileMenuFlyoutLauncher not found';"
                "  btn.click();"
                "  return 'ok';"
                "})()"
            ),
            "returnByValue": True,
        })
        val = r.get("result", {}).get("result", {}).get("value", "")
        if val != "ok":
            raise RuntimeError(f"File menu click failed: {val}")

        await asyncio.sleep(1.5)

        # Step 2: Click "Create a Copy"
        logger.info("UI download: clicking 'Create a Copy'...")
        r = await _cdp_send(ws, mid, "Runtime.evaluate", {
            "expression": (
                "(() => {"
                '  const el = document.querySelector(\'[data-unique-id="FileMenuCreateACopySection"]\');'
                "  if (!el) return 'not found';"
                "  el.click();"
                "  return 'ok';"
                "})()"
            ),
            "returnByValue": True,
        })
        val = r.get("result", {}).get("result", {}).get("value", "")
        if val != "ok":
            raise RuntimeError(f"'Create a Copy' click failed: {val}")

        await asyncio.sleep(1)

        # Step 3: Click "Download a Copy"
        logger.info("UI download: clicking 'Download a Copy'...")
        r = await _cdp_send(ws, mid, "Runtime.evaluate", {
            "expression": (
                "(() => {"
                '  const el = document.querySelector(\'[data-unique-id="DownloadACopy"]\');'
                "  if (!el) return 'not found';"
                "  el.click();"
                "  return 'ok';"
                "})()"
            ),
            "returnByValue": True,
        })
        val = r.get("result", {}).get("result", {}).get("value", "")
        if val != "ok":
            raise RuntimeError(f"'Download a Copy' click failed: {val}")

    # Wait for the file to appear in ~/Downloads
    timeout_s = timeout_ms / 1000
    poll_interval = 0.5
    elapsed = 0.0

    while elapsed < timeout_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        after = set(DOWNLOADS_DIR.glob(f"{stem}*"))
        new_files = after - before
        # Filter out partial downloads (.crdownload, .part, .tmp)
        _PARTIAL_SUFFIXES = {".crdownload", ".part", ".tmp", ".download"}
        completed = [
            f for f in new_files
            if f.suffix.lower() not in _PARTIAL_SUFFIXES and f.stat().st_size > 0
        ]
        if completed:
            # Pick the newest
            src = max(completed, key=lambda p: p.stat().st_mtime)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(destination))
            size = destination.stat().st_size
            logger.info(
                "UI download: copied %s (%d bytes) → %s", src.name, size,
                destination
            )
            return {
                "status": "downloaded",
                "path": str(destination),
                "size_bytes": size,
                "method": "ui_click",
                "source_file": str(src),
            }

    raise RuntimeError(
        f"File did not appear in {DOWNLOADS_DIR} within {timeout_s}s"
    )


async def download_sharepoint_file(
    manager,
    sharepoint_url: str,
    destination: Path,
    timeout_ms: int = 60_000,
) -> dict:
    """Download a file from SharePoint via the persistent browser.

    Args:
        manager: A :class:`TeamsBrowserManager` instance.
        sharepoint_url: Full SharePoint URL (view or download).
        destination: Local path to save the downloaded file.
        timeout_ms: Download timeout in milliseconds.

    Returns:
        A dict with ``status`` (``"downloaded"``, ``"error"``, or
        ``"auth_required"``) and additional context fields.
    """
    if not manager.is_alive():
        return {
            "status": "error",
            "error": "Browser not running. Call open_teams_browser first.",
        }

    download_url = _make_download_url(sharepoint_url)
    pw = None
    direct_err: Optional[Exception] = None

    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]

        # --- Strategy 1: direct download.aspx URL (short timeout) ---
        try:
            result = await _try_direct_download(ctx, download_url,
                                                 destination,
                                                 min(timeout_ms, 15_000))
            logger.info("Downloaded %s (%d bytes) to %s via direct URL",
                        sharepoint_url, result["size_bytes"], destination)
            return result
        except _TIMEOUT_ERRORS as first_err:
            direct_err = first_err
            logger.warning("Direct download failed (%s). "
                           "Trying Excel Online UI fallback...", first_err)

        # Navigate to the document so the Office Online iframe loads
        # (needed for strategy 2 UI fallback). Non-fatal if this fails.
        try:
            page = await ctx.new_page()
            try:
                await page.goto(sharepoint_url, wait_until="load",
                                timeout=timeout_ms)
                await page.wait_for_timeout(5_000)
            finally:
                await page.close()
        except Exception as nav_err:
            logger.warning("Iframe pre-load navigation failed (%s); "
                           "strategy 2 may still work if doc is already open",
                           type(nav_err).__name__)

    except Exception as exc:
        logger.exception("SharePoint direct download setup failed")
        return {"status": "error", "error": str(exc)}
    finally:
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass

    # --- Strategy 2: Excel Online UI via raw CDP ---
    try:
        result = await _try_ui_download(sharepoint_url, destination,
                                         timeout_ms)
        logger.info("Downloaded %s (%d bytes) to %s via UI click",
                    sharepoint_url, result["size_bytes"], destination)
        return result
    except _TIMEOUT_ERRORS as ui_err:
        logger.error("UI download also failed: %s", ui_err)
        return {
            "status": "auth_required",
            "error": (
                f"Both download strategies failed. "
                f"Direct: {direct_err}. UI: {ui_err}. "
                f"SharePoint authentication may have expired — "
                f"open the browser and authenticate, then retry."
            ),
        }
    except Exception as exc:
        logger.exception("SharePoint UI download failed")
        return {"status": "error", "error": str(exc)}

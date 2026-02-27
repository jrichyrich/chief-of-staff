"""Download files from SharePoint using the persistent Playwright browser.

Uses the same CDP-connected browser that Teams tools use (already
Okta-authenticated). Opens a new page, converts the SharePoint URL
to a direct download link, intercepts the download, and saves locally.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _make_download_url(sharepoint_url: str) -> str:
    """Convert a SharePoint view URL into a direct download URL.

    Replaces ``action=<anything>`` with ``action=download`` so that
    SharePoint responds with ``Content-Disposition: attachment``.
    """
    if re.search(r"[?&]action=", sharepoint_url):
        return re.sub(r"([?&])action=\w+", r"\1action=download", sharepoint_url)
    # No action param — append it
    sep = "&" if "?" in sharepoint_url else "?"
    return f"{sharepoint_url}{sep}action=download"


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
    page = None

    try:
        pw, browser = await manager.connect()
        ctx = browser.contexts[0]
        page = await ctx.new_page()

        async with page.expect_download(timeout=timeout_ms) as download_info:
            await page.goto(download_url, wait_until="commit", timeout=timeout_ms)

        download = await download_info.value
        failure = await download.failure()
        if failure:
            return {"status": "error", "error": f"Download failed: {failure}"}

        destination.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(str(destination))

        size = destination.stat().st_size
        if size == 0:
            return {"status": "error", "error": "Downloaded file is empty (0 bytes)"}

        logger.info("Downloaded %s (%d bytes) to %s", sharepoint_url, size, destination)
        return {
            "status": "downloaded",
            "path": str(destination),
            "size_bytes": size,
        }

    except TimeoutError:
        return {
            "status": "auth_required",
            "error": (
                "Download timed out — SharePoint authentication may have expired. "
                "Open the browser and authenticate, then retry."
            ),
        }
    except Exception as exc:
        logger.exception("SharePoint download failed")
        return {"status": "error", "error": str(exc)}
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass

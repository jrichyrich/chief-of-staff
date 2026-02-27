"""General-purpose SharePoint download tools for MCP server.

Provides a generic ``download_from_sharepoint`` tool that can download any
file from the organization's SharePoint via the persistent Playwright browser
(same one used for Teams messaging — already Okta-authenticated).
"""

import json
import logging
import re
import sys
from pathlib import Path

import config as app_config

logger = logging.getLogger("jarvis-mcp")

# Allowed file extensions for downloaded files (security guard)
_ALLOWED_EXTENSIONS = {
    ".xlsx", ".xls", ".csv",          # Spreadsheets
    ".docx", ".doc",                   # Word
    ".pptx", ".ppt",                   # PowerPoint
    ".pdf",                            # PDF
    ".txt", ".md", ".json", ".yaml",   # Text / data
    ".zip",                            # Archives
    ".png", ".jpg", ".jpeg", ".gif",   # Images
}


def _infer_filename(sharepoint_url: str) -> str:
    """Extract a filename from the SharePoint URL, or generate a default."""
    # Try ?file= parameter first
    match = re.search(r"[?&]file=([^&]+)", sharepoint_url)
    if match:
        return match.group(1)
    # Try last path segment before query string (skip .aspx pages)
    path_match = re.search(r"/([^/?]+\.\w{2,5})(?:\?|$)", sharepoint_url)
    if path_match:
        candidate = path_match.group(1)
        if not candidate.lower().endswith(".aspx"):
            return candidate
    return "sharepoint_download"


def register(mcp, state):
    """Register SharePoint download tools with the MCP server."""

    @mcp.tool()
    async def download_from_sharepoint(
        sharepoint_url: str,
        destination_dir: str = "",
        filename: str = "",
    ) -> str:
        """Download any file from SharePoint using the persistent browser.

        Uses the same Okta-authenticated Chromium browser as Teams tools.
        Supports Excel, Word, PowerPoint, PDF, and other common file types.

        The browser must be running (call open_teams_browser first if needed).

        Two download strategies are tried automatically:
        1. Direct download via download.aspx URL (fastest, works for most files)
        2. Excel Online UI fallback via CDP (for Excel files when direct fails)

        Args:
            sharepoint_url: Full SharePoint URL to the document. Accepts view
                URLs (Doc.aspx), sharing links (/:x:/r/), or direct links.
            destination_dir: Directory to save the file. Defaults to
                data/sharepoint-downloads/. Must be within allowed paths.
            filename: Override the filename. If empty, inferred from the URL.
        """
        from browser.manager import TeamsBrowserManager
        from browser.sharepoint_download import download_sharepoint_file

        if not sharepoint_url or not sharepoint_url.strip():
            return json.dumps({
                "status": "error",
                "error": "sharepoint_url is required.",
            })

        sharepoint_url = sharepoint_url.strip()

        # Resolve destination directory
        if destination_dir:
            dest_dir = Path(destination_dir).resolve()
        else:
            dest_dir = app_config.SHAREPOINT_DOWNLOAD_DIR.resolve()

        # Security: restrict to allowed directories
        allowed_roots = [
            app_config.SHAREPOINT_DOWNLOAD_DIR.resolve(),
            app_config.DATA_DIR.resolve(),
            Path.home().resolve() / "Documents",
            Path.home().resolve() / "Downloads",
            Path.home().resolve() / "Library" / "CloudStorage",
        ]
        if not any(
            dest_dir == root or dest_dir.is_relative_to(root)
            for root in allowed_roots
        ):
            return json.dumps({
                "status": "error",
                "error": (
                    f"Access denied: destination must be within allowed "
                    f"directories ({', '.join(str(r) for r in allowed_roots)})"
                ),
            })

        # Resolve filename
        resolved_filename = filename.strip() if filename else _infer_filename(sharepoint_url)

        # Security: validate extension
        ext = Path(resolved_filename).suffix.lower()
        if ext and ext not in _ALLOWED_EXTENSIONS:
            return json.dumps({
                "status": "error",
                "error": (
                    f"File extension '{ext}' not allowed. "
                    f"Supported: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
                ),
            })

        destination = dest_dir / resolved_filename

        # Ensure browser is running
        manager = TeamsBrowserManager()
        if not manager.is_alive():
            launch_result = manager.launch()
            if launch_result.get("status") == "error":
                return json.dumps({
                    "status": "error",
                    "step": "browser_launch",
                    "error": launch_result["error"],
                })

        # Download
        dl_result = await download_sharepoint_file(
            manager, sharepoint_url, destination
        )

        if dl_result["status"] == "downloaded":
            dl_result["filename"] = resolved_filename
            return json.dumps({
                "status": "downloaded",
                "path": dl_result["path"],
                "filename": resolved_filename,
                "size_bytes": dl_result["size_bytes"],
                "method": dl_result.get("method", "unknown"),
                "message": (
                    f"Downloaded '{resolved_filename}' "
                    f"({dl_result['size_bytes']:,} bytes) to {dl_result['path']}"
                ),
            })

        return json.dumps(dl_result)

    # Expose at module level for testing
    module = sys.modules[__name__]
    module.download_from_sharepoint = download_from_sharepoint

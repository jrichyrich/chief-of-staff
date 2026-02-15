import platform
import subprocess
from typing import Optional

_IS_MACOS = platform.system() == "Darwin"


def _escape_osascript(text: str) -> str:
    """Escape text for safe use in AppleScript strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


class Notifier:
    """Send macOS notifications and alerts via osascript."""

    @staticmethod
    def send(
        title: str,
        message: str,
        subtitle: Optional[str] = None,
        sound: Optional[str] = "default",
    ) -> dict:
        if not _IS_MACOS:
            return {"error": "Notifications are only available on macOS"}

        title_escaped = _escape_osascript(title)
        message_escaped = _escape_osascript(message)

        script = f'display notification "{message_escaped}" with title "{title_escaped}"'
        if subtitle:
            script += f' subtitle "{_escape_osascript(subtitle)}"'
        if sound:
            script += f' sound name "{_escape_osascript(sound)}"'

        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return {"status": "sent", "title": title, "message": message}
        except subprocess.TimeoutExpired:
            return {"error": "Notification timed out"}
        except subprocess.CalledProcessError as e:
            return {"error": f"osascript failed: {e.stderr.strip()}"}
        except FileNotFoundError:
            return {"error": "osascript not found — not running on macOS?"}

    @staticmethod
    def send_alert(title: str, message: str) -> dict:
        if not _IS_MACOS:
            return {"error": "Alerts are only available on macOS"}

        title_escaped = _escape_osascript(title)
        message_escaped = _escape_osascript(message)

        script = f'display alert "{title_escaped}" message "{message_escaped}"'

        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            return {"status": "sent", "title": title}
        except subprocess.TimeoutExpired:
            return {"error": "Alert timed out (user may not have responded)"}
        except subprocess.CalledProcessError as e:
            return {"error": f"osascript failed: {e.stderr.strip()}"}
        except FileNotFoundError:
            return {"error": "osascript not found — not running on macOS?"}

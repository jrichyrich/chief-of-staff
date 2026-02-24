"""Shared constants for Teams browser automation."""

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

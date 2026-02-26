"""Shared constants for Teams browser automation."""

# Timeout (ms) for waiting for user to complete SSO authentication.
AUTH_TIMEOUT_MS = 300_000

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

# Okta configuration.
OKTA_URL = "https://mychg.okta.com"

# URL patterns that indicate we're on the Okta dashboard (authenticated).
OKTA_DASHBOARD_PATTERNS = (
    "/app/UserHome",
    "/app/user-home",
    "/enduser/catalog",
)

# CSS selectors for the Teams app tile on the Okta dashboard, tried in order.
# Tile is named "Microsoft Office 365 Teams" (verified 2026-02-26).
OKTA_TEAMS_TILE_SELECTORS = (
    'a[data-se="app-card"]:has-text("Microsoft Office 365 Teams")',
    'a[data-se="app-card"]:has-text("Teams")',
    'a:has-text("Microsoft Office 365 Teams")',
    'a[aria-label*="Teams"]',
)

# Selectors for intermediate Microsoft SSO prompts after Okta tile click.
# "Do you trust mychg.com?" consent page and OAuth error retry buttons.
MS_SSO_CONTINUE_SELECTORS = (
    'input[type="submit"][value="Continue"]',
    'input#idSIButton9',
    'input[type="submit"][value="Yes"]',
)
MS_SSO_RETRY_SELECTORS = (
    'button#error-action-clear-cache',
    'button#error-action',
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

# --- Group chat creation selectors (verified 2026-02-26) ---

# Selector for the Chat tab in the left sidebar.
CHAT_TAB_SELECTORS = (
    'button[aria-label*="Chat ("]',
    'button[aria-label="Chat"]',
)

# Selectors for the "New message" button in the chat pane.
NEW_CHAT_SELECTORS = (
    'button[aria-label*="New message"]',
    '[data-tid="chat-pane-new-chat"]',
)

# Selectors for the "To:" recipient picker input field.
TO_FIELD_SELECTORS = (
    '[data-tid*="people-picker"] input',
    'input[placeholder*="Enter name"]',
    'input[placeholder*="name, chat, channel"]',
)

# Selector for recipient suggestion items in the people picker dropdown.
RECIPIENT_SUGGESTION_SELECTOR = '[data-tid*="people-picker"] [role="option"]'

# Selectors for the Send button (used when Enter alone doesn't send).
SEND_BUTTON_SELECTORS = (
    'button[data-tid="sendMessageCommands-send"]',
    'button[aria-label*="Send"]',
)

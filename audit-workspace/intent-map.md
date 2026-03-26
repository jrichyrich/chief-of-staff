# Intent Map — Teams Messaging via Graph API

## Chunk 1: GraphClient — Auth & HTTP Transport
- **Purpose**: MSAL-based OAuth2 auth with token caching; httpx transport with retry logic for all Graph API calls
- **User-facing feature(s)**: Infrastructure — backs all Teams send/read operations
- **Files**: `connectors/graph_client.py`
- **Key functions/classes**: `GraphClient`, `ensure_authenticated`, `_request`, `_build_token_cache`, `_device_code_flow`, `_auth_code_flow`, `proactive_token_refresh`
- **Inputs**: client_id, tenant_id, scopes; raw HTTP method+path+body
- **Outputs**: MSAL access tokens; parsed JSON responses or typed exceptions
- **Depends on**: msal, msal-extensions, httpx, vault.keychain
- **Risk level**: High

## Chunk 2: GraphClient — Teams Methods
- **Purpose**: Graph API calls for Teams chat operations: list, read messages, send, reply, chat management
- **User-facing feature(s)**: Send Teams message, Read Teams messages, Reply to message, Manage chat members
- **Files**: `connectors/graph_client.py` (lines 611–829)
- **Key functions/classes**: `list_chats`, `get_chat_messages`, `send_chat_message`, `reply_to_chat_message`, `find_chat_by_members`, `resolve_user_email`, `get_user_by_email`, `create_chat`, `update_chat_topic`, `list_chat_members`, `add_chat_member`, `remove_chat_member`
- **Inputs**: chat_id, message text, member emails, display names
- **Outputs**: Graph API response dicts or exceptions
- **Depends on**: Chunk 1 (_request)
- **Risk level**: High

## Chunk 3: MCP Tool Layer — post/reply/manage/read
- **Purpose**: Exposes Teams operations as MCP tools; backend routing (graph → browser fallback); chat resolution logic
- **User-facing feature(s)**: `post_teams_message`, `reply_to_teams_message`, `manage_teams_chat`, `read_teams_messages`
- **Files**: `mcp_tools/teams_browser_tools.py` (lines 147–771)
- **Key functions/classes**: `_graph_send_message`, `post_teams_message`, `reply_to_teams_message`, `manage_teams_chat`, `read_teams_messages`
- **Inputs**: MCP tool call args (target, message, chat_id, etc.)
- **Outputs**: JSON strings back to Claude/MCP caller
- **Depends on**: Chunk 2 (GraphClient), browser posters (fallback), M365 bridge (fallback)
- **Risk level**: High

## Chunk 4: MCP Tool Layer — Browser Lifecycle
- **Purpose**: Manages persistent Playwright/agent-browser for Teams fallback path
- **User-facing feature(s)**: `open_teams_browser`, `close_teams_browser`, `confirm_teams_post`, `cancel_teams_post`
- **Files**: `mcp_tools/teams_browser_tools.py` (lines 1–146, 326–525)
- **Key functions/classes**: `open_teams_browser`, `close_teams_browser`, `_wait_for_teams`, `_get_poster`, `_get_manager`, `_get_ab`
- **Inputs**: backend config (`TEAMS_SEND_BACKEND`), browser state
- **Outputs**: JSON status strings
- **Depends on**: browser.manager, browser.teams_poster, browser.ab_poster, browser.okta_auth
- **Risk level**: Medium

## Chunk 5: Config & Initialization
- **Purpose**: Credential loading, backend selection, GraphClient lifecycle (startup/shutdown)
- **User-facing feature(s)**: Infrastructure — determines which path runs
- **Files**: `config.py` (lines 163–177), `mcp_server.py` (lines 200–254)
- **Key functions/classes**: `M365_CLIENT_ID`, `M365_TENANT_ID`, `M365_GRAPH_ENABLED`, `TEAMS_SEND_BACKEND`, `TEAMS_READ_BACKEND`; lifespan GraphClient init/close
- **Inputs**: env vars, vault/keychain secrets
- **Outputs**: populated `_state.graph_client`, backend routing decisions
- **Depends on**: vault.keychain, connectors.graph_client
- **Risk level**: High

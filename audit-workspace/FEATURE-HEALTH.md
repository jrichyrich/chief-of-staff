# Feature Health Map

**Date**: 2026-03-12
**Based on**: Consolidated audit of 6 source reports (35 unique findings)

---

| Feature | Health | Finding Count | Top Issue |
|---------|--------|--------------|-----------|
| Secret Management (vault/keychain) | 🟡 | 6 | AUD-007: No subprocess timeout -- can freeze MCP server startup |
| Auth Flow (MSAL, device code, token refresh) | 🔴 | 7 | AUD-001: Client credentials use wrong scopes -- daemon auth always fails |
| Teams Messaging (send) | 🔴 | 5 | AUD-008: Substring display-name match delivers to wrong recipient |
| Teams Messaging (read) | 🟡 | 3 | AUD-018: O(N) sequential API calls, ~10s for 50 chats |
| Email Send/Reply | 🔴 | 5 | AUD-002/003: BCC, reply_all, CC silently dropped on Graph path |
| SSL/TLS Handling | 🟢 | 0 | Clean -- SSL never disabled, proper context chain |
| Backend Fallback Logic | 🟡 | 4 | AUD-015/016: Identical exception branches mask bugs; httpx errors skip fallback |
| Config & Lifecycle | 🟡 | 4 | AUD-021: Unguarded close() can prevent memory_store cleanup |
| Security (cross-cutting) | 🟡 | 6 | AUD-010: Token cache file world-readable; AUD-028: Teams Graph skips confirm_send |

---

## Key Takeaways

**Three areas are red and need immediate attention:**

1. **Auth Flow**: The client credentials scope bug (AUD-001) means daemon/headless mode is completely broken. This is the single most impactful finding.

2. **Email Send/Reply**: Silent data loss -- BCC and reply_all are dropped without any error. Users sending BCC emails through the Graph backend have no indication recipients were lost.

3. **Teams Send**: Messages can go to the wrong person due to substring matching with no disambiguation. Combined with `issubset` chat matching (AUD-017), the misdirection risk compounds.

**SSL/TLS is the one clean area** -- no findings, good practices throughout.

**The yellow areas** share a common theme: exception handling and fallback logic that works for the happy path but has gaps in edge cases (timeouts, unexpected errors, shutdown races).

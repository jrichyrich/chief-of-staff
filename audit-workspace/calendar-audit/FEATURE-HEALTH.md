# Feature Health Map

| Feature | Health | Critical | Warnings | Top Issue |
|---------|--------|----------|----------|-----------|
| List calendars | 🟢 | 0 | 0 | Clean |
| Get/search events | 🟡 | 1 | 3 | Prompt injection -- user-controlled data in M365 bridge prompts |
| Create/update/delete events | 🟡 | 1 | 5 | Prompt injection + alarms silently dropped on M365 + UID brute-force scan |
| Find my open slots | 🟢 | 0 | 2 | Boolean type-safety in event normalization |
| Find group availability | 🟢 | 0 | 0 | Guidance-only tool -- no runtime logic |
| Event ownership tracking | 🟡 | 1 | 2 | No output validation -- fabricated events could corrupt ownership DB |
| Provider routing & fallback | 🟢 | 0 | 2 | Thin test coverage (4 tests for 15+ routing paths) |
| Event deduplication | 🟢 | 0 | 1 | `str(None)` collision in dedupe keys |
| Security (all features) | 🟡 | 2 | 4 | Prompt injection via M365 bridge is primary risk |
| Infrastructure / Cross-cutting | 🟡 | 0 | 4 | No SIGKILL escalation on subprocess timeout; thin boundary tests |

## Health Key
- 🔴 Critical -- has findings that cause real harm in production
- 🟡 Needs Work -- functional with meaningful gaps
- 🟢 Clean -- minor notes only or nothing to flag

## Total Finding Counts
- 🔴 Critical: 2
- 🟡 Warning: 16
- 🟢 Note: 11
- 💀 Dead weight: 1 item

## Recommended Focus Order

**First**: Harden the M365 bridge prompt injection surface (Findings #1 and #2). Add a system prompt with explicit data/instruction boundaries and server-side output validation on bridge responses. This is the only realistic external attack vector -- crafted meeting invites are a common delivery mechanism in enterprise environments, and the bridge model has write access to M365 calendars.

**Second**: Fix the Apple backend UID mismatch (`eventkit.py:159`) so `_find_event_by_uid` uses the correct API for external identifiers. This eliminates the 4-year brute-force scan on every update/delete, which is a latent performance issue that will worsen as calendar history grows.

**Third**: Close the test coverage gaps on the provider router (expand from 4 to ~15 tests) and M365 bridge (add bridge-level write operation tests and Apple provider adapter tests). These boundary layers are where integration bugs are most likely to surface.

**Fourth**: Address the remaining warnings as a batch -- silent exception swallowing in `_run()`, the dropped `alarms` parameter, `provider_preference` validation, subprocess SIGKILL escalation, and the double `decide_read` call.

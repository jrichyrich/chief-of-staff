# Feature Health Map: find_my_open_slots Pipeline

| Feature | Health | Top Issue |
|---------|--------|-----------|
| M365 Calendar Data Fetch | :red_circle: | Bridge silently drops events — caused production failure today |
| Availability Analysis (end-to-end) | :red_circle: | Wrong results due to incomplete input data from M365 bridge |
| Observability / Debugging | :red_circle: | Zero visibility into which events arrived — no way to detect drops |
| Tentative Classification | :yellow_circle: | user_email not passed — any tentative attendee marks event as soft |
| M365 Connectivity Management | :yellow_circle: | Stale state on check failure; silent exception swallow |
| Event Deduplication | :yellow_circle: | ical_uid not available from bridge; fallback dedup is fragile |
| Availability Engine (core algorithm) | :green_circle: | Well-implemented — correct for the data it receives |
| Apple Calendar Data Fetch | :green_circle: | Deterministic, reliable, well-tested |
| Provider Routing | :green_circle: | Clean logic, handles all cases |
| Soft Block Classification | :green_circle: | Good keyword/attendee detection with confidence scoring |
| Formatted Slot Sharing | :green_circle: | Clean output, timezone-aware |
| Security (cross-cutting) | :yellow_circle: | Prompt sanitization present but basic; subprocess spawning reviewed |

## Legend
- :red_circle: = Broken or unreliable — needs immediate fix
- :yellow_circle: = Works but has known issues — fix when able
- :green_circle: = Clean — no action needed

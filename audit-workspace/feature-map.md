# Feature Map: find_my_open_slots Pipeline

| Feature | Chunks Involved | Risk |
|---------|----------------|------|
| Availability Analysis (find_my_open_slots) | mcp-tool-handler, availability-engine, unified-calendar-routing | Critical |
| M365 Calendar Data Fetch | m365-provider-chain, unified-calendar-routing | Critical |
| Apple Calendar Data Fetch | apple-provider, unified-calendar-routing | Low |
| Event Normalization | availability-engine | High |
| Soft Block Classification | availability-engine | Medium |
| Provider Routing | unified-calendar-routing | Medium |
| Formatted Slot Sharing | availability-engine | Low |

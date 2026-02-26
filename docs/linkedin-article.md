# How I Built an AI Chief of Staff That Runs My Security Organization

## The Problem Nobody Talks About

I'm a VP of Security, Identity, and Privacy at CHG Healthcare. I manage a team across IAM, SecOps, Product Security, and Privacy & GRC. On any given day, I'm context-switching between Outlook, Teams, Jira, Apple Calendar, iMessage, Okta, Confluence, SharePoint, and at least three security tools — before my first meeting starts.

The problem isn't any single tool. It's the aggregate. The cognitive load of synthesizing information scattered across a dozen platforms into something actionable. Every morning I was spending 30-45 minutes just building a mental model of the day: What's on my calendar? What emails came in overnight? Are there any incidents? Which delegations are overdue? What decisions am I blocking?

I kept thinking: an executive with this problem hires a Chief of Staff. Someone who pulls together the briefing, tracks the action items, flags the risks, and makes sure nothing falls through the cracks.

So I built one. I named him Jarvis.

---

## What Jarvis Actually Is

Jarvis is not a chatbot. It's not a wrapper around an LLM that summarizes your email.

It's an AI orchestration system built on Anthropic's Claude, running as an MCP (Model Context Protocol) server that integrates with Claude Code and Claude Desktop. At its core, a "Chief of Staff" agent manages a roster of 44 specialized expert agents, each with scoped tool access, persistent memory, and a specific job to do.

The numbers as of today:

- **105+ tools** across 24 specialized modules
- **44 expert agents** — from daily briefing to security auditing to OKR tracking
- **14 SQLite tables** with full-text search, vector embeddings, and temporal decay
- Integrations with **Apple Calendar, Reminders, Mail, and iMessage** (native macOS via PyObjC)
- **Microsoft 365** — Outlook, Teams, SharePoint
- **Atlassian** — Jira and Confluence for project and knowledge management
- **Browser automation** — Playwright-driven Chromium that authenticates through Okta SSO and posts to Teams

It runs on my machine. My data stays local. The memory persists across sessions with confidence scoring and temporal decay — facts I stored six months ago gradually lose weight unless I pin them.

---

## How It Started vs. How It's Going

Version 0.1 was a fact store. Literally just `store_fact` and `query_memory`. I wanted Claude to remember things about my team, my preferences, and my projects between conversations.

Then I added document ingestion — PDFs, markdown, code files chunked into vectors with ChromaDB. Then calendar integration. Then reminders. Then email.

Each integration followed the same pattern: I'd catch myself doing something repetitive across multiple tools and ask, "What if Jarvis could also do this?" The answer was always yes, and each new capability compounded the ones before it.

The real inflection point was expert agents. Instead of one monolithic AI trying to do everything, I built a system where the Chief of Staff agent delegates to specialists. A `meeting_prep` agent that pulls calendar context, email threads, relationship notes, and pending delegations for a 1:1. A `security_auditor` agent that only has access to security-relevant tools. An `okr_tracker` that parses our OKR spreadsheet and flags at-risk initiatives.

Each agent is defined in YAML. Each declares its capabilities. The system only gives it the tools those capabilities allow. A `daily_briefing` agent can read your calendar and email but can't send messages. A `communications` agent can send but needs explicit confirmation before external delivery.

That constraint model — capability-gated tool access — is what makes the system trustworthy enough to actually use.

---

## What a Day With Jarvis Looks Like

Here's a real morning.

I open Claude Code and say: "What do I need to know today?"

Jarvis queries seven sources in parallel:

1. **M365 Calendar** — meetings, conflicts, prep needed
2. **Apple Calendar** — personal and iCloud events
3. **Outlook email** — flagged, unread, threads involving my directs
4. **Teams** — mentions, DMs, active incident threads
5. **Memory** — overdue delegations, pending decisions, upcoming deadlines
6. **Reminders** — tasks due today
7. **iMessages** — anything from my team overnight

In about 15 seconds, I have a synthesized briefing with conflicts flagged, action items highlighted, and a recommended focus order. No app-switching. No scanning five inboxes.

Later in the day, I need to send a formatted message to a colleague in Teams. Jarvis launches a persistent Chromium browser, authenticates through our Okta SSO (including handling Microsoft's "Do you trust this domain?" consent prompts automatically), navigates to Teams, finds the person, and prepares the message for my confirmation. I say "send it." Done.

A webhook fires from Jira — a blocker was raised on a critical initiative. An event rule matches the pattern, dispatches the `proactive_alerts` agent, which assesses the risk and delivers a summary to me via notification.

None of this is hypothetical. This is Tuesday.

---

## The Hard Parts

Building Jarvis taught me that AI orchestration is 20% LLM magic and 80% plumbing.

**The calendar problem.** I needed events from both Apple Calendar and Microsoft 365. That meant building a unified routing layer that tracks which provider owns which event, handles CRUD across both, and merges availability without double-counting. I also learned the hard way: never name a Python package `calendar/` — it shadows Python's stdlib module and breaks the entire Anthropic SDK import chain.

**Browser automation at enterprise scale.** Posting to Teams sounds simple until your org requires Okta SSO with FastPass MFA, Microsoft throws a "Do you trust this domain?" consent page, and then a third-party cookie issue causes an infinite redirect loop on the SSO reprocess page. I built an authentication flow that handles all of these edge cases — tile detection with retry loops, SSO prompt auto-clicking, and a fallback to direct navigation when the redirect chain breaks.

**Memory that forgets gracefully.** Not all facts are equal. A preference I stated yesterday matters more than something I mentioned three months ago. The memory system uses temporal decay with a 90-day half-life, confidence scoring, and pinned facts that never decay. Combined with hybrid search (full-text BM25 + vector similarity with MMR reranking), Jarvis retrieves what's relevant, not just what matches keywords.

**Trust boundaries.** This is the one I think about most. Jarvis can send emails, post to Teams, and reply to iMessages. Every outbound message runs through a safety-tiered routing system that considers: Is this internal or external? Is this a first contact? What's the urgency? The result is one of three tiers: auto-send, confirm required, or draft only. External first-contact messages always require confirmation. I sleep fine at night.

---

## What I've Learned

**Start with memory, not automation.** The most valuable thing Jarvis does isn't sending messages or managing my calendar. It's remembering. Relationships, preferences, decisions, context — the things that fall out of your head between meetings. If you build nothing else, build a persistent fact store.

**Agents beat monoliths.** A single prompt trying to do everything will hallucinate, lose context, and make mistakes. Forty-four focused agents with scoped access and specific system prompts are dramatically more reliable. Each one is simple. The orchestration makes them powerful.

**Compound capability is real.** Calendar access alone is useful. Calendar + email + memory is transformative. Each new integration doesn't add linearly — it multiplies the value of everything already connected. Person enrichment pulls from six sources in parallel. That's only possible because each source was already integrated for its own reasons.

**The barrier to entry is lower than you think.** The MCP protocol means you can start with a single tool — `store_fact` — and have it working inside Claude Desktop in an afternoon. You don't need 105 tools to get value. You need one that solves a real pain point, and the discipline to keep iterating.

---

## The Real Takeaway

Jarvis started as a personal productivity hack. But building it revealed something bigger about where software is going.

For two decades, the model has been: a vendor builds a product, ships it to millions of users, and everyone adapts their workflow to fit the tool. You learn Salesforce's way of doing CRM. You learn Jira's way of tracking work. You learn Outlook's way of managing email. The software doesn't know you. You know it.

Jarvis inverts that relationship.

My Jarvis knows my team, my priorities, my meeting patterns, my decision-making style, and the six platforms I actually use every day. It doesn't ask me to switch contexts — it eliminates the need to. And the architecture isn't proprietary to my role. A sales leader builds a different set of agents with different integrations, but the foundation is the same: persistent memory that knows you, scoped agents that do the work, and an orchestration layer shaped to your specific workflow and tech stack.

This is where personal software is headed. Not more SaaS platforms that everyone conforms to. Individually tailored orchestration layers that conform to you. Software that knows you — what you care about, how you work, what you've decided, and what you're likely to forget.

The AI models are ready. The integration protocols exist. The question isn't whether this future arrives. It's whether you build yours or wait for someone to sell you a generic version of it.

I chose to build.

---

*Jason Richards is VP of Security, Identity & Privacy at CHG Healthcare, where he leads the ISP organization across IAM, SecOps, Product Security, and Privacy & GRC.*

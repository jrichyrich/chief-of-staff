I built an AI Chief of Staff. His name is Jarvis.

Not a chatbot. Not a copilot that autocompletes my sentences. An orchestration system that manages 44 expert agents, holds persistent memory across sessions, and integrates with every tool I touch — Outlook, Teams, Jira, Apple Calendar, iMessage, Okta, and more.

What does that actually mean?

This morning, Jarvis pulled my calendar from two providers, flagged a scheduling conflict, summarized an active incident thread in Teams, and sent three formatted messages to colleagues — all through a browser it authenticated through Okta SSO on its own.

Six months ago, that was 45 minutes of context-switching across six apps before my first meeting.

The system isn't magic. It's 105 tools, 14 database tables, a SQLite memory store with temporal decay, and a lot of iterative problem-solving. I didn't plan to build something this large. I started with a simple fact store and kept asking "what if it could also..."

But the real insight isn't what Jarvis does for me. It's what it represents.

We've spent 20 years adapting ourselves to software. Learning the UI, conforming to the workflow someone else designed, switching between apps that don't talk to each other.

Jarvis flips that. It's software that adapts to me — my tools, my team, my patterns, my priorities. And the same architecture works for anyone. A sales leader's Jarvis looks completely different from mine, but the foundation is identical: persistent memory, scoped agents, and integrations tailored to their stack.

This is the future of personal software. Not another SaaS platform everyone conforms to. An orchestration layer anyone can tailor to the way they actually work.

More in my full writeup (link in comments).

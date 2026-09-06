---
title: Critical facts
description: "~120 tokens that are always true and always injected by the SessionStart hook. Pointers only — never values that change."
---

# Critical facts (always loaded)

- Owner: [[your-name]], role, language, timezone.
- Prices: see [[pricing]]. Finances: see [[finance-overview]].
- Servers/access: [[ssh-hosts]]; secrets live in your password manager, never in the wiki.
- Active clients (pointers): [[client-a]], [[client-b]].
- Rules: never touch production without an explicit go; write durable knowledge back (wiki_append/wiki_create).

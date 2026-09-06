# wiki-inbox — Telegram capture bot

Koden er klar; det eneste der mangler er et bot-token, som kun Mads kan oprette.

## 1. Opret botten (Mads, 2 minutter)
1. Åbn Telegram → **@BotFather** → `/newbot` → navn fx "Hjernen", brugernavn fx `mahope_wiki_bot`.
2. Kopiér tokenet. Gem det i Bitwarden som "infra: wiki-inbox telegram token".
3. Find dit numeriske user-id: skriv til **@userinfobot** (eller start botten og se `from.id` i loggen).

## 2. Env-fil på hetzner-main
```
/etc/dokploy/wiki-inbox.env   (chmod 600)
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USER_ID=<dit id>
GITHUB_TOKEN=<samme fine-grained token som wiki-mcp>
WIKI_REPO=you/your-vault
WHISPER_MODEL=small        # tom = ingen transskription af voice memos (dansk virker med small/medium)
```

## 3. Deploy
Dokploy → projekt "Wiki Infrastructure" → ny Compose `wiki-inbox`, repo mahope/llm-wiki, compose path `deploy/wiki-inbox/docker-compose.yml` → Deploy. Ingen domæne/Traefik (botten poller Telegram).

## 4. Brug
- Send tekst, billede (med caption) eller voice memo til botten → `_inbox/YYYY-MM-DD-HHMM-<slug>.md` (+ vedhæftning) committes og pushes med det samme; botten svarer med filnavn.
- Routinen **Wiki Inbox Triage** (06:30) behandler filer med `triaged: false` og lægger indholdet på den rette side eller i `_review-queue.md`.
- Kun `TELEGRAM_ALLOWED_USER_ID` må skrive; alle andre får "Ikke tilladt".

## Noter
- Voice: `faster-whisper` med `WHISPER_MODEL=small` (~500 MB download første gang, CPU int8, dansk OK). Sæt tom for at springe over.
- Billeder gemmes i `_inbox/` ved siden af noten; triage-routinen refererer dem, men læser dem ikke.

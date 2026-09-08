# Wiki Agent — Dokploy Setup Guide

## 1. Opret GitHub Token

Gå til: https://github.com/settings/tokens?type=beta

- **Token name:** `wiki-agent-dokploy`
- **Expiration:** 90 days
- **Repository access:** Only select repositories → **llm-wiki**
- **Permissions → Contents:** Read and write
- Klik **Generate token** → kopiér tokenet

## 2. Find Hostinger IMAP password

Det er login-passwordet til den mailkonto du satte i `HOSTINGER_EMAIL` (samme som webmail.hostinger.com).

## 3. Deploy i Dokploy

1. Åbn Dokploy dashboard
2. Opret nyt **Project**: "Wiki Infrastructure"
3. I projektet, opret ny **Compose** service:
   - **Name:** wiki-agent
   - **Source:** GitHub → `mahope/llm-wiki`
   - **Compose path:** `deploy/wiki-agent/docker-compose.yml`
4. Under **Environment Variables**, tilføj:

```
HOSTINGER_PASSWORD=dit-hostinger-password
RESEND_API_KEY=re_dit-resend-api-key-her
GITHUB_TOKEN=github_pat_dit-token-her
```

5. Klik **Deploy**

## 4. Verificér

Tjek logs i Dokploy for:
```
=== Wiki Agent starting ===
Cloning wiki repo...
Wiki agent ready. Starting cron...
```

Email-export kører første gang inden for 4 timer. Briefing-send kører inden for 30 min efter næste remote agent push.

## Hvad den gør

| Job | Schedule (UTC) | DK tid | Hvad |
|-----|---------------|--------|------|
| Email export | 04,08,12,16,20 | 06,10,14,18,22 | IMAP → _sources/ → git push |
| Pull + send | */30 | Hver 30 min | Git pull → send nye briefings |
| Dashboard | 05:00 | 07:00 | Scores + dashboard → git push |
| Health check | Søn 17:00 | Søn 19:00 | HTTP check af client sites |

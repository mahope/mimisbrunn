#!/usr/bin/env python3
"""
wiki-inbox — Telegram-bot til capture fra telefonen (issue #17).

Modtager tekst, billeder og voice memos fra ÉN tilladt bruger, skriver dem som
`_inbox/YYYY-MM-DD-HHMM-<slug>.md` (frontmatter: source: telegram, triaged: false)
i wiki-repoet, committer og pusher. Routinen "Wiki Inbox Triage" tager resten.

Env:
  TELEGRAM_BOT_TOKEN         fra BotFather
  TELEGRAM_ALLOWED_USER_ID   numerisk Telegram user-id (kun denne bruger)
  GITHUB_TOKEN, WIKI_REPO    (owner/repo) — bruges af entrypoint til klon + push
  WIKI_ROOT                  /wiki
  WHISPER_MODEL              fx "small" (valgfrit; faster-whisper). Tom = ingen transskription.

Ren stdlib + urllib (ingen SDK). Long polling.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED = str(os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")).strip()
WIKI = Path(os.environ.get("WIKI_ROOT", "/wiki"))
INBOX = WIKI / "_inbox"
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "").strip()
_whisper = None


def api(method: str, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{method}", data=data), timeout=70) as r:
        return json.load(r)


def download(file_id: str, dest: Path) -> Path:
    info = api("getFile", file_id=file_id)["result"]
    with urllib.request.urlopen(f"{FILE_API}/{info['file_path']}", timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


def transcribe(path: Path) -> str:
    global _whisper
    if not WHISPER_MODEL:
        return ""
    try:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = _whisper.transcribe(str(path), language="da", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        return f"[transskription fejlede: {e.__class__.__name__}]"


def git(*args):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=WIKI, capture_output=True, text=True, env=env, timeout=120)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9æøå]+", "-", s.lower()).strip("-")
    return s[:40] or "note"


def save_note(kind: str, text: str, attachments: list[Path], meta: dict) -> Path:
    INBOX.mkdir(exist_ok=True)
    now = dt.datetime.now()
    first = (text.strip().split("\n")[0] if text.strip() else kind)
    name = f"{now:%Y-%m-%d-%H%M}-{slugify(first)}.md"
    path = INBOX / name
    fm = ["---", "source: telegram", f"kind: {kind}", f"date: {now:%Y-%m-%d %H:%M}", "triaged: false"]
    for k, v in meta.items():
        fm.append(f"{k}: {v}")
    if attachments:
        fm.append("attachments:")
        fm += [f"  - {a.name}" for a in attachments]
    fm.append("---")
    body = text.strip() or f"({kind} uden tekst)"
    path.write_text("\n".join(fm) + "\n\n" + body + "\n", encoding="utf-8", newline="\n")
    return path


def commit_push(paths: list[Path], msg: str) -> str:
    git("add", "--", *[str(p.relative_to(WIKI)) for p in paths])
    r = git("commit", "-q", "-m", msg)
    if r.returncode != 0:
        return "intet at committe"
    pull = git("pull", "--rebase", "-q", "origin", "main")
    if pull.returncode != 0:
        git("rebase", "--abort")
        return "commit ok, men pull --rebase fejlede (ligger lokalt)"
    push = git("push", "-q", "origin", "main")
    return "pushet" if push.returncode == 0 else f"push fejlede: {push.stderr.strip()[:120]}"


def handle(msg: dict) -> str:
    chat_id = msg["chat"]["id"]
    uid = str(msg.get("from", {}).get("id", ""))
    if ALLOWED and uid != ALLOWED:
        return "Ikke tilladt."
    text = msg.get("text") or msg.get("caption") or ""
    attachments: list[Path] = []
    kind = "tekst"
    meta = {"telegram_message_id": msg.get("message_id")}
    if msg.get("photo"):
        kind = "billede"
        INBOX.mkdir(exist_ok=True)
        biggest = msg["photo"][-1]
        attachments.append(download(biggest["file_id"], INBOX / f"{dt.datetime.now():%Y-%m-%d-%H%M}-{biggest['file_unique_id']}.jpg"))
    if msg.get("document"):
        kind = "fil"
        d = msg["document"]
        attachments.append(download(d["file_id"], INBOX / f"{dt.datetime.now():%Y-%m-%d-%H%M}-{slugify(d.get('file_name', 'fil'))}{Path(d.get('file_name', '')).suffix}"))
    if msg.get("voice") or msg.get("audio"):
        kind = "voice"
        v = msg.get("voice") or msg.get("audio")
        audio = download(v["file_id"], INBOX / f"{dt.datetime.now():%Y-%m-%d-%H%M}-voice.ogg")
        attachments.append(audio)
        tr = transcribe(audio)
        text = (text + "\n\n" if text else "") + (tr or "(voice memo — ingen transskription konfigureret; lyt til filen)")
    note = save_note(kind, text, attachments, meta)
    status = commit_push([note, *attachments], f"wiki: inbox-capture {note.stem}")
    return f"Gemt: _inbox/{note.name} ({kind}) — {status}. Triage kører kl. 06:30."


def main():
    print("wiki-inbox bot starter", flush=True)
    offset = 0
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=60, allowed_updates=["message"])
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                m = upd.get("message")
                if not m:
                    continue
                try:
                    reply = handle(m)
                except Exception as e:
                    reply = f"Fejl: {e.__class__.__name__}: {str(e)[:120]}"
                    print(reply, file=sys.stderr, flush=True)
                api("sendMessage", chat_id=m["chat"]["id"], text=reply, reply_to_message_id=m.get("message_id"))
        except Exception as e:
            print(f"loop-fejl: {e!r}", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()

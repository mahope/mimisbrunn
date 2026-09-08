#!/usr/bin/env python3
"""
Møde-transskription (cloud) -> dansk referat -> _sources/meetings/ -> klar til /wiki-ingest.

Udbyder-agnostisk: STT-motoren er udskiftelig via --stt-provider (openai nu, syvai på sigt).
Kun stdlib — ingen pip-afhængigheder.

Nøgler fra miljø:
  OPENAI_API_KEY      (til transskription med gpt-4o-transcribe)
  ANTHROPIC_API_KEY   (til referat med Claude; udelad med --no-summary)

Brug:
  export OPENAI_API_KEY=sk-...
  export ANTHROPIC_API_KEY=sk-ant-...
  python scripts/transcribe-meeting.py moede.m4a --client "En Kunde" --participants "Anna, Bo"

Output: _sources/meetings/YYYY-MM-DD-<klient>-moede.md  (referat + fuld transskription)
Derefter:  /wiki-ingest _sources/meetings/<fil>
"""
import sys, os, re, json, argparse, datetime, uuid, subprocess, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "_sources", "meetings")
MAX_MB = 25  # OpenAI upload-grænse


def slug(s):
    s = s.lower()
    for a, b in [("æ", "ae"), ("ø", "oe"), ("å", "aa"), (" ", "-")]:
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9\-]", "", s) or "moede"


# ---------- STT-udbydere (udskiftelige) ----------
def _post_transcription(path, fields, url, key, who):
    """POST en lydfil + form-felter til et OpenAI-kompatibelt /audio/transcriptions-endpoint."""
    fname = os.path.basename(path)
    data = open(path, "rb").read()
    boundary = "----meeting" + uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        if value is None:
            continue
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.exit(f"{who} STT-fejl {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def _openai_audio(path, fields):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("Mangler OPENAI_API_KEY i miljøet.")
    return _post_transcription(path, fields, "https://api.openai.com/v1/audio/transcriptions", key, "OpenAI")


def transcribe_openai(path, model, language, prompt=None):
    return _openai_audio(path, {"model": model, "language": language,
                                "response_format": "text", "prompt": prompt}).strip()


def parse_speakers(spec: str) -> dict:
    """"1=Anna,2=Bo" -> {1: "Anna", 2: "Bo"}.

    Uden navne staar der "Taler 1" og "Taler 2" i transskriptet, og saa kan man ikke
    tilskrive en beslutning til nogen bagefter (issue #46)."""
    out = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        num, name = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        try:
            out[int(num.strip())] = name
        except ValueError:
            continue
    return out


def diarized_text(segments, names=None):
    """Byg en talermærket transskription ud fra segmenter med .speaker (indeks)."""
    names = names or {}
    lines, last = [], None
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        spk = s.get("speaker")
        if isinstance(spk, int):
            label = names.get(spk + 1) or f"Taler {spk + 1}"
        else:
            label = "Taler ?"
        if label == last and lines:
            lines[-1] += " " + text
        else:
            lines.append(f"**[{label}]** {text}")
            last = label
    return "\n\n".join(lines)


def transcribe_syvai(path, model, language, prompt=None, names=None):
    """syv.ai / Hviske (syv-transcribe): bedste dansk-STT med ML-taleradskillelse (diarize=auto).
    ML-diarisering klynger stemmer uafhængigt af kanaler → virker også på mikrofon-optagelser.
    Returnerer en talermærket transskription."""
    key = os.environ.get("SYVAI_API_KEY") or os.environ.get("HVISKE_API_KEY")
    if not key:
        sys.exit("Mangler SYVAI_API_KEY i miljøet (syv.ai/Hviske-nøgle, hv_...).")
    m = model if (model and model.startswith("syv")) else "syv-transcribe"
    fields = {"model": m, "language": language, "response_format": "verbose_json",
              "diarize": "auto", "prompt": prompt}
    raw = _post_transcription(path, fields, "https://platform.syv.ai/v1/audio/transcriptions", key, "syv.ai")
    return diarized_text(json.loads(raw).get("segments", []), names)


def transcribe_segments(path, language, prompt=None, model="whisper-1"):
    """Transskribér med segment-tidsstempler (verbose_json; whisper-1 understøtter timestamps)."""
    raw = _openai_audio(path, {"model": model, "language": language,
                               "response_format": "verbose_json", "prompt": prompt})
    d = json.loads(raw)
    return [{"start": float(s.get("start", 0.0)), "text": (s.get("text") or "").strip()}
            for s in d.get("segments", []) if (s.get("text") or "").strip()]


STT = {"openai": transcribe_openai, "syvai": transcribe_syvai}


# ---------- Stereo-diarisering via kanal-split ----------
def ffsplit_stereo(path):
    """Split et stereo-spor til to mono-filer (venstre, højre). Returnerer (L, R)."""
    base = os.path.splitext(path)[0]
    left, right = base + ".L.ogg", base + ".R.ogg"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path,
         "-filter_complex", "channelsplit=channel_layout=stereo[L][R]",
         "-map", "[L]", "-ac", "1", "-c:a", "libopus", "-b:a", "24k", left,
         "-map", "[R]", "-ac", "1", "-c:a", "libopus", "-b:a", "24k", right],
        capture_output=True, text=True)
    return left, right


def merge_dialogue(seg_a, spk_a, seg_b, spk_b):
    """Flet to talers segmenter til én tidssorteret, talermærket dialog."""
    tagged = [(s["start"], spk_a, s["text"]) for s in seg_a] + \
             [(s["start"], spk_b, s["text"]) for s in seg_b]
    tagged.sort(key=lambda t: t[0])
    lines, last = [], None
    for _, spk, text in tagged:
        if spk == last and lines:
            lines[-1] += " " + text
        else:
            lines.append(f"**[{spk}]** {text}")
            last = spk
    return "\n\n".join(lines)


# ---------- Referat via Claude ----------
def summarize_claude(transcript, client, model):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("  (springer referat over — ingen ANTHROPIC_API_KEY)")
        return None
    prompt = (
        f"Her er en rå transskription af et møde ({client}). Lav et kort dansk referat.\n"
        "Ret oplagte transskriptionsfejl i navne/termer ud fra kontekst. Struktur:\n"
        "## Resumé (2-3 sætninger)\n## Beslutninger\n## Action items (hvem gør hvad)\n"
        "## Deltagere & emner\nVær faktuel; opfind intet der ikke er i transskriptionen.\n\n"
        f"---\n{transcript}"
    )
    payload = json.dumps({"model": model, "max_tokens": 2000,
                          "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload, method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode("utf-8"))
            return d["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        print(f"  (referat fejlede {e.code}: {e.read().decode('utf-8','replace')[:200]})")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio_file")
    ap.add_argument("--client", default="ukendt")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--participants", default="")
    ap.add_argument("--language", default="da")
    ap.add_argument("--stt-provider", default="openai", choices=list(STT))
    ap.add_argument("--stt-model", default="gpt-4o-transcribe")
    ap.add_argument("--summary-model", default="claude-sonnet-5")
    ap.add_argument("--no-summary", action="store_true")
    ap.add_argument("--prompt", default=None, help="vokabular-hint til STT (navne/termer) for bedre stavning")
    ap.add_argument("--diarize-stereo", action="store_true", help="split L/R-kanaler og transskribér hver taler for sig")
    ap.add_argument("--speaker-a", default="Taler A", help="navn på venstre kanal (L)")
    ap.add_argument("--speaker-b", default="Taler B", help="navn på højre kanal (R)")
    ap.add_argument("--speakers", default="",
                    help='navngiv talere fra ML-diarisering, fx "1=Anna,2=Bo". '
                         'Uden dem staar der "Taler 1", og beslutninger kan ikke tilskrives nogen')
    ap.add_argument("--segments-model", default="whisper-1", help="model til tidsstemplede segmenter (kræver timestamps)")
    a = ap.parse_args()

    if not os.path.isfile(a.audio_file):
        sys.exit(f"Lydfil findes ikke: {a.audio_file}")
    mb = os.path.getsize(a.audio_file) / 1e6
    if a.stt_provider == "openai" and mb > MAX_MB:
        sys.exit(f"Filen er {mb:.1f} MB > {MAX_MB} MB (OpenAI-grænse). Del lyden op eller komprimér (fx til .m4a/.ogg).")

    if a.diarize_stereo:
        print(f"Diariserer via kanal-split (2 talere, sprog={a.language}, {mb:.1f} MB)…")
        left, right = ffsplit_stereo(a.audio_file)
        if not (os.path.isfile(left) and os.path.isfile(right)):
            sys.exit("Kunne ikke splitte stereo-kanaler (ffmpeg-fejl).")
        seg_l = transcribe_segments(left, a.language, a.prompt, a.segments_model)
        seg_r = transcribe_segments(right, a.language, a.prompt, a.segments_model)
        for p in (left, right):
            try: os.remove(p)
            except OSError: pass
        transcript = merge_dialogue(seg_l, a.speaker_a, seg_r, a.speaker_b)
        model_label = f"{a.stt_provider}/{a.segments_model} (kanal-split diarisering)"
        print(f"  {len(seg_l)} + {len(seg_r)} segmenter → talermærket dialog ({len(transcript)} tegn)")
    else:
        print(f"Transskriberer ({a.stt_provider}/{a.stt_model}, sprog={a.language}, {mb:.1f} MB)…")
        names = parse_speakers(a.speakers)
        if a.stt_provider == "syvai":
            transcript = transcribe_syvai(a.audio_file, a.stt_model, a.language, a.prompt, names)
        else:
            transcript = STT[a.stt_provider](a.audio_file, a.stt_model, a.language, a.prompt)
        model_label = f"{a.stt_provider}/{a.stt_model}"
        print(f"  transskript: {len(transcript)} tegn")

    summary = None
    if not a.no_summary:
        print(f"Genererer referat ({a.summary_model})…")
        summary = summarize_claude(transcript, a.client, a.summary_model)

    os.makedirs(DEST, exist_ok=True)
    fn = f"{a.date}-{slug(a.client)}-moede.md"
    out = os.path.join(DEST, fn)
    n = 2  # undgå kollision når samme klient ringer flere gange samme dag
    while os.path.exists(out):
        fn = f"{a.date}-{slug(a.client)}-moede-{n}.md"
        out = os.path.join(DEST, fn)
        n += 1
    parts = [
        f"# Møde: {a.client} — {a.date}\n",
        f"- **Klient/emne:** {a.client}",
        f"- **Dato:** {a.date}",
        f"- **Deltagere:** {a.participants or '(udfyld)'}",
        f"- **Kilde:** {os.path.basename(a.audio_file)} · STT {model_label}\n",
        "> Rå møde-kilde til ingest. Distilleres til entiteter via /wiki-ingest.\n",
    ]
    if summary:
        parts += ["---\n", "# Referat\n", summary, "\n"]
    parts += ["---\n", "# Fuld transskription\n", transcript, "\n"]
    open(out, "w", encoding="utf-8").write("\n".join(parts))
    rel = os.path.relpath(out, ROOT).replace(os.sep, "/")
    print(f"Gemt: {rel}")
    print(f"Næste skridt:  /wiki-ingest {rel}")


if __name__ == "__main__":
    main()

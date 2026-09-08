#!/usr/bin/env python3
"""
Refuse to let real personal data into this public template.

This repository is a template. Its scripts and docs get copied back and forth
from a private vault full of clients, prices, servers and people, and that sync
has no filter. It failed once already: `scripts/eval/answers.yaml` sat here in
public with an hourly rate, package prices, a production IP address, client and
contact names and personal facts, because the file was copied wholesale from a
working vault.

A secret scanner would never have caught it. gitleaks looks for credentials —
things with a shape, like `sk-...` or a private key block. An email address, a
phone number and a server's IP have no such shape; they are only sensitive
because of whose they are. That is what this script is for.

It checks three classes with a real chance of being personal data:

  email   addresses outside the obvious placeholder domains
  ip      public IPv4 addresses (private, loopback and documentation ranges are fine)
  phone   Danish-format phone numbers

Anything genuinely intended to be here goes in `.allowed-data`, one entry per
line, `#` for comments. Adding a line there is a decision, and the reviewer of
the pull request gets to see it.

Usage:
  python scripts/no-private-data.py          # exit 1 on any finding
  python scripts/no-private-data.py --list   # show what is allowlisted and why
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WIKI_ROOT", Path(__file__).resolve().parent.parent))
ALLOW = ROOT / ".allowed-data"
EXT = {".md", ".yaml", ".yml", ".py", ".html", ".json", ".sh", ".toml", ".txt"}
SKIP_DIRS = {".git", "node_modules", "_sources", "_index", "__pycache__", ".venv"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Et punktum efter nummeret er som regel bare slutningen paa saetningen, ikke et
# versionsnummer. Kun et tal foer eller efter diskvalificerer.
PHONE_RE = re.compile(r"(?<!\d)(?:\+45[ ]?)?\d{2}[ ]\d{2}[ ]\d{2}[ ]\d{2}(?!\d)")

# Domæner der tydeligt er pladsholdere og derfor altid i orden.
OK_MAIL = re.compile(
    r"@(example\.(com|org|net)|eksempel\.dk|domain\.tld|yourdomain\.[a-z]+|"
    r"test\.local|localhost|email\.com|mail\.example)$", re.I)

# Private, loopback, link-local, multicast og dokumentationsområder.
def privat_ip(ip: str) -> bool:
    try:
        a, b, c, d = (int(x) for x in ip.split("."))
    except ValueError:
        return True
    if not all(0 <= x <= 255 for x in (a, b, c, d)):
        return True                                   # versionsnummer, ikke en adresse
    if any(len(t) > 1 and t.startswith("0") for t in ip.split(".")):
        return True                                   # foranstillet nul: ikke en adresse
    if a in (0, 10, 127) or a >= 224:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 169 and b == 254:
        return True
    if (a, b) in ((192, 0), (198, 51), (203, 0)):     # dokumentationsområder
        return True
    if a == 1 and b == 1 and c == 1:                  # 1.1.1.1, offentlig resolver
        return True
    if (a, b) == (8, 8):                              # 8.8.8.8
        return True
    return False


def allowlist() -> set[str]:
    if not ALLOW.exists():
        return set()
    ud = set()
    for line in ALLOW.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ud.add(line.lower())
    return ud


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="vis allowlisten")
    a = ap.parse_args()

    tilladt = allowlist()
    if a.list:
        print(f"# {ALLOW.name} — {len(tilladt)} tilladte vaerdier")
        for v in sorted(tilladt):
            print(f"  {v}")
        return 0

    fund = []
    for p in sorted(ROOT.rglob("*")):
        if p.is_dir() or p.suffix.lower() not in EXT:
            continue
        if any(d in p.parts for d in SKIP_DIRS):
            continue
        if p.name == ALLOW.name or p.samefile(Path(__file__)):
            continue
        for nr, linje in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in EMAIL_RE.finditer(linje):
                v = m.group(0)
                if OK_MAIL.search(v) or v.lower() in tilladt:
                    continue
                fund.append(("email", v, p, nr, linje))
            # SVG-path-data ser ud som IP-adresser i tusindvis. Spring linjen over.
            if "<path" not in linje and ' d="M' not in linje:
                for m in IP_RE.finditer(linje):
                    v = m.group(0)
                    if privat_ip(v) or v in tilladt:
                        continue
                    fund.append(("ip", v, p, nr, linje))
            for m in PHONE_RE.finditer(linje):
                v = m.group(0)
                if v.lower() in tilladt or re.sub(r"\D", "", v) in {"12345678", "12345679"}:
                    continue
                fund.append(("phone", v, p, nr, linje))

    if not fund:
        print("Ingen personhenførbare data fundet.")
        return 0

    print(f"BLOKERET: {len(fund)} mulige personhenførbare vaerdier\n")
    for art, v, p, nr, linje in fund:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        print(f"  [{art}] {v}")
        print(f"        {rel}:{nr}  {linje.strip()[:100]}")
    print("\nEr en af dem bevidst og i orden, saa skriv den i `.allowed-data` — én pr. linje.")
    print("Er den ikke, saa erstat den med en pladsholder foer du pusher.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

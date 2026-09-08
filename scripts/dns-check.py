#!/usr/bin/env python3
"""
Slå wikiens domænepåstande op i DNS.

Tredje art i drift-verifikationen, og den eneste der kan køre uden
credentials — DNS er offentligt. Formålet er at finde domæner wikien omtaler som
levende, men som ikke længere findes. Et dødt domæne i en vidensbase er en påstand
ingen falder over, fordi der ikke er noget der fejler.

To opslag, fordi ét ikke er nok:

  A-record  — svarer domænet på et opslag? Fejler både for udløbne og for
              registrerede-men-upegede domæner.
  NS-record — har det navneservere? Så findes det stadig, det er bare ikke sat op.
              Ingen navneservere betyder udløbet eller aldrig registreret.

Scriptet retter aldrig en side. Et domæne der ikke svarer kan være udløbet, omdøbt,
en tastefejl — eller helt legitimt, som `indretningmedpl.dk`, der ikke er et domæne
men et afkortet SSH-brugernavn wikien selv forklarer. Den slags kan kun et menneske
afgøre, og et script der «rettede» det ville ødelægge en rigtig oplysning.

Brug:
  python scripts/dns-check.py                 # kun dem der ikke svarer
  python scripts/dns-check.py --alle          # også dem der svarer
  python scripts/dns-check.py --ns            # slå navneservere op på de døde
  python scripts/dns-check.py --json
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WIKI_ROOT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

# Leverandør- og dokumentationsdomæner er ikke påstande om din egen drift.
STØJ = ("wordpress.org", "github.com", "patchstack.com", "google.com", "hostinger.com",
        "dokploy.com", "anthropic.com", "claude.ai", "npmjs.com", "cloudflare.com",
        "downloads.w.org", "docs.", "developer.", "www.w3.org", "schema.org",
        "gmail.com", "hotmail.com", "gravatar.com", "example.com", "localhost",
        "sentry.io", "staticflickr.com", "simply.com")


def domaener() -> tuple[collections.Counter, dict]:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "claims.py"),
                          "--kind", "domain", "--json"],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    claims = json.loads(out.stdout or "[]")
    tael: collections.Counter = collections.Counter()
    hvor: dict[str, str] = {}
    for c in claims:
        d = str(c["vaerdi"]).lower().strip(".")
        if any(s in d for s in STØJ) or d.count(".") > 3 or len(d) < 5:
            continue
        tael[d] += 1
        hvor.setdefault(d, f"{c['sti']}:{c['linje']}")
    return tael, hvor


def har_a(d: str) -> tuple[str, str | None]:
    try:
        return d, socket.gethostbyname(d)
    except Exception:
        return d, None


def har_ns(d: str) -> tuple[str, str, str]:
    """REGISTRERET hvis der er navneservere, FINDES IKKE ved NXDOMAIN."""
    try:
        r = subprocess.run(["nslookup", "-type=NS", d, "1.1.1.1"], capture_output=True,
                           text=True, timeout=25, encoding="utf-8", errors="replace")
        t = ((r.stdout or "") + (r.stderr or ""))
        low = t.lower()
        if "nameserver" in low and "=" in low:
            ns = sorted({l.split("=")[-1].strip().rstrip(".")
                         for l in t.splitlines() if "nameserver" in l.lower()})
            return d, "REGISTRERET", ", ".join(ns[:2])
        if "non-existent domain" in low or "nxdomain" in low:
            return d, "FINDES IKKE", ""
        return d, "uklart", ""
    except Exception as e:
        return d, "uklart", e.__class__.__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alle", action="store_true", help="vis også dem der svarer")
    ap.add_argument("--ns", action="store_true", help="slå navneservere op på dem uden A-record")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    tael, hvor = domaener()
    levende, døde = {}, []
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for d, ip in ex.map(har_a, tael):
            if ip:
                levende[d] = ip
            else:
                døde.append(d)

    ns_status: dict[str, tuple[str, str]] = {}
    if a.ns or a.json:
        with cf.ThreadPoolExecutor(max_workers=12) as ex:
            for d, st, note in ex.map(har_ns, sorted(døde)):
                ns_status[d] = (st, note)

    if a.json:
        print(json.dumps({
            "levende": levende,
            "uden_a_record": [{"domaene": d, "antal": tael[d], "sted": hvor[d],
                               "ns": ns_status.get(d, ("", ""))[0],
                               "navneservere": ns_status.get(d, ("", ""))[1]}
                              for d in sorted(døde, key=lambda x: -tael[x])],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"# Domæner i wikien — {len(tael)} unikke\n")
    print(f"  svarer i DNS:  {len(levende)}")
    print(f"  uden A-record: {len(døde)}\n")
    for d in sorted(døde, key=lambda x: (-tael[x], x)):
        st, note = ns_status.get(d, ("", ""))
        mark = {"FINDES IKKE": "✗", "REGISTRERET": "~"}.get(st, " ")
        print(f" {mark} x{tael[d]:<3} {d:<40} {hvor[d]}" + (f"   [{note}]" if note else ""))
    if a.alle:
        print("\n## Svarer\n")
        for d, ip in sorted(levende.items()):
            print(f"   {d:<40} {ip}")
    if not a.ns:
        print("\nKør med --ns for at skille udløbne domæner fra registrerede-men-upegede.")
    print("\nEt domæne uden A-record er ikke nødvendigvis en fejl: det kan være parkeret,")
    print("omdøbt — eller slet ikke et domæne. Scriptet retter derfor ingenting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

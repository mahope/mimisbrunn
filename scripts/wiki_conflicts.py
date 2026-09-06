"""
Deterministisk modsigelses-detektor til wiki_append (issue #11).

find_conflicts(existing_text, new_text) -> [ {key, old, new} ]
Nøgler: e-mail, telefon, beløb (kr/DKK), versionsnummer pr. navngivet ting, "kontaktperson", "hoster/kører på".
Kollision = samme nøgle med forskellig værdi i ny tekst vs. eksisterende tekst.
Kør `python scripts/wiki_conflicts.py` for selvtest.
"""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+45\s?)?(?:\d{2}\s?){4}\b")
AMOUNT = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)\s?(?:kr\.?|dkk)(?:/(?:md|time|t|år))?", re.I)
AMOUNT_CTX = re.compile(r"([a-zæøå][\w\-]{2,})[^.\n]{0,40}?(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)\s?(?:kr\.?|dkk)(/(?:md|time|t|år))?", re.I)
VERSION = re.compile(r"\b([A-Za-z][\w.+-]{1,20})\s+v?(\d+\.\d+(?:\.\d+)?)\b")
CONTACT = re.compile(r"kontaktperson(?:en)?\s*(?:er|:)\s*\**([A-ZÆØÅ][\wæøå]+(?:\s[A-ZÆØÅ][\wæøå]+)*)", re.I)
HOSTED = re.compile(r"(?:kører|hostes|hosted|ligger)(?:\s+(?:nu|stadig|fortsat|i dag))?\s+(?:på|hos)\s+\**([A-Za-zÆØÅæøå][\w.-]+)", re.I)


def _norm_amount(s):
    return s.replace(" ", "").replace(".", "").replace(",", ".")


def extract(text):
    """key -> værdi (normaliseret). Sidste forekomst vinder inden for samme tekst."""
    facts = {}
    for m in EMAIL.finditer(text):
        facts.setdefault("email", set()).add(m.group(0).lower())
    for m in PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) in (8, 10):
            facts.setdefault("telefon", set()).add(digits[-8:])
    for m in AMOUNT_CTX.finditer(text):
        key = f"beløb:{m.group(1).lower()}{m.group(3) or ''}"
        facts[key] = _norm_amount(m.group(2))
    for m in VERSION.finditer(text):
        name = m.group(1).lower()
        if name in ("kl", "pr", "ca", "nr", "version", "v"):
            continue
        facts[f"version:{name}"] = m.group(2)
    for m in CONTACT.finditer(text):
        facts["kontaktperson"] = m.group(1).strip().lower()
    for m in HOSTED.finditer(text):
        facts["hostes-på"] = m.group(1).strip(".").lower()
    return facts


def find_conflicts(existing_text, new_text):
    old, new = extract(existing_text), extract(new_text)
    out = []
    for key, nv in new.items():
        if key not in old:
            continue
        ov = old[key]
        if isinstance(nv, set):
            # sæt-nøgler (email/telefon): kun konflikt hvis ny tekst introducerer værdier OG gammel havde andre — og der er 1 værdi hver
            if len(nv) == 1 and len(ov) == 1 and nv != ov:
                out.append({"key": key, "old": next(iter(ov)), "new": next(iter(nv))})
        elif str(nv) != str(ov):
            out.append({"key": key, "old": ov, "new": nv})
    return out


def _selftest():
    cases = [
        ("Timepris 900 kr/time aftalt.", "Timepris 950 kr/time fra oktober.", 1),
        ("Timepris 900 kr/time aftalt.", "Timepris 900 kr/time bekræftet.", 0),
        ("Kontaktperson er Thea Lynggren.", "Kontaktperson: Frederik Lund.", 1),
        ("Sitet kører på Hetzner (fsn1).", "Sitet kører nu hos Webdock.", 1),
        ("WordPress 6.8 installeret.", "WordPress 7.0 opdateret.", 1),
        ("Mail: info@solpaneler.eu", "Ny mail: kontakt@solpaneler.eu", 1),
        ("Mail: info@solpaneler.eu og fj@solpaneler.eu", "Skriv til fj@solpaneler.eu", 0),
        ("Tlf. 62 65 10 16.", "Ring 62 65 10 17.", 1),
        ("Pakke 2 koster 45.000 kr", "Pakke 2 koster 45.000 kr inkl. moms", 0),
    ]
    ok = True
    for old, new, n in cases:
        got = find_conflicts(old, new)
        flag = "OK " if len(got) == n else "FEJL"
        if len(got) != n:
            ok = False
        print(f"{flag} {old!r} + {new!r} -> {got}")
    print("ALLE OK" if ok else "FEJL I SELVTEST")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)

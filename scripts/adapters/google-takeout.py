#!/usr/bin/env python3
"""Parse Google Takeout export and extract wiki-relevant data."""
import json, os, sys
from pathlib import Path
from datetime import datetime

def parse_google_takeout(zip_path, output_dir):
    """Extract contacts, calendar, drive metadata from Google Takeout."""
    import zipfile
    zf = zipfile.ZipFile(zip_path)

    os.makedirs(output_dir, exist_ok=True)
    results = {"contacts": 0, "calendar": 0, "drive": 0}

    for name in zf.namelist():
        # Contacts (vCard format)
        if "Contacts" in name and name.endswith(".vcf"):
            out = os.path.join(output_dir, "contacts.vcf")
            with open(out, 'wb') as f:
                f.write(zf.read(name))
            content = zf.read(name).decode("utf-8", errors="replace")
            results["contacts"] = content.count("BEGIN:VCARD")

        # Calendar (ICS format)
        if "Calendar" in name and name.endswith(".ics"):
            cal_name = name.split("/")[-1].replace(".ics", "")
            out = os.path.join(output_dir, f"calendar-{cal_name}.ics")
            with open(out, 'wb') as f:
                f.write(zf.read(name))
            content = zf.read(name).decode("utf-8", errors="replace")
            results["calendar"] += content.count("BEGIN:VEVENT")

        # Drive file listing (just names, not content)
        if "Drive" in name and name.endswith(".json"):
            try:
                data = json.loads(zf.read(name))
                results["drive"] += 1
            except Exception:
                pass

    summary = f"# Google Takeout Summary\n\nDate: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    summary += f"- Contacts: {results['contacts']}\n"
    summary += f"- Calendar events: {results['calendar']}\n"
    summary += f"- Drive files found: {results['drive']}\n"

    with open(os.path.join(output_dir, "takeout-summary.md"), 'w', encoding='utf-8') as f:
        f.write(summary)

    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: google-takeout.py <path-to-takeout.zip> [output-dir]")
        sys.exit(1)

    source = sys.argv[1]
    wiki_root = Path(__file__).resolve().parent.parent.parent
    output = sys.argv[2] if len(sys.argv) > 2 else str(wiki_root / "_sources" / "google-takeout")

    results = parse_google_takeout(source, output)
    print(f"Google Takeout parsed:")
    for k, v in results.items():
        print(f"  {k}: {v}")

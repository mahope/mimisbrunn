#!/usr/bin/env python3
"""Parse LinkedIn data export and extract wiki-relevant data."""
import csv, os, sys, io
from pathlib import Path
from datetime import datetime

def parse_linkedin_export(zip_or_dir, output_dir):
    """Extract profile, positions, education, skills from LinkedIn export."""
    files = {}

    if str(zip_or_dir).endswith(".zip"):
        import zipfile
        zf = zipfile.ZipFile(zip_or_dir)
        for name in zf.namelist():
            if name.endswith(".csv"):
                fname = name.split("/")[-1]
                files[fname] = zf.read(name).decode("utf-8")
    else:
        for f in Path(zip_or_dir).rglob("*.csv"):
            files[f.name] = f.read_text(encoding="utf-8")

    os.makedirs(output_dir, exist_ok=True)
    results = {"profile": None, "positions": [], "education": [], "skills": [], "volunteering": []}

    if "Profile.csv" in files:
        reader = csv.DictReader(io.StringIO(files["Profile.csv"]))
        for row in reader:
            results["profile"] = dict(row)
            break

    if "Positions.csv" in files:
        reader = csv.DictReader(io.StringIO(files["Positions.csv"]))
        results["positions"] = [dict(row) for row in reader]

    if "Education.csv" in files:
        reader = csv.DictReader(io.StringIO(files["Education.csv"]))
        results["education"] = [dict(row) for row in reader]

    if "Skills.csv" in files:
        reader = csv.DictReader(io.StringIO(files["Skills.csv"]))
        results["skills"] = [dict(row) for row in reader]

    if "Volunteering.csv" in files:
        reader = csv.DictReader(io.StringIO(files["Volunteering.csv"]))
        results["volunteering"] = [dict(row) for row in reader]

    # Write summary
    summary = f"# LinkedIn Export Summary\n\nDate: {datetime.now().strftime('%Y-%m-%d')}\n\n"

    if results["profile"]:
        p = results["profile"]
        summary += f"## Profile\n- **Name:** {p.get('First Name', '')} {p.get('Last Name', '')}\n"
        summary += f"- **Headline:** {p.get('Headline', '')}\n"
        summary += f"- **Location:** {p.get('Geo Location', '')}\n\n"

    if results["positions"]:
        summary += "## Positions\n\n| Period | Title | Company |\n|--------|-------|---------|\n"
        for pos in results["positions"]:
            started = pos.get("Started On", "?")
            finished = pos.get("Finished On", "present")
            summary += f"| {started} - {finished} | {pos.get('Title', '')} | {pos.get('Company Name', '')} |\n"
        summary += "\n"

    if results["education"]:
        summary += "## Education\n\n"
        for edu in results["education"]:
            summary += f"- **{edu.get('School Name', '')}** ({edu.get('Start Date', '')}-{edu.get('End Date', '')}) — {edu.get('Degree Name', '')}\n"
        summary += "\n"

    if results["skills"]:
        summary += f"## Skills ({len(results['skills'])})\n\n"
        summary += ", ".join(s.get("Name", "") for s in results["skills"][:30]) + "\n\n"

    if results["volunteering"]:
        summary += "## Volunteering\n\n"
        for vol in results["volunteering"]:
            summary += f"- **{vol.get('Company Name', '')}** — {vol.get('Role', '')} ({vol.get('Started On', '')}-{vol.get('Finished On', 'present')})\n"

    out_path = os.path.join(output_dir, "linkedin-summary.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(summary)

    # Also save raw CSVs
    for fname, content in files.items():
        with open(os.path.join(output_dir, fname), 'w', encoding='utf-8') as f:
            f.write(content)

    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: linkedin.py <path-to-export.zip-or-dir> [output-dir]")
        sys.exit(1)

    source = sys.argv[1]
    wiki_root = Path(__file__).resolve().parent.parent.parent
    output = sys.argv[2] if len(sys.argv) > 2 else str(wiki_root / "_sources" / "linkedin")

    results = parse_linkedin_export(source, output)
    print(f"LinkedIn export parsed:")
    print(f"  Profile: {'Yes' if results['profile'] else 'No'}")
    print(f"  Positions: {len(results['positions'])}")
    print(f"  Education: {len(results['education'])}")
    print(f"  Skills: {len(results['skills'])}")
    print(f"  Volunteering: {len(results['volunteering'])}")
    print(f"  Output: {output}")

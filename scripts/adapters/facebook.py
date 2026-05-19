#!/usr/bin/env python3
"""Parse Facebook data export and extract wiki-relevant data."""
import json, os, sys, re
from datetime import datetime
from pathlib import Path

def parse_facebook_export(zip_path, output_dir):
    """Extract profile, friends, events, posts from Facebook export."""
    import zipfile
    zf = zipfile.ZipFile(zip_path)

    os.makedirs(output_dir, exist_ok=True)
    results = {"profile": None, "friends": 0, "events": 0, "posts": 0, "groups": 0}

    # Find the prefix (Facebook exports nest in a folder)
    prefix = ""
    for name in zf.namelist():
        if "profile_information/profile_information.json" in name:
            prefix = name.rsplit("profile_information/", 1)[0]
            break

    # Extract key JSON files
    key_files = [
        "personal_information/profile_information/profile_information.json",
        "connections/friends/your_friends.json",
        "your_facebook_activity/events/your_events.json",
        "your_facebook_activity/groups/your_groups.json",
        "your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json",
    ]

    for rel_path in key_files:
        full_path = prefix + rel_path
        if full_path in zf.namelist():
            fname = rel_path.split("/")[-1]
            out = os.path.join(output_dir, fname)
            with open(out, 'wb') as f:
                f.write(zf.read(full_path))

    # Parse profile
    profile_path = os.path.join(output_dir, "profile_information.json")
    if os.path.exists(profile_path):
        with open(profile_path, encoding='utf-8') as f:
            data = json.load(f)
        results["profile"] = data.get("profile_v2", {})

    # Count friends
    friends_path = os.path.join(output_dir, "your_friends.json")
    if os.path.exists(friends_path):
        with open(friends_path, encoding='utf-8') as f:
            data = json.load(f)
        results["friends"] = len(data.get("friends_v2", []))

    # Count events
    events_path = os.path.join(output_dir, "your_events.json")
    if os.path.exists(events_path):
        with open(events_path, encoding='utf-8') as f:
            data = json.load(f)
        results["events"] = len(data.get("your_events_v2", []))

    # Count posts
    posts_path = os.path.join(output_dir, "your_posts__check_ins__photos_and_videos_1.json")
    if os.path.exists(posts_path):
        with open(posts_path, encoding='utf-8') as f:
            data = json.load(f)
        results["posts"] = len(data) if isinstance(data, list) else 0

    # Write summary
    summary = f"# Facebook Export Summary\n\nDate: {datetime.now().strftime('%Y-%m-%d')}\n\n"

    if results["profile"]:
        p = results["profile"]
        name = p.get("name", {})
        summary += f"## Profile\n- **Name:** {name.get('full_name', '?')}\n"
        bday = p.get("birthday", {})
        if bday:
            summary += f"- **Birthday:** {bday.get('day', '?')}/{bday.get('month', '?')}/{bday.get('year', '?')}\n"
        rel = p.get("relationship", {})
        if rel:
            summary += f"- **Relationship:** {rel.get('status', '?')} — {rel.get('partner', '?')}\n"
        summary += "\n"

    summary += f"## Stats\n- Friends: {results['friends']}\n- Events: {results['events']}\n- Posts: {results['posts']}\n"

    out_path = os.path.join(output_dir, "facebook-summary.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(summary)

    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: facebook.py <path-to-export.zip> [output-dir]")
        sys.exit(1)

    source = sys.argv[1]
    wiki_root = Path(__file__).resolve().parent.parent.parent
    output = sys.argv[2] if len(sys.argv) > 2 else str(wiki_root / "_sources" / "facebook")

    results = parse_facebook_export(source, output)
    print(f"Facebook export parsed:")
    print(f"  Profile: {'Yes' if results['profile'] else 'No'}")
    print(f"  Friends: {results['friends']}")
    print(f"  Events: {results['events']}")
    print(f"  Posts: {results['posts']}")
    print(f"  Output: {output}")

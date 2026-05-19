#!/usr/bin/env python3
"""Parse Claude.ai data export and extract wiki-relevant conversations."""
import json, os, sys, re
from datetime import datetime
from pathlib import Path

def parse_claude_export(zip_or_dir, output_dir):
    """Extract conversations from Claude export."""
    conversations = []

    if str(zip_or_dir).endswith(".zip"):
        import zipfile
        zf = zipfile.ZipFile(zip_or_dir)
        for name in zf.namelist():
            if name.endswith(".json") and "conversation" in name.lower():
                try:
                    data = json.loads(zf.read(name))
                    if isinstance(data, list):
                        conversations.extend(data)
                    elif isinstance(data, dict):
                        conversations.append(data)
                except Exception:
                    pass
    else:
        conv_dir = Path(zip_or_dir)
        for f in conv_dir.rglob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    conversations.extend(data)
                elif isinstance(data, dict):
                    conversations.append(data)
            except Exception:
                pass

    os.makedirs(output_dir, exist_ok=True)
    exported = []

    for conv in conversations:
        name = conv.get("name", conv.get("title", "Untitled"))
        created = conv.get("created_at", conv.get("create_time", ""))
        messages = conv.get("chat_messages", conv.get("messages", []))

        if not isinstance(messages, list) or len(messages) < 4:
            continue

        date_str = str(created)[:10] if created else "unknown"
        safe_name = re.sub(r'[^\w\s-]', '', str(name)).strip().replace(' ', '-').lower()[:60]
        filename = f"{date_str}_{safe_name}.md"

        content = f"# {name}\n\nDate: {date_str}\nSource: Claude\nMessages: {len(messages)}\n\n---\n\n"
        for msg in messages[:50]:
            role = msg.get("sender", msg.get("role", "unknown"))
            text = msg.get("text", msg.get("content", ""))
            if isinstance(text, list):
                text = " ".join(str(p) for p in text)
            text = str(text)[:500]
            prefix = "**User:**" if role in ("human", "user") else "**Claude:**"
            content += f"{prefix} {text}\n\n"

        out_path = os.path.join(output_dir, filename)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(content)
        exported.append({"file": filename, "title": name, "date": date_str, "messages": len(messages)})

    return exported

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: claude.py <path-to-export.zip-or-dir> [output-dir]")
        sys.exit(1)

    source = sys.argv[1]
    wiki_root = Path(__file__).resolve().parent.parent.parent
    output = sys.argv[2] if len(sys.argv) > 2 else str(wiki_root / "_sources" / "claude-history")

    results = parse_claude_export(source, output)
    print(f"Exported {len(results)} conversations to {output}")
    for r in results[:10]:
        print(f"  {r['date']}: {r['title']} ({r['messages']} messages)")

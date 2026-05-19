#!/usr/bin/env python3
"""Parse ChatGPT data export and extract wiki-relevant conversations."""
import json, os, sys, re
from datetime import datetime
from pathlib import Path

def parse_chatgpt_export(zip_or_dir, output_dir):
    """Extract conversations from ChatGPT export."""
    conversations_file = None

    if str(zip_or_dir).endswith(".zip"):
        import zipfile
        zf = zipfile.ZipFile(zip_or_dir)
        for name in zf.namelist():
            if name.endswith("conversations.json"):
                conversations_file = zf.read(name)
                break
        if not conversations_file:
            print("No conversations.json found in ZIP")
            return []
        conversations = json.loads(conversations_file)
    else:
        path = Path(zip_or_dir) / "conversations.json"
        if not path.exists():
            print(f"No conversations.json at {path}")
            return []
        conversations = json.loads(path.read_text(encoding="utf-8"))

    os.makedirs(output_dir, exist_ok=True)
    exported = []

    for conv in conversations:
        title = conv.get("title", "Untitled")
        create_time = conv.get("create_time", 0)
        mapping = conv.get("mapping", {})

        messages = []
        for node_id, node in mapping.items():
            msg = node.get("message")
            if not msg:
                continue
            role = msg.get("author", {}).get("role", "")
            content_parts = msg.get("content", {}).get("parts", [])
            text = " ".join(str(p) for p in content_parts if isinstance(p, str))
            if text and role in ("user", "assistant"):
                messages.append({"role": role, "text": text[:2000]})

        if len(messages) < 4:
            continue

        date_str = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d") if create_time else "unknown"
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-').lower()[:60]
        filename = f"{date_str}_{safe_title}.md"

        content = f"# {title}\n\nDate: {date_str}\nSource: ChatGPT\nMessages: {len(messages)}\n\n---\n\n"
        for msg in messages[:50]:
            prefix = "**User:**" if msg["role"] == "user" else "**Assistant:**"
            content += f"{prefix} {msg['text'][:500]}\n\n"

        out_path = os.path.join(output_dir, filename)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(content)
        exported.append({"file": filename, "title": title, "date": date_str, "messages": len(messages)})

    return exported

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: chatgpt.py <path-to-export.zip-or-dir> [output-dir]")
        sys.exit(1)

    source = sys.argv[1]
    wiki_root = Path(__file__).resolve().parent.parent.parent
    output = sys.argv[2] if len(sys.argv) > 2 else str(wiki_root / "_sources" / "chatgpt")

    results = parse_chatgpt_export(source, output)
    print(f"Exported {len(results)} conversations to {output}")
    for r in results[:10]:
        print(f"  {r['date']}: {r['title']} ({r['messages']} messages)")

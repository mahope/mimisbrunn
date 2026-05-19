#!/usr/bin/env python3
"""Parse Notion export and convert to wiki format."""
import os, sys, re
from pathlib import Path

def parse_notion_export(zip_or_dir, output_dir):
    """Extract markdown files from Notion export, preserve links."""
    files = []

    if str(zip_or_dir).endswith(".zip"):
        import zipfile
        zf = zipfile.ZipFile(zip_or_dir)
        os.makedirs(output_dir, exist_ok=True)
        for name in zf.namelist():
            if name.endswith(".md"):
                content = zf.read(name).decode("utf-8")
                fname = name.split("/")[-1]
                # Clean Notion's UUID suffixes from filenames
                fname = re.sub(r'\s+[a-f0-9]{32}\.md$', '.md', fname)
                fname = fname.replace(' ', '-').lower()
                out = os.path.join(output_dir, fname)
                with open(out, 'w', encoding='utf-8') as f:
                    f.write(content)
                files.append(fname)
    else:
        os.makedirs(output_dir, exist_ok=True)
        for f in Path(zip_or_dir).rglob("*.md"):
            content = f.read_text(encoding="utf-8")
            fname = f.name
            fname = re.sub(r'\s+[a-f0-9]{32}\.md$', '.md', fname)
            fname = fname.replace(' ', '-').lower()
            out = os.path.join(output_dir, fname)
            with open(out, 'w', encoding='utf-8') as fh:
                fh.write(content)
            files.append(fname)

    return files

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: notion.py <path-to-export.zip-or-dir> [output-dir]")
        sys.exit(1)

    source = sys.argv[1]
    wiki_root = Path(__file__).resolve().parent.parent.parent
    output = sys.argv[2] if len(sys.argv) > 2 else str(wiki_root / "_sources" / "notion")

    files = parse_notion_export(source, output)
    print(f"Exported {len(files)} Notion pages to {output}")

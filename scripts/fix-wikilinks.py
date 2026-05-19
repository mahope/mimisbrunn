#!/usr/bin/env python3
"""Find plain-text entity mentions and convert to [[wikilinks]].
Only links first occurrence per section. Dry-run by default."""
import re, yaml, sys
from pathlib import Path

wiki = Path(__file__).resolve().parent.parent
entities_dir = wiki / "entities"
DRY_RUN = "--apply" not in sys.argv

def extract_frontmatter(content):
    if not content.startswith("---"):
        return {}, 0
    try:
        end = content.index("---", 3)
        return yaml.safe_load(content[3:end].strip()) or {}, end + 3
    except Exception:
        return {}, 0

# Build entity name -> file stem mapping
entity_map = {}  # display name -> (stem, display)
for f in entities_dir.rglob("*.md"):
    try:
        content = f.read_text(encoding="utf-8")
        fm, _ = extract_frontmatter(content)
        entity_name = fm.get("entity", "")
        aliases = fm.get("aliases", []) or []
        stem = f.stem

        if entity_name and len(entity_name) >= 3:
            entity_map[entity_name.lower()] = (stem, entity_name)
        for alias in aliases:
            if alias and len(alias) >= 3:
                entity_map[alias.lower()] = (stem, alias)
    except Exception:
        pass

# Sort by length (longest first) to avoid partial matches
sorted_names = sorted(entity_map.keys(), key=len, reverse=True)

# Filter out very common words that happen to be entity names
SKIP_NAMES = {"vue", "mysql", "redis", "plane", "buffer", "dash", "acf",
              "tea", "jens", "marie", "malthe"}

def is_inside_wikilink(text, start, end):
    depth = 0
    for i in range(start - 1, -1, -1):
        if i > 0 and text[i-1:i+1] == "]]":
            depth += 1
        elif i > 0 and text[i-1:i+1] == "[[":
            if depth > 0:
                depth -= 1
            else:
                return True
    return False

def is_inside_frontmatter(text, pos):
    before = text[:pos]
    dashes = [m.start() for m in re.finditer(r'^---\s*$', before, re.MULTILINE)]
    return len(dashes) % 2 == 1

def is_inside_heading(text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    line = text[line_start:pos]
    return line.lstrip().startswith("#")

def is_inside_code(text, pos):
    before = text[:pos]
    backtick_blocks = before.count("```")
    return backtick_blocks % 2 == 1

def process_file(filepath, entity_map, sorted_names):
    content = filepath.read_text(encoding="utf-8")
    own_stem = filepath.stem.lower()
    fm, fm_end = extract_frontmatter(content)
    own_entity = (fm.get("entity", "") or "").lower()
    own_aliases = [a.lower() for a in (fm.get("aliases", []) or [])]

    changes = []
    sections = re.split(r'(^##\s+.*$)', content, flags=re.MULTILINE)

    new_content = []
    for section in sections:
        linked_in_section = set()
        for name in sorted_names:
            if name in SKIP_NAMES:
                continue
            stem, display = entity_map[name]
            if stem.lower() == own_stem or name == own_entity or name in own_aliases:
                continue

            pattern = re.compile(r'(?<!\[\[)(?<!\|)\b(' + re.escape(name) + r')\b(?!\]\])(?!\|)', re.IGNORECASE)
            match = pattern.search(section)
            if match and stem not in linked_in_section:
                pos = match.start()
                if is_inside_frontmatter(content, content.find(section) + pos):
                    continue
                if is_inside_heading(section, pos):
                    continue
                if is_inside_code(section, pos):
                    continue

                original_text = match.group(1)
                if original_text.lower() == stem.lower():
                    replacement = f"[[{stem}]]"
                else:
                    replacement = f"[[{stem}|{original_text}]]"

                section = section[:match.start()] + replacement + section[match.end():]
                linked_in_section.add(stem)
                changes.append((filepath.name, original_text, stem))

        new_content.append(section)

    return "".join(new_content), changes

# Process all files
total_changes = 0
all_changes = []
files_changed = 0

for f in sorted(entities_dir.rglob("*.md")):
    try:
        new_content, changes = process_file(f, entity_map, sorted_names)
        if changes:
            all_changes.extend(changes)
            total_changes += len(changes)
            files_changed += 1
            if not DRY_RUN:
                f.write_text(new_content, encoding="utf-8")
    except Exception as e:
        print(f"ERROR processing {f.name}: {e}")

# Report
mode = "DRY RUN" if DRY_RUN else "APPLIED"
print(f"\n=== {mode} ===")
print(f"Files scanned: {len(list(entities_dir.rglob('*.md')))}")
print(f"Files with changes: {files_changed}")
print(f"Total wikilinks added: {total_changes}")

if all_changes:
    print(f"\nTop 20 changes:")
    for filename, original, target in all_changes[:20]:
        print(f"  {filename}: '{original}' -> [[{target}]]")

if DRY_RUN:
    print(f"\nRun with --apply to apply changes.")

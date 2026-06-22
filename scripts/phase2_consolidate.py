#!/usr/bin/env python3
"""
Phase 2: Consolidate — Memory deduplication and compression.

Scans MEMORY.md and USER.md for:
  - Exact duplicate lines
  - Highly similar entries (same topic, different wording)
  - Stale/outdated facts

Usage:
  python3 phase2_consolidate.py --analyze          # Read-only analysis
  python3 phase2_consolidate.py --auto-apply       # Remove exact duplicates
  python3 phase2_consolidate.py --rollback         # Restore from backup
"""

import argparse, json, os, re, shutil, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
MEMORIES_DIR = HERMES_HOME / "memories"
BACKUP_DIR = HERMES_HOME / "backups"

MEMORY_FILE = MEMORIES_DIR / "memory.md"
USER_FILE = MEMORIES_DIR / "user.md"

SEPARATOR = "§"  # Hermes memory entry separator


def now():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def read_entries(path):
    """Read a memory file and return list of (index, text) entries."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    entries = []
    for i, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if stripped:
            entries.append((i, stripped))
    return entries


def write_entries(path, entries, backup=True):
    """Write entries back to file, with optional backup."""
    if backup and path.exists():
        ts = now()
        bak = MEMORIES_DIR / f"{path.name}.bak.{ts}"
        shutil.copy2(path, bak)
        print(f"  💾 Backup: {bak.name}")

    text = "\n".join(e[1] for e in entries) + "\n"
    path.write_text(text, encoding="utf-8")
    print(f"  ✅ Written {len(entries)} entries to {path.name}")


def find_exact_duplicates(entries):
    """Find exact duplicate entries (same text, different line)."""
    seen = {}
    duplicates = []
    for idx, text in entries:
        if text in seen:
            duplicates.append((idx, text, seen[text]))
        else:
            seen[text] = idx
    return duplicates


def find_similar_entries(entries, threshold=0.85):
    """Find pairs of entries with high similarity (same topic)."""
    pairs = []
    texts = [(i, re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', ' ', t).lower()) for i, t in entries]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            idx1, t1 = texts[i]
            idx2, t2 = texts[j]
            ratio = SequenceMatcher(None, t1, t2).ratio()
            if ratio >= threshold:
                pairs.append((entries[i][1], entries[j][1], round(ratio, 3)))
    return pairs


def backup_all():
    """Create a full backup of memory files."""
    ts = now()
    backup_path = BACKUP_DIR / f"phase2-{ts}"
    backup_path.mkdir(parents=True, exist_ok=True)

    for f in [MEMORY_FILE, USER_FILE, HERMES_HOME / "SOUL.md"]:
        if f.exists():
            shutil.copy2(f, backup_path / f.name)
            print(f"  💾 Backed up: {f.name}")

    # Create rollback script
    rollback = backup_path / "rollback.sh"
    rollback.write_text(f"""#!/bin/bash
# Rollback Phase 2 consolidation — {ts}
echo "Restoring memory files from backup..."
cp "{backup_path}/memory.md" "{MEMORY_FILE}" 2>/dev/null
cp "{backup_path}/user.md" "{USER_FILE}" 2>/dev/null
cp "{backup_path}/SOUL.md" "{HERMES_HOME}/SOUL.md" 2>/dev/null
echo "✅ Restored from {ts}"
""")
    rollback.chmod(0o755)
    print(f"  💾 Rollback script: {rollback}")
    return backup_path


def analyze():
    """Read-only analysis of memory files."""
    for label, path in [("MEMORY.md", MEMORY_FILE), ("USER.md", USER_FILE)]:
        entries = read_entries(path)
        if not entries:
            print(f"\n  {label}: empty or not found")
            continue

        total_chars = sum(len(e[1]) for e in entries)
        print(f"\n  {label}: {len(entries)} entries, {total_chars} chars")

        # Exact duplicates
        dupes = find_exact_duplicates(entries)
        if dupes:
            print(f"    🔁 Exact duplicates: {len(dupes)}")
            for idx, text, orig in dupes[:5]:
                print(f"      L{idx} = L{orig}: {text[:60]}...")

        # Similar entries
        similar = find_similar_entries(entries)
        if similar:
            print(f"    🔄 Similar pairs (≥0.85): {len(similar)}")
            for a, b, score in similar[:5]:
                print(f"      ({score}) {a[:50]}")
                print(f"             {b[:50]}")

        # Stats
        topics = Counter()
        for _, text in entries:
            # Extract key topics
            topic_matches = re.findall(r'^([A-Z][a-zA-Z/_-]+|[a-zA-Z]{2,}:\s+)', text)
            if topic_matches:
                topics[topic_matches[0].rstrip(": ")] += 1
            else:
                # Use first word as rough topic
                first = text.split()[0][:20] if text.split() else "?"
                topics[first] += 1

        print(f"    📊 Topic distribution:")
        for topic, count in topics.most_common(10):
            print(f"      {topic}: {count}x")


def auto_apply():
    """Remove exact duplicates (safe operation)."""
    # Backup first
    print("📦 Creating backup...")
    backup_all()

    for label, path in [("MEMORY.md", MEMORY_FILE), ("USER.md", USER_FILE)]:
        entries = read_entries(path)
        if not entries:
            continue

        dupes = find_exact_duplicates(entries)
        if not dupes:
            print(f"  {label}: no exact duplicates to remove")
            continue

        dupe_indices = set(d[0] for d in dupes)
        cleaned = [e for e in entries if e[0] not in dupe_indices]

        print(f"  {label}: removing {len(dupes)} exact duplicates "
              f"({len(entries)} → {len(cleaned)} entries, "
              f"saved {sum(len(d[1]) for d in dupes)} chars)")

        write_entries(path, cleaned, backup=False)


def main():
    parser = argparse.ArgumentParser(description="Phase 2: Memory Consolidation")
    parser.add_argument("--analyze", action="store_true", help="Read-only analysis")
    parser.add_argument("--auto-apply", action="store_true", help="Remove exact duplicates")
    parser.add_argument("--rollback", metavar="BACKUP_DIR", help="Restore from backup")
    args = parser.parse_args()

    if args.rollback:
        bak = Path(args.rollback).expanduser()
        if not bak.exists():
            print(f"❌ Backup directory not found: {bak}")
            sys.exit(1)
        rollback_script = bak / "rollback.sh"
        if rollback_script.exists():
            print(f"📦 Running rollback: {rollback_script}")
            os.system(f"bash {rollback_script}")
        else:
            print(f"❌ No rollback script in {bak}")
        return

    if args.analyze:
        analyze()
    elif args.auto_apply:
        auto_apply()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

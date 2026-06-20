#!/usr/bin/env python3
"""
Skill Precipitator Hook — Incremental session processor for Hermes integration.

Designed to run as a cron job (every 5 min) or called from skill_precipitator.py.

Flow:
  1. Load state (last processed session id)
  2. Query SessionDB for NEW sessions since last check
  3. For each complex session (≥5 tool calls, user-initiated, non-cron):
     a. Extract case
     b. Save to agent/cases/ (leveraging miner.save_case)
  4. After scanning, load ALL cases and re-cluster
  5. Check if any cluster reached threshold (≥3 cases)
  6. Output results (for cron delivery) or append to MEMORY.md

Usage:
  python3 -m precipitator.hook             # Run incremental scan, output to stdout
  python3 -m precipitator.hook --all        # Full re-scan (ignore index)
  python3 -m precipitator.hook --notify     # Run + append findings to MEMORY.md
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Paths
HERMES_HOME = os.path.expanduser("~/.hermes")
SCRIPTS_DIR = os.path.join(HERMES_HOME, "scripts")
CASES_DIR = os.path.join(HERMES_HOME, "agent", "cases")
INDEX_PATH = os.path.join(HERMES_HOME, "agent", ".case_index.json")
MEMORY_PATH = os.path.join(HERMES_HOME, "memories", "MEMORY.md")

# Threshold: after N similar cases, suggest skill creation
SKILL_THRESHOLD = 3

# Add paths
for p in [SCRIPTS_DIR, os.path.join(HERMES_HOME, "hermes-agent")]:
    if p not in sys.path:
        sys.path.insert(0, p)


def load_index() -> Dict:
    """Load the case processing index."""
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH) as f:
            return json.load(f)
    return {
        "last_processed": "",       # last session id processed
        "last_run": 0,              # timestamp
        "total_scanned": 0,
        "total_extracted": 0,
        "total_cases": 0,
        "threshold_hits": 0,
        "skills_created": [],
        "run_count": 0,
    }


def save_index(index: Dict):
    """Save the case processing index."""
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    index["last_run"] = time.time()
    index["run_count"] = index.get("run_count", 0) + 1
    index["total_cases"] = len([
        f for f in os.listdir(CASES_DIR) if f.endswith(".md")
    ]) if os.path.isdir(CASES_DIR) else 0
    
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2)


def get_recent_sessions(db, since_id: str = "", limit: int = 200) -> List[Dict]:
    """Get sessions newer than since_id."""
    all_sessions = db.list_sessions_rich(limit=limit)
    
    if not since_id:
        return all_sessions
    
    # Find where our last processed session is
    found = False
    new_sessions = []
    for s in all_sessions:
        if s["id"] == since_id:
            found = True
            continue
        if found:
            new_sessions.append(s)
    
    # If last session not found, return everything (fresh start)
    if not found:
        return all_sessions
    
    return new_sessions


def is_complex_worthy(session_data: Dict, messages: List) -> bool:
    """Quick check: is this session worth extracting a case from?"""
    source = session_data.get("source", "")
    if source in ("cron", "webhook", "system"):
        return False
    
    tool_call_count = session_data.get("tool_call_count", 0)
    if tool_call_count < 5:
        return False
    
    # Check if it's user-initiated (first user message isn't system)
    for m in messages[:3]:
        if m.get("role") == "user":
            content = str(m.get("content", ""))
            skip_prefixes = [
                "[IMPORTANT", "[CONTEXT COMPACTION", "[Replying to",
                "[System note",
            ]
            if any(content.startswith(p) for p in skip_prefixes):
                return False
            if len(content.strip()) < 10:
                return False
            return True
    return False


def check_threshold_and_act(cases: List[Dict], index: Dict) -> List[Dict]:
    """
    Cluster all existing cases and check if any cluster reached threshold.
    Returns list of new threshold hits.
    """
    # Import here - will be available in incremental_scan scope
    from precipitator.miner import cluster_cases as _cluster_func
    
    clusters = _cluster_func(cases, similarity_threshold=0.45)
    
    new_hits = []
    for cid, cluster in clusters.items():
        if len(cluster) >= SKILL_THRESHOLD:
            # Check if this cluster was already notified
            already_hit = any(
                cid in hit.get("cluster_id", "")
                for hit in index.get("recent_hits", [])
            )
            if not already_hit:
                # Get representative cases
                samples = [
                    {"title": c.get("title", "")[:60], "tools": c.get("tool_count", 0)}
                    for c in cluster[:5]
                ]
                new_hits.append({
                    "cluster_id": cid,
                    "case_count": len(cluster),
                    "samples": samples,
                    "detected_at": time.time(),
                })
    
    return new_hits


def append_to_memory(text: str):
    """Append a finding to MEMORY.md with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n§\n[skill-precipitator {timestamp}]\n{text}\n"
    
    with open(MEMORY_PATH, "a") as f:
        f.write(entry)
    
    return entry


def incremental_scan(scan_all: bool = False, notify: bool = False) -> str:
    """
    Run the incremental scan.
    Returns a human-readable report string.
    """
    from hermes_state import SessionDB
    from precipitator.miner import (
        analyze_session, save_case, load_cases,
        collect_tool_calls, cluster_cases,
    )
    
    index = load_index()
    db = SessionDB()
    
    lines = []
    lines.append(f"🔬 Skill Precipitator Hook — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"   Run: #{index.get('run_count', 0) + 1}")
    lines.append("")
    
    if scan_all:
        sessions = db.list_sessions_rich(limit=10000)
        since_info = "full scan (ALL sessions)"
    else:
        since_id = index.get("last_processed", "")
        sessions = get_recent_sessions(db, since_id=since_id, limit=500)
        since_info = f"since {since_id[:30]}..." if since_id else "first run (all)"
    
    lines.append(f"📥 Scanning ({since_info})")
    lines.append(f"   Found {len(sessions)} unprocessed sessions")
    
    if not sessions:
        lines.append("   ✅ No new sessions to process")
        # Still do threshold check on existing cases
        existing = load_cases()
        if existing:
            new_hits = check_threshold_and_act(existing, index)
            if new_hits:
                lines.append(f"\n🎯 Threshold hits: {len(new_hits)}")
                for hit in new_hits:
                    lines.append(f"   • {hit['cluster_id']}: {hit['case_count']} cases")
                    for s in hit['samples'][:3]:
                        lines.append(f"     - {s['title']}")
            else:
                lines.append("   No new threshold hits")
        
        save_index(index)
        return "\n".join(lines)
    
    # Process each session
    extracted = 0
    skipped = {"simple": 0, "cron": 0, "no_substance": 0}
    newest_id = index.get("last_processed", "")
    
    for s in sessions:
        sid = s["id"]
        source = s.get("source", "")
        
        if source in ("cron", "webhook"):
            skipped["cron"] += 1
            continue
        
        msgs = db.get_messages_as_conversation(sid) or []
        
        _, _, tc_count = collect_tool_calls(msgs)
        if tc_count < 5:
            skipped["simple"] += 1
            continue
        
        # Full analysis
        try:
            case = analyze_session(s, msgs)
            if case:
                filepath = save_case(case)
                extracted += 1
                newest_id = sid  # Track newest processed
        except Exception as e:
            lines.append(f"   ⚠ Error processing {sid[:30]}: {e}")
    
    # Update index with the actual last session seen
    if sessions:
        index["last_processed"] = sessions[-1]["id"]
    index["total_extracted"] = index.get("total_extracted", 0) + extracted
    index["total_scanned"] = index.get("total_scanned", 0) + len(sessions)
    
    lines.append(f"\n📊 Results: {extracted} extracted, {skipped}")
    
    # Threshold check
    existing = load_cases()
    if existing:
        lines.append(f"   Total cases: {len(existing)}")
        new_hits = check_threshold_and_act(existing, index)
        
        if new_hits:
            # Record hits
            recent_hits = index.get("recent_hits", [])
            for hit in new_hits:
                recent_hits.append(hit)
            index["recent_hits"] = recent_hits[-10:]  # Keep last 10
            index["threshold_hits"] = index.get("threshold_hits", 0) + len(new_hits)
            
            lines.append(f"\n{'='*50}")
            lines.append(f"🎯 NEW SKILL CANDIDATES FOUND ({len(new_hits)})")
            lines.append(f"{'='*50}")
            
            for hit in new_hits:
                lines.append(f"\n  📄 {hit['cluster_id']}")
                lines.append(f"     Cases: {hit['case_count']}")
                lines.append(f"     Examples:")
                for s in hit['samples'][:5]:
                    lines.append(f"       • [{s['tools']}t] {s['title']}")
                lines.append(f"     → Run: python3 ~/.hermes/scripts/skill_precipitator.py forge --min-cases 3")
                lines.append(f"     → Or install: python3 ~/.hermes/scripts/skill_precipitator.py install <name>")
            
            # Optionally append to MEMORY.md if --notify
            if notify:
                for hit in new_hits:
                    summary = f"Skill candidate found: {hit['cluster_id']} ({hit['case_count']} similar sessions)"
                    append_to_memory(summary)
                lines.append(f"\n   ✅ Appended {len(new_hits)} findings to MEMORY.md")
        else:
            lines.append("   No new threshold hits")
    
    save_index(index)
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Skill Precipitator Hook")
    parser.add_argument("--all", action="store_true", help="Full re-scan (ignore index)")
    parser.add_argument("--notify", action="store_true", help="Append findings to MEMORY.md")
    args = parser.parse_args()
    
    report = incremental_scan(scan_all=args.all, notify=args.notify)
    print(report)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

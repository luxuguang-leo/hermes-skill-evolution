#!/usr/bin/env python3
"""Skill Evolution Hook — Incremental session processor (cron-based)."""
import json, os, sys, time
from collections import Counter
from datetime import datetime

HERMES_HOME = os.path.expanduser("~/.hermes")
CASES_DIR = os.path.join(HERMES_HOME, "agent", "cases")
INDEX_PATH = os.path.join(HERMES_HOME, "agent", ".case_index.json")
SKILL_THRESHOLD = 3

for p in [os.path.join(HERMES_HOME, "scripts"), os.path.join(HERMES_HOME, "hermes-agent")]:
    if p not in sys.path: sys.path.insert(0, p)


def load_index() -> dict:
    if os.path.exists(INDEX_PATH):
        return json.load(open(INDEX_PATH))
    return {"last_processed": "", "last_run": 0, "total_scanned": 0, "total_extracted": 0,
            "total_cases": 0, "threshold_hits": 0, "run_count": 0}


def save_index(index: dict):
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    index["last_run"] = time.time()
    index["run_count"] = index.get("run_count", 0) + 1
    index["total_cases"] = len([f for f in os.listdir(CASES_DIR) if f.endswith(".md")]) if os.path.isdir(CASES_DIR) else 0
    json.dump(index, open(INDEX_PATH, "w"), indent=2)


def get_recent_sessions(db, since_id="", limit=500):
    all_sessions = db.list_sessions_rich(limit=limit)
    if not since_id:
        return all_sessions
    for i, s in enumerate(all_sessions):
        if s["id"] == since_id:
            return all_sessions[i+1:]
    return all_sessions


def check_threshold(index: dict) -> list:
    from evolution.miner import load_cases, cluster_cases as do_cluster
    cases = load_cases()
    if not cases:
        return []
    clusters = do_cluster(cases, threshold=0.45)
    hits = []
    for cid, cluster in clusters.items():
        if len(cluster) >= SKILL_THRESHOLD:
            already = any(cid in h.get("cluster_id", "") for h in index.get("recent_hits", []))
            if not already:
                hits.append({
                    "cluster_id": cid, "case_count": len(cluster),
                    "samples": [{"title": c.get("title", "")[:60], "tools": c.get("tool_count", 0)} for c in cluster[:5]],
                    "detected_at": time.time(),
                })
    return hits


def incremental_scan(scan_all=False, notify=False) -> str:
    from hermes_state import SessionDB
    from evolution.miner import collect_tool_calls, analyze_session, save_case, load_cases

    index = load_index()
    db = SessionDB()
    lines = [f"Skill Evolution Hook — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]

    if scan_all:
        sessions = db.list_sessions_rich(limit=10000)
    else:
        sessions = get_recent_sessions(db, index.get("last_processed", ""))
    lines.append(f"Sessions: {len(sessions)}")

    if not sessions:
        hits = check_threshold(index)
        for h in hits:
            lines.append(f"Threshold: {h['cluster_id']} ({h['case_count']} cases)")
        save_index(index)
        return "\n".join(lines) + "\nNo new sessions."

    extracted = 0
    for s in sessions:
        if s.get("source") in ("cron", "webhook"):
            continue
        msgs = db.get_messages_as_conversation(s["id"]) or []
        _, _, tc = collect_tool_calls(msgs)
        if tc < 5:
            continue
        try:
            case = analyze_session(s, msgs)
            if case:
                save_case(case)
                extracted += 1
        except:
            pass

    index["last_processed"] = sessions[-1]["id"]
    index["total_extracted"] = index.get("total_extracted", 0) + extracted
    index["total_scanned"] = index.get("total_scanned", 0) + len(sessions)
    lines.append(f"Extracted: {extracted}")

    existing = load_cases()
    if existing:
        lines.append(f"Total cases: {len(existing)}")
        hits = check_threshold(index)
        if hits:
            recent = index.get("recent_hits", [])
            recent.extend(hits)
            index["recent_hits"] = recent[-10:]
            index["threshold_hits"] = index.get("threshold_hits", 0) + len(hits)
            lines.append(f"NEW CANDIDATES ({len(hits)})")
            for h in hits:
                lines.append(f"  {h['cluster_id']} ({h['case_count']}c)")
                for s in h["samples"][:3]:
                    lines.append(f"    [{s['tools']}t] {s['title']}")

    save_index(index)
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true")
    p.add_argument("--notify", action="store_true")
    args = p.parse_args()
    print(incremental_scan(scan_all=args.all, notify=args.notify))

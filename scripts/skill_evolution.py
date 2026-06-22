#!/usr/bin/env python3
"""Skill Evolution v2.0 — Auto-discover reusable workflows from session history.

Usage:
  scan [--limit N] [--all]     Scan sessions → extract cases
  cluster [--threshold F]      Cluster cases → find patterns
  forge [--min-cases N]        Forge skills from clusters
  status                       Show system status
  validate [--live]            Validate candidates
  install <name>               Install a candidate as skill
"""
import argparse, json, os, sys, time
from datetime import datetime

SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from mining import VERSION
from mining.miner import scan_sessions, load_cases, cluster_cases, get_summary, save_case
from mining.forge import forge_skill, get_candidate_paths
from mining.validator import validate_all_candidates, install_candidate


def cmd_scan(args):
    t0 = time.time()
    cases = scan_sessions(limit=args.limit, scan_all=args.all)
    if not cases:
        return print("No cases found.")
    paths = [save_case(c) for c in cases]
    s = get_summary(cases)
    print(f"Saved {len(paths)} cases ({s['total']} total, avg {s['avg_tools']:.0f} tools)")
    print(f"Types: {', '.join(f'{k}={v}' for k,v in s['by_type'].items())}")
    print(f"Intents: {', '.join(f'{k}={v}' for k,v in s['by_intent'].items())}")
    print(f"Time: {time.time()-t0:.1f}s")


def cmd_cluster(args):
    cases = load_cases()
    if not cases:
        return print("No cases. Run scan first.")
    clusters = cluster_cases(cases, threshold=args.threshold)
    print(f"{len(cases)} cases → {len(clusters)} clusters")
    for cid, cluster in sorted(clusters.items()):
        print(f"  {cid}: {len(cluster)} cases")
        for c in cluster[:3]:
            print(f"    [{c.get('tool_count',0)}t] {c.get('title', c.get('case_name','?'))[:60]}")
        if len(cluster) > 3:
            print(f"    ... +{len(cluster)-3} more")
    with open(os.path.expanduser("~/.hermes/agent/clusters.json"), "w") as f:
        json.dump({cid: {"count": len(cluster), "cases": [{"case_name": c.get("case_name","?"), "tool_count": c.get("tool_count",0)} for c in cluster]} for cid, cluster in clusters.items()}, f, indent=2)
    print("Saved to ~/.hermes/agent/clusters.json")


def cmd_forge(args):
    cases = load_cases()
    if not cases:
        return print("No cases. Run scan first.")
    clusters = cluster_cases(cases, threshold=args.threshold)
    forgeable = {cid: c for cid, c in clusters.items() if len(c) >= args.min_cases}
    if not forgeable:
        sizes = {cid: len(c) for cid, c in clusters.items()}
        return print(f"No clusters ≥{args.min_cases}. Sizes: {sizes}")
    results = []
    for cid, cluster in sorted(forgeable.items()):
        r = forge_skill(cid, cluster, auto_llm=not args.no_llm)
        results.append(r)
        print(f"  {r['skill_name']} ({r['case_count']}c) → {r['safe_name']}/")
    with open(os.path.expanduser("~/.hermes/agent/candidates_list.json"), "w") as f:
        json.dump([{"name": r["skill_name"], "safe_name": r["safe_name"], "case_count": r["case_count"], "cluster_id": r["cluster_id"]} for r in results], f, indent=2)
    print(f"\nGenerated {len(results)} candidates. Run 'install <name>' to deploy.")


def cmd_status(args):
    cases = load_cases()
    s = get_summary(cases)
    print(f"Skill Evolution v{VERSION}")
    print(f"Cases: {s['total']} (avg {s['avg_tools']:.0f}t, max {s['max_tools']}t)")
    clusters_path = os.path.expanduser("~/.hermes/agent/clusters.json")
    clusters = json.load(open(clusters_path)) if os.path.exists(clusters_path) else {}
    print(f"Clusters: {len(clusters)}")
    candidates = get_candidate_paths()
    print(f"Candidates: {len(candidates)}")
    for c in candidates:
        src = "LLM" if c.get("has_analysis") else "template"
        print(f"  {c['name']} ({c['case_count']}c, {src})")


def cmd_validate(args):
    results = validate_all_candidates(dry_run=not args.live)
    if not results:
        return print("No candidates.")
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")
    for r in results:
        icon = "✅" if r["status"] == "pass" else "❌"
        print(f"  {icon} {r['name']}: {r['message'][:80]}")
    print(f"\n{passed} passed, {failed} failed, {errors} errors")
    if not args.live:
        print("Use --live to execute tests")


def cmd_install(args):
    candidates = get_candidate_paths()
    target = next((c for c in candidates if c["name"] == args.name or c["dir"] == args.name), None)
    if not target:
        return print(f"Not found: {args.name}. Available: {', '.join(c['name'] for c in candidates)}")
    cdir = os.path.expanduser(f"~/.hermes/agent/candidates/{target['dir']}")
    result = install_candidate(cdir, target["dir"])
    print(f"{'✅' if result['status']=='success' else '❌'} {result['message']}")


def main():
    p = argparse.ArgumentParser(description=f"Skill Evolution v{VERSION}")
    sp = p.add_subparsers(dest="cmd")
    sp.add_parser("scan").add_argument("--limit", type=int, default=100)
    sp.add_parser("scan").add_argument("--all", action="store_true")
    sp.add_parser("cluster").add_argument("--threshold", type=float, default=0.5)
    sp.add_parser("forge").add_argument("--min-cases", type=int, default=3)
    sp.add_parser("forge").add_argument("--threshold", type=float, default=0.5)
    sp.add_parser("forge").add_argument("--no-llm", action="store_true")
    sp.add_parser("status")
    sp.add_parser("validate").add_argument("--live", action="store_true")
    sp.add_parser("install").add_argument("name")
    args = p.parse_args()
    if not args.cmd:
        return p.print_help()
    {"scan": cmd_scan, "cluster": cmd_cluster, "forge": cmd_forge,
     "status": cmd_status, "validate": cmd_validate, "install": cmd_install}[args.cmd](args)
    return 0

if __name__ == "__main__":
    sys.exit(main())

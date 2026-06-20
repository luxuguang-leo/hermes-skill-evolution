#!/usr/bin/env python3
"""
Skill Precipitator v2 — Auto-discover reusable workflows from session history.

Usage:
  skill_precipitator.py scan [--limit N] [--all]    # Scan sessions → extract cases
  skill_precipitator.py cluster                      # Cluster cases → find patterns
  skill_precipitator.py forge [--min-cases N]         # Forge skills from clusters
  skill_precipitator.py status                        # Show system status
  skill_precipitator.py report                        # Full report of candidates
  skill_precipitator.py validate [--live]             # Validate all candidates
  skill_precipitator.py install <name>                # Install a candidate as skill
  skill_precipitator.py test                          # Run synthetic test to verify system

Architecture:
  ┌──────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
  │  Scan        │ →   │  Cluster     │ →   │  Forge        │ →   │  Validate    │
  │  (miner)     │     │  (miner)     │     │  (forge+LLM)  │     │  (validator) │
  └──────────────┘     └──────────────┘     └───────────────┘     └──────────────┘
                                                                          │
                                                                          ▼
                                                                   ┌──────────────┐
                                                                   │  Install     │
                                                                   │  (presenter) │
                                                                   └──────────────┘
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# Add scripts directory to path for module imports
SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from precipitator import VERSION
from precipitator.miner import (
    scan_sessions,
    save_cases,
    load_cases,
    cluster_cases,
    get_summary,
)
from precipitator.forge import (
    forge_skill,
    get_candidate_paths,
    list_candidates,
    call_llm,
)
from precipitator.validator import (
    run_test,
    validate_all_candidates,
    install_candidate,
)
from precipitator.presenter import (
    generate_report_markdown,
    present_summary,
)


def cmd_scan(args):
    """Scan sessions and extract cases."""
    print(f"🔍 Scanning sessions (limit={args.limit}, all={args.all})...")
    t0 = time.time()
    
    cases = scan_sessions(limit=args.limit, scan_all=args.all)
    
    if not cases:
        print("No cases found.")
        return
    
    # Save cases
    paths = save_cases(cases)
    print(f"\nSaved {len(paths)} case files to ~/.hermes/agent/cases/")
    
    # Show summary
    summary = get_summary(cases)
    print(f"\n📊 Summary:")
    print(f"  Total cases: {summary['total']}")
    print(f"  Avg tools/case: {summary['avg_tools']}")
    print(f"  Max tools: {summary['max_tools']}")
    print(f"\n  By type:")
    for t, c in summary.get("by_type", {}).items():
        print(f"    {t}: {c}")
    print(f"\n  By intent:")
    for t, c in summary.get("by_intent", {}).items():
        print(f"    {t}: {c}")
    
    print(f"\n  Time: {time.time() - t0:.1f}s")


def cmd_cluster(args):
    """Cluster existing cases."""
    print("🔗 Clustering cases...")
    
    cases = load_cases()
    if not cases:
        print("No cases found. Run 'scan' first.")
        return
    
    print(f"Loaded {len(cases)} cases")
    
    clusters = cluster_cases(cases, similarity_threshold=args.threshold)
    
    print(f"\nFound {len(clusters)} clusters:")
    for cid, cluster in sorted(clusters.items()):
        print(f"  {cid}: {len(cluster)} cases")
        for c in cluster[:3]:
            name = c.get("title", c.get("case_name", "?"))[:60]
            tools = c.get("tool_count", 0)
            print(f"    [{tools}tools] {name}")
        if len(cluster) > 3:
            print(f"    ... and {len(cluster)-3} more")
    
    # Save cluster info
    cluster_info = {}
    for cid, cluster in clusters.items():
        cluster_info[cid] = {
            "count": len(cluster),
            "cases": [{"case_name": c.get("case_name", "?"), "tool_count": c.get("tool_count", 0)} for c in cluster],
        }
    
    clusters_path = os.path.expanduser("~/.hermes/agent/clusters.json")
    with open(clusters_path, "w", encoding="utf-8") as f:
        json.dump(cluster_info, f, ensure_ascii=False, indent=2)
    print(f"\nCluster details saved to {clusters_path}")


def cmd_forge(args):
    """
    Forge skill candidates from clusters.
    1. Load cases → cluster them
    2. For each cluster with ≥ min_cases cases, generate a skill draft
    3. Use LLM if available, fallback to template
    """
    print("🔨 Forging skill candidates...")
    
    cases = load_cases()
    if not cases:
        print("No cases found. Run 'scan' first.")
        return
    
    print(f"Loaded {len(cases)} cases")
    
    # Cluster
    clusters = cluster_cases(cases, similarity_threshold=args.threshold)
    print(f"Found {len(clusters)} clusters")
    
    # Filter by minimum size
    forgeable = {cid: cluster for cid, cluster in clusters.items() if len(cluster) >= args.min_cases}
    
    if not forgeable:
        print(f"No clusters with ≥{args.min_cases} cases. Use --min-cases to lower threshold.")
        print(f"Cluster sizes: {', '.join(f'{cid}={len(c)}' for cid, c in sorted(clusters.items()))}")
        return
    
    print(f"Forgeable clusters (≥{args.min_cases} cases): {len(forgeable)}")
    
    use_llm = not args.no_llm
    results = []
    
    for cid, cluster in sorted(forgeable.items()):
        print(f"\n  🎯 {cid} ({len(cluster)} cases)...")
        
        result = forge_skill(cid, cluster, auto_llm=use_llm)
        results.append(result)
        
        print(f"    Name: {result['skill_name']}")
        print(f"    Dir: {result['safe_name']}")
        print(f"    LLM: {'✓' if use_llm and 'LLM' in result.get('skill_draft', '')[:5] else '✗ (template)'}")
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Generated {len(results)} skill candidates:")
    for r in results:
        print(f"  📄 {r['skill_name']} ({r['case_count']} cases) → {r['safe_name']}/")
    
    # Present to user
    print(f"\n{generate_report_markdown()}")
    
    # Save candidate list
    candidates_list = [{
        "name": r["skill_name"],
        "safe_name": r["safe_name"],
        "case_count": r["case_count"],
        "cluster_id": r["cluster_id"],
        "candidate_dir": r["candidate_dir"],
    } for r in results]
    
    candidates_path = os.path.expanduser("~/.hermes/agent/candidates_list.json")
    with open(candidates_path, "w", encoding="utf-8") as f:
        json.dump(candidates_list, f, ensure_ascii=False, indent=2)
    print(f"Candidate list saved to {candidates_path}")


def cmd_status(args):
    """Show system status."""
    print(f"⚙️  Skill Precipitator v{VERSION}")
    print(f"{'='*50}")
    
    # Case count
    cases = load_cases()
    summary = get_summary(cases)
    print(f"\n📂 Cases: {summary['total']}")
    print(f"  Avg tools: {summary['avg_tools']}")
    print(f"  Max tools: {summary['max_tools']}")
    
    # Patterns
    if summary.get("by_type"):
        print(f"\n  🏷️  Signature patterns:")
        for t, c in summary["by_type"].items():
            print(f"    {t}: {c} cases")
    
    if summary.get("by_intent"):
        print(f"\n  🎯  User intents:")
        for t, c in summary["by_intent"].items():
            print(f"    {t}: {c} cases")
    
    # Clusters
    clusters_path = os.path.expanduser("~/.hermes/agent/clusters.json")
    if os.path.exists(clusters_path):
        with open(clusters_path) as f:
            clusters = json.load(f)
        print(f"\n🔗 Clusters: {len(clusters)}")
        for cid, info in sorted(clusters.items()):
            print(f"  {cid}: {info['count']} cases")
    
    # Candidates
    candidates = get_candidate_paths()
    print(f"\n📝 Skill Candidates: {len(candidates)}")
    for c in candidates:
        src = "🤖 LLM" if c.get("has_analysis") else "📋 Template"
        print(f"  {c['name']} ({c['case_count']} cases, {src})")


def cmd_report(args):
    """Generate a full report."""
    print(generate_report_markdown())


def cmd_validate(args):
    """Validate candidates."""
    print("🧪 Validating skill candidates...")
    
    results = validate_all_candidates(dry_run=not args.live)
    
    if not results:
        print("No candidates to validate.")
        return
    
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")
    
    print(f"\nResults: {passed} passed, {failed} failed, {errors} errors")
    
    for r in results:
        status_icon = "✅" if r["status"] == "pass" else ("❌" if r["status"] == "fail" else "⚠️")
        mode = r.get("mode", "dry-run")
        print(f"  {status_icon} {r['name']}: {r['message'][:80]} ({mode})")
    
    if not args.live:
        print(f"\n💡 Use --live to actually execute tests")


def cmd_install(args):
    """Install a candidate as a real skill."""
    candidates = get_candidate_paths()
    
    # Find by name or dir
    target = None
    for c in candidates:
        if c["name"] == args.name or c["dir"] == args.name:
            target = c
            break
    
    if not target:
        print(f"Candidate '{args.name}' not found.")
        print(f"Available: {', '.join(c['name'] for c in candidates)}")
        return
    
    cdir = os.path.expanduser(f"~/.hermes/agent/candidates/{target['dir']}")
    result = install_candidate(cdir, target["dir"])
    
    if result["status"] == "success":
        print(f"✅ {result['message']}")
        print(f"   Path: {result['path']}")
    else:
        print(f"❌ {result['message']}")


def cmd_test(args):
    """
    Run synthetic test to verify the entire pipeline works.
    Creates mock sessions with known patterns and checks extraction.
    """
    print("🧪 Running synthetic system test...")
    
    from precipitator.signatures import (
        compute_signature,
        classify_session_type,
        signature_similarity,
        extract_sequence_signature,
        extract_user_intent,
    )
    
    tests_passed = 0
    tests_total = 0
    
    def check(name, condition, detail=""):
        nonlocal tests_passed, tests_total
        tests_total += 1
        if condition:
            tests_passed += 1
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}: {detail}")
    
    print("\n### 1. Signature Classification Test")
    
    # Test: SHELL-heavy session
    shell_tools = ["terminal"] * 20 + ["read_file"] * 3 + ["write_file"] * 2
    sig = compute_signature(shell_tools)
    types = classify_session_type(sig, len(shell_tools))
    check("SHELL-heavy classification", "HEAVY_SHELL" in types or "_SHELL" in types, f"got {types}")
    check("SHELL ratio > 0.7", sig.get("SHELL", 0) > 0.7, f"SHELL={sig.get('SHELL',0)}")
    
    # Test: Browser session
    browser_tools = ["browser_navigate"] * 5 + ["browser_click"] * 5 + ["browser_snapshot"] * 3 + ["browser_vision"] * 2
    sig = compute_signature(browser_tools)
    types = classify_session_type(sig, len(browser_tools))
    check("BROWSER-heavy classification", "HEAVY_BROWSER" in types or "_BROWSER" in types, f"got {types}")
    
    # Test: Hybrid session
    hybrid_tools = ["terminal"] * 8 + ["browser_navigate"] * 3 + ["read_file"] * 2 + ["write_file"] * 2 + ["web_search"] * 3
    sig = compute_signature(hybrid_tools)
    types = classify_session_type(sig, len(hybrid_tools))
    check("HYBRID detection", "HYBRID" in types, f"got {types}")
    
    # Test: Similarity
    sig1 = compute_signature(["terminal"] * 20 + ["read_file"] * 3)
    sig2 = compute_signature(["terminal"] * 18 + ["read_file"] * 5)
    sim = signature_similarity(sig1, sig2)
    check("Similarity (same type)", sim > 0.9, f"sim={sim:.3f}")
    
    # Test: Different signatures should have low similarity
    sig3 = compute_signature(["browser_navigate"] * 10 + ["browser_click"] * 5)
    sim_diff = signature_similarity(sig1, sig3)
    check("Similarity (different types)", sim_diff < 0.5, f"sim={sim_diff:.3f}")
    
    print(f"\n### 2. Sequence Pattern Test")
    
    sequences = [
        ["terminal", "terminal", "terminal"],
        ["read_file", "patch", "write_file"],
        ["browser_navigate", "browser_snapshot", "browser_click"],
    ]
    ngrams = extract_sequence_signature(sequences)
    check("n-gram extraction", len(ngrams) > 0, f"got {len(ngrams)} patterns")
    check("contains bigram", any(">" in k for k in ngrams), f"keys={list(ngrams.keys())[:5]}")
    check("contains trigram", any(k.count(">") > 1 for k in ngrams), f"keys={list(ngrams.keys())[:5]}")
    
    print(f"\n### 3. Intent Extraction Test")
    
    intent = extract_user_intent(["Install a GPU model for me"])
    check("Chinese install intent", intent.get("install-setup", 0) > 0, f"got {intent}")
    
    intent2 = extract_user_intent(["Research the latest developments in this field"])
    check("Chinese research intent", intent2.get("research", 0) > 0, f"got {intent2}")
    
    intent3 = extract_user_intent(["Download this YouTube video"])
    check("Chinese download intent", intent3.get("download-media", 0) > 0, f"got {intent3}")
    
    # Pipeline integration test
    print(f"\n### 4. Pipeline Integration Test")
    from precipitator.miner import analyze_session, generate_case_name
    
    # Create mock session data
    mock_session = {
        "id": "test_001",
        "title": "Test Session",
        "source": "feishu",
    }
    
    mock_messages = [
        {"role": "user", "content": "Research the Loop Engineering framework for me"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "web_search"}},
            {"function": {"name": "web_search"}},
        ]},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "web_extract"}},
            {"function": {"name": "read_file"}},
        ]},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "write_file"}},
            {"function": {"name": "read_file"}},
        ]},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "session_search"}},
        ]},
        {"role": "user", "content": "Go deeper, keep investigating"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "web_search"}},
            {"function": {"name": "web_extract"}},
        ]},
    ]
    
    case = analyze_session(mock_session, mock_messages)
    check("Session analysis (mock)", case is not None, f"got None")
    if case:
        check("Tool count > 5", case["tool_count"] >= 5, f"got {case['tool_count']}")
        check("Web intent detected", "research" in case.get("intent", {}), f"intent={case.get('intent')}")
    
    # Final
    print(f"\n{'='*50}")
    print(f"🏁 Test Results: {tests_passed}/{tests_total} passed")
    
    if tests_passed == tests_total:
        print("✅ All tests passed! System is working correctly.")
    else:
        print(f"❌ {tests_total - tests_passed} tests failed.")
    
    return 0 if tests_passed == tests_total else 1


def main():
    parser = argparse.ArgumentParser(
        description=f"Skill Precipitator v{VERSION} — Auto-discover reusable workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    
    sub = parser.add_subparsers(dest="command", help="Command")
    
    # scan
    p_scan = sub.add_parser("scan", help="Scan sessions and extract cases")
    p_scan.add_argument("--limit", type=int, default=100, help="Number of recent sessions to scan")
    p_scan.add_argument("--all", action="store_true", help="Scan all sessions")
    
    # cluster
    p_cluster = sub.add_parser("cluster", help="Cluster existing cases")
    p_cluster.add_argument("--threshold", type=float, default=0.5, help="Similarity threshold (0-1)")
    
    # forge
    p_forge = sub.add_parser("forge", help="Forge skill candidates from clusters")
    p_forge.add_argument("--min-cases", type=int, default=3, help="Minimum cases per cluster")
    p_forge.add_argument("--threshold", type=float, default=0.5, help="Similarity threshold")
    p_forge.add_argument("--no-llm", action="store_true", help="Skip LLM, use template only")
    
    # status
    sub.add_parser("status", help="Show system status")
    
    # report
    sub.add_parser("report", help="Full report of candidates")
    
    # validate
    p_val = sub.add_parser("validate", help="Validate candidates")
    p_val.add_argument("--live", action="store_true", help="Actually run test scripts")
    
    # install
    p_inst = sub.add_parser("install", help="Install a candidate as skill")
    p_inst.add_argument("name", help="Candidate name or directory")
    
    # test
    sub.add_parser("test", help="Run synthetic system test")
    
    args = parser.parse_args()
    
    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "cluster":
        cmd_cluster(args)
    elif args.command == "forge":
        cmd_forge(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "test":
        return cmd_test(args)
    else:
        parser.print_help()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

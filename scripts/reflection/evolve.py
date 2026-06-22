#!/usr/bin/env python3
"""
Phase 3: Evolve — Auto-maintenance actions based on Reflection scan results.

Reads the scan report and suggests/provides auto-maintenance:
  - Archive zombie skills to .archive/
  - Memory consolidation recommendations
  - Cron health check

Usage:
  python3 phase3_evolve.py --report              # Show actionable items from scan
  python3 phase3_evolve.py --archive-zombies     # Archive zombies (dry-run)
  python3 phase3_evolve.py --archive-zombies --apply  # Actually archive them
  python3 phase3_evolve.py --check-crons         # Verify cron jobs are healthy
"""

import argparse, json, os, shutil, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
REFLECTION_DIR = HERMES_HOME / "reflection"
SKILLS_DIR = HERMES_HOME / "skills"
ARCHIVE_DIR = SKILLS_DIR / ".archive"

# Skills that are intentionally stable (not zombies)
STABLE_SKILLS = {
    "plan", "systematic-debugging", "test-driven-development",
    "requesting-code-review", "subagent-driven-development",
    "github-auth", "github-code-review", "github-pr-workflow",
    "github-repo-management", "codebase-inspection",
}


def load_scan_report():
    """Load the latest scan report."""
    report_path = REFLECTION_DIR / "scan-report.json"
    if not report_path.exists():
        print(f"❌ No scan report found. Run reflection_scan.py first.")
        return None
    return json.loads(report_path.read_text())


def format_size(n):
    if n < 1000:
        return f"{n} B"
    return f"{n/1000:.1f} KB"


def zombie_skills(report, dry_run=True):
    """Identify and optionally archive zombie skills."""
    skills = report.get("skills", {}).get("skills", [])
    zombies = [s for s in skills if s.get("is_zombie")]
    zombies = [s for s in zombies if s["name"] not in STABLE_SKILLS]

    if not zombies:
        print("✅ No zombie skills to archive.")
        return

    print(f"\n  📦 Zombie skills ({len(zombies)}) candidates for archive:")
    for z in sorted(zombies, key=lambda x: -x["last_modified_days"]):
        cat = f" ({z['category']})" if z.get("category") else ""
        print(f"    {z['name']}{cat} — {z['last_modified_days']}d unchanged, {z['size_human']}")

    if dry_run:
        print(f"\n  🔍 Dry-run mode. Use --apply to actually archive.")
        return

    # Actually archive
    archived = 0
    for z in zombies:
        src_path = Path(z["path"])
        if not src_path.exists():
            continue
        dst = ARCHIVE_DIR / z["name"]
        if dst.exists():
            print(f"    ⚠️ {z['name']} already in archive, skipping")
            continue
        shutil.move(str(src_path), str(dst))
        print(f"    ✅ {z['name']} → .archive/")
        archived += 1

    print(f"\n  ✅ Archived {archived}/{len(zombies)} zombie skills")
    return archived


def memory_health(report):
    """Report memory water level and consolidation suggestions."""
    mem = report.get("memory", {})
    memory = mem.get("memory", {})
    user = mem.get("user_profile", {})

    issues = []
    if memory.get("is_near_limit"):
        issues.append(f"MEMORY.md: {memory['size_human']} / 2.2KB limit "
                      f"({memory['usage_pct']}%) — run phase2_consolidate.py")

    if user.get("is_near_limit"):
        issues.append(f"USER.md: {user['size_human']} / 1.4KB limit "
                      f"({user['usage_pct']}%) — run phase2_consolidate.py")

    return issues


def kanban_health(report):
    """Report kanban blockers."""
    kanban = report.get("kanban", {})
    stuck = kanban.get("stuck", [])
    if stuck:
        return [f"Kanban: {len(stuck)} tasks stuck >48h — "
                f"{', '.join(t['title'][:30] for t in stuck[:3])}"]
    return []


def check_crons():
    """Check if required cron jobs exist."""
    required = {
        "unified-weekly-maintenance": "0 3 * * 0",
        "skill-evolution-hook": "daily 12:00",
    }
    try:
        result = os.popen("hermes cron list 2>/dev/null").read()
        issues = []
        for name, expected_schedule in required.items():
            if name not in result:
                issues.append(f"Missing cron: {name} (expected: {expected_schedule})")
        return issues
    except Exception:
        return ["Could not check cron status (hermes CLI not available)"]


def show_report(report):
    """Show actionable items from the scan report."""
    if not report:
        return

    print("=" * 50)
    print("📊 Reflection Scan — Actionable Items")
    print("=" * 50)

    # Memory
    mem_issues = memory_health(report)
    if mem_issues:
        print("\n  💾 Memory:")
        for i in mem_issues:
            print(f"    ⚠️ {i}")

    # Zombies
    skills = report.get("skills", {})
    zombies = [s for s in skills.get("skills", [])
               if s.get("is_zombie") and s["name"] not in STABLE_SKILLS]
    if zombies:
        print(f"\n  📦 Zombie skills ({len(zombies)}):")
        for z in sorted(zombies, key=lambda x: -x["last_modified_days"])[:5]:
            cat = f" ({z['category']})" if z.get("category") else ""
            print(f"    ⚰️ {z['name']}{cat} — {z['last_modified_days']}d")
        if len(zombies) > 5:
            print(f"    ... and {len(zombies)-5} more")

    # Kanban
    kanban_issues = kanban_health(report)
    if kanban_issues:
        print("\n  📋 Kanban:")
        for i in kanban_issues:
            print(f"    ⏳ {i}")

    # Cron
    cron_issues = check_crons()
    if cron_issues:
        print("\n  ⏰ Cron:")
        for i in cron_issues:
            print(f"    ❌ {i}")

    # Summary
    total_issues = len(mem_issues) + len(zombies) + len(kanban_issues) + len(cron_issues)
    if total_issues == 0:
        print("\n  ✅ All clear — no actionable items.")

    return total_issues


def main():
    parser = argparse.ArgumentParser(description="Phase 3: Evolve — Auto-Maintenance")
    parser.add_argument("--report", action="store_true", help="Show actionable items")
    parser.add_argument("--archive-zombies", action="store_true",
                       help="List zombie skills (dry-run)")
    parser.add_argument("--apply", action="store_true",
                       help="Apply archive (use with --archive-zombies)")
    parser.add_argument("--check-crons", action="store_true",
                       help="Verify cron jobs are healthy")
    args = parser.parse_args()

    report = load_scan_report()

    if args.report or not any([args.archive_zombies, args.check_crons]):
        show_report(report)

    if args.archive_zombies:
        if not report:
            print("❌ No scan report. Run reflection_scan.py first.")
            return
        zombie_skills(report, dry_run=not args.apply)

    if args.check_crons:
        issues = check_crons()
        if issues:
            print("\n  ⏰ Cron health:")
            for i in issues:
                print(f"    ❌ {i}")
        else:
            print("\n  ⏰ All required crons OK ✅")


if __name__ == "__main__":
    main()

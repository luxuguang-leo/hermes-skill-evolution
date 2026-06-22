"""Validator — Run test scenarios for skill candidates."""
import os, subprocess, sys
from typing import Any, Dict, List
from .forge import get_candidate_paths

HERMES_HOME = os.path.expanduser("~/.hermes")
CANDIDATES_DIR = os.path.join(HERMES_HOME, "agent", "candidates")


def run_test(candidate_dir: str, dry_run: bool = True) -> Dict:
    test_path = os.path.join(candidate_dir, "tests", "test_skill.py")
    if not os.path.exists(test_path):
        return {"status": "error", "message": "No test found", "path": test_path}
    with open(test_path) as f:
        content = f.read()
    try:
        compile(content, test_path, "exec")
    except SyntaxError as e:
        return {"status": "fail", "message": f"Syntax: {e}", "path": test_path}
    if dry_run:
        return {"status": "pass", "message": f"Syntax OK ({len(content.splitlines())} lines)", "path": test_path, "mode": "dry-run"}
    r = subprocess.run([sys.executable, test_path], capture_output=True, text=True, timeout=30)
    passed = r.returncode == 0
    return {"status": "pass" if passed else "fail", "message": r.stdout.strip() if passed else r.stderr.strip()[:500],
            "path": test_path, "mode": "live", "exit_code": r.returncode}


def validate_all_candidates(dry_run: bool = True) -> List[Dict]:
    results = []
    for c in get_candidate_paths():
        r = run_test(os.path.join(CANDIDATES_DIR, c["dir"]), dry_run=dry_run)
        r.update({"name": c["name"], "dir": c["dir"], "case_count": c.get("case_count", 0)})
        results.append(r)
    return results


def install_candidate(candidate_dir: str, skill_name: str) -> Dict:
    src = os.path.join(candidate_dir, "SKILL.md")
    if not os.path.exists(src):
        return {"status": "error", "message": "SKILL.md not found"}
    dst = os.path.join(HERMES_HOME, "skills", skill_name, "SKILL.md")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src) as f:
        content = f.read()
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "success", "message": f"Installed: {skill_name} → {dst}", "path": dst}

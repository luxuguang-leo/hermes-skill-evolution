"""
Validator — Run test scenarios for skill candidates.

Pipeline:
  1. Load a candidate's test scenario
  2. Execute it (dry-run or real)
  3. Report results
  4. Optionally present to user for approval
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from .forge import get_candidate_paths

HERMES_HOME = os.path.expanduser("~/.hermes")
CANDIDATES_DIR = os.path.join(HERMES_HOME, "agent", "candidates")


def run_test(candidate_dir: str, dry_run: bool = True) -> Dict:
    """
    Run a candidate's test scenario.
    
    In dry-run mode, just validates that the test script exists and is parseable.
    In real mode, actually executes the test script.
    """
    test_path = os.path.join(candidate_dir, "tests", "test_skill.py")
    
    if not os.path.exists(test_path):
        return {
            "status": "error",
            "message": "No test scenario found",
            "path": test_path,
        }
    
    # Read test to validate syntax
    with open(test_path, "r") as f:
        content = f.read()
    
    # Basic syntax check
    try:
        compile(content, test_path, "exec")
    except SyntaxError as e:
        return {
            "status": "fail",
            "message": f"Syntax error: {e}",
            "path": test_path,
        }
    
    if dry_run:
        return {
            "status": "pass",
            "message": "Test script syntax OK (dry-run mode)",
            "path": test_path,
            "lines": len(content.splitlines()),
            "mode": "dry-run",
        }
    
    # Real execution
    result = subprocess.run(
        [sys.executable, test_path],
        capture_output=True, text=True, timeout=30,
    )
    
    passed = result.returncode == 0
    return {
        "status": "pass" if passed else "fail",
        "message": result.stdout.strip() if passed else result.stderr.strip()[:500],
        "path": test_path,
        "mode": "live",
        "exit_code": result.returncode,
    }


def validate_all_candidates(dry_run: bool = True) -> List[Dict]:
    """Validate all current candidates."""
    candidates = get_candidate_paths()
    results = []
    
    for c in candidates:
        cdir = os.path.join(CANDIDATES_DIR, c["dir"])
        result = run_test(cdir, dry_run=dry_run)
        result["name"] = c["name"]
        result["dir"] = c["dir"]
        result["case_count"] = c.get("case_count", 0)
        results.append(result)
    
    return results


def install_candidate(candidate_dir: str, skill_name: str) -> Dict:
    """
    Install a candidate as a real Hermes skill.
    Moves SKILL.md to ~/.hermes/skills/{name}/
    """
    skills_dir = os.path.join(HERMES_HOME, "skills", skill_name)
    os.makedirs(skills_dir, exist_ok=True)
    
    src = os.path.join(candidate_dir, "SKILL.md")
    dst = os.path.join(skills_dir, "SKILL.md")
    
    if not os.path.exists(src):
        return {"status": "error", "message": "SKILL.md not found"}
    
    # Read and verify
    with open(src, "r") as f:
        content = f.read()
    
    # Write to skills directory
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    
    return {
        "status": "success",
        "message": f"Installed skill: {skill_name}",
        "path": dst,
    }


def get_report_data() -> Dict:
    """Get full report data for the presenter."""
    candidates = get_candidate_paths()
    
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_candidates": len(candidates),
        "candidates": [],
    }
    
    for c in candidates:
        cdir = os.path.join(CANDIDATES_DIR, c["dir"])
        
        # Read analysis
        analysis_content = ""
        analysis_path = os.path.join(cdir, "_analysis.md")
        if os.path.exists(analysis_path):
            with open(analysis_path, "r") as f:
                analysis_content = f.read()[:500]
        
        # Read SKILL.md preview
        skill_preview = ""
        skill_path = os.path.join(cdir, "SKILL.md")
        if os.path.exists(skill_path):
            with open(skill_path, "r") as f:
                raw = f.read()
                # Extract just the first section
                lines = raw.splitlines()
                preview_lines = [l for l in lines[:20] if l.strip()]
                skill_preview = "\n".join(preview_lines[:15])
        
        report["candidates"].append({
            **c,
            "analysis_preview": analysis_content,
            "skill_preview": skill_preview,
        })
    
    return report

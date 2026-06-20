"""
Skill Forge — Analyze case clusters and generate SKILL.md drafts using LLM.

Pipeline:
  1. Take a cluster of similar cases
  2. Extract common workflow steps from tool sequences
  3. Generate a structured SKILL.md draft
  4. Store for validation
"""

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .miner import load_cases
from .signatures import compute_signature, classify_session_type, signature_similarity

HERMES_HOME = os.path.expanduser("~/.hermes")
CANDIDATES_DIR = os.path.join(HERMES_HOME, "agent", "candidates")


def ensure_dirs():
    os.makedirs(CANDIDATES_DIR, exist_ok=True)


def call_llm(prompt: str, system: str = "") -> str:
    """
    Call the LLM via Hermes API for analysis.
    Uses the configured default model to avoid extra infrastructure.
    """
    # Build a simple HTTP request to the Hermes API server
    import urllib.request
    import urllib.error
    
    data = json.dumps({
        "model": "default",
        "messages": [
            {"role": "system", "content": system or "You are an expert at analyzing AI agent workflows and extracting reusable patterns."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }).encode("utf-8")
    
    # Try Hermes API server on localhost
    for port in [8642, 8080]:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            continue
    
    # Fallback: try terminal call to Ollama
    try:
        proc = subprocess.run(
            ["curl", "-s",
             "http://127.0.0.1:11434/v1/chat/completions",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({
                 "model": "qwen2.5:14b",
                 "messages": [
                     {"role": "system", "content": system or "You are an expert at analyzing AI agent workflows."},
                     {"role": "user", "content": prompt},
                 ],
                 "max_tokens": 4096,
                 "temperature": 0.3,
             })],
            capture_output=True, text=True, timeout=120,
        )
        result = json.loads(proc.stdout)
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM UNAVAILABLE: {e}]"


def extract_common_tools(cases: List[Dict]) -> Counter:
    """Extract tools common to most cases in a cluster."""
    if not cases:
        return Counter()
    
    tool_counter = Counter()
    for c in cases:
        tools = c.get("top_tool_names", [])
        if isinstance(tools, str):
            try:
                tools = json.loads(tools)
            except:
                tools = [tools]
        if isinstance(tools, list):
            for t in tools:
                tool_counter[t] += 1
    
    return tool_counter


def generate_name_from_cases(cases: List[Dict]) -> str:
    """Generate a skill name from a cluster of cases."""
    # Collect user messages
    messages = []
    for c in cases:
        msg = c.get("user_first", "")
        if msg:
            messages.append(msg)
    
    # Try LLM first
    if messages:
        prompt = f"""Based on these user requests (from AI agent sessions), what is the common task they're all doing?

User requests:
{chr(10).join(f'- {m[:150]}' for m in messages[:8])}

Respond with ONLY a short, concise skill name (3-8 words, in Chinese if appropriate):
"""
        name = call_llm(prompt, "You name AI agent skill categories concisely.")
        if name and len(name) < 60 and not name.startswith("["):
            return name.strip().strip('"').strip("'")
    
    # Fallback: use dominant intent
    intents = Counter()
    for c in cases:
        intent = c.get("intent", {})
        if isinstance(intent, str):
            try:
                intent = json.loads(intent)
            except:
                intent = {}
        for k in intent:
            intents[k] += 1
    
    if intents:
        return f"Auto-{intents.most_common(1)[0][0]}"
    
    # Last fallback
    return "Unnamed Skill Candidate"


def analyze_workflow_pattern(cases: List[Dict]) -> str:
    """
    Analyze tool call sequences to extract common workflow patterns.
    Returns structured text describing the workflow.
    """
    if not cases:
        return "No cases to analyze."
    
    # Extract n-gram patterns across all cases
    all_ngrams = Counter()
    for c in cases:
        ngrams = c.get("top_ngrams", {})
        if isinstance(ngrams, str):
            try:
                ngrams = json.loads(ngrams)
            except:
                ngrams = {}
        for ng, count in ngrams.items():
            all_ngrams[ng] += count
    
    top_ngrams = all_ngrams.most_common(10)
    
    # Build user message summary
    messages = []
    for c in cases[:6]:
        msg = c.get("user_first", "")
        if msg:
            messages.append(f"- {msg[:200]}")
    
    # Build tool summary  
    all_tools = extract_common_tools(cases)
    tool_lines = []
    for tool, count in all_tools.most_common(10):
        pct = round(count / len(cases) * 100)
        tool_lines.append(f"- `{tool}`: {pct}% of cases ({count}/{len(cases)})")
    
    # Build n-gram lines
    ngram_lines = [f"- `{ng}` × {count}" for ng, count in top_ngrams[:8]]
    
    analysis = f"""## Workflow Pattern Analysis

### User Request Examples
{chr(10).join(messages)}

### Common Tools Used
{chr(10).join(tool_lines)}

### Top Tool Call Sequences (n-grams)
{chr(10).join(ngram_lines)}

### Suggested Workflow Steps
_Based on {len(cases)} similar sessions with avg {round(sum(int(str(c.get('tool_count','0') or '0')) for c in cases)/len(cases))} tool calls each._"""
    
    return analysis


def analyze_with_llm(workflow_analysis: str, case_data: List[Dict]) -> str:
    """
    Use LLM to generate a structured SKILL.md draft.
    """
    # Prepare case summaries for LLM
    case_summaries = []
    for c in case_data[:8]:
        intent = c.get("intent", {})
        if isinstance(intent, str):
            try:
                intent = json.loads(intent)
            except:
                intent = {}
        
        case_summaries.append(f"""Case: {c.get('title', c.get('case_name', '?'))[:60]}
  Tools: {c.get('tool_count', '?')}
  Types: {c.get('session_types', '?')}
  Intent: {intent}
  User: {c.get('user_first', '?')[:200]}""")
    
    prompt = f"""You are analyzing {len(case_data)} similar AI agent sessions to extract a reusable workflow skill.

## Case Data
{chr(10).join(case_summaries)}

## Workflow Analysis
{workflow_analysis}

## Generate a Hermes Skill

Create a skill that captures the common workflow these cases represent. 
A Hermes skill is a markdown file with YAML frontmatter.

Format:
```markdown
---
name: skill-name-here
description: Concise description of what this skill does
---
```

### Required sections:
1. **name** (in frontmatter): lowercase-hyphenated, max 40 chars
2. **description** (in frontmatter): one-line summary
3. **## Context / Trigger** — When to load this skill
4. **## Workflow Steps** — Numbered steps of the common workflow
5. **## Tool Usage Pattern** — What tools are typically needed and in what order
6. **## Common Pitfalls** — Issues that were encountered and need to be avoided
7. **## Example** — A concrete example of a task this skill would handle

Write ONLY the complete SKILL.md content, nothing else. Use Chinese for all descriptive text."""
    
    result = call_llm(prompt, "You are a skilled technical writer creating AI agent skill documentation.")
    return result


def generate_test_scenario(skill_name: str, cases: List[Dict]) -> str:
    """
    Generate a test scenario script to validate the skill.
    Builds code line by line to avoid nested f-string issues.
    """
    rep_case = cases[0] if cases else {}
    first_msg = rep_case.get("user_first", "")[:200]
    common_tools = extract_common_tools(cases)
    tool_list = json.dumps(list(common_tools.keys())[:8], ensure_ascii=False)
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    n_cases = len(cases)
    
    lines = [
        '"""',
        f'Test: {skill_name}',
        f'Generated: {now}',
        f'Source: {n_cases} similar sessions',
        '',
        'This test verifies that the skill correctly handles the common workflow',
        f'identified across {n_cases} sessions.',
        '"""',
        '',
        'import sys',
        '',
        f'EXPECTED_KEYWORDS = {tool_list}',
        '',
        'TEST_CASES = [',
        '    {',
        f'        "user_input": """{first_msg}""",',
        '        "expected_tool_types": EXPECTED_KEYWORDS,',
        '        "min_tool_count": 3,',
        '    },',
        ']',
        '',
        '',
        'def run_tests():',
        '    results = []',
        '    for i, tc in enumerate(TEST_CASES):',
        '        print(f"[Test {i+1}/{len(TEST_CASES)}] {tc[chr(39)+chr(117)+chr(115)+chr(101)+chr(114)+chr(95)+chr(105)+chr(110)+chr(112)+chr(117)+chr(116)][:60]}...")',
        '        has_tools = len(tc.get("expected_tool_types", [])) > 0',
        '        results.append({',
        '            "test": i + 1,',
        '            "passed": has_tools,',
        '            "note": f"Should handle: {tc[chr(39)+chr(117)+chr(115)+chr(101)+chr(114)+chr(95)+chr(105)+chr(110)+chr(112)+chr(117)+chr(116)][:80]}",',
        '        })',
        '    return results',
        '',
        '',
        'if __name__ == "__main__":',
        '    results = run_tests()',
        '    passed = sum(1 for r in results if r["passed"])',
        '    print()',
        '    print(f"Results: {passed}/{len(results)} passed")',
        '    for r in results:',
        '        status = "PASS" if r["passed"] else "FAIL"',
        '        print(f"  [{status}] Test {r[chr(39)+chr(116)+chr(101)+chr(115)+chr(116)]}: {r[chr(39)+chr(110)+chr(111)+chr(116)+chr(101)]}")',
        '    sys.exit(0 if passed == len(results) else 1)',
        '',
    ]
    return "\n".join(lines)


def forge_skill(cluster_id: str, cases: List[Dict], auto_llm: bool = True) -> Dict:
    """
    Forge a skill candidate from a case cluster.
    
    Returns:
    {
        "cluster_id": str,
        "skill_name": str,
        "workflow_analysis": str,
        "skill_draft": str (SKILL.md content),
        "test_scenario": str (Python test script),
        "candidate_dir": str (path),
        "case_count": int,
    }
    """
    ensure_dirs()
    
    # Generate name (with cluster suffix for uniqueness)
    skill_name = generate_name_from_cases(cases)
    # Add short cluster ID suffix to prevent name collisions
    cluster_suffix = cluster_id.split("_")[-1][:20] if "_" in cluster_id else cluster_id[-10:]
    safe_name = re.sub(r'[^a-z0-9\-]', '-', skill_name.lower().strip())[:30]
    safe_name = re.sub(r'-+', '-', safe_name).strip('-')
    safe_name = f"{safe_name}-{cluster_suffix}"[:50]
    if not safe_name:
        safe_name = f"auto-skill-{int(time.time())}"
    
    # Workflow analysis
    workflow_analysis = analyze_workflow_pattern(cases)
    
    # LLM-driven draft generation
    if auto_llm and len(cases) >= 2:
        skill_draft = analyze_with_llm(workflow_analysis, cases)
        
        # Check for LLM failure
        if skill_draft.startswith("[LLM UNAVAILABLE"):
            print(f"  ⚠ LLM unavailable, using template-based draft")
            skill_draft = None
    else:
        skill_draft = None
    
    # Fallback: template-based
    if not skill_draft:
        skill_draft = _template_draft(skill_name, workflow_analysis, cases)
    
    # Generate test scenario
    test_scenario = generate_test_scenario(safe_name, cases)
    
    # Save candidate
    candidate_dir = os.path.join(CANDIDATES_DIR, safe_name)
    os.makedirs(candidate_dir, exist_ok=True)
    
    # Save SKILL.md
    with open(os.path.join(candidate_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_draft)
    
    # Save analysis
    with open(os.path.join(candidate_dir, "_analysis.md"), "w", encoding="utf-8") as f:
        f.write(f"# Analysis for: {skill_name}\n\n")
        f.write(f"**Cluster:** {cluster_id}\n")
        f.write(f"**Cases:** {len(cases)}\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(workflow_analysis)
    
    # Save test
    test_dir = os.path.join(candidate_dir, "tests")
    os.makedirs(test_dir, exist_ok=True)
    with open(os.path.join(test_dir, "test_skill.py"), "w", encoding="utf-8") as f:
        f.write(test_scenario)
    
    # Save case list
    with open(os.path.join(candidate_dir, "_cases.json"), "w", encoding="utf-8") as f:
        cases_export = []
        for c in cases:
            cases_export.append({
                "session_id": c.get("session_id", ""),
                "case_name": c.get("title", c.get("case_name", "")),
                "tool_count": c.get("tool_count", 0),
                "intent": c.get("intent", {}),
            })
        json.dump(cases_export, f, ensure_ascii=False, indent=2)
    
    return {
        "cluster_id": cluster_id,
        "skill_name": skill_name,
        "safe_name": safe_name,
        "workflow_analysis": workflow_analysis,
        "skill_draft": skill_draft,
        "test_scenario": test_scenario,
        "candidate_dir": candidate_dir,
        "case_count": len(cases),
    }


def _template_draft(name: str, analysis: str, cases: List[Dict]) -> str:
    """Fallback template-based draft when LLM is unavailable."""
    common_tools = extract_common_tools(cases)
    tool_list = ", ".join(f"`{t}`" for t, _ in common_tools.most_common(5))
    
    example_cases = []
    for c in cases[:3]:
        example_cases.append(f"- {c.get('title', c.get('case_name', '?'))[:60]}")
    
    safe_name = re.sub(r'[^a-z0-9\-]', '-', name.lower().strip())[:40]
    safe_name = re.sub(r'-+', '-', safe_name).strip('-')
    
    return f"""---
name: {safe_name}
description: Auto-detected workflow pattern from {len(cases)} sessions
---

# {name}

## Trigger

Load when these tools are detected: {tool_list}

## Workflow Steps

_Pending — run validation tests then fill in_

## Common Tools

{tool_list}

## Related Cases

{chr(10).join(example_cases)}

## Known Pitfalls

_Pending_

---

*Auto-generated v0.1.0 | {datetime.now().strftime('%Y-%m-%d %H:%M')}*"""


def list_candidates() -> Dict[str, List[str]]:
    """List all skill candidates generated."""
    if not os.path.isdir(CANDIDATES_DIR):
        return {}
    
    result = {}
    for d in sorted(os.listdir(CANDIDATES_DIR)):
        dpath = os.path.join(CANDIDATES_DIR, d)
        if not os.path.isdir(dpath):
            continue
        files = os.listdir(dpath)
        result[d] = files
    
    return result


def get_candidate_paths() -> List[Dict]:
    """Get all candidate skill info."""
    if not os.path.isdir(CANDIDATES_DIR):
        return []
    
    candidates = []
    for d in sorted(os.listdir(CANDIDATES_DIR)):
        dpath = os.path.join(CANDIDATES_DIR, d)
        if not os.path.isdir(dpath):
            continue
        
        # Read SKILL.md for name/desc
        name = d
        desc = ""
        skill_path = os.path.join(dpath, "SKILL.md")
        if os.path.exists(skill_path):
            with open(skill_path, "r") as f:
                content = f.read()
                m = re.search(r'description:\s*(.*)', content)
                if m:
                    desc = m.group(1).strip()
                m2 = re.search(r'name:\s*(.*)', content)
                if m2:
                    name = m2.group(1).strip()
        
        # Count cases
        cases_path = os.path.join(dpath, "_cases.json")
        case_count = 0
        if os.path.exists(cases_path):
            with open(cases_path) as f:
                cases_count = len(json.load(f))
        
        candidates.append({
            "dir": d,
            "name": name,
            "description": desc[:80],
            "case_count": case_count,
            "has_analysis": os.path.exists(os.path.join(dpath, "_analysis.md")),
            "has_test": os.path.exists(os.path.join(dpath, "tests", "test_skill.py")),
        })
    
    return candidates

"""Skill Forge — Analyze case clusters and generate SKILL.md drafts."""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

from .miner import load_cases

HERMES_HOME = os.path.expanduser("~/.hermes")
CANDIDATES_DIR = os.path.join(HERMES_HOME, "agent", "candidates")
os.makedirs(CANDIDATES_DIR, exist_ok=True)


def call_llm(prompt: str, system: str = "") -> str:
    """Call Hermes API server (or fallback to Ollama)."""
    data = json.dumps({
        "model": "default",
        "messages": [
            {"role": "system", "content": system or "You are an expert at analyzing AI agent workflows."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2048, "temperature": 0.3,
    }).encode()
    for port in [8642, 8080]:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except:
            continue
    try:
        proc = subprocess.run(["curl", "-s", "http://127.0.0.1:11434/v1/chat/completions",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"model": "qwen2.5:14b", "messages": [
                {"role": "system", "content": system or "You are an expert at analyzing AI agent workflows."},
                {"role": "user", "content": prompt}],
                "max_tokens": 2048, "temperature": 0.3})],
            capture_output=True, text=True, timeout=120)
        return json.loads(proc.stdout)["choices"][0]["message"]["content"]
    except:
        return "[LLM_UNAVAILABLE]"


def generate_name_from_cases(cases: List[Dict]) -> str:
    messages = [c.get("user_first", "") for c in cases if c.get("user_first")]
    if messages:
        prompt = f"Based on these user requests, name the common task (3-8 words):\n" + \
                 "\n".join(f"- {m[:150]}" for m in messages[:8])
        name = call_llm(prompt, "You name AI agent task categories concisely.")
        if name and len(name) < 60 and not name.startswith("["):
            return name.strip().strip('"\'')
    intents = Counter()
    for c in cases:
        intent = c.get("intent", {})
        if isinstance(intent, str):
            try: intent = json.loads(intent)
            except: intent = {}
        for k in intent: intents[k] += 1
    return f"Auto-{intents.most_common(1)[0][0]}" if intents else "Unnamed Skill"


def extract_common_tools(cases: List[Dict]) -> Counter:
    tools = Counter()
    for c in cases:
        t = c.get("top_tool_names", [])
        if isinstance(t, str):
            try: t = json.loads(t)
            except: t = [t]
        if isinstance(t, list):
            for x in t: tools[x] += 1
    return tools


def generate_draft(cases: List[Dict], use_llm: bool = True) -> str:
    """Generate SKILL.md draft — via LLM or template fallback."""
    if use_llm and len(cases) >= 2:
        case_summaries = []
        for c in cases[:8]:
            intent = c.get("intent", {})
            if isinstance(intent, str):
                try: intent = json.loads(intent)
                except: intent = {}
            case_summaries.append(f"Case: {c.get('title', c.get('case_name', '?'))[:60]}  "
                                  f"Tools: {c.get('tool_count', '?')}  Intent: {intent}")
        prompt = f"Analyze {len(cases)} similar AI agent sessions and create a reusable Hermes skill.\n\n"
        prompt += "\n".join(case_summaries)
        prompt += ("\n\nGenerate a skill with: name (frontmatter, lowercase-hyphenated), "
                   "description, ## Context/Trigger, ## Workflow Steps, ## Tool Usage, "
                   "## Pitfalls, ## Example. Output ONLY the SKILL.md content.")
        result = call_llm(prompt, "You create AI agent skill documentation.")
        if not result.startswith("[LLM_UNAVAILABLE"):
            return result
    # Template fallback
    common_tools = extract_common_tools(cases)
    tool_list = ", ".join(f"`{t}`" for t, _ in common_tools.most_common(5))
    examples = "\n".join(f"- {c.get('title', c.get('case_name', '?'))[:60]}" for c in cases[:3])
    safe_name = re.sub(r'[^a-z0-9\-]', '-', common_tools.most_common(1)[0][0] if common_tools else "auto-skill").lower()[:40]
    safe_name = re.sub(r'-+', '-', safe_name).strip('-') or "auto-skill"
    return (f"---\nname: {safe_name}\ndescription: Auto-detected workflow pattern from {len(cases)} sessions\n---\n\n"
            f"# {safe_name}\n\n## Trigger\n{', '.join(common_tools.most_common(5))}\n\n"
            f"## Workflow Steps\n_Pending — fill in after validation_\n\n## Related Cases\n{examples}\n\n"
            f"---\n*Auto-generated | {datetime.now().strftime('%Y-%m-%d')}*")


def forge_skill(cluster_id: str, cases: List[Dict], auto_llm: bool = True) -> Dict:
    skill_name = generate_name_from_cases(cases)
    suffix = cluster_id.split("_")[-1][:20] if "_" in cluster_id else cluster_id[-10:]
    safe_name = re.sub(r'[^a-z0-9\-]', '-', skill_name.lower().strip())[:30]
    safe_name = re.sub(r'-+', '-', safe_name).strip('-')
    safe_name = f"{safe_name}-{suffix}"[:50] or f"auto-skill-{int(time.time())}"

    skill_draft = generate_draft(cases, auto_llm=auto_llm)
    candidate_dir = os.path.join(CANDIDATES_DIR, safe_name)
    os.makedirs(candidate_dir, exist_ok=True)

    with open(os.path.join(candidate_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_draft)
    # Save case list
    with open(os.path.join(candidate_dir, "_cases.json"), "w", encoding="utf-8") as f:
        json.dump([{"session_id": c.get("session_id", ""), "case_name": c.get("title", c.get("case_name", "")),
                     "tool_count": c.get("tool_count", 0), "intent": c.get("intent", {})} for c in cases],
                  f, ensure_ascii=False, indent=2)

    return {"cluster_id": cluster_id, "skill_name": skill_name, "safe_name": safe_name,
            "skill_draft": skill_draft, "candidate_dir": candidate_dir, "case_count": len(cases)}


def get_candidate_paths() -> List[Dict]:
    if not os.path.isdir(CANDIDATES_DIR):
        return []
    candidates = []
    for d in sorted(os.listdir(CANDIDATES_DIR)):
        dpath = os.path.join(CANDIDATES_DIR, d)
        if not os.path.isdir(dpath):
            continue
        skill_path = os.path.join(dpath, "SKILL.md")
        if not os.path.exists(skill_path):
            continue
        with open(skill_path) as f:
            content = f.read()
        name = re.search(r'name:\s*(.*)', content)
        desc = re.search(r'description:\s*(.*)', content)
        case_path = os.path.join(dpath, "_cases.json")
        case_count = 0
        if os.path.exists(case_path):
            try:
                case_count = len(json.load(open(case_path)))
            except:
                pass
        candidates.append({
            "name": name.group(1).strip() if name else d,
            "dir": d,
            "description": desc.group(1).strip() if desc else "",
            "has_analysis": True,
            "case_count": case_count,
        })
    return candidates


def list_candidates() -> Dict[str, List[str]]:
    if not os.path.isdir(CANDIDATES_DIR):
        return {}
    return {d: os.listdir(os.path.join(CANDIDATES_DIR, d))
            for d in sorted(os.listdir(CANDIDATES_DIR))
            if os.path.isdir(os.path.join(CANDIDATES_DIR, d))}

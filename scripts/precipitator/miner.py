"""
Case Miner — Extract structured cases from Hermes SessionDB.

Pipeline:
  1. List all recent sessions
  2. For each complex session (≥5 tool calls, user-initiated):
     a. Compute tool call signature
     b. Extract sequence patterns (n-grams)
     c. Analyze user intent
     d. Classify session type
  3. Save as structured case file
  4. Cluster similar cases
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import VERSION
from .signatures import (
    classify_session_type,
    compute_signature,
    extract_sequence_signature,
    extract_user_intent,
    signature_similarity,
)

# ── Paths ──
HERMES_HOME = os.path.expanduser("~/.hermes")
CASES_DIR = os.path.join(HERMES_HOME, "agent", "cases")

# Tools that indicate "this was a real task with substance"
SIGNAL_TOOLS = {
    "terminal", "execute_code", "browser_navigate", "browser_click",
    "web_search", "web_extract", "patch", "cronjob", "send_message",
    "email_send", "text_to_speech", "delegate_task",
}

# Sessions to always skip
SKIP_PREFIXES = [
    "[IMPORTANT", "[CONTEXT COMPACTION", "[Replying to", "[System note",
]


def ensure_dirs():
    os.makedirs(CASES_DIR, exist_ok=True)


def get_session_db():
    """Get Hermes SessionDB instance."""
    sys.path.insert(0, os.path.join(HERMES_HOME, "hermes-agent"))
    try:
        from hermes_state import SessionDB
        return SessionDB()
    except Exception as e:
        print(f"Error loading SessionDB: {e}")
        return None


def collect_tool_calls(messages: List[Dict]) -> Tuple[List[str], List[List[str]], int]:
    """
    Collect all tool call names and sequences from messages.
    Returns (flat_names, batch_sequences, total_calls).
    """
    tool_names = []
    tool_sequences = []
    
    for m in messages:
        if m.get("role") != "assistant":
            continue
        tcs = m.get("tool_calls")
        if not tcs or not isinstance(tcs, list):
            continue
        
        batch = []
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            # OpenAI format: function.name
            name = tc.get("function", {}).get("name") or tc.get("name", "")
            if name:
                batch.append(name)
                tool_names.append(name)
        
        if batch:
            tool_sequences.append(batch)
    
    return tool_names, tool_sequences, len(tool_names)


def is_user_initiated(messages: List[Dict]) -> bool:
    """Check if this is a real user-initiated session."""
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return False
    
    for m in user_msgs[:3]:
        content = str(m.get("content", ""))
        for prefix in SKIP_PREFIXES:
            if content.startswith(prefix):
                return False
    
    # Check first real user message has substance
    first = str(user_msgs[0].get("content", ""))
    if len(first.strip()) < 10 and user_msgs[0].get("role") == "user":
        return False
    
    return True


def extract_user_messages(messages: List[Dict]) -> List[str]:
    """Extract user message contents."""
    return [
        str(m.get("content", ""))
        for m in messages
        if m.get("role") == "user"
        and str(m.get("content", "")).strip()
    ]


def generate_case_name(session_data: Dict, user_msgs: List[str], patterns: List[str], tool_names: List[str]) -> str:
    """Generate a meaningful case name."""
    # Use title if available and meaningful
    title = session_data.get("title")
    if title and title != "(no title)" and len(title) > 3:
        return title[:80]
    
    # Use first user message
    for msg in user_msgs:
        content = msg.strip()
        if len(content) > 5:
            # Clean common prefixes
            cleaned = re.sub(r'^(research|analyze|check|help|setup|install|configure)\s*', '', content)
            return cleaned[:80]
    
    # Fallback: pattern-based
    if patterns:
        p = patterns[0].replace("HEAVY_", "").replace("_", " ").strip()
        return f"{p} Task ({len(tool_names)} tools)"
    
    return f"Task ({len(tool_names)} tools)"


def analyze_session(session_data: Dict, messages: List[Dict]) -> Optional[Dict]:
    """
    Analyze a single session and extract structured case info.
    Returns None for sessions too simple or not worth casing.
    """
    sid = session_data["id"]
    
    # Skip cron/system sessions
    source = session_data.get("source", "")
    if source in ("cron", "webhook", "system"):
        return None
    
    # Collect tool calls
    tool_names, tool_sequences, tool_count = collect_tool_calls(messages)
    
    if tool_count < 5:
        return None
    
    # Check user-initiated
    if not is_user_initiated(messages):
        return None
    
    user_msgs = extract_user_messages(messages)
    
    # Compute signatures
    signature = compute_signature(tool_names)
    session_types = classify_session_type(signature, tool_count)
    sequence_patterns = extract_sequence_signature(tool_sequences)
    intent = extract_user_intent(user_msgs)
    
    # Top tools
    tool_counter = Counter(tool_names)
    top_tools = tool_counter.most_common(15)
    
    # Generate case name
    case_name = generate_case_name(session_data, user_msgs, session_types, tool_names)
    
    return {
        "session_id": sid,
        "session_source": source,
        "title": session_data.get("title", "") or "",
        "case_name": case_name,
        "tool_count": tool_count,
        "signature": signature,
        "session_types": session_types,
        "sequence_key": ">".join(sorted(signature.keys())),
        "intent": intent,
        "top_tools": top_tools,
        "top_tool_names": [t[0] for t in top_tools[:8]],
        "sequence_batches": len(tool_sequences),
        "top_ngrams": dict(Counter(sequence_patterns).most_common(10)),
        "user_first": user_msgs[0][:300] if user_msgs else "",
        "user_count": len(user_msgs),
        "analyzed_at": time.time(),
        "version": VERSION,
    }


def save_case(case: Dict):
    """Save a case as a structured markdown file."""
    ensure_dirs()
    
    # Safe filename
    safe_name = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff\-_ ]', '', case["case_name"])[:60]
    safe_name = re.sub(r'\s+', '_', safe_name.strip())[:60]
    if not safe_name:
        safe_name = "unnamed"
    date_str = datetime.fromtimestamp(case["analyzed_at"]).strftime("%Y%m%d")
    filename = f"{date_str}_{safe_name}.md"
    filepath = os.path.join(CASES_DIR, filename)
    
    intent_str = json.dumps(case.get("intent", {}), ensure_ascii=False)
    
    content = f"""---
title: "{case['case_name']}"
session_id: "{case['session_id'][:28]}"
tool_count: {case['tool_count']}
signature: {json.dumps(case['signature'])}
session_types: {json.dumps(case['session_types'])}
intent: {intent_str}
date: {datetime.fromtimestamp(case['analyzed_at']).strftime('%Y-%m-%d %H:%M')}
source: {case.get('session_source', 'unknown')}
top_tool_names: {json.dumps([t[0] for t in case.get('top_tools', [])[:8]])}
user_first: {json.dumps(case.get('user_first', '')[:200])}
status: pending
---

## Session Summary

**Title:** {case.get('title', 'N/A')}
**Source:** {case.get('session_source', 'unknown')}
**Tool calls:** {case['tool_count']} in {case['sequence_batches']} batches
**Signature:** {', '.join(f'{k}={v}' for k,v in sorted(case['signature'].items()))}
**Types:** {', '.join(case['session_types'])}

### Top Tools Used
| Tool | Count |
|:---|:---:|
"""
    for tool, count in case["top_tools"][:12]:
        content += f"| `{tool}` | {count} |\n"
    
    content += f"""
### User Intent
| Intent | Confidence |
|:---|:---:|
"""
    if case.get("intent"):
        for intent, conf in sorted(case["intent"].items(), key=lambda x: -x[1]):
            content += f"| {intent} | {conf:.0%} |\n"
    else:
        content += "| — | — |\n"
    
    content += f"""
### Top N-gram Patterns
"""
    ngrams = case.get("top_ngrams", {})
    if isinstance(ngrams, dict):
        sorted_ngrams = sorted(ngrams.items(), key=lambda x: -x[1])[:8]
        for ngram, count in sorted_ngrams:
            content += f"- `{ngram}` × {count}\n"
    
    content += f"""
### First User Message
> {case['user_first'][:300]}

---
*Auto-extracted v{case['version']} | {datetime.fromtimestamp(case['analyzed_at']).strftime('%Y-%m-%d %H:%M')}*
"""
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    return filepath


def load_cases() -> List[Dict]:
    """Load all existing case metadata from cases directory."""
    cases = []
    if not os.path.isdir(CASES_DIR):
        return cases
    
    for fname in sorted(os.listdir(CASES_DIR)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(CASES_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            raw = f.read()
        
        # Parse YAML-like frontmatter
        match = re.match(r'^---\n(.*?)\n---', raw, re.DOTALL)
        if not match:
            continue
        
        meta = {}
        for line in match.group(1).split("\n"):
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"')
            try:
                meta[key] = json.loads(val) if val.lower() in ("true", "false", "null") or val.startswith(("{", "[", '"')) else val
            except (json.JSONDecodeError, ValueError):
                meta[key] = val
        
        meta["_filename"] = fname
        cases.append(meta)
    
    return cases


def _parse_json_field(case: Dict, field: str, default=None):
    """Safely parse a JSON-encoded field from case frontmatter."""
    val = case.get(field)
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def _parse_case_name(case: Dict) -> str:
    """Extract meaningful case name from various fields."""
    for key in ["case_name", "title", "user_first"]:
        val = case.get(key, "")
        if isinstance(val, str) and len(val) > 3:
            return val[:80]
    return "(unnamed)"


def _intent_similarity(intent1: Dict, intent2: Dict) -> float:
    """Compute overlap between two intent dicts."""
    if not intent1 or not intent2:
        return 0.0
    keys1 = set(intent1.keys())
    keys2 = set(intent2.keys())
    if not keys1 or not keys2:
        return 0.0
    intersection = keys1 & keys2
    union = keys1 | keys2
    return len(intersection) / len(union) if union else 0.0


def _normalize_msg(msg: str) -> str:
    """Normalize user message for keyword matching."""
    if not msg:
        return ""
    msg = msg.lower()
    # Keep Chinese chars + alphanumeric
    msg = re.sub(r'[^a-z0-9\u4e00-\u9fff\s]', ' ', msg)
    # Remove very common words
    stopwords = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
                 "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
                 "没有", "看", "好", "自己", "这", "the", "a", "an", "is", "it",
                 "to", "and", "in", "for", "of"}
    tokens = [w for w in msg.split() if w not in stopwords and len(w) > 1]
    return " ".join(tokens)


def _keyword_similarity(msg1: str, msg2: str) -> float:
    """Compute keyword overlap between two user messages."""
    n1 = set(_normalize_msg(msg1).split())
    n2 = set(_normalize_msg(msg2).split())
    if not n1 or not n2:
        return 0.0
    intersection = n1 & n2
    union = n1 | n2
    return len(intersection) / len(union) if union else 0.0


def cluster_cases(cases: List[Dict], similarity_threshold: float = 0.45) -> Dict[str, List[Dict]]:
    """
    Multi-factor clustering:
      0.3 × signature_similarity
      0.3 × intent_similarity
      0.2 × ngram_overlap
      0.2 × keyword_similarity
    """
    if not cases:
        return {}
    
    # Pre-process all cases
    processed = []
    for c in cases:
        sig = _parse_json_field(c, "signature", {})
        intent = _parse_json_field(c, "intent", {})
        stypes = _parse_json_field(c, "session_types", [])
        ngrams = _parse_json_field(c, "top_ngrams", {})
        msg = c.get("user_first", c.get("title", "")) or ""
        
        processed.append({
            "case": c,
            "signature": sig,
            "intent": intent,
            "session_types": stypes if isinstance(stypes, list) else [stypes],
            "ngrams": set(ngrams.keys()) if isinstance(ngrams, dict) else set(),
            "message": msg,
            "name": _parse_case_name(c),
        })
    
    clusters = []
    assigned = set()
    
    for i, p1 in enumerate(processed):
        if i in assigned:
            continue
        
        cluster = [p1["case"]]
        assigned.add(i)
        
        for j, p2 in enumerate(processed):
            if j in assigned or i == j:
                continue
            
            # Multi-factor similarity
            sig_sim = signature_similarity(p1["signature"], p2["signature"])
            
            intent_sim = _intent_similarity(p1["intent"], p2["intent"])
            
            ngram_sim = 0.0
            if p1["ngrams"] and p2["ngrams"]:
                intersection = p1["ngrams"] & p2["ngrams"]
                union = p1["ngrams"] | p2["ngrams"]
                ngram_sim = len(intersection) / len(union) if union else 0.0
            
            kw_sim = _keyword_similarity(p1["message"], p2["message"])
            
            # Weighted combination
            sim = (0.30 * sig_sim + 0.30 * intent_sim + 0.20 * ngram_sim + 0.20 * kw_sim)
            
            if sim >= similarity_threshold:
                cluster.append(p2["case"])
                assigned.add(j)
        
        clusters.append(cluster)
    
    # Name clusters by dominant type + most common intent
    result = {}
    for i, cluster in enumerate(clusters):
        if not cluster:
            continue
        
        types = Counter()
        intents = Counter()
        for c in cluster:
            st = _parse_json_field(c, "session_types", [])
            if isinstance(st, list):
                for t in st:
                    types[t] += 1
            intent = _parse_json_field(c, "intent", {})
            if isinstance(intent, dict):
                for k in intent:
                    intents[k] += 1
        
        dominant_type = types.most_common(1)[0][0] if types else "UNKNOWN"
        top_intent = intents.most_common(1)[0][0] if intents else ""
        
        label = dominant_type
        if top_intent:
            label += f"_{top_intent}"
        
        cluster_id = f"cluster_{i:03d}_{label}"
        result[cluster_id] = cluster
    
    return result


def scan_sessions(limit: int = 100, scan_all: bool = False) -> List[Dict]:
    """Scan sessions and extract cases."""
    db = get_session_db()
    if not db:
        print("ERROR: Cannot access SessionDB")
        return []
    
    total = 10000 if scan_all else limit
    sessions = db.list_sessions_rich(limit=total)
    print(f"Found {len(sessions)} sessions in DB")
    
    cases = []
    skipped = {"simple": 0, "cron": 0, "no_substance": 0}
    
    for s in sessions:
        sid = s["id"]
        source = s.get("source", "")
        
        if source in ("cron", "webhook"):
            skipped["cron"] += 1
            continue
        
        msgs = db.get_messages_as_conversation(sid) or []
        case = analyze_session(s, msgs)
        
        if case is None:
            _, _, tc = collect_tool_calls(msgs)
            if tc < 5:
                skipped["simple"] += 1
            else:
                skipped["no_substance"] += 1
            continue
        
        cases.append(case)
    
    print(f"\nExtracted: {len(cases)} cases")
    print(f"Skipped: {skipped}")
    
    return cases


def save_cases(cases: List[Dict]) -> List[str]:
    """Save cases and return file paths."""
    paths = []
    for case in cases:
        path = save_case(case)
        paths.append(path)
    return paths


def get_summary(cases: List[Dict]) -> Dict:
    """Generate summary statistics."""
    if not cases:
        return {"total": 0, "by_type": {}, "by_intent": {}}
    
    by_type = Counter()
    by_intent = Counter()
    tool_counts = []
    
    for c in cases:
        types = c.get("session_types", [])
        if isinstance(types, str):
            try:
                types = json.loads(types)
            except:
                types = [types]
        for t in types:
            by_type[t] += 1
        
        intent = c.get("intent", {})
        if isinstance(intent, str):
            try:
                intent = json.loads(intent)
            except:
                intent = {}
        for k in intent:
            by_intent[k] += 1
        
        tool_counts.append(int(str(c.get("tool_count", "0") or "0")))
    
    return {
        "total": len(cases),
        "by_type": dict(by_type.most_common()),
        "by_intent": dict(by_intent.most_common()),
        "avg_tools": round(sum(tool_counts) / len(tool_counts), 1) if tool_counts else 0,
        "max_tools": max(tool_counts) if tool_counts else 0,
    }

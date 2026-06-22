"""Case Miner — Extract structured cases from Hermes SessionDB."""
import json, os, re, sys, time
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import VERSION
from .signatures import classify_session_type, compute_signature, extract_sequence_signature, extract_user_intent, signature_similarity

HERMES_HOME = os.path.expanduser("~/.hermes")
CASES_DIR = os.path.join(HERMES_HOME, "agent", "cases")
SIGNAL_TOOLS = {"terminal", "execute_code", "browser_navigate", "browser_click",
                "web_search", "web_extract", "patch", "cronjob", "send_message",
                "email_send", "text_to_speech", "delegate_task"}
SKIP_PREFIXES = ["[IMPORTANT", "[CONTEXT COMPACTION", "[Replying to", "[System note"]

os.makedirs(CASES_DIR, exist_ok=True)


def get_session_db():
    sys.path.insert(0, os.path.join(HERMES_HOME, "hermes-agent"))
    try:
        from hermes_state import SessionDB
        return SessionDB()
    except Exception as e:
        print(f"Error loading SessionDB: {e}")
        return None


def collect_tool_calls(messages: List[Dict]) -> tuple:
    tool_names, tool_sequences = [], []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        tcs = m.get("tool_calls")
        if not tcs:
            continue
        batch = []
        for tc in tcs:
            name = tc.get("function", {}).get("name") or tc.get("name", "")
            if name:
                batch.append(name)
                tool_names.append(name)
        if batch:
            tool_sequences.append(batch)
    return tool_names, tool_sequences, len(tool_names)


def is_user_initiated(messages: List[Dict]) -> bool:
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return False
    for m in user_msgs[:3]:
        content = str(m.get("content", ""))
        if any(content.startswith(p) for p in SKIP_PREFIXES):
            return False
    first = str(user_msgs[0].get("content", ""))
    return len(first.strip()) >= 10


def extract_user_messages(messages: List[Dict]) -> List[str]:
    return [str(m["content"]) for m in messages if m.get("role") == "user" and str(m.get("content", "")).strip()]


def generate_case_name(session_data: Dict, user_msgs: List[str], patterns: List[str], tool_names: List[str]) -> str:
    title = session_data.get("title")
    if title and title != "(no title)" and len(title) > 3:
        return title[:80]
    for msg in user_msgs:
        content = msg.strip()
        if len(content) > 5:
            return re.sub(r'^(research|analyze|check|help|setup|install|configure)\s*', '', content)[:80]
    p = patterns[0].replace("HEAVY_", "").replace("_", " ").strip() if patterns else "Task"
    return f"{p} ({len(tool_names)} tools)"


def analyze_session(session_data: Dict, messages: List[Dict]) -> Optional[Dict]:
    sid = session_data["id"]
    source = session_data.get("source", "")
    if source in ("cron", "webhook", "system"):
        return None
    tool_names, tool_sequences, tool_count = collect_tool_calls(messages)
    if tool_count < 5 or not is_user_initiated(messages):
        return None
    user_msgs = extract_user_messages(messages)
    signature = compute_signature(tool_names)
    session_types = classify_session_type(signature, tool_count)
    sequence_patterns = extract_sequence_signature(tool_sequences)
    intent = extract_user_intent(user_msgs)
    top_tools = Counter(tool_names).most_common(15)
    return {
        "session_id": sid,
        "session_source": source,
        "title": session_data.get("title", ""),
        "case_name": generate_case_name(session_data, user_msgs, session_types, tool_names),
        "tool_count": tool_count,
        "signature": signature,
        "session_types": session_types,
        "sequence_key": ">".join(sorted(signature)),
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


def save_case(case: Dict) -> str:
    safe_name = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff\-_ ]', '', case["case_name"])[:60]
    safe_name = re.sub(r'\s+', '_', safe_name.strip())[:60]
    if not safe_name:
        safe_name = "unnamed"
    date_str = datetime.fromtimestamp(case["analyzed_at"]).strftime("%Y%m%d")
    filepath = os.path.join(CASES_DIR, f"{date_str}_{safe_name}.md")
    content = (
        f"---\ntitle: \"{case['case_name']}\"\nsession_id: \"{case['session_id'][:28]}\"\n"
        f"tool_count: {case['tool_count']}\nsignature: {json.dumps(case['signature'])}\n"
        f"session_types: {json.dumps(case['session_types'])}\n"
        f"intent: {json.dumps(case.get('intent', {}))}\n"
        f"date: {datetime.fromtimestamp(case['analyzed_at']).strftime('%Y-%m-%d %H:%M')}\n"
        f"source: {case.get('session_source', 'unknown')}\n"
        f"top_tool_names: {json.dumps([t[0] for t in case.get('top_tools', [])[:8]])}\n"
        f"user_first: {json.dumps(case.get('user_first', '')[:200])}\n"
        f"status: pending\n---\n\n"
        f"## Session\n**Title:** {case.get('title', 'N/A')}  \n"
        f"**Tools:** {case['tool_count']} in {case['sequence_batches']} batches  \n"
        f"**Signature:** {', '.join(f'{k}={v}' for k,v in sorted(case['signature'].items()))}  "
        f"**Types:** {', '.join(case['session_types'])}\n\n"
    )
    for tool, count in case["top_tools"][:12]:
        content += f"- `{tool}` × {count}\n"
    content += "\n*Auto-extracted v{} | {}*".format(case['version'],
        datetime.fromtimestamp(case['analyzed_at']).strftime('%Y-%m-%d %H:%M'))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def load_cases() -> List[Dict]:
    cases = []
    if not os.path.isdir(CASES_DIR):
        return cases
    for fname in sorted(os.listdir(CASES_DIR)):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(CASES_DIR, fname), encoding="utf-8") as f:
            raw = f.read()
        m = re.match(r'^---\n(.*?)\n---', raw, re.DOTALL)
        if not m:
            continue
        meta = {"_filename": fname}
        for line in m.group(1).split("\n"):
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip().strip('"')
            try:
                meta[k] = json.loads(v) if v.lower() in ("true", "false", "null") or v.startswith(("{", "[")) else v
            except (json.JSONDecodeError, ValueError):
                meta[k] = v
        cases.append(meta)
    return cases


def _keyword_overlap(msg1: str, msg2: str) -> float:
    """Simple keyword overlap between two messages."""
    def tokens(s):
        s = re.sub(r'[^a-z0-9\u4e00-\u9fff\s]', ' ', s.lower())
        stopwords = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
                     "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
                     "没有", "看", "好", "自己", "这", "the", "a", "an", "is", "it",
                     "to", "and", "in", "for", "of", "at", "on"}
        return {w for w in s.split() if w not in stopwords and len(w) > 1}
    n1, n2 = tokens(msg1), tokens(msg2)
    if not n1 or not n2:
        return 0.0
    return len(n1 & n2) / len(n1 | n2)


def cluster_cases(cases: List[Dict], threshold: float = 0.45) -> Dict[str, List[Dict]]:
    """Multi-factor clustering: signature + intent + keyword overlap."""
    if not cases:
        return {}
    processed = []
    for c in cases:
        sig = c.get("signature", {})
        if isinstance(sig, str):
            try: sig = json.loads(sig)
            except: sig = {}
        intent = c.get("intent", {})
        if isinstance(intent, str):
            try: intent = json.loads(intent)
            except: intent = {}
        msg = c.get("user_first", c.get("title", "")) or ""
        processed.append({"case": c, "signature": sig, "intent": intent, "message": msg,
                          "name": c.get("case_name", c.get("title", "(unnamed)"))[:80]})
    clusters, assigned = [], set()
    for i, p1 in enumerate(processed):
        if i in assigned:
            continue
        cluster = [p1["case"]]
        assigned.add(i)
        for j, p2 in enumerate(processed):
            if j in assigned:
                continue
            sig_sim = signature_similarity(p1["signature"], p2["signature"])
            intent_sim = (len(set(p1["intent"]) & set(p2["intent"])) /
                          len(set(p1["intent"]) | set(p2["intent"]))) if p1["intent"] and p2["intent"] else 0.0
            kw_sim = _keyword_overlap(p1["message"], p2["message"])
            if 0.35 * sig_sim + 0.35 * intent_sim + 0.30 * kw_sim >= threshold:
                cluster.append(p2["case"])
                assigned.add(j)
        clusters.append(cluster)
    result = {}
    for i, cluster in enumerate(clusters):
        if not cluster:
            continue
        types, intents = Counter(), Counter()
        for c in cluster:
            st = c.get("session_types", [])
            if isinstance(st, str):
                try: st = json.loads(st)
                except: st = [st]
            if isinstance(st, list):
                for t in st: types[t] += 1
            intent = c.get("intent", {})
            if isinstance(intent, str):
                try: intent = json.loads(intent)
                except: intent = {}
            for k in intent: intents[k] += 1
        dt = types.most_common(1)[0][0] if types else "UNKNOWN"
        ti = intents.most_common(1)[0][0] if intents else ""
        result[f"cluster_{i:03d}_{dt}_{ti}" if ti else f"cluster_{i:03d}_{dt}"] = cluster
    return result


def get_summary(cases: List[Dict]) -> Dict:
    if not cases:
        return {"total": 0, "avg_tools": 0, "max_tools": 0, "by_type": {}, "by_intent": {}}
    tools = [int(c.get("tool_count", 0)) for c in cases]
    types = Counter()
    intents = Counter()
    for c in cases:
        st = c.get("session_types", [])
        if isinstance(st, str):
            try: st = json.loads(st)
            except: st = [st]
        if isinstance(st, list):
            for t in st: types[t] += 1
        intent = c.get("intent", {})
        if isinstance(intent, str):
            try: intent = json.loads(intent)
            except: intent = {}
        for k in intent: intents[k] += 1
    return {"total": len(cases), "avg_tools": sum(tools) / len(tools), "max_tools": max(tools),
            "by_type": dict(types.most_common(10)), "by_intent": dict(intents.most_common(10))}


def scan_sessions(limit: int = 100, scan_all: bool = False) -> List[Dict]:
    db = get_session_db()
    if not db:
        return []
    sessions = db.list_sessions_rich(limit=10000 if scan_all else limit)
    print(f"Found {len(sessions)} sessions")
    cases = []
    for s in sessions:
        sid, source = s["id"], s.get("source", "")
        if source in ("cron", "webhook"):
            continue
        msgs = (db.get_messages_as_conversation(sid) or [])
        if len([m for m in msgs if m.get("role") == "assistant"]) > 0 and \
           len([m for m in msgs if m.get("role") == "user"]) > 0:
            case = analyze_session(s, msgs)
            if case:
                cases.append(case)
    return cases

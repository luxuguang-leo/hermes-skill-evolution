"""Tool call signature system — session pattern detection engine."""
from collections import Counter
from typing import Dict, List

# Tool → category: prefix-based for grouped tools, exact match for the rest
TOOL_CATEGORIES = {
    "terminal": "SHELL",
    "execute_code": "CODE",
    "read_file": "FILE",
    "write_file": "FILE",
    "patch": "FILE",
    "search_files": "FILE",
    "cronjob": "CRON",
    "email_send": "EMAIL",
    "email_search": "EMAIL",
    "text_to_speech": "MEDIA",
    "vision_analyze": "VISION",
    "send_message": "NOTIFY",
    "skill_view": "SKILL",
    "skill_manage": "SKILL",
    "memory": "MEMORY",
    "delegate_task": "DELEGATE",
}

# Prefix catch-all for browser_*, web_* tools
TOOL_PREFIXES = {"browser_": "BROWSER", "web_": "WEB"}

# Intent keywords: {intent: [keywords]}
INTENT_SIGNALS = {
    "install-setup": ["安装", "配置", "部署", "下载", "install", "setup", "deploy", "configure"],
    "research": ["研究", "分析", "调研", "research", "analyze", "investigate", "study", "what is", "how does"],
    "fix-debug": ["修复", "修", "坏", "bug", "错误", "fix", "debug", "error", "broken", "not working", "issue"],
    "create-generate": ["生成", "创建", "写", "create", "generate", "write", "make", "build", "draft"],
    "search-find": ["搜索", "找", "查找", "search", "find", "look for", "locate"],
    "monitor-check": ["检查", "看下", "监控", "check", "monitor", "verify", "status", "validate"],
    "download-media": ["下载", "download", "youtube", "video", "audio", "media"],
    "query-info": ["多少", "什么", "谁", "什么时候", "where", "what", "how", "when", "which", "tell me about"],
}


def classify_tool(name: str) -> str:
    for prefix, cat in TOOL_PREFIXES.items():
        if name.startswith(prefix):
            return cat
    return TOOL_CATEGORIES.get(name, "OTHER")


def compute_signature(tool_names: List[str]) -> Dict[str, float]:
    """Compute {category: proportion} from tool calls. Proportions sum to 1.0."""
    if not tool_names:
        return {}
    cats = Counter(classify_tool(n) for n in tool_names)
    total = sum(cats.values())
    return {c: round(n / total, 3) for c, n in cats.most_common()}


def classify_session_type(signature: Dict[str, float], tool_count: int) -> List[str]:
    if not signature or tool_count == 0:
        return ["UNKNOWN"]
    types = []
    sorted_cats = sorted(signature.items(), key=lambda x: -x[1])
    for cat, prop in sorted_cats:
        if prop >= 0.35:
            types.append(f"HEAVY_{cat}")
        elif prop >= 0.20:
            types.append(f"_{cat}")
    if sum(1 for _, p in sorted_cats if p >= 0.10) >= 3:
        types.append("HYBRID")
    if tool_count >= 30:
        types.append("COMPLEX")
    elif tool_count >= 15:
        types.append("MEDIUM")
    return types if types else ["UNKNOWN"]


def signature_similarity(sig1: Dict[str, float], sig2: Dict[str, float]) -> float:
    """Cosine similarity between two signatures."""
    all_cats = set(sig1) | set(sig2)
    dot = sum(sig1.get(c, 0) * sig2.get(c, 0) for c in all_cats)
    n1 = sum(v * v for v in sig1.values()) ** 0.5
    n2 = sum(v * v for v in sig2.values()) ** 0.5
    return dot / (n1 * n2) if n1 and n2 else 0.0


def extract_sequence_signature(tool_sequences: List[List[str]], max_ngram: int = 3) -> Dict[str, int]:
    """Extract n-gram patterns from tool call sequences (e.g. SHELL>SHELL>FILE)."""
    classified = []
    for batch in tool_sequences:
        for tool in batch:
            classified.append(classify_tool(tool))
    patterns = Counter()
    for c in classified:
        patterns[c] += 1
    for i in range(len(classified) - 1):
        patterns[f"{classified[i]}>{classified[i+1]}"] += 1
    for i in range(len(classified) - 2):
        patterns[f"{classified[i]}>{classified[i+1]}>{classified[i+2]}"] += 1
    return dict(patterns)


def extract_user_intent(user_messages: List[str]) -> Dict[str, float]:
    """Returns {intent: confidence} from first user message."""
    if not user_messages:
        return {}
    first = user_messages[0].lower() if user_messages else ""
    intents = {}
    for intent, keywords in INTENT_SIGNALS.items():
        found = sum(1 for kw in keywords if kw in first)
        if found:
            intents[intent] = min(found / 3.0, 1.0)
    return intents

"""
Tool call signature system — the core pattern detection engine.

Instead of keyword matching, we classify sessions by their tool call *signature*:
what types of tools are used, in what proportions, and in what sequences.

Signature types (a session can have multiple):
  SHELL_HEAVY    — mostly terminal commands
  BROWSER        — browser_navigate + browser_click for interaction
  CODE_EXEC      — execute_code for programmatic work
  WEB_RESEARCH   — web_search + web_extract pairs
  FILE_OPS       — read/write/patch cycles
  MULTI_MODEL    — skill_view + multiple provider calls
  CRON_SETUP     — cronjob tool used
  EMAIL          — email send/search
  MEDIA_DOWNLOAD — youtube/media download
  NOTIFICATION   — send_message to platforms
  HYBRID         — 3+ signature types
"""

from collections import Counter
from typing import Dict, List, Tuple

# Tool categories
TOOL_CATEGORIES = {
    # Shell/terminal operations
    "terminal": "SHELL",
    # Browser interactions
    "browser_navigate": "BROWSER",
    "browser_click": "BROWSER",
    "browser_type": "BROWSER",
    "browser_snapshot": "BROWSER",
    "browser_vision": "BROWSER_VISION",
    "browser_scroll": "BROWSER",
    # Code execution
    "execute_code": "CODE",
    # Web research
    "web_search": "WEB",
    "web_extract": "WEB",
    "web_scrape": "WEB",
    # File operations
    "read_file": "FILE",
    "write_file": "FILE",
    "patch": "FILE",
    "search_files": "FILE",
    # Cron jobs
    "cronjob": "CRON",
    # Email
    "email_send": "EMAIL",
    "email_search": "EMAIL",
    # Media
    "text_to_speech": "MEDIA",
    "vision_analyze": "VISION",
    # Messaging
    "send_message": "NOTIFY",
    # Skills/memory
    "skill_view": "SKILL",
    "skill_manage": "SKILL",
    "memory": "MEMORY",
    # Browser support
    "browser_get_images": "BROWSER",
    "browser_press": "BROWSER",
    "browser_back": "BROWSER",
    "browser_console": "BROWSER",
    # Delegation
    "delegate_task": "DELEGATE",
}


def classify_tool(name: str) -> str:
    """Classify a single tool call into a category."""
    return TOOL_CATEGORIES.get(name, "OTHER")


def compute_signature(tool_names: List[str]) -> Dict[str, float]:
    """
    Compute the tool call signature for a session.
    
    Returns a dict of {category: proportion} where proportions sum to 1.0.
    For example: {"SHELL": 0.45, "BROWSER": 0.30, "FILE": 0.15, "OTHER": 0.10}
    """
    if not tool_names:
        return {}
    
    categories = Counter()
    for name in tool_names:
        categories[classify_tool(name)] += 1
    
    total = sum(categories.values())
    return {cat: round(count / total, 3) for cat, count in categories.most_common()}


def classify_session_type(signature: Dict[str, float], tool_count: int) -> List[str]:
    """
    Classify session type (can be multiple) from signature proportions.
    """
    if not signature or tool_count == 0:
        return ["UNKNOWN"]
    
    types = []
    
    # Get the dominant categories (top 2 by proportion)
    sorted_cats = sorted(signature.items(), key=lambda x: -x[1])
    
    for cat, prop in sorted_cats:
        if prop >= 0.35:
            types.append(f"HEAVY_{cat}")
        elif prop >= 0.20:
            types.append(f"_{cat}")
    
    # Add hybrid label for diverse sessions
    significant_cats = [c for c, p in sorted_cats if p >= 0.10]
    if len(significant_cats) >= 3:
        types.append("HYBRID")
    
    # Add complexity label
    if tool_count >= 30:
        types.append("COMPLEX")
    elif tool_count >= 15:
        types.append("MEDIUM")
    
    return types if types else ["UNKNOWN"]


def signature_similarity(sig1: Dict[str, float], sig2: Dict[str, float]) -> float:
    """
    Compute cosine similarity between two signatures.
    Two sessions with similar tool usage patterns are likely doing similar things.
    """
    all_cats = set(sig1.keys()) | set(sig2.keys())
    
    dot_product = 0.0
    norm1 = 0.0
    norm2 = 0.0
    
    for cat in all_cats:
        v1 = sig1.get(cat, 0.0)
        v2 = sig2.get(cat, 0.0)
        dot_product += v1 * v2
        norm1 += v1 * v1
        norm2 += v2 * v2
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / ((norm1 ** 0.5) * (norm2 ** 0.5))


def extract_sequence_signature(tool_sequences: List[List[str]], max_ngram: int = 3) -> Dict[str, int]:
    """
    Extract n-gram patterns from tool call sequences.
    This captures "what tools are called in sequence" — the real workflow pattern.
    
    For example: ["terminal", "terminal", "patch"] → "SHELL>SHELL>FILE"
    """
    from collections import defaultdict
    
    # Flatten and classify
    classified = []
    for batch in tool_sequences:
        for tool in batch:
            classified.append(classify_tool(tool))
    
    patterns = defaultdict(int)
    
    # Unigrams
    for c in classified:
        patterns[c] += 1
    
    # Bigrams
    for i in range(len(classified) - 1):
        bigram = f"{classified[i]}>{classified[i+1]}"
        patterns[bigram] += 1
    
    # Trigrams
    for i in range(len(classified) - 2):
        trigram = f"{classified[i]}>{classified[i+1]}>{classified[i+2]}"
        patterns[trigram] += 1
    
    return dict(patterns)


def extract_user_intent(user_messages: List[str]) -> Dict[str, float]:
    """
    Extract intent keywords from user messages.
    Returns {intent_category: confidence}
    """
    if not user_messages:
        return {}
    
    first_msg = user_messages[0].lower() if user_messages else ""
    
    intent_signals = {
        "install-setup": ["安装", "配置", "部署", "下载", "install", "setup", "deploy", "setup", "configure", "install"],
        "research": ["研究", "分析", "调研", "research", "analyze", "investigate", "study", "what is", "how does"],
        "fix-debug": ["修复", "修", "坏", "bug", "错误", "fix", "debug", "error", "broken", "not working", "issue"],
        "create-generate": ["生成", "创建", "写", "create", "generate", "write", "make", "build", "draft"],
        "search-find": ["搜索", "找", "查找", "search", "find", "look for", "locate", "where is"],
        "monitor-check": ["检查", "看下", "监控", "check", "monitor", "verify", "status", "validate"],
        "download-media": ["下载", "download", "youtube", "video", "audio", "media", "get"],
        "plan-orgnize": ["规划", "计划", "安排", "整理", "plan", "organize", "list", "prepare", "arrange", "schedule"],
        "query-info": ["多少", "什么", "谁", "什么时候", "where", "what", "how", "when", "which", "tell me about"],
    }
    
    intents = {}
    for intent, keywords in intent_signals.items():
        found = sum(1 for kw in keywords if kw in first_msg)
        if found > 0:
            intents[intent] = min(found / 3.0, 1.0)
    
    return intents

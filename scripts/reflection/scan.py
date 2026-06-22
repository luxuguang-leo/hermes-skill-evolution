#!/usr/bin/env python3
"""
Hermes Reflection — Phase 1: Scan
====================================
Idle-time memory consolidation scanner.
Scans sessions, skills, kanban, and memory to produce a weekly health report.

Usage:
    python3 ~/.hermes/scripts/reflection_scan.py
    python3 ~/.hermes/scripts/reflection_scan.py --days 14
    python3 ~/.hermes/scripts/reflection_scan.py --json-only
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
SESSIONS_DIR = HERMES_HOME / "sessions"
SKILLS_DIR = HERMES_HOME / "skills"
MEMORIES_DIR = HERMES_HOME / "memories"
REFLECTION_DIR = HERMES_HOME / "reflection"
# Kanban DB could be at legacy flat path or in boards subdirectory
KANBAN_DB_FLAT = HERMES_HOME / "kanban.db"
KANBAN_BOARDS_DIR = HERMES_HOME / "kanban" / "boards"
SOUL_FILE = HERMES_HOME / "SOUL.md"
MEMORY_FILE = MEMORIES_DIR / "memory.md"
USER_FILE = MEMORIES_DIR / "user.md"

REFLECTION_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ─────────────────────────────────────────────────────────────────

def now():
    return datetime.now(timezone.utc)

def days_ago(n):
    return now() - timedelta(days=n)

def human_size(n):
    if n < 1000:
        return f"{n} B"
    elif n < 1_000_000:
        return f"{n/1000:.1f} KB"
    else:
        return f"{n/1_000_000:.1f} MB"

def read_file_safe(path):
    """Read a file safely, return empty string on error."""
    try:
        if path.exists() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 1. Session Scan
# ═══════════════════════════════════════════════════════════════════════════

def scan_sessions(lookback_days=7):
    """Scan session files.
    - Recent window (lookback_days): counts, source breakdown
    - All sessions: keyword analysis (to catch cross-week patterns)
    """
    cutoff = days_ago(lookback_days)
    recent_sessions = []
    all_keywords = Counter()
    source_counts = Counter()
    
    if not SESSIONS_DIR.exists():
        return {"total": 0, "sources": {}, "top_keywords": [], "sessions": []}
    
    EN_STOP = {"the", "you", "not", "use", "this", "that", "are", "was", "for",
               "and", "but", "has", "have", "been", "all", "can", "will", "get",
               "with", "from", "your", "its", "may", "also", "each", "set", "key",
               "value", "name", "type", "file", "path", "data", "text", "mode",
               "size", "line", "code", "any", "out", "new", "one", "two", "runs",
               "returns", "require", "required", "requires", "string", "number",
               "default", "true", "false", "none", "null", "bool", "int", "str",
               "list", "dict", "class", "self", "main", "init", "test", "format",
               "based", "made", "done", "used", "valid", "count", "total", "base",
               "info", "show", "open", "help", "need", "make", "part", "print",
               "other", "some", "much", "than", "over", "into", "only", "when",
               "what", "which", "their", "them", "these", "those", "while",
               "where", "here", "there", "well", "back", "call", "such", "more",
               "very", "just", "like", "know", "take", "look", "find", "work",
               "want", "tell", "think", "ask", "try", "put", "let", "give",
               "results", "contain", "containing", "specified", "specifies",
               "follow", "following", "indicates", "indicate", "enable",
               }
    
    def extract_keywords(text, counter):
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        en_words = re.findall(r'\b[A-Z][a-zA-Z0-9_-]{2,}\b', text)
        for w in cn_words + en_words:
            kw = w.lower().strip()
            if len(kw) >= 2 and kw not in EN_STOP and not kw.isdigit():
                counter[kw] += 1
    
    for f in sorted(SESSIONS_DIR.glob("session_*.json"), reverse=True):
        m = re.match(r"session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", f.name)
        if not m:
            continue
        
        try:
            file_dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                               int(m.group(4)), int(m.group(5)), int(m.group(6)),
                               tzinfo=timezone.utc)
        except ValueError:
            continue
        
        is_recent = file_dt >= cutoff
        
        # Determine source
        source = "chat"
        if "cron" in f.name:
            source = "cron"
        elif "api" in f.name:
            source = "api"
        
        # Read session file content
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                raw = fh.read(100000)
            data = json.loads(raw)
            text = json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, Exception):
            text = ""
        
        # Always extract keywords (all-time, for cross-week patterns)
        extract_keywords(text, all_keywords)
        
        # Recent window stats only
        if is_recent:
            source_counts[source] += 1
            recent_sessions.append({
                "file": f.name,
                "date": file_dt.strftime("%Y-%m-%d %H:%M"),
                "source": source,
                "size_bytes": len(text),
            })
    
    return {
        "recent_total": len(recent_sessions),
        "recent_days": lookback_days,
        "sources": dict(source_counts),
        "top_keywords": [{"word": w, "count": c} for w, c in all_keywords.most_common(20) if c >= 3],
        "sessions": recent_sessions[:50],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. Skill Audit
# ═══════════════════════════════════════════════════════════════════════════

def scan_skills():
    """Audit all installed skills for usage frequency and staleness.
    Walks category subdirectories recursively."""
    if not SKILLS_DIR.exists():
        return {"total": 0, "zombie": [], "skills": []}
    
    skills = []
    now_ts = time.time()
    
    # Walk recursively through category subdirectories
    for skill_dir in sorted(SKILLS_DIR.rglob("*")):
        if not skill_dir.is_dir():
            continue
        sk_file = skill_dir / "SKILL.md"
        if not sk_file.exists():
            continue
        
        # Use the last directory component as the skill name
        name = skill_dir.name
        
        # Get last modified time
        mtime = sk_file.stat().st_mtime
        last_modified_days = (now_ts - mtime) / 86400
        
        # Estimate size
        size = len(sk_file.read_text(encoding="utf-8", errors="replace"))
        
        # Staleness: 60+ days without modification
        # (30 days is too aggressive — many skills are intentionally static docs)
        is_zombie = last_modified_days > 60
        
        skills.append({
            "name": name,
            "category": skill_dir.parent.name if skill_dir.parent != SKILLS_DIR else "",
            "path": str(skill_dir),
            "size": size,
            "size_human": human_size(size),
            "last_modified_days": round(last_modified_days, 1),
            "is_zombie": is_zombie,
        })
    
    zombies = [s for s in skills if s["is_zombie"]]
    
    return {
        "total": len(skills),
        "zombie_count": len(zombies),
        "total_size": sum(s["size"] for s in skills),
        "zombies": zombies,
        "skills": skills,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. Kanban Check
# ═══════════════════════════════════════════════════════════════════════════

def scan_kanban():
    """Check Kanban DB for stuck or long-running tasks.
    Looks in boards subdirectory first, then legacy flat path."""
    # Find all kanban DBs in boards subdirectory
    board_dbs = []
    if KANBAN_BOARDS_DIR.exists():
        board_dbs.extend(KANBAN_BOARDS_DIR.rglob("kanban.db"))
    if KANBAN_DB_FLAT.exists():
        board_dbs.append(KANBAN_DB_FLAT)
    
    if not board_dbs:
        return {"status": "no_kanban_db", "total": 0, "stuck": [], "boards": []}
    
    all_boards = []
    all_tasks = []
    stuck_tasks = []
    
    for db_path in board_dbs:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            
            # Each DB file represents one board.
            # Board name comes from the parent directory slug.
            board_slug = db_path.parent.name
            board_name = board_slug.replace("-", " ").title()
            
            all_boards.append({
                "name": board_name,
                "slug": board_slug,
                "db_path": str(db_path),
            })
            
            # Tasks table uses integer epoch timestamps, not ISO strings
            cursor = conn.execute(
                "SELECT id, title, status, created_at, started_at, "
                "completed_at, assignee FROM tasks"
            )
            for row in cursor.fetchall():
                task = dict(row)
                task["board"] = board_name
                
                status = task.get("status", "")
                if status in ("running", "blocked", "in_progress", "ready"):
                    started = task.get("started_at") or task.get("created_at")
                    if started and isinstance(started, (int, float)):
                        age_hours = (time.time() - started) / 3600
                        if age_hours > 24:
                            task["stuck_hours"] = round(age_hours, 1)
                            stuck_tasks.append(task)
            conn.close()
        except (sqlite3.Error, Exception) as e:
            print(f"  ⚠️ Kanban DB error ({db_path}): {e}", flush=True)
    
    return {
        "status": "ok",
        "total_boards": len(all_boards),
        "active_tasks": len(all_tasks),
        "stuck_count": len(stuck_tasks),
        "boards": all_boards,
        "stuck": stuck_tasks,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. Memory Water Level
# ═══════════════════════════════════════════════════════════════════════════

def scan_memory():
    """Check memory and user profile file sizes vs limits."""
    result = {}
    
    # MEMORY.md
    mem_content = read_file_safe(MEMORY_FILE)
    mem_len = len(mem_content)
    result["memory"] = {
        "path": str(MEMORY_FILE),
        "size": mem_len,
        "size_human": human_size(mem_len),
        "limit": 2200,
        "usage_pct": round(mem_len / 2200 * 100, 1) if mem_len > 0 else 0,
        "is_near_limit": mem_len > 1800,
    }
    
    # USER.md
    user_content = read_file_safe(USER_FILE)
    user_len = len(user_content)
    result["user_profile"] = {
        "path": str(USER_FILE),
        "size": user_len,
        "size_human": human_size(user_len),
        "limit": 1375,
        "usage_pct": round(user_len / 1375 * 100, 1) if user_len > 0 else 0,
        "is_near_limit": user_len > 1100,
    }
    
    # SOUL.md
    soul_content = read_file_safe(SOUL_FILE)
    soul_len = len(soul_content)
    result["soul"] = {
        "path": str(SOUL_FILE),
        "size": soul_len,
        "size_human": human_size(soul_len),
        "line_count": soul_content.count("\n") + 1 if soul_content else 0,
        "recommended_max": 6000,  # ~80 lines
        "is_within_range": soul_len <= 6000,
    }
    
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 5. Pattern Detection (simple keyword clustering)
# ═══════════════════════════════════════════════════════════════════════════

def detect_patterns(session_data, skill_data):
    """Detect recurring patterns from session keywords and other signals."""
    patterns = []
    
    # Pattern 1: Topics appearing across ALL sessions (cross-week detection)
    if session_data.get("top_keywords"):
        freq_words = [k["word"] for k in session_data["top_keywords"] if k["count"] >= 5]
        if len(freq_words) >= 3:
            patterns.append({
                "type": "recurring_topic",
                "confidence": "medium",
                "signal": f"关键词 '{', '.join(freq_words[:5])}' 出现在多个 session 中",
                "suggestion": "考虑将这些主题封装为 skill 或更新 SOUL.md Mission",
                "keywords": freq_words[:5],
            })
    
    # Pattern 2: Zombie skills
    if skill_data.get("zombie_count", 0) > 0:
        zombie_names = [s["name"] for s in skill_data["zombies"][:5]]
        patterns.append({
            "type": "zombie_skills",
            "confidence": "high",
            "signal": f"有 {skill_data['zombie_count']} 个 skill 超过60天未修改",
            "suggestion": f"用 Curator 检查或清理: {', '.join(zombie_names[:3])}",
            "skills": zombie_names,
        })
    
    # Pattern 3: Memory near limit
    # Detected in scan_memory(), reported separately
    
    return patterns


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def run_scan(lookback_days=7):
    """Run the full Phase 1 scan and return results."""
    print(f"🔍 Hermes Reflection Phase 1 — Scan ({now().strftime('%Y-%m-%d %H:%M')})")
    print(f"   看板: {lookback_days} 天\n")
    
    # 1. Session scan
    print("  📋 Session scan...", end=" ", flush=True)
    sessions = scan_sessions(lookback_days)
    print(f"{sessions['recent_total']} recent sessions, {len(sessions['top_keywords'])} all-time keywords")
    
    # 2. Skill audit
    print("  📦 Skill audit...", end=" ", flush=True)
    skills = scan_skills()
    print(f"{skills['total']} skills, {skills['zombie_count']} zombies")
    
    # 3. Kanban check
    print("  📋 Kanban check...", end=" ", flush=True)
    kanban = scan_kanban()
    if kanban.get("status") == "ok":
        print(f"{kanban['total_boards']} boards, {kanban['stuck_count']} stuck tasks")
    else:
        print(f"{kanban.get('status', 'error')}")
    
    # 4. Memory water level
    print("  💾 Memory check...", end=" ", flush=True)
    memory = scan_memory()
    mem_pct = memory["memory"]["usage_pct"]
    user_pct = memory["user_profile"]["usage_pct"]
    print(f"MEMORY {mem_pct}%, USER {user_pct}%")
    
    # 5. Pattern detection
    print("  🔄 Pattern detection...", end=" ", flush=True)
    patterns = detect_patterns(sessions, skills)
    print(f"{len(patterns)} patterns found\n")
    
    # Compile report
    report = {
        "scan_time": now().isoformat(),
        "lookback_days": lookback_days,
        "sessions": sessions,
        "skills": skills,
        "kanban": kanban,
        "memory": memory,
        "patterns": patterns,
    }
    
    # Save report
    report_file = REFLECTION_DIR / "scan-report.json"
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"  💾 Report saved: {report_file}")
    
    return report


def format_summary(report):
    """Format the report into a human-readable summary."""
    lines = []
    s = report["sessions"]
    sk = report["skills"]
    kb = report["kanban"]
    mem = report["memory"]
    pat = report["patterns"]
    
    lines.append(f"🧠 Reflection Report — {now().strftime('%Y-%m-%d')}")
    # Format summary
    s = report["sessions"]
    
    lines.append(f"📊 扫描统计")
    lines.append(f"  近{s['recent_days']}天会话: {s['recent_total']} 个")
    for src, count in sorted(s["sources"].items()):
        lines.append(f"    - {src}: {count}")
    if s["top_keywords"]:
        kw = ", ".join(f"{k['word']}({k['count']})" for k in s["top_keywords"][:8])
        lines.append(f"  全量高频关键词: {kw}")
    
    lines.append("")
    
    # 📦 Skills
    lines.append("📦 Skill 审计")
    lines.append(f"  总数: {sk['total']} | 僵尸: {sk['zombie_count']}")
    if sk.get("zombies"):
        for z in sk["zombies"][:5]:
            cat = f" ({z['category']})" if z.get("category") else ""
            lines.append(f"    ⚰️ {z['name']}{cat} — {z['last_modified_days']}天未修改")
        if len(sk["zombies"]) > 5:
            lines.append(f"    ... 还有 {len(sk['zombies']) - 5} 个")
    # Show category breakdown
    cat_counts = Counter(s.get("category", "") for s in sk.get("skills", []))
    lines.append(f"  分类: {', '.join(f'{k}:{v}' for k, v in sorted(cat_counts.items()) if k)}")
    
    lines.append("")
    
    # 📋 Kanban
    lines.append("📋 Kanban 看板")
    if kb.get("status") == "ok":
        lines.append(f"  看板数: {kb['total_boards']}")
        for b in kb.get("boards", []):
            lines.append(f"    {b['name']} ({b['slug']})")
        if kb["stuck_count"] > 0:
            lines.append(f"  ⏳ 卡住的任务: {kb['stuck_count']}")
            for t in kb["stuck"][:3]:
                lines.append(f"    ⏳ {t['title']} ({t['stuck_hours']}h)")
    else:
        lines.append(f"  {kb.get('status', 'N/A')}")
    
    lines.append("")
    
    # 💾 Memory
    lines.append("💾 记忆水位")
    lines.append(f"  MEMORY.md: {mem['memory']['size_human']} (每条目上限2.2KB)")
    if mem["memory"]["is_near_limit"]:
        lines.append("    ⚠️ 接近条目上限，建议压缩")
    lines.append(f"  USER.md: {mem['user_profile']['size_human']} (每条目上限1.4KB)")
    if mem["user_profile"]["is_near_limit"]:
        lines.append("    ⚠️ 接近条目上限，建议压缩")
    lines.append(f"  SOUL.md: {mem['soul']['line_count']} 行 / {mem['soul']['size_human']}")
    
    lines.append("")
    
    # 🔄 Patterns
    if pat:
        lines.append("🔄 检测到的模式")
        for p in pat:
            icon = {"recurring_topic": "🔄", "zombie_skills": "⚰️"}.get(p["type"], "📌")
            lines.append(f"  {icon} [{p['confidence']}] {p['signal']}")
            lines.append(f"    建议: {p['suggestion']}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Reflection Phase 1 — Scan")
    parser.add_argument("--days", type=int, default=7, help="Session lookback days")
    parser.add_argument("--json-only", action="store_true", help="Only output JSON report")
    args = parser.parse_args()
    
    report = run_scan(lookback_days=args.days)
    
    if args.json_only:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n" + "=" * 50)
        print(format_summary(report))

"""
Presenter — Generate human-readable reports and handle user approval flow.
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List

from .validator import get_report_data

HERMES_HOME = os.path.expanduser("~/.hermes")
CANDIDATES_DIR = os.path.join(HERMES_HOME, "agent", "candidates")


def generate_report_html() -> str:
    """Generate an HTML report of all skill candidates."""
    data = get_report_data()
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Skill Precipitator Report</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #0d1117; color: #c9d1d9; }}
h1 {{ color: #58a6ff; }}
.candidate {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin: 16px 0; }}
.candidate h2 {{ margin: 0 0 8px; color: #f0f6fc; }}
.meta {{ color: #8b949e; font-size: 0.9em; margin-bottom: 12px; }}
pre {{ background: #0d1117; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 0.85em; border: 1px solid #30363d; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; margin: 2px; }}
.tag-llm {{ background: #1f6feb33; color: #58a6ff; }}
.tag-template {{ background: #d2992233; color: #d29922; }}
.tag-verified {{ background: #23863633; color: #3fb950; }}
</style></head><body>
<h1>🔬 Skill Precipitator Report</h1>
<p>Generated: {data['generated_at']} | Total candidates: {data['total_candidates']}</p>
"""
    
    for c in data["candidates"]:
        tag_class = "tag-llm" if c.get("has_analysis") else "tag-template"
        tag_text = "LLM" if c.get("has_analysis") else "Template"
        
        html += f"""
<div class="candidate">
<h2>{c['name']}</h2>
<div class="meta">
  <span class="tag {tag_class}">{tag_text}</span>
  <span>{c['case_count']} cases</span>
  <span>| dir: {c['dir']}</span>
</div>
<pre>{c['skill_preview'][:600]}</pre>
</div>"""
    
    html += "</body></html>"
    return html


def generate_report_markdown() -> str:
    """Generate a markdown report for console output."""
    data = get_report_data()
    
    md = f"# 🔬 Skill Precipitator Report\n\n"
    md += f"**Generated:** {data['generated_at']}  \n"
    md += f"**Candidates:** {data['total_candidates']}\n\n"
    
    if not data["candidates"]:
        md += "_No candidates yet. Run scan first._\n"
        return md
    
    for i, c in enumerate(data["candidates"], 1):
        source = "🤖 LLM-generated" if c.get("has_analysis") else "📋 Template"
        md += f"### {i}. {c['name']} {source}\n\n"
        md += f"- **Description:** {c.get('description', '—')}\n"
        md += f"- **Source cases:** {c['case_count']} sessions\\n"
        md += f"- **Directory:** `{c['dir']}`\n"
        
        if c.get("analysis_preview"):
            preview_lines = c["analysis_preview"].splitlines()[:5]
            md += f"- **Analysis preview:**\n"
            for line in preview_lines:
                if line.strip():
                    md += f"  > {line.strip()[:100]}\n"
        
        md += "\n"
    
    md += "---\n"
    md += f"*Run `skill_precipitator.py --candidate <name>` to view details*\n"
    md += f"*Run `skill_precipitator.py --install <name>` to install as skill*\n"
    
    return md


def present_summary(candidates: List[Dict]) -> str:
    """Present a compact summary of what was found."""
    if not candidates:
        return "No precipitable patterns found."
    
    lines = []
    lines.append(f"## Found {len(candidates)} Skill Candidates\\n")
    
    for i, c in enumerate(candidates, 1):
        lines.append(f"### {i}. {c['skill_name']}")
        lines.append(f"  - Source: {c['case_count']} similar sessions")
        lines.append(f"  - Dir: `~/.hermes/agent/candidates/{c['safe_name']}/`")
        lines.append("")
    
    return "\n".join(lines)

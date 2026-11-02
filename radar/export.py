"""Export the radar dataset as an Obsidian-friendly Markdown note."""
from __future__ import annotations

import os
import re
from typing import Any

from .util import local_date, parse_datetime, utcnow

MARKER_START = "<!-- tech-radar:start -->"
MARKER_END = "<!-- tech-radar:end -->"
_WIKI_UNSAFE = re.compile(r"[\[\]|#^]")


def _safe_wiki(text: str) -> str:
    return _WIKI_UNSAFE.sub(" ", text or "").strip()


def _cell(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _link(title: str, url: str) -> str:
    return f"[{_cell(title)}]({url})"


def _difficulty(value: Any) -> str:
    try:
        level = max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return ""
    return "★" * level + "☆" * (5 - level)


def _item_line(item: dict[str, Any]) -> str:
    source = item.get("source_name", "")
    return f"- {_link(item.get('title', ''), item.get('url', ''))} · {_cell(source)}"


def build_markdown(dataset: dict[str, Any], date_str: str) -> str:
    stats = dataset.get("stats", {})
    items = dataset.get("items", [])
    tiers = stats.get("by_tier", {})

    lines: list[str] = []
    lines.append(f"# 技术雷达 {date_str}")
    lines.append("")
    lines.append("> 自动生成。只保存标题、摘要与链接，引用请回源。")
    lines.append("")
    lines.append("## 本期概览")
    lines.append("")
    lines.append("| 指标 | 数量 |")
    lines.append("|---|---|")
    lines.append(f"| 条目 | {stats.get('total_items', 0)} |")
    lines.append(f"| 官方动态 | {tiers.get('official', 0)} |")
    lines.append(f"| GitHub 趋势 | {tiers.get('github', 0)} |")
    lines.append(f"| 学习精选 | {tiers.get('learning', 0)} |")
    lines.append(f"| 知识卡片 | {stats.get('knowledge_cards', 0)} |")
    lines.append(f"| 源健康 | {stats.get('sources_ok', 0)}/{stats.get('sources_total', 0)} |")
    lines.append("")

    cards = [item for item in items if item.get("knowledge") and item["knowledge"].get("concept")]
    if cards:
        lines.append("## 知识卡片")
        lines.append("")
        for item in cards:
            knowledge = item["knowledge"]
            concept = _safe_wiki(knowledge.get("concept", "未命名概念"))
            lines.append(f"### [[{concept}]]")
            if knowledge.get("one_liner"):
                lines.append(f"- 一句话：{knowledge['one_liner']}")
            if knowledge.get("why_it_matters"):
                lines.append(f"- 为什么重要：{knowledge['why_it_matters']}")
            path = knowledge.get("learning_path") or []
            if isinstance(path, list) and path:
                lines.append("- 学习路径：" + " → ".join(str(step) for step in path))
            difficulty = _difficulty(knowledge.get("difficulty"))
            if difficulty:
                lines.append(f"- 难度：{difficulty}")
            lines.append(f"- 来源：{_link(item.get('title', ''), item.get('url', ''))} · {_cell(item.get('source_name', ''))}")
            lines.append("")

    sections = [
        ("official", "官方动态"),
        ("github", "GitHub 趋势"),
        ("learning", "学习精选"),
    ]
    for tier, title in sections:
        subset = [item for item in items if item.get("tier") == tier][:12]
        lines.append(f"## {title}")
        lines.append("")
        if not subset:
            lines.append("今日无重大动态。")
        else:
            lines.extend(_item_line(item) for item in subset)
        lines.append("")

    errors = [row for row in dataset.get("health", []) if row.get("status") == "error"]
    lines.append("## 源健康")
    lines.append("")
    if not errors:
        lines.append("全部源正常。")
    else:
        for row in errors:
            lines.append(f"- {_cell(row.get('source_name', ''))}：{_cell(row.get('error', ''))[:180]}")
    lines.append("")

    return "\n".join(lines)


def export_markdown(
    dataset: dict[str, Any],
    out_dir: str,
    date_str: str | None = None,
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or dataset.get("generated_at") or utcnow().isoformat()
    if not date_str:
        tz_name = dataset.get("settings", {}).get("timezone", "Asia/Shanghai")
        date_str = local_date(tz_name, parse_datetime(generated_at))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{date_str}-技术雷达.md")
    block = f"{MARKER_START}\n{build_markdown(dataset, date_str)}\n{MARKER_END}"

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            existing = fh.read()
        if MARKER_START in existing and MARKER_END in existing:
            pattern = re.compile(
                re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
                re.DOTALL,
            )
            updated = pattern.sub(block, existing)
        else:
            updated = existing.rstrip() + "\n\n" + block + "\n"
    else:
        frontmatter = "\n".join([
            "---",
            f"title: 技术雷达 {date_str}",
            f"date: {date_str}",
            "tags:",
            "  - AI工具雷达",
            "  - 技术雷达",
            "source: tech-radar",
            f"generated_at: {generated_at}",
            "---",
            "",
        ])
        updated = frontmatter + block + "\n"

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(updated)
    return path


def summarize_for_console(path: str) -> str:
    return f"exported: {path}"

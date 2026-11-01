"""LLM summarization with a deterministic fallback and an on-disk cache."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import requests

from .models import Item
from .util import load_json, save_json, truncate

PROMPT_VERSION = "v1"
DEFAULT_SYSTEM_PROMPT = """你是技术雷达编辑，服务对象是中文 Java/全栈开发者，关注 AI 应用开发与工程实践。
请对输入的每条技术更新输出中文分析。只输出 JSON 数组，不要 Markdown、不要解释。
每个元素的字段：
- id: 原样返回输入 id
- summary: 一句话中文摘要，不超过 60 字
- why: 为什么值得看，1-2 句，具体说明对开发者的影响
- knowledge: 对象或 null。仅当这条内容包含可复用的知识点时才填写：
  - concept: 知识点名称
  - one_liner: 一句话解释
  - why_it_matters: 为什么重要
  - learning_path: 2-3 步学习/实践路径
  - difficulty: 1-5 的整数
不要编造输入中没有的事实；不确定就写得保守。"""


def _cache_key(item: Item) -> str:
    payload = f"{PROMPT_VERSION}\x1f{item.title}\x1f{item.url}".encode("utf-8", "ignore")
    return hashlib.sha1(payload).hexdigest()


def _fallback(item: Item) -> dict[str, Any]:
    raw = item.summary_raw.strip()
    summary = truncate(raw, 160) if raw else truncate(item.title, 160)
    if item.tier == "official":
        why = "官方发布/变更，直接影响你正在使用的工具或平台。"
    elif item.tier == "github":
        stars = (item.extra or {}).get("stars")
        stars_today = (item.extra or {}).get("stars_today")
        if stars:
            why = f"GitHub 热度项目（约 {stars} stars），值得看它的实现思路或生态影响。"
        elif stars_today:
            why = f"今日新增约 {stars_today} stars，属于正在升温的项目。"
        else:
            why = "GitHub 趋势项目，值得关注其用途和维护状态。"
    else:
        why = "高质量学习材料，适合补充知识体系或用作实践参考。"
    return {"summary": summary, "why": why, "knowledge": None}


class LLMClient:
    def __init__(self, llm_settings: dict[str, Any]):
        self.settings = llm_settings or {}
        self.provider = (os.environ.get("LLM_PROVIDER") or self.settings.get("provider") or "deepseek").lower()
        self.model = self.settings.get("model") or "deepseek-chat"
        self.base_url = os.environ.get("LLM_BASE_URL") or self.settings.get("base_url") or ""
        self.api_key = ""
        if self.provider == "deepseek":
            self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            self.model = os.environ.get("DEEPSEEK_MODEL") or self.model
            self.base_url = self.base_url or "https://api.deepseek.com"
        elif self.provider in {"ark", "volcengine", "doubao"}:
            self.api_key = os.environ.get("ARK_API_KEY", "")
            self.model = os.environ.get("ARK_MODEL", "")
            self.base_url = self.base_url or "https://ark.cn-beijing.volces.com/api/v3"
        else:
            self.api_key = ""

    @property
    def available(self) -> bool:
        return bool(self.settings.get("enabled", True) and self.api_key and self.base_url and self.model)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 2200,
        }
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=int(self.settings.get("timeout_seconds", 60)),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _batch_prompt(batch: list[Item]) -> str:
    rows = []
    for item in batch:
        rows.append({
            "id": item.id,
            "title": item.title,
            "source": item.source_name,
            "tier": item.tier,
            "published_at": item.published_at,
            "tags": item.tags,
            "summary": truncate(item.summary_raw, 600),
            "url": item.url,
            "stars": (item.extra or {}).get("stars"),
        })
    return json.dumps(rows, ensure_ascii=False, indent=2)


def summarize_items(items: list[Item], llm_settings: dict[str, Any], cache_path: str) -> dict[str, Any]:
    """Fill summary/why/knowledge for the highest-scoring items. Never raises."""
    stats = {"provider": None, "model": None, "calls": 0, "hits": 0, "fallbacks": 0, "errors": []}
    cache = load_json(cache_path, {})
    client = LLMClient(llm_settings)
    stats["provider"] = client.provider
    stats["model"] = client.model if client.available else None
    if not client.settings.get("enabled", True):
        stats["errors"].append("LLM disabled")

    max_items = int(llm_settings.get("max_items", 30))
    min_score = float(llm_settings.get("min_score", 35))
    batch_size = max(1, int(llm_settings.get("batch_size", 8)))
    candidates = [
        item for item in sorted(items, key=lambda i: i.score, reverse=True)
        if item.score >= min_score
    ][:max_items]
    candidate_ids = {item.id for item in candidates}

    for item in items:
        if (item.extra or {}).get("carried_forward") and item.summary:
            stats["hits"] += 1
            continue
        if item.id not in candidate_ids:
            result = _fallback(item)
            item.summary = result["summary"]
            item.why = result["why"]
            item.knowledge = result["knowledge"]
            stats["fallbacks"] += 1
            continue
        cached = cache.get(_cache_key(item))
        if cached:
            item.summary = cached.get("summary") or _fallback(item)["summary"]
            item.why = cached.get("why") or _fallback(item)["why"]
            item.knowledge = cached.get("knowledge")
            stats["hits"] += 1

    pending = [item for item in candidates if not cache.get(_cache_key(item))]
    if pending and not client.available:
        if client.settings.get("enabled", True):
            stats["errors"].append("LLM unavailable: missing API key/provider config")
        for item in pending:
            result = _fallback(item)
            item.summary = result["summary"]
            item.why = result["why"]
            item.knowledge = result["knowledge"]
            stats["fallbacks"] += 1
        save_json(cache_path, cache)
        return stats

    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        try:
            content = client.complete(DEFAULT_SYSTEM_PROMPT, _batch_prompt(batch))
            stats["calls"] += 1
            parsed = {row.get("id"): row for row in _parse_json_array(content) if isinstance(row, dict)}
        except Exception as exc:
            stats["errors"].append(f"{type(exc).__name__}: {exc}")
            parsed = {}

        for item in batch:
            row = parsed.get(item.id)
            if row and isinstance(row.get("summary"), str) and row.get("summary").strip():
                result = {
                    "summary": truncate(row["summary"].strip(), 200),
                    "why": truncate(str(row.get("why") or "").strip(), 300),
                    "knowledge": row.get("knowledge") if isinstance(row.get("knowledge"), dict) else None,
                }
            else:
                result = _fallback(item)
                stats["fallbacks"] += 1
            item.summary = result["summary"]
            item.why = result["why"]
            item.knowledge = result["knowledge"]
            cache[_cache_key(item)] = result

    save_json(cache_path, cache)
    return stats

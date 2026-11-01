"""Persistence: state files, dataset snapshots, and static site assembly."""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from typing import Any

from .models import Item, SourceHealth, item_from_dict
from .util import iso, load_json, parse_datetime, save_json, url_key, utcnow

OUTPUT_VERSION = 1


def state_paths(data_dir: str) -> dict[str, str]:
    state_dir = os.path.join(data_dir, "state")
    return {
        "state_dir": state_dir,
        "monitors": os.path.join(state_dir, "monitors.json"),
        "stars": os.path.join(state_dir, "stars.json"),
        "llm_cache": os.path.join(state_dir, "llm_cache.json"),
    }


def load_state(data_dir: str) -> dict[str, Any]:
    paths = state_paths(data_dir)
    return {
        "monitors": load_json(paths["monitors"], {}),
        "stars": load_json(paths["stars"], {}),
        "llm_cache_path": paths["llm_cache"],
    }


def save_state(data_dir: str, state: dict[str, Any]) -> None:
    paths = state_paths(data_dir)
    save_json(paths["monitors"], state.get("monitors", {}))
    save_json(paths["stars"], state.get("stars", {}))


def _dataset_stats(items: list[Item], healths: list[SourceHealth], llm_stats: dict[str, Any]) -> dict[str, Any]:
    by_tier = {"official": 0, "github": 0, "learning": 0}
    for item in items:
        if item.tier in by_tier:
            by_tier[item.tier] += 1
    ok = sum(1 for h in healths if h.status in {"ok", "baseline"})
    return {
        "total_items": len(items),
        "by_tier": by_tier,
        "knowledge_cards": sum(1 for item in items if item.knowledge),
        "clusters": len({item.cluster_id for item in items if item.cluster_id}),
        "sources_total": len(healths),
        "sources_ok": ok,
        "sources_error": sum(1 for h in healths if h.status == "error"),
        "sources_baseline": sum(1 for h in healths if h.status == "baseline"),
        "llm": llm_stats,
    }


def write_dataset(
    data_dir: str,
    items: list[Item],
    healths: list[SourceHealth],
    llm_stats: dict[str, Any],
    config: dict[str, Any],
    demo: bool = False,
) -> dict[str, Any]:
    items = sorted(items, key=lambda i: (i.score, i.published_at), reverse=True)
    generated_at = iso()
    dataset = {
        "version": OUTPUT_VERSION,
        "generated_at": generated_at,
        "demo": demo,
        "settings": {
            "timezone": config.get("settings", {}).get("timezone", "Asia/Shanghai"),
            "window_hours": config.get("settings", {}).get("window_hours", 168),
        },
        "stats": _dataset_stats(items, healths, llm_stats),
        "health": [h.to_dict() for h in healths],
        "items": [item.to_dict() for item in items],
    }
    save_json(os.path.join(data_dir, "items.json"), dataset)

    history_dir = os.path.join(data_dir, "history")
    today = utcnow().strftime("%Y-%m-%d")
    snapshot = {
        "date": today,
        "generated_at": generated_at,
        "stats": dataset["stats"],
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "tier": item.tier,
                "source_name": item.source_name,
                "published_at": item.published_at,
                "score": item.score,
                "tags": item.tags,
            }
            for item in items[:300]
        ],
    }
    save_json(os.path.join(history_dir, f"{today}.json"), snapshot)
    index_path = os.path.join(history_dir, "index.json")
    index = load_json(index_path, [])
    if not isinstance(index, list):
        index = []
    index = [row for row in index if row.get("date") != today]
    index.append({
        "date": today,
        "generated_at": generated_at,
        "total_items": dataset["stats"]["total_items"],
        "knowledge_cards": dataset["stats"]["knowledge_cards"],
    })
    index = sorted(index, key=lambda row: row.get("date", ""))
    save_json(index_path, index)
    _prune_history(history_dir, index, days=180)
    return dataset


def _prune_history(history_dir: str, index: list[dict[str, Any]], days: int) -> None:
    cutoff = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    keep: list[dict[str, Any]] = []
    for row in index:
        date = row.get("date", "")
        path = os.path.join(history_dir, f"{date}.json")
        if date and date < cutoff and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        elif date:
            keep.append(row)
    if len(keep) != len(index):
        save_json(os.path.join(history_dir, "index.json"), keep)


def build_public(data_dir: str, web_dir: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(web_dir):
        src = os.path.join(web_dir, name)
        dst = os.path.join(out_dir, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    data_out = os.path.join(out_dir, "data")
    os.makedirs(data_out, exist_ok=True)
    shutil.copy2(os.path.join(data_dir, "items.json"), os.path.join(data_out, "items.json"))
    history_src = os.path.join(data_dir, "history")
    if os.path.isdir(history_src):
        shutil.copytree(history_src, os.path.join(data_out, "history"), dirs_exist_ok=True)
    with open(os.path.join(out_dir, ".nojekyll"), "w", encoding="utf-8") as fh:
        fh.write("")
    return out_dir


def read_dataset(data_dir: str) -> dict[str, Any]:
    return load_json(os.path.join(data_dir, "items.json"), {"items": [], "health": [], "stats": {}})


def carry_forward_failed_sources(
    items: list[Item],
    healths: list[SourceHealth],
    data_dir: str,
    window_hours: int,
) -> tuple[list[Item], int]:
    """Keep the last good items for sources that failed on this run.

    A transient timeout should not silently remove a source from the dashboard.
    The health tab still shows the error, and cards are marked as cached.
    """
    failed = {health.source_id for health in healths if health.status == "error"}
    if not failed:
        return items, 0
    previous = read_dataset(data_dir)
    cutoff = utcnow() - timedelta(hours=window_hours)
    seen_ids = {item.id for item in items}
    seen_urls = {url_key(item.url) for item in items}
    carried: list[Item] = []
    for row in previous.get("items", []):
        if row.get("source_id") not in failed:
            continue
        published = parse_datetime(row.get("published_at"))
        if published < cutoff:
            continue
        if row.get("id") in seen_ids or url_key(row.get("url", "")) in seen_urls:
            continue
        item = item_from_dict(row)
        item.extra = dict(item.extra or {})
        item.extra["carried_forward"] = True
        carried.append(item)
        seen_ids.add(item.id)
        seen_urls.add(url_key(item.url))
    return items + carried, len(carried)

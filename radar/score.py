"""Scoring and trend helpers."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import Item
from .util import parse_datetime, utcnow

LEARNING_KEYWORDS = {
    "tutorial", "guide", "how to", "explained", "explain", "architecture",
    "design", "best practice", "benchmark", "deep dive", "internals", "spec",
    "protocol", "pattern", "原理", "详解", "实践", "架构", "设计", "教程",
    "入门", "深入", "源码", "实战", "面试", "知识",
}


def recency_score(published_at: str, now: datetime, half_life_hours: float) -> float:
    published = parse_datetime(published_at)
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    return max(0.0, min(1.0, math.exp(-math.log(2) * age_hours / max(1.0, half_life_hours))))


def momentum_score(item: Item) -> float:
    extra = item.extra or {}
    signals: list[float] = []
    stars = extra.get("stars")
    if isinstance(stars, (int, float)) and stars > 0:
        signals.append(min(1.0, math.log10(stars + 1) / 4.5))
    stars_today = extra.get("stars_today")
    if isinstance(stars_today, (int, float)) and stars_today > 0:
        signals.append(min(1.0, stars_today / 300))
    delta = extra.get("star_delta_7d")
    if isinstance(delta, (int, float)) and delta > 0:
        signals.append(min(1.0, delta / 500))
    points = extra.get("hn_points")
    if isinstance(points, (int, float)) and points > 0:
        signals.append(min(1.0, points / 300))
    return max(signals) if signals else 0.45


def learning_score(item: Item) -> float:
    text = " ".join([item.title, item.summary_raw, " ".join(item.tags)]).lower()
    hits = sum(1 for keyword in LEARNING_KEYWORDS if keyword in text)
    if hits >= 3:
        return 1.0
    if hits == 2:
        return 0.85
    if hits == 1:
        return 0.7
    return 0.5


def score_item(item: Item, settings: dict[str, Any], now: datetime) -> float:
    scoring = settings.get("scoring", {})
    source_weight = float((item.extra or {}).get("source_weight", 3)) / 5.0
    recency = recency_score(
        item.published_at,
        now,
        float(scoring.get("recency_half_life_hours", 36)),
    )
    if (item.extra or {}).get("future_timestamp"):
        # A clamped future timestamp must not rank like a fresh item.
        recency *= 0.3
    momentum = momentum_score(item)
    learning = learning_score(item)
    score = (
        float(scoring.get("source", 0.35)) * source_weight
        + float(scoring.get("recency", 0.30)) * recency
        + float(scoring.get("momentum", 0.20)) * momentum
        + float(scoring.get("learning", 0.15)) * learning
    )
    item.score = round(score * 100, 1)
    return item.score


def apply_scores(items: list[Item], settings: dict[str, Any]) -> None:
    now = utcnow()
    for item in items:
        score_item(item, settings, now)
    apply_source_diversity(items, settings)


def apply_source_diversity(items: list[Item], settings: dict[str, Any]) -> None:
    """Keep one prolific feed from occupying the whole top of the radar."""
    diversity = settings.get("diversity", {})
    top_per_source = int(diversity.get("top_per_source", 2))
    decay = float(diversity.get("decay", 0.94))
    by_source: dict[str, list[Item]] = {}
    for item in items:
        by_source.setdefault(item.source_id, []).append(item)
    for source_items in by_source.values():
        source_items.sort(key=lambda i: i.score, reverse=True)
        for index, item in enumerate(source_items):
            if index >= top_per_source:
                steps = 1 + (index - top_per_source) // 2
                item.score = round(item.score * (decay ** steps), 1)


def filter_window(items: list[Item], window_hours: int) -> list[Item]:
    cutoff = utcnow() - timedelta(hours=window_hours)
    kept: list[Item] = []
    for item in items:
        published = parse_datetime(item.published_at)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published >= cutoff:
            kept.append(item)
    return kept


def update_star_history(items: list[Item], state: dict[str, Any]) -> None:
    """Record daily GitHub star counts and compute a 7-day delta when possible."""
    today = utcnow().strftime("%Y-%m-%d")
    for item in items:
        repo = (item.extra or {}).get("full_name") or (item.extra or {}).get("repo")
        stars = (item.extra or {}).get("stars")
        if not repo or not isinstance(stars, (int, float)):
            continue
        history = state.get(repo, [])
        if not isinstance(history, list):
            history = []
        if history and history[-1].get("date") == today:
            history[-1]["stars"] = int(stars)
        else:
            history.append({"date": today, "stars": int(stars)})
        history = history[-90:]
        state[repo] = history

        cutoff = (utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        baseline = None
        for entry in history:
            if entry.get("date", "") <= cutoff:
                baseline = entry
        if baseline:
            item.extra["star_delta_7d"] = int(stars) - int(baseline.get("stars", stars))

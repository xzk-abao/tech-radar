"""Source fetchers: RSS/Atom, GitHub API, GitHub Trending, HTML change monitors."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import feedparser
import requests
from bs4 import BeautifulSoup

from .models import Item, SourceHealth
from .util import (
    clean_text,
    iso,
    parse_datetime,
    stable_id,
    truncate,
    utcnow,
)

DEFAULT_TIMEOUT = 15
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0 Safari/537.36"
)
GITHUB_API = "https://api.github.com"
MONITOR_STATE_FILE = "monitors.json"


def _headers(url: str) -> dict[str, str]:
    headers = {"User-Agent": BROWSER_UA, "Accept": "application/rss+xml, application/atom+xml, text/html;q=0.9, */*;q=0.8"}
    if url.startswith(GITHUB_API):
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[requests.Response | None, str, int]:
    started = time.monotonic()
    try:
        resp = requests.get(url, headers=_headers(url), timeout=timeout)
        latency = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 400:
            return resp, f"HTTP {resp.status_code}", latency
        return resp, "", latency
    except requests.RequestException as exc:
        latency = int((time.monotonic() - started) * 1000)
        return None, f"{type(exc).__name__}: {exc}", latency


def _entry_datetime(entry: Any, source: dict[str, Any] | None = None) -> str:
    """Normalize an entry timestamp; some feeds mislabel local time as GMT."""
    offset = timedelta(hours=float((source or {}).get("timezone_offset_hours", 0)))
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return iso(parse_datetime(value) + offset)
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            return iso(parse_datetime(value) + offset)
    return iso()


def _mark_stale_if_needed(health: SourceHealth, items: list[Item], settings: dict[str, Any]) -> None:
    """Flag a reachable source whose newest item is outside the retention window."""
    if health.status != "ok" or not items:
        return
    window_hours = int(settings.get("window_hours", 720))
    cutoff = utcnow() - timedelta(hours=window_hours)
    newest = max(parse_datetime(item.published_at) for item in items)
    if newest < cutoff:
        note = f"no items within {window_hours}h window; latest {iso(newest)}"
        health.status = "stale"
        health.error = truncate(f"{health.error}; {note}" if health.error else note, 300)


def _feed_item(entry: Any, source: dict[str, Any]) -> Item | None:
    title = clean_text(entry.get("title", ""), 300)
    link = entry.get("link") or ""
    if not link:
        for candidate in entry.get("links", []) or []:
            if candidate.get("href"):
                link = candidate["href"]
                break
    if not title or not link:
        return None
    raw = entry.get("summary") or entry.get("description") or ""
    if not raw and entry.get("content"):
        try:
            raw = entry["content"][0].get("value", "")
        except (IndexError, AttributeError, TypeError):
            raw = ""
    tags = [clean_text(t.get("term", ""), 40) for t in (entry.get("tags") or []) if t.get("term")]
    published_at = _entry_datetime(entry, source)
    return Item(
        id=stable_id(source["id"], link, title),
        source_id=source["id"],
        source_name=source["name"],
        tier=source["tier"],
        title=title,
        url=link,
        published_at=published_at,
        summary_raw=clean_text(raw, 800),
        tags=tags[:8] + [t for t in source.get("tags", []) if t not in tags][:8],
        extra={"author": clean_text(entry.get("author", ""), 80)},
        fetched_at=iso(),
    )


def fetch_feed(source: dict[str, Any], settings: dict[str, Any]) -> tuple[list[Item], SourceHealth]:
    health = SourceHealth(
        source_id=source["id"], source_name=source["name"], tier=source["tier"],
        checked_at=iso(),
    )
    resp, error, latency = _get(source["url"], int(settings.get("timeout_seconds", DEFAULT_TIMEOUT)))
    health.latency_ms = latency
    health.http_status = resp.status_code if resp is not None else None
    if error:
        health.status = "error"
        health.error = error
        return [], health

    feed = feedparser.parse(resp.content)
    if feed.bozo and not getattr(feed, "entries", None):
        health.status = "error"
        health.error = f"feed parse error: {truncate(str(getattr(feed, 'bozo_exception', '')), 160)}"
        return [], health

    limit = int(settings.get("max_items_per_source", 20))
    items = [item for item in (_feed_item(e, source) for e in feed.entries[:limit]) if item]
    health.status = "ok"
    health.items = len(items)
    health.last_item_at = max((i.published_at for i in items), default=None)
    _mark_stale_if_needed(health, items, settings)
    return items, health


def _github_search_items(source: dict[str, Any], settings: dict[str, Any]) -> tuple[list[Item], SourceHealth]:
    health = SourceHealth(
        source_id=source["id"], source_name=source["name"], tier=source["tier"],
        checked_at=iso(),
    )
    date_7d = (utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    per_page = int(settings.get("github_search_per_page", 10))
    seen: set[str] = set()
    items: list[Item] = []
    errors: list[str] = []
    latency_total = 0

    for query in source.get("queries", []):
        q = query.replace("{date_7d}", date_7d)
        url = f"{GITHUB_API}/search/repositories?q={quote(q)}&sort=stars&order=desc&per_page={per_page}"
        resp, error, latency = _get(url, 20)
        latency_total += latency
        if error:
            errors.append(f"{q}: {error}")
            continue
        try:
            payload = resp.json()
        except ValueError:
            errors.append(f"{q}: invalid JSON")
            continue
        for repo in payload.get("items", []):
            full_name = repo.get("full_name")
            if not full_name or full_name in seen:
                continue
            if repo.get("fork") or repo.get("archived"):
                continue
            if int(repo.get("stargazers_count") or 0) < 30:
                continue
            if not _repo_relevant(repo):
                continue
            seen.add(full_name)
            description = clean_text(repo.get("description") or "", 500)
            topics = repo.get("topics") or []
            items.append(Item(
                id=stable_id(source["id"], full_name),
                source_id=source["id"],
                source_name=source["name"],
                tier=source["tier"],
                title=full_name,
                url=repo.get("html_url") or f"https://github.com/{full_name}",
                published_at=iso(parse_datetime(repo.get("created_at"))),
                summary_raw=description,
                tags=list(dict.fromkeys(topics[:8] + [t for t in source.get("tags", [])])),
                extra={
                    "full_name": full_name,
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "language": repo.get("language"),
                    "topics": topics,
                    "query": q,
                },
                fetched_at=iso(),
            ))

    health.latency_ms = latency_total
    health.http_status = 200 if items or not errors else 500
    health.items = len(items)
    if items:
        health.status = "ok"
        health.last_item_at = max((i.published_at for i in items), default=None)
        if errors:
            health.error = truncate("; ".join(errors), 300)
        _mark_stale_if_needed(health, items, settings)
    else:
        health.status = "error"
        health.error = truncate("; ".join(errors) or "no items", 300)
    return items, health


def _github_watchlist_items(source: dict[str, Any], settings: dict[str, Any]) -> tuple[list[Item], SourceHealth]:
    health = SourceHealth(
        source_id=source["id"], source_name=source["name"], tier=source["tier"],
        checked_at=iso(),
    )
    items: list[Item] = []
    errors: list[str] = []
    latency_total = 0

    for repo in source.get("repos", []):
        url = f"{GITHUB_API}/repos/{repo}/releases?per_page=3"
        resp, error, latency = _get(url, 20)
        latency_total += latency
        if error:
            errors.append(f"{repo}: {error}")
            continue
        try:
            releases = resp.json()
        except ValueError:
            errors.append(f"{repo}: invalid JSON")
            continue
        if not isinstance(releases, list):
            errors.append(f"{repo}: unexpected payload")
            continue
        for release in releases[:3]:
            title = f"{repo} {release.get('tag_name') or release.get('name') or ''}".strip()
            body = clean_text(release.get("body") or "", 700)
            html_url = release.get("html_url") or f"https://github.com/{repo}/releases"
            items.append(Item(
                id=stable_id(source["id"], repo, release.get("id") or html_url),
                source_id=source["id"],
                source_name=source["name"],
                tier=source["tier"],
                title=title,
                url=html_url,
                published_at=iso(parse_datetime(release.get("published_at") or release.get("created_at"))),
                summary_raw=body,
                tags=list(dict.fromkeys(["release", repo.split("/")[-1]] + source.get("tags", []))),
                extra={"repo": repo, "tag": release.get("tag_name"), "prerelease": release.get("prerelease", False)},
                fetched_at=iso(),
            ))

    health.latency_ms = latency_total
    health.http_status = 200 if items or not errors else 500
    health.items = len(items)
    if items:
        health.status = "ok"
        health.last_item_at = max((i.published_at for i in items), default=None)
        if errors:
            health.error = truncate("; ".join(errors), 300)
        _mark_stale_if_needed(health, items, settings)
    else:
        health.status = "error"
        health.error = truncate("; ".join(errors) or "no releases", 300)
    return items, health


_STARS_TODAY_RE = re.compile(r"([\d,]+)\s+stars?\s+today", re.IGNORECASE)
_AI_TERM_RE = re.compile(
    r"(?<![a-z0-9])(ai|agent|agents|llm|llms|mcp|rag|langchain|langchain4j|"
    r"spring-ai|genai|prompt|prompts|copilot|codegen|embedding|embeddings|"
    r"inference|transformer|deepseek|openai|claude|gemini|qwen|ollama|vllm|"
    r"model-context-protocol)(?![a-z0-9])",
    re.IGNORECASE,
)
_AI_CN_TERMS = ("人工智能", "大模型", "智能体", "知识库", "检索增强")
_SPAM_RE = re.compile(
    r"(?<![a-z0-9])(activator|crack|keygen|cheat|torrent|destiny|junk|wallpaper|ringtone)(?![a-z0-9])",
    re.IGNORECASE,
)


def _repo_relevant(repo: dict[str, Any]) -> bool:
    text = " ".join([
        str(repo.get("name") or ""),
        str(repo.get("description") or ""),
        " ".join(repo.get("topics") or []),
    ])
    if _SPAM_RE.search(text):
        return False
    return bool(_AI_TERM_RE.search(text)) or any(term in text for term in _AI_CN_TERMS)


_TRENDING_BLOCK_RE = re.compile(
    r"(jailbreak|jailbreaks|nsfw|porn|onlyfans|紫微斗数|排盘|算命|astrology|horoscope)",
    re.IGNORECASE,
)


def _github_trending_items(source: dict[str, Any], settings: dict[str, Any]) -> tuple[list[Item], SourceHealth]:
    health = SourceHealth(
        source_id=source["id"], source_name=source["name"], tier=source["tier"],
        checked_at=iso(),
    )
    resp, error, latency = _get(source["url"], 20)
    health.latency_ms = latency
    health.http_status = resp.status_code if resp is not None else None
    if error:
        health.status = "error"
        health.error = error
        return [], health

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = soup.select("article.Box-row")
    limit = int(settings.get("github_trending_limit", 15))
    items: list[Item] = []
    for article in articles[:limit]:
        link = article.select_one("h2 a[href]")
        if not link or not link.get("href"):
            continue
        repo = link["href"].strip("/")
        description = article.select_one("p")
        description_text = clean_text(description.get_text(" ", strip=True) if description else "", 500)
        if _TRENDING_BLOCK_RE.search(f"{repo} {description_text}"):
            continue
        lang = article.select_one("[itemprop='programmingLanguage']")
        row_text = article.get_text(" ", strip=True)
        stars_match = _STARS_TODAY_RE.search(row_text)
        stars_today = int(stars_match.group(1).replace(",", "")) if stars_match else 0
        items.append(Item(
            id=stable_id(source["id"], repo),
            source_id=source["id"],
            source_name=source["name"],
            tier=source["tier"],
            title=repo,
            url=f"https://github.com/{repo}",
            published_at=iso(),
            summary_raw=description_text,
            tags=list(dict.fromkeys(["github", "trending"] + source.get("tags", []))),
            extra={
                "full_name": repo,
                "stars_today": stars_today,
                "language": clean_text(lang.get_text(strip=True), 40) if lang else None,
                "snapshot": True,
            },
            fetched_at=iso(),
        ))
    health.status = "ok" if items else "error"
    health.items = len(items)
    health.error = "" if items else "no trending rows parsed"
    health.last_item_at = iso() if items else None
    return items, health


def fetch_html_monitor(source: dict[str, Any], settings: dict[str, Any], state: dict[str, Any]) -> tuple[list[Item], SourceHealth]:
    health = SourceHealth(
        source_id=source["id"], source_name=source["name"], tier=source["tier"],
        checked_at=iso(),
    )
    resp, error, latency = _get(source["url"], int(settings.get("timeout_seconds", 20)))
    health.latency_ms = latency
    health.http_status = resp.status_code if resp is not None else None
    if error:
        health.status = "error"
        health.error = error
        return [], health

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    previous = state.get(source["id"])
    state[source["id"]] = {"hash": digest, "checked_at": iso(), "url": source["url"]}

    if not previous:
        health.status = "baseline"
        return [], health
    if previous.get("hash") == digest:
        health.status = "ok"
        return [], health

    title = soup.title.get_text(strip=True) if soup.title else source["name"]
    items = [Item(
        id=stable_id(source["id"], digest),
        source_id=source["id"],
        source_name=source["name"],
        tier=source["tier"],
        title=f"{source['name']} 页面更新：{clean_text(title, 80)}",
        url=source["url"],
        published_at=iso(),
        summary_raw="检测到页面内容变化，可能包含新的文档、公告或版本说明。",
        tags=list(dict.fromkeys(["docs", "update"] + source.get("tags", []))),
        extra={"previous_hash": previous.get("hash"), "current_hash": digest},
        fetched_at=iso(),
    )]
    health.status = "ok"
    health.items = 1
    health.last_item_at = iso()
    return items, health


def fetch_source(source: dict[str, Any], settings: dict[str, Any], monitor_state: dict[str, Any], lock: threading.Lock) -> tuple[list[Item], SourceHealth]:
    try:
        source_type = source.get("type")
        if source_type == "feed":
            return fetch_feed(source, settings)
        if source_type == "github_search":
            return _github_search_items(source, settings)
        if source_type == "github_watchlist":
            return _github_watchlist_items(source, settings)
        if source_type == "github_trending":
            return _github_trending_items(source, settings)
        if source_type == "html_monitor":
            with lock:
                return fetch_html_monitor(source, settings, monitor_state)
        return [], SourceHealth(
            source_id=source["id"], source_name=source["name"], tier=source["tier"],
            status="skipped", error=f"unknown type: {source_type}", checked_at=iso(),
        )
    except Exception as exc:  # one broken source must never stop the radar
        return [], SourceHealth(
            source_id=source["id"], source_name=source["name"], tier=source["tier"],
            status="error", error=f"{type(exc).__name__}: {exc}", checked_at=iso(),
        )


def fetch_all(config: dict[str, Any], monitor_state: dict[str, Any]) -> tuple[list[Item], list[SourceHealth]]:
    settings = config.get("settings", {})
    sources = [s for s in config.get("sources", []) if s.get("enabled", True)]
    lock = threading.Lock()
    items: list[Item] = []
    healths: list[SourceHealth] = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(sources)))) as pool:
        futures = {
            pool.submit(fetch_source, source, settings, monitor_state, lock): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                source_items, health = future.result()
            except Exception as exc:
                source_items, health = [], SourceHealth(
                    source_id=source["id"], source_name=source["name"], tier=source["tier"],
                    status="error", error=f"{type(exc).__name__}: {exc}", checked_at=iso(),
                )
            for item in source_items:
                item.extra.setdefault("source_weight", source.get("weight", 3))
            items.extend(source_items)
            healths.append(health)
    healths.sort(key=lambda h: [s["id"] for s in sources].index(h.source_id))
    return items, healths

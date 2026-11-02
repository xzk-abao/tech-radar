"""Small, dependency-light helpers shared by the pipeline."""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "spm", "from", "share_token", "fbclid", "gclid",
}
_TOKEN_RE = re.compile(r"[a-z0-9一-鿿]+")
_VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+){1,3}\b", re.IGNORECASE)
_SERIAL_RE = re.compile(r"(?:\b(?:issue|no\.?)\s*|(?<!\w)#)\s*(\d+)", re.IGNORECASE)
_CN_SERIAL_RE = re.compile(r"第\s*(\d+)\s*期")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
    "is", "are", "was", "were", "be", "by", "at", "from", "as", "it", "its",
    "this", "that", "new", "update", "updates", "release", "releases",
    "announcing", "introducing", "version", "v",
    "的", "了", "是", "在", "和", "与", "及", "或", "一个", "我们", "你",
    "发布", "更新", "新版", "版本", "关于", "如何",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    dt = dt or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def local_date(tz_name: str = "UTC", now: datetime | None = None) -> str:
    """Date string in the configured timezone; falls back to UTC on unknown tz."""
    moment = now or utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = timezone.utc
    return moment.astimezone(tz).strftime("%Y-%m-%d")


def parse_datetime(value: Any, default: datetime | None = None) -> datetime:
    """Parse feedparser time tuples, RFC822, ISO 8601, or epoch values."""
    if isinstance(value, tuple) and len(value) >= 6:
        try:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
        except (ValueError, OverflowError):
            return default or utcnow()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return default or utcnow()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value or not isinstance(value, str):
        return default or utcnow()

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    return default or utcnow()


def clean_text(value: str | None, limit: int | None = None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def normalize_url(url: str) -> str:
    """Drop tracking parameters, fragments and trailing slashes."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def url_key(url: str) -> str:
    return normalize_url(url)


def stable_id(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8", "ignore")
    return hashlib.sha1(payload).hexdigest()[:16]


def title_tokens(title: str) -> set[str]:
    tokens = {t for t in _TOKEN_RE.findall(title.lower()) if len(t) > 1}
    return {t for t in tokens if t not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def extract_versions(title: str) -> set[str]:
    return {v.lower().lstrip("v") for v in _VERSION_RE.findall(title)}


def extract_serials(title: str) -> set[str]:
    """Return issue/serial numbers such as Issue 669, No. 42, #123, 第 669 期."""
    return set(_SERIAL_RE.findall(title)) | set(_CN_SERIAL_RE.findall(title))


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


TIER_LABELS = {
    "official": "官方动态",
    "github": "GitHub 趋势",
    "learning": "学习精选",
}

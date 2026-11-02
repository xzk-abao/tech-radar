import json
from datetime import timedelta
from pathlib import Path

import requests

from email.utils import format_datetime

from radar.fetch import (
    _entry_datetime,
    _get,
    _mark_stale_if_needed,
    _normalize_future,
    _repo_relevant,
    fetch_feed,
)
from radar.models import Item, SourceHealth
from radar.util import iso, parse_datetime, utcnow


def test_entry_datetime_applies_source_offset():
    entry = {"published_parsed": (2026, 11, 1, 14, 0, 0, 6, 305, 0)}
    assert _entry_datetime(entry, {"timezone_offset_hours": -8}) == "2026-11-01T06:00:00+00:00"


def test_entry_datetime_defaults_to_utc():
    entry = {"published_parsed": (2026, 11, 1, 14, 0, 0, 6, 305, 0)}
    assert _entry_datetime(entry, {}) == "2026-11-01T14:00:00+00:00"


def test_config_applies_source_quality_fixes():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config" / "sources.json").read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in config["sources"]}

    assert sources["javaguide"]["enabled"] is False
    assert sources["inside_java"]["enabled"] is True
    assert sources["inside_java"]["url"] == "https://inside.java/feed.xml"
    assert sources["infoq_cn"]["timezone_offset_hours"] == -8


def test_ai_agent_repo_is_relevant():
    assert _repo_relevant({
        "name": "agent-kit",
        "description": "A toolkit for building AI agents",
        "topics": ["llm", "mcp"],
    })


def test_chinese_ai_description_is_relevant():
    assert _repo_relevant({
        "name": "mika",
        "description": "手机上的私人 AI 助理，替你操作 App",
        "topics": [],
    })


def test_windows_activator_is_not_relevant():
    assert not _repo_relevant({
        "name": "win-activation-toolkit",
        "description": "Windows and Office setup suite with HWID and Ohook",
        "topics": ["windows"],
    })


def make_item(published_at):
    return Item(
        id="i1",
        source_id="s1",
        source_name="Source",
        tier="official",
        title="Title",
        url="https://example.com",
        published_at=published_at,
    )


def make_health(status="ok"):
    return SourceHealth(source_id="s1", source_name="Source", tier="official", status=status)


def test_old_items_mark_source_stale():
    health = make_health()
    _mark_stale_if_needed(
        health,
        [make_item(iso(utcnow() - timedelta(days=60)))],
        {"window_hours": 720},
    )

    assert health.status == "stale"
    assert "720h" in health.error


def test_recent_items_keep_source_ok():
    health = make_health()
    _mark_stale_if_needed(
        health,
        [make_item(iso(utcnow() - timedelta(hours=4)))],
        {"window_hours": 720},
    )

    assert health.status == "ok"


def test_stale_check_does_not_override_error_or_baseline():
    for status in ("error", "baseline"):
        health = make_health(status)
        _mark_stale_if_needed(
            health,
            [make_item(iso(utcnow() - timedelta(days=60)))],
            {"window_hours": 720},
        )
        assert health.status == status


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


def test_get_retries_transient_http_errors(monkeypatch):
    calls = []
    responses = [FakeResponse(503), FakeResponse(200)]

    def fake_get(*args, **kwargs):
        calls.append(1)
        return responses.pop(0)

    monkeypatch.setattr("radar.fetch.requests.get", fake_get)
    monkeypatch.setattr("radar.fetch.time.sleep", lambda seconds: None)

    response, error, _ = _get("https://example.com", attempts=2, backoff=0.01)

    assert error == ""
    assert response.status_code == 200
    assert len(calls) == 2


def test_get_does_not_retry_404(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return FakeResponse(404)

    monkeypatch.setattr("radar.fetch.requests.get", fake_get)
    monkeypatch.setattr("radar.fetch.time.sleep", lambda seconds: None)

    response, error, _ = _get("https://example.com", attempts=3, backoff=0.01)

    assert response.status_code == 404
    assert error == "HTTP 404"
    assert len(calls) == 1


def test_get_retries_network_errors(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout("timed out")
        return FakeResponse(200)

    monkeypatch.setattr("radar.fetch.requests.get", fake_get)
    monkeypatch.setattr("radar.fetch.time.sleep", lambda seconds: None)

    response, error, _ = _get("https://example.com", attempts=2, backoff=0.01)

    assert error == ""
    assert response.status_code == 200
    assert len(calls) == 2


def test_future_timestamp_is_clamped():
    extra = {}
    future = iso(utcnow() + timedelta(days=1))

    result = _normalize_future(future, extra, {"future_tolerance_hours": 2})

    assert extra["future_timestamp"] is True
    assert extra["original_published_at"] == future
    assert parse_datetime(result) <= utcnow() + timedelta(hours=2)


def test_recent_timestamp_is_not_clamped():
    extra = {}
    recent = iso(utcnow() - timedelta(hours=1))

    result = _normalize_future(recent, extra, {"future_tolerance_hours": 2})

    assert result == recent
    assert "future_timestamp" not in extra


def test_fetch_feed_clamps_future_items_and_notes_health(monkeypatch):
    future = format_datetime(utcnow() + timedelta(days=1))
    xml = f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Future feed</title>
      <item><title>Future release</title><link>https://example.com/future</link>
      <pubDate>{future}</pubDate></item>
    </channel></rss>"""

    class Response:
        status_code = 200
        content = xml.encode("utf-8")

    monkeypatch.setattr("radar.fetch._get_for_source", lambda url, settings, timeout=15: (Response(), "", 1))
    items, health = fetch_feed(
        {"id": "s1", "name": "Source", "tier": "official", "url": "https://example.com/feed"},
        {"window_hours": 720, "max_items_per_source": 20},
    )

    assert items[0].extra["future_timestamp"] is True
    assert "future-dated" in health.error


def test_fetch_feed_marks_old_feed_stale(monkeypatch):
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Old feed</title>
      <item><title>Old release</title><link>https://example.com/old</link>
      <pubDate>Mon, 01 Jul 2026 00:00:00 GMT</pubDate></item>
    </channel></rss>"""

    class Response:
        status_code = 200
        content = xml.encode("utf-8")

    monkeypatch.setattr("radar.fetch._get_for_source", lambda url, settings, timeout=15: (Response(), "", 1))
    items, health = fetch_feed(
        {"id": "s1", "name": "Source", "tier": "official", "url": "https://example.com/feed"},
        {"window_hours": 720, "max_items_per_source": 20},
    )

    assert len(items) == 1
    assert health.status == "stale"

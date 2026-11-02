import json
from datetime import timedelta
from pathlib import Path

from radar.fetch import _entry_datetime, _mark_stale_if_needed, _repo_relevant, fetch_feed
from radar.models import Item, SourceHealth
from radar.util import iso, utcnow


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


def test_fetch_feed_marks_old_feed_stale(monkeypatch):
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Old feed</title>
      <item><title>Old release</title><link>https://example.com/old</link>
      <pubDate>Mon, 01 Jul 2026 00:00:00 GMT</pubDate></item>
    </channel></rss>"""

    class Response:
        status_code = 200
        content = xml.encode("utf-8")

    monkeypatch.setattr("radar.fetch._get", lambda url, timeout=15: (Response(), "", 1))
    items, health = fetch_feed(
        {"id": "s1", "name": "Source", "tier": "official", "url": "https://example.com/feed"},
        {"window_hours": 720, "max_items_per_source": 20},
    )

    assert len(items) == 1
    assert health.status == "stale"

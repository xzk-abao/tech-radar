import json
from pathlib import Path

from radar.fetch import _entry_datetime, _repo_relevant


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

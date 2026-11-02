import json

from radar.models import Item
from radar.summarize import LLMClient, _cache_key, summarize_items


def make_item(item_id="i1", title="A release"):
    return Item(
        id=item_id,
        source_id="s1",
        source_name="Source",
        tier="official",
        title=title,
        url=f"https://example.com/{item_id}",
        published_at="2026-10-31T08:00:00+00:00",
        summary_raw="Raw summary",
        score=80.0,
    )


def test_cache_key_includes_provider_and_model():
    item = make_item()

    deepseek = _cache_key(item, "deepseek", "deepseek-chat")
    other_model = _cache_key(item, "deepseek", "deepseek-reasoner")
    other_provider = _cache_key(item, "ark", "deepseek-chat")

    assert deepseek != other_model
    assert deepseek != other_provider


def test_summarize_records_invalid_json_and_falls_back(monkeypatch, tmp_path):
    item = make_item()
    monkeypatch.setattr(LLMClient, "available", property(lambda self: True))
    monkeypatch.setattr(LLMClient, "complete", lambda self, system, user: "not json")

    stats = summarize_items(
        [item],
        {"enabled": True, "max_items": 1, "min_score": 0, "batch_size": 1},
        str(tmp_path / "cache.json"),
    )

    assert stats["calls"] == 1
    assert any("JSON" in error for error in stats["errors"])
    assert stats["fallbacks"] >= 1
    assert item.summary


def test_summarize_records_partial_json_rows(monkeypatch, tmp_path):
    items = [make_item("i1"), make_item("i2")]
    payload = json.dumps([{"id": "i1", "summary": "ok", "why": "why"}])
    monkeypatch.setattr(LLMClient, "available", property(lambda self: True))
    monkeypatch.setattr(LLMClient, "complete", lambda self, system, user: payload)

    stats = summarize_items(
        items,
        {"enabled": True, "max_items": 2, "min_score": 0, "batch_size": 2},
        str(tmp_path / "cache.json"),
    )

    assert stats["calls"] == 1
    assert any("1/2 valid rows" in error for error in stats["errors"])
    assert items[0].summary == "ok"
    assert items[1].summary

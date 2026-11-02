import json
import os
from datetime import datetime, timezone

from radar.models import Item, SourceHealth
from radar.store import _dataset_stats, build_public, write_dataset


def test_write_dataset_and_build_public(tmp_path):
    data_dir = tmp_path / "data"
    web_dir = tmp_path / "web"
    out_dir = tmp_path / "public"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>radar</html>", encoding="utf-8")

    item = Item(
        id="i1",
        source_id="s1",
        source_name="Source",
        tier="official",
        title="Title",
        url="https://example.com",
        published_at="2026-10-31T08:00:00+00:00",
        summary="summary",
        why="why",
        score=88.0,
        cluster_id="c1",
    )
    health = SourceHealth(source_id="s1", source_name="Source", tier="official", status="ok", items=1)
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 168}}
    dataset = write_dataset(str(data_dir), [item], [health], {"model": None}, config)

    assert dataset["stats"]["total_items"] == 1
    assert dataset["stats"]["sources_with_items"] == 1
    assert dataset["health"][0]["effective_items"] == 1
    assert os.path.exists(data_dir / "items.json")
    assert os.path.exists(data_dir / "history" / "index.json")

    build_public(str(data_dir), str(web_dir), str(out_dir))
    assert os.path.exists(out_dir / "index.html")
    assert os.path.exists(out_dir / "data" / "items.json")
    saved = json.loads((out_dir / "data" / "items.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["title"] == "Title"


def test_stale_sources_are_not_counted_as_ok():
    healths = [
        SourceHealth(source_id="ok", source_name="OK", tier="official", status="ok"),
        SourceHealth(source_id="stale", source_name="Stale", tier="official", status="stale"),
    ]

    stats = _dataset_stats([], healths, {})

    assert stats["sources_ok"] == 1
    assert stats["sources_stale"] == 1
    assert stats["sources_with_items"] == 0


def test_dataset_stats_report_raw_and_deduped(tmp_path):
    data_dir = tmp_path / "data"
    items = [
        Item(
            id=f"i{n}",
            source_id="s1",
            source_name="Source",
            tier="official",
            title=f"Title {n}",
            url=f"https://example.com/{n}",
            published_at="2026-10-31T08:00:00+00:00",
            score=80.0,
            cluster_id=f"c{n}",
        )
        for n in range(3)
    ]
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}

    dataset = write_dataset(str(data_dir), items, [], {}, config, raw_items=5)

    assert dataset["stats"]["raw_items"] == 5
    assert dataset["stats"]["total_items"] == 3
    assert dataset["stats"]["deduped"] == 2


def test_dataset_stats_default_raw_items(tmp_path):
    data_dir = tmp_path / "data"
    item = Item(
        id="i1",
        source_id="s1",
        source_name="Source",
        tier="official",
        title="Title",
        url="https://example.com",
        published_at="2026-10-31T08:00:00+00:00",
        score=80.0,
        cluster_id="c1",
    )
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}

    dataset = write_dataset(str(data_dir), [item], [], {}, config)

    assert dataset["stats"]["raw_items"] == dataset["stats"]["total_items"]
    assert dataset["stats"]["deduped"] == 0


def test_history_snapshot_uses_configured_timezone(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    item = Item(
        id="i1",
        source_id="s1",
        source_name="Source",
        tier="official",
        title="Title",
        url="https://example.com",
        published_at="2026-10-31T08:00:00+00:00",
        score=80.0,
        cluster_id="c1",
    )
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}
    fixed = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("radar.util.utcnow", lambda: fixed)

    write_dataset(str(data_dir), [item], [], {}, config)

    assert (data_dir / "history" / "2026-11-02.json").exists()
    index = json.loads((data_dir / "history" / "index.json").read_text(encoding="utf-8"))
    assert index[-1]["date"] == "2026-11-02"


def test_effective_items_use_final_primaries(tmp_path):
    data_dir = tmp_path / "data"
    item = Item(
        id="i1",
        source_id="s1",
        source_name="Source",
        tier="official",
        title="Title",
        url="https://example.com",
        published_at="2026-10-31T08:00:00+00:00",
        score=88.0,
        cluster_id="c1",
    )
    healths = [
        SourceHealth(source_id="s1", source_name="Source", tier="official", status="ok", items=20),
        SourceHealth(source_id="s2", source_name="Empty", tier="official", status="ok", items=9),
    ]
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}

    dataset = write_dataset(str(data_dir), [item], healths, {}, config)

    by_id = {row["source_id"]: row for row in dataset["health"]}
    assert by_id["s1"]["items"] == 20
    assert by_id["s1"]["effective_items"] == 1
    assert by_id["s2"]["items"] == 9
    assert by_id["s2"]["effective_items"] == 0
    assert dataset["stats"]["sources_with_items"] == 1

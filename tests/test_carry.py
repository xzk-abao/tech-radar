from datetime import timedelta

from radar.models import Item, SourceHealth
from radar.store import carry_forward_failed_sources, write_dataset
from radar.util import iso, utcnow


def make_item(source_id, title):
    return Item(
        id=f"{source_id}-{title}",
        source_id=source_id,
        source_name=source_id,
        tier="official",
        title=title,
        url=f"https://example.com/{source_id}/{title}",
        published_at=iso(),
        summary="summary",
        why="why",
        score=50.0,
    )


def test_carry_forward_keeps_items_for_failed_source(tmp_path):
    data_dir = str(tmp_path / "data")
    good = make_item("s1", "kept")
    other = make_item("s2", "not-kept")
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}
    write_dataset(data_dir, [good, other], [], {}, config)

    health = SourceHealth(source_id="s1", source_name="s1", tier="official", status="error")
    items, carried = carry_forward_failed_sources([], [health], data_dir, 720)
    assert carried == 1
    assert [item.source_id for item in items] == ["s1"]
    assert items[0].extra["carried_forward"] is True


def test_carry_forward_skips_old_items(tmp_path):
    data_dir = str(tmp_path / "data")
    old = make_item("s1", "old")
    old.published_at = iso(utcnow() - timedelta(days=60))
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}
    write_dataset(data_dir, [old], [], {}, config)

    health = SourceHealth(source_id="s1", source_name="s1", tier="official", status="error")
    items, carried = carry_forward_failed_sources([], [health], data_dir, 720)
    assert carried == 0
    assert items == []

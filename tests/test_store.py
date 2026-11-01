import json
import os

from radar.models import Item, SourceHealth
from radar.store import build_public, write_dataset


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
    assert os.path.exists(data_dir / "items.json")
    assert os.path.exists(data_dir / "history" / "index.json")

    build_public(str(data_dir), str(web_dir), str(out_dir))
    assert os.path.exists(out_dir / "index.html")
    assert os.path.exists(out_dir / "data" / "items.json")
    saved = json.loads((out_dir / "data" / "items.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["title"] == "Title"

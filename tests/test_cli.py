import json
from pathlib import Path

from radar.cli import main
from radar.models import Item
from radar.store import write_dataset


def make_dataset(tmp_path):
    data_dir = tmp_path / "data"
    item = Item(
        id="i1",
        source_id="s1",
        source_name="Source",
        tier="official",
        title="Claude Code v2.1.316",
        url="https://example.com/release",
        published_at="2026-10-31T08:00:00+00:00",
        summary="summary",
        why="why",
        score=80.0,
        knowledge={
            "concept": "Agent Skills",
            "one_liner": "按需加载 SOP。",
            "why_it_matters": "避免上下文膨胀。",
            "learning_path": ["读文档"],
            "difficulty": 2,
        },
    )
    config = {"settings": {"timezone": "Asia/Shanghai", "window_hours": 720}}
    write_dataset(str(data_dir), [item], [], {}, config)
    return data_dir


def test_build_command_uses_out_argument(tmp_path):
    data_dir = make_dataset(tmp_path)
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>radar</html>", encoding="utf-8")
    public_dir = tmp_path / "public"

    rc = main([
        "build",
        "--out", str(data_dir),
        "--web", str(web_dir),
        "--public", str(public_dir),
    ])
    assert rc == 0
    assert (public_dir / "index.html").exists()
    assert (public_dir / "data" / "items.json").exists()


def test_export_command_uses_out_argument(tmp_path):
    data_dir = make_dataset(tmp_path)
    export_dir = tmp_path / "export"

    rc = main([
        "export",
        "--out", str(data_dir),
        "--dir", str(export_dir),
    ])
    assert rc == 0
    notes = list(export_dir.glob("*技术雷达.md"))
    assert len(notes) == 1
    assert "Agent Skills" in notes[0].read_text(encoding="utf-8")


def test_demo_uses_enabled_sources_and_effective_counts(tmp_path):
    data_dir = tmp_path / "data"
    public_dir = tmp_path / "public"

    rc = main(["demo", "--out", str(data_dir), "--public", str(public_dir)])

    assert rc == 0
    dataset = json.loads((data_dir / "items.json").read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config" / "sources.json").read_text(encoding="utf-8"))
    enabled = sum(1 for source in config["sources"] if source.get("enabled", True))

    assert dataset["stats"]["sources_total"] == enabled
    assert not any(row["source_id"] == "javaguide" for row in dataset["health"])
    assert dataset["stats"]["sources_with_items"] == dataset["stats"]["total_items"]

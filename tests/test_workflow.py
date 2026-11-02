from pathlib import Path


def test_actions_cache_keeps_previous_dataset_for_carry_forward():
    """carry_forward_failed_sources reads data/items.json, so it must survive runners."""
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "radar.yml").read_text(encoding="utf-8")
    cache_step = workflow.split("name: Restore radar state", 1)[1].split("name: Collect", 1)[0]

    assert "data/items.json" in cache_step

from pathlib import Path


def read_workflow() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / "radar.yml").read_text(encoding="utf-8")


def test_actions_cache_keeps_previous_dataset_for_carry_forward():
    """carry_forward_failed_sources reads data/items.json, so it must survive runners."""
    workflow = read_workflow()
    cache_step = workflow.split("name: Restore radar state", 1)[1].split("name: Collect", 1)[0]

    assert "data/items.json" in cache_step


def test_workflow_runs_tests_on_pull_requests():
    workflow = read_workflow()
    on_block = workflow.split("on:", 1)[1].split("permissions:", 1)[0]

    assert "pull_request:" in on_block


def test_pages_steps_are_skipped_on_pull_requests():
    workflow = read_workflow()
    upload_block = workflow.split("actions/upload-pages-artifact", 1)[1].split("- name:", 1)[0]
    deploy_block = workflow.split("  deploy:", 1)[1].split("steps:", 1)[0]

    assert "github.event_name != 'pull_request'" in upload_block
    assert "github.event_name != 'pull_request'" in deploy_block


def test_concurrency_is_scoped_per_ref():
    workflow = read_workflow()
    concurrency_block = workflow.split("concurrency:", 1)[1].split("jobs:", 1)[0]

    assert "github.ref" in concurrency_block

from radar.dedupe import cluster_items
from radar.models import Item


def make_item(title, url, source_id="s", tier="learning", extra=None):
    return Item(
        id=f"{source_id}-{title}",
        source_id=source_id,
        source_name=source_id,
        tier=tier,
        title=title,
        url=url,
        published_at="2026-10-31T08:00:00+00:00",
        extra=extra or {},
    )


def test_same_url_clusters():
    items = [
        make_item("OpenAI announces GPT-6", "https://example.com/gpt6?utm_source=x"),
        make_item("GPT-6 is here", "https://example.com/gpt6"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_similar_titles_cluster():
    items = [
        make_item("Claude Code releases v2.1.316", "https://a.example/1"),
        make_item("Claude Code v2.1.316 released", "https://b.example/2"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1


def test_different_versions_do_not_cluster():
    items = [
        make_item("Claude Code releases v2.1.316", "https://a.example/1"),
        make_item("Claude Code releases v2.1.315", "https://a.example/2"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 2


def test_same_github_repo_clusters():
    items = [
        make_item("owner/repo", "https://github.com/owner/repo", tier="github", extra={"full_name": "owner/repo"}),
        make_item("owner/repo trending", "https://github.com/owner/repo?tab=readme", tier="github", extra={"full_name": "owner/repo"}),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1
    assert clusters[0][0].tier == "github"
    assert clusters[0][0].cluster_size == 2


def test_unrelated_items_not_clustered():
    items = [
        make_item("Spring Boot 4.0 released", "https://spring.io/blog/1"),
        make_item("React 20 announced", "https://react.dev/blog/2"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 2

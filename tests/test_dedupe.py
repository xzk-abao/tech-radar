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


def test_same_source_serial_issues_do_not_cluster():
    items = [
        make_item("Java Weekly, Issue 669", "https://www.baeldung.com/java-weekly-669", source_id="baeldung"),
        make_item("Java Weekly, Issue 668", "https://www.baeldung.com/java-weekly-668", source_id="baeldung"),
    ]
    clusters = cluster_items(items)

    assert len(clusters) == 2


def test_same_source_similar_changelog_posts_do_not_cluster():
    items = [
        make_item("GitHub Copilot app, Universe releases", "https://github.blog/1", source_id="github_changelog"),
        make_item("Security extension for the GitHub Copilot app", "https://github.blog/2", source_id="github_changelog"),
        make_item("GitHub Copilot in VS Code, Universe releases", "https://github.blog/3", source_id="github_changelog"),
    ]
    clusters = cluster_items(items)

    assert len(clusters) == 3


def test_cross_source_same_title_still_clusters():
    items = [
        make_item("Introducing GPT-6.1 Terra", "https://openai.com/index/gpt-6-1-terra", source_id="openai_news"),
        make_item("GPT-6.1 Terra", "https://simonwillison.net/2026/nov/1/gpt-6-1-terra", source_id="simon_willison"),
    ]
    clusters = cluster_items(items)

    assert len(clusters) == 1
    assert len(clusters[0]) == 2

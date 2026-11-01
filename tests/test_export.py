from radar.export import MARKER_START, export_markdown


def dataset():
    return {
        "generated_at": "2026-10-31T08:00:00+00:00",
        "stats": {
            "total_items": 2,
            "by_tier": {"official": 1, "github": 1, "learning": 0},
            "knowledge_cards": 1,
            "sources_ok": 1,
            "sources_total": 1,
        },
        "health": [],
        "items": [
            {
                "title": "Claude Code v2.1.316",
                "url": "https://github.com/anthropics/claude-code/releases",
                "source_name": "Claude Code Releases",
                "tier": "official",
                "knowledge": {
                    "concept": "Agent Skills",
                    "one_liner": "按需加载领域 SOP。",
                    "why_it_matters": "避免 system prompt 膨胀。",
                    "learning_path": ["读文档", "写一个 SKILL.md"],
                    "difficulty": 2,
                },
            },
            {
                "title": "lightpanda-io/browser",
                "url": "https://github.com/lightpanda-io/browser",
                "source_name": "GitHub Trending",
                "tier": "github",
                "knowledge": None,
            },
        ],
    }


def test_export_creates_obsidian_note(tmp_path):
    path = export_markdown(dataset(), str(tmp_path), date_str="2026-10-31")
    text = open(path, encoding="utf-8").read()
    assert text.startswith("---")
    assert "tags:" in text and "AI工具雷达" in text
    assert "# 技术雷达 2026-10-31" in text
    assert "[[Agent Skills]]" in text
    assert MARKER_START in text
    assert "lightpanda-io/browser" in text


def test_export_replaces_block_and_keeps_user_text(tmp_path):
    path = tmp_path / "2026-10-31-技术雷达.md"
    path.write_text("# 我的笔记\n\n用户手写内容\n", encoding="utf-8")

    export_markdown(dataset(), str(tmp_path), date_str="2026-10-31")
    text = path.read_text(encoding="utf-8")
    assert "用户手写内容" in text
    assert text.count(MARKER_START) == 1
    assert "Agent Skills" in text

    export_markdown(dataset(), str(tmp_path), date_str="2026-10-31")
    text = path.read_text(encoding="utf-8")
    assert "用户手写内容" in text
    assert text.count(MARKER_START) == 1

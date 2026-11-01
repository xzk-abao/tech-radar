from radar.fetch import _repo_relevant


def test_ai_agent_repo_is_relevant():
    assert _repo_relevant({
        "name": "agent-kit",
        "description": "A toolkit for building AI agents",
        "topics": ["llm", "mcp"],
    })


def test_chinese_ai_description_is_relevant():
    assert _repo_relevant({
        "name": "mika",
        "description": "手机上的私人 AI 助理，替你操作 App",
        "topics": [],
    })


def test_windows_activator_is_not_relevant():
    assert not _repo_relevant({
        "name": "win-activation-toolkit",
        "description": "Windows and Office setup suite with HWID and Ohook",
        "topics": ["windows"],
    })

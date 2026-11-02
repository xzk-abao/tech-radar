from datetime import timezone

from radar.util import (
    clean_text,
    extract_serials,
    extract_versions,
    jaccard,
    normalize_url,
    parse_datetime,
    stable_id,
    title_tokens,
)


def test_normalize_url_drops_tracking_and_trailing_slash():
    url = "https://Example.com/Path/?utm_source=x&ref=y&a=1#frag"
    assert normalize_url(url) == "https://example.com/Path?a=1"


def test_parse_datetime_accepts_iso_z_and_rfc822():
    iso_dt = parse_datetime("2026-10-31T08:00:00Z")
    assert iso_dt.tzinfo == timezone.utc
    assert iso_dt.hour == 8
    rfc_dt = parse_datetime("Sat, 31 Oct 2026 08:00:00 GMT")
    assert rfc_dt.year == 2026 and rfc_dt.hour == 8


def test_clean_text_strips_tags_and_entities():
    assert clean_text("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"


def test_stable_id_accepts_non_string_parts():
    assert stable_id("release", 123) == stable_id("release", "123")


def test_versions_and_tokens():
    assert extract_versions("Claude Code v2.1.316 released") == {"2.1.316"}
    tokens = title_tokens("Claude Code releases v2.1.316")
    assert "claude" in tokens and "code" in tokens
    assert "releases" not in tokens
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_extract_serials():
    assert extract_serials("Java Weekly, Issue 669") == {"669"}
    assert extract_serials("第 669 期 Java Weekly") == {"669"}
    assert extract_serials("No. 42 release") == {"42"}
    assert extract_serials("#123 fix") == {"123"}
    assert extract_serials("C# 12 support") == set()
    assert extract_serials("No serial here") == set()

from datetime import timedelta

from radar.models import Item
from radar.score import apply_scores, recency_score, update_star_history
from radar.util import iso, utcnow


def make_item(title="A useful release", tier="official", weight=5, published_at=None, extra=None):
    extra = dict(extra or {})
    extra["source_weight"] = weight
    return Item(
        id=title,
        source_id="s",
        source_name="s",
        tier=tier,
        title=title,
        url="https://example.com/" + title.replace(" ", "-"),
        published_at=published_at or iso(),
        summary_raw="A guide and deep dive into architecture best practice",
        tags=["architecture", "guide"],
        extra=extra,
    )


def test_recency_decays_with_age():
    now = utcnow()
    fresh = recency_score(iso(now), now, 36)
    old = recency_score(iso(now - timedelta(days=7)), now, 36)
    assert fresh > 0.99
    assert old < 0.05


def test_apply_scores_prefers_stronger_source():
    settings = {"scoring": {"source": 0.35, "recency": 0.3, "momentum": 0.2, "learning": 0.15, "recency_half_life_hours": 36}}
    strong = make_item("Strong official", weight=5)
    weak = make_item("Weak learning", tier="learning", weight=2)
    apply_scores([strong, weak], settings)
    assert strong.score > weak.score


def test_future_timestamp_reduces_recency_score():
    settings = {"scoring": {"source": 0.35, "recency": 0.3, "momentum": 0.2, "learning": 0.15, "recency_half_life_hours": 36}}
    normal = make_item("Same release")
    future = make_item("Same release", extra={"future_timestamp": True})

    apply_scores([normal, future], settings)

    assert future.score < normal.score


def test_star_history_computes_delta():
    state = {}
    item = make_item(extra={"full_name": "owner/repo", "stars": 1200})
    update_star_history([item], state)
    assert state["owner/repo"][-1]["stars"] == 1200
    # Simulate a seven-day-old baseline.
    old_date = (utcnow() - timedelta(days=8)).strftime("%Y-%m-%d")
    state["owner/repo"].insert(0, {"date": old_date, "stars": 1000})
    item2 = make_item(extra={"full_name": "owner/repo", "stars": 1500})
    update_star_history([item2], state)
    assert item2.extra["star_delta_7d"] == 500

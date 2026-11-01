"""Core data models for the tech radar pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Any


@dataclass
class Item:
    """A normalized radar item from any source."""

    id: str
    source_id: str
    source_name: str
    tier: str
    title: str
    url: str
    published_at: str
    summary_raw: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = ""
    score: float = 0.0
    cluster_id: str = ""
    cluster_size: int = 1
    members: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    why: str = ""
    knowledge: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def item_from_dict(row: dict[str, Any]) -> Item:
    """Rebuild an Item from a stored dataset row."""
    known = {field.name for field in fields(Item)}
    return Item(**{key: value for key, value in row.items() if key in known})


@dataclass
class SourceHealth:
    """Health record for one source after a fetch attempt."""

    source_id: str
    source_name: str
    tier: str
    status: str = "unknown"  # ok | error | skipped | baseline
    http_status: int | None = None
    items: int = 0
    error: str = ""
    latency_ms: int = 0
    last_item_at: str | None = None
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

"""Cluster items that describe the same event across sources."""
from __future__ import annotations

from urllib.parse import urlsplit

from .models import Item
from .util import extract_versions, jaccard, stable_id, title_tokens, url_key

TIER_PRIORITY = {"official": 3, "github": 2, "learning": 1}


def _same_event(a: Item, b: Item) -> bool:
    if url_key(a.url) == url_key(b.url):
        return True

    a_versions = extract_versions(a.title)
    b_versions = extract_versions(b.title)
    if a_versions and b_versions and a_versions != b_versions:
        return False

    a_tokens = title_tokens(a.title)
    b_tokens = title_tokens(b.title)
    similarity = jaccard(a_tokens, b_tokens)
    if similarity >= 0.62:
        return True

    a_host = urlsplit(a.url).netloc.lower()
    b_host = urlsplit(b.url).netloc.lower()
    if a_host and a_host == b_host and similarity >= 0.45:
        return True

    # Same GitHub repository (trending + search + releases).
    a_repo = a.extra.get("full_name") or a.extra.get("repo")
    b_repo = b.extra.get("full_name") or b.extra.get("repo")
    if a_repo and b_repo and str(a_repo).lower() == str(b_repo).lower():
        return True
    return False


def cluster_items(items: list[Item]) -> list[list[Item]]:
    """Return groups of items. Each group is sorted with the best primary first."""
    clusters: list[list[Item]] = []
    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        for cluster in clusters:
            if _same_event(item, cluster[0]):
                cluster.append(item)
                break
        else:
            clusters.append([item])

    for cluster in clusters:
        cluster.sort(key=lambda i: (TIER_PRIORITY.get(i.tier, 0), i.published_at), reverse=True)
        primary = cluster[0]
        cluster_id = stable_id("cluster", url_key(primary.url), primary.title)
        for member in cluster:
            member.cluster_id = cluster_id
            member.cluster_size = len(cluster)
            member.members = [
                {
                    "source_name": other.source_name,
                    "title": other.title,
                    "url": other.url,
                    "published_at": other.published_at,
                }
                for other in cluster
            ]
    return clusters

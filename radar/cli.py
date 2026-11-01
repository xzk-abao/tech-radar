"""Command line entry points."""
from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .dedupe import cluster_items
from .export import export_markdown
from .fetch import fetch_all
from .models import Item, SourceHealth
from .score import apply_scores, filter_window, update_star_history
from .store import (
    build_public,
    carry_forward_failed_sources,
    load_state,
    read_dataset,
    save_state,
    write_dataset,
)
from .summarize import summarize_items
from .util import iso, load_json, utcnow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, "config", "sources.json")
DEFAULT_DATA = os.path.join(ROOT, "data")
DEFAULT_WEB = os.path.join(ROOT, "web")
DEFAULT_PUBLIC = os.path.join(ROOT, "public")
DEFAULT_EXPORT_DIR = r"D:\mdStudy\personal-knowledge-base\AI\04-资料库\AI工具雷达"


def _load_config(path: str, only: str | None = None) -> dict:
    config = load_json(path, None)
    if not config:
        raise SystemExit(f"config not found or invalid: {path}")
    if only:
        wanted = {part.strip() for part in only.split(",") if part.strip()}
        config["sources"] = [s for s in config.get("sources", []) if s.get("id") in wanted]
        missing = wanted - {s["id"] for s in config["sources"]}
        if missing:
            print(f"warning: unknown source ids: {', '.join(sorted(missing))}", file=sys.stderr)
    return config


def _print_health(healths: list[SourceHealth]) -> None:
    print(f"{'source':32s} {'tier':9s} {'status':9s} {'items':>5s}  error")
    print("-" * 100)
    for health in sorted(healths, key=lambda h: (h.tier, h.source_id)):
        error = (health.error or "")[:55]
        print(f"{health.source_id:32s} {health.tier:9s} {health.status:9s} {health.items:5d}  {error}")


def run(args: argparse.Namespace) -> int:
    config = _load_config(args.config, args.only)
    settings = config.get("settings", {})
    if args.no_llm:
        settings.setdefault("llm", {})["enabled"] = False
    state = load_state(args.out)
    items, healths = fetch_all(config, state["monitors"])
    window_hours = int(settings.get("window_hours", 720))
    items, carried = carry_forward_failed_sources(items, healths, args.out, window_hours)
    if carried:
        print(f"carried forward {carried} items from failed sources")
    items = filter_window(items, window_hours)
    update_star_history(items, state["stars"])
    clusters = cluster_items(items)
    primaries = [cluster[0] for cluster in clusters]
    apply_scores(primaries, settings)

    llm_stats = summarize_items(primaries, settings.get("llm", {}), state["llm_cache_path"])

    dataset = write_dataset(args.out, primaries, healths, llm_stats, config)
    save_state(args.out, state)
    build_public(args.out, args.web, args.public)

    stats = dataset["stats"]
    print(f"radar: {stats['total_items']} items, {stats['clusters']} clusters, "
          f"{stats['knowledge_cards']} knowledge cards")
    print(f"health: {stats['sources_ok']}/{stats['sources_total']} sources ok, "
          f"{stats['sources_error']} errors, {stats['sources_baseline']} baseline")
    if llm_stats.get("errors"):
        print("llm notes: " + "; ".join(llm_stats["errors"])[:300])
    _print_health(healths)
    print(f"public: {args.public}")
    return 0


def build(args: argparse.Namespace) -> int:
    dataset = read_dataset(args.out)
    if not dataset.get("items"):
        print("warning: dataset is empty", file=sys.stderr)
    path = build_public(args.out, args.web, args.public)
    print(f"public: {path}")
    return 0


def serve(args: argparse.Namespace) -> int:
    build(args)
    os.chdir(args.public)
    handler = SimpleHTTPRequestHandler
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"serving {args.public} on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def check(args: argparse.Namespace) -> int:
    config = _load_config(args.config, args.only)
    state = load_state(args.out)
    items, healths = fetch_all(config, state["monitors"])
    _print_health(healths)
    print(f"\n{len(items)} raw items fetched")
    return 0


def export(args: argparse.Namespace) -> int:
    dataset = read_dataset(args.out)
    if not dataset.get("items"):
        print("warning: dataset is empty", file=sys.stderr)
    target = args.dir or os.environ.get("TECH_RADAR_EXPORT_DIR", DEFAULT_EXPORT_DIR)
    path = export_markdown(dataset, target, date_str=args.date)
    print(f"exported: {path}")
    return 0


def demo(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    fixture_path = args.fixture or os.path.join(ROOT, "fixtures", "demo_items.json")
    rows = load_json(fixture_path, [])
    if not rows:
        raise SystemExit(f"demo fixture not found or empty: {fixture_path}")
    items: list[Item] = []
    for row in rows:
        items.append(Item(
            id=row.get("id") or f"demo-{len(items)}",
            source_id=row.get("source_id", "demo"),
            source_name=row.get("source_name", "Demo"),
            tier=row.get("tier", "learning"),
            title=row.get("title", "Untitled"),
            url=row.get("url", "https://example.com"),
            published_at=row.get("published_at", iso()),
            summary_raw=row.get("summary_raw", ""),
            tags=row.get("tags", []),
            extra=row.get("extra", {}),
            fetched_at=iso(),
        ))
    clusters = cluster_items(items)
    primaries = [cluster[0] for cluster in clusters]
    for item in primaries:
        item.extra.setdefault("source_weight", 4)
    apply_scores(primaries, config.get("settings", {}))
    llm_stats = {"provider": "demo", "model": None, "calls": 0, "hits": 0, "fallbacks": 0, "errors": []}
    for item in primaries:
        item.summary = item.extra.get("summary") or (item.summary_raw or item.title)[:160]
        item.why = item.extra.get("why", "演示数据：用于预览仪表盘布局。")
        item.knowledge = item.extra.get("knowledge")
    healths = [
        SourceHealth(source_id=s["id"], source_name=s["name"], tier=s["tier"], status="ok", checked_at=iso())
        for s in config.get("sources", [])
    ]
    dataset = write_dataset(args.out, primaries, healths, llm_stats, config, demo=True)
    build_public(args.out, args.web, args.public)
    print(f"demo: {dataset['stats']['total_items']} items -> {args.public}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar", description="Tech radar pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", default=DEFAULT_CONFIG)
        p.add_argument("--out", default=DEFAULT_DATA, help="data directory")
        p.add_argument("--web", default=DEFAULT_WEB)
        p.add_argument("--public", default=DEFAULT_PUBLIC)

    p_run = sub.add_parser("run", help="fetch sources, analyze, and build the site")
    common(p_run)
    p_run.add_argument("--only", help="comma-separated source ids")
    p_run.add_argument("--no-llm", action="store_true")
    p_run.set_defaults(func=run)

    p_build = sub.add_parser("build", help="rebuild the static site from data/items.json")
    common(p_build)
    p_build.set_defaults(func=build)

    p_serve = sub.add_parser("serve", help="build then serve locally")
    common(p_serve)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.set_defaults(func=serve)

    p_check = sub.add_parser("check", help="fetch sources and print health only")
    common(p_check)
    p_check.add_argument("--only")
    p_check.set_defaults(func=check)

    p_export = sub.add_parser("export", help="export the dataset as an Obsidian markdown note")
    common(p_export)
    p_export.add_argument("--dir", help="target directory")
    p_export.add_argument("--date", help="date override (YYYY-MM-DD)")
    p_export.set_defaults(func=export)

    p_demo = sub.add_parser("demo", help="build the site from fixtures/demo_items.json")
    common(p_demo)
    p_demo.add_argument("--fixture")
    p_demo.set_defaults(func=demo)

    args = parser.parse_args(argv)
    return args.func(args)

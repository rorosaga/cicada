"""What would change if saved posts were drawn as rows under their lists (G246, ruling 81; ``saved_posts``).

    api/.venv/bin/python -m api.scripts.saved_posts_dry_run --bank <path>

Prints one JSON object of COUNTS, never a title, a link, a word of a post or an id of one. It changes nothing: no file, no
commit, whatever ``saved_posts.HIDE_POSTS`` says (it turns the constant on in its own process to measure the answer, and
never writes). Exit 0 done, 2 not a bank.

The coordinator reads it on the real memory before the flip and reports it to the person in words:

* ``posts`` and ``works`` (every other media page), the posts by site and by door (the origin that brought them in),
  the works by kind and door;
* ``earned_by_sign``: how many posts hold each sign (a post may hold several), ``earned`` and ``rows`` (a post with none);
* ``would_leave``: the pages that stop being nodes in the graph and lines in Clusters (``clusters_media`` counts Media's
  main view as the app draws it), and how many of them are not archived;
* ``degree``: pages whose degree falls, and by how much at most (a row's edges no longer count toward its target);
* ``doors_without_a_list``: posts that came in through a door that puts them on no site's list (a browser bookmark, a
  paste, the notch, Telegram, an agent): each is on its site's "Saved another way" (``saved_another_way``, a count a site);
* ``saved_another_way``: how many posts each site's "Saved another way" stream holds (the posts no other stream of the site has);
* ``links_on_two_pages``: post links that exist as two pages (the bookmark and paste doors keep the host as written);
* ``related_lines``: ``## Related`` entries that would be filtered, and the pages that carry them;
* ``old_shape_episodes``: connector saves whose text sits under the person's note, which earn nothing;
* ``timing_ms``: the graph build and its ETag, cold and warm, before (the flag off: what the route does today) and
  after. Cold is a fresh process's cost (the cached headers dropped); the logo and photo caches outside the bank are read
  as they are on this Mac.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ARCHIVED = {"archived", "dropped"}


def _ms(fn) -> tuple[float, object]:
    start = time.perf_counter()
    out = fn()
    return round((time.perf_counter() - start) * 1000, 1), out


def _clusters_media(nodes) -> int:
    """Media's main view as the app draws it: every media node but a quiet feed item (``ClustersModel.mediaShown``)."""
    return sum(1 for n in nodes if n.type == "media" and not (n.media_kind == "feed" and n.quiet))


def _components(pairs: list[tuple[str, list[str]]]) -> tuple[int, int]:
    """``(links on more than one page, pages beyond the first)`` over ``(page, [spellings of its link])``."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for page, urls in pairs:
        for url in urls:
            parent[find(url)] = find(f"page:{page}")
    groups: Counter = Counter(find(f"page:{page}") for page, _ in pairs)
    doubled = [n for n in groups.values() if n > 1]
    return len(doubled), sum(n - 1 for n in doubled)


def _swap(module, name, value):
    held = getattr(module, name)
    setattr(module, name, value)
    return held


def measure(bank: Path) -> dict:
    from api.services import (bank_index, graph_builder, quiet_pages, saved_lists, saved_posts, sync_service)
    from api.services.media_kinds import kind_of

    bank_index.invalidate()
    held = saved_posts.HIDE_POSTS
    saved_posts.HIDE_POSTS = True   # the answer the flip would give; restored below, nothing is ever written
    try:
        out = _measure(bank, bank_index, graph_builder, quiet_pages, saved_lists, saved_posts, sync_service, kind_of)
    finally:
        saved_posts.HIDE_POSTS = held
    return out


def _measure(bank, bank_index, graph_builder, quiet_pages, saved_lists, saved_posts, sync_service, kind_of) -> dict:
    pages = bank_index.files(bank, "entities")
    media = [p for p in pages if str(p.frontmatter.get("type") or "").lower() == "media"]
    verdict = saved_posts.verdict(bank)
    posts = {p.stem: p for p in media if p.stem in verdict.state.posts}
    works = [p for p in media if p.stem not in posts]
    list_origins = {p.origin for p in saved_lists.PLATFORMS.values() if p.kind == "posts"} | {"pinterest"}

    by_sign: Counter = Counter()
    for pid in verdict.earned:
        for sign in verdict.signs[pid]:
            by_sign[sign] += 1
    rows = verdict.rows
    door = lambda p: str(p.frontmatter.get("origin") or "none")  # noqa: E731
    doors_without = Counter(door(p) for pid, p in posts.items() if door(p) not in list_origins)
    doors_without_rows = Counter(door(p) for pid, p in posts.items() if door(p) not in list_origins and pid in rows)

    from api.services import source_streams

    another_way = {site: len(ids) for site, ids in sorted(source_streams.another_way(bank).items())}

    pairs = []
    for pid, p in posts.items():
        site = verdict.state.sites.get(pid)
        found = saved_lists.canonical(site, str((p.frontmatter.get("media") or {}).get("url") or "")) if site else None
        if found:
            pairs.append((pid, [found[0], *found[1]]))
    doubled, extra = _components(pairs)

    related_lines = related_pages = 0
    for p in pages:
        try:
            changed = saved_posts.related_changed(bank, p.body())
        except Exception:  # noqa: BLE001 - one unreadable page costs its own count
            continue
        if changed:
            related_lines += changed
            related_pages += 1

    old_shape = 0
    for e in bank_index.files(bank, "episodes"):
        if e.frontmatter.get("has_note") and saved_posts._old_shape(e):
            old_shape += 1

    # The graph before (the flag off: what the route does today) and after (on), cold and warm, and its ETag.
    def build(on: bool):
        saved_posts.HIDE_POSTS = on
        bank_index.invalidate()
        graph_builder.reset_cache()
        cold, g = _ms(lambda: graph_builder.build_graph(bank))
        warm, _ = _ms(lambda: graph_builder.build_graph(bank))
        return cold, warm, g

    def etag(on: bool):
        saved_posts.HIDE_POSTS = on
        bank_index.invalidate()

        def one():
            with bank_index.shared_scans():   # the route's one listing of each folder, shared by the stamp and the ETag
                extra = f"|posts:False:{saved_posts.stamp(bank)}" if on else ""
                return sync_service.etag_for(bank, "entities", "edges", "hubs", "inbox", "logos", "photos", extra=extra)

        cold, _ = _ms(one)
        warm, _ = _ms(one)
        return cold, warm

    held_hide = saved_posts.HIDE_POSTS
    try:
        now_cold, now_warm, now = build(False)
        after_cold, after_warm, after = build(True)
        etag_off_cold, etag_off_warm = etag(False)
        etag_on_cold, etag_on_warm = etag(True)
    finally:
        saved_posts.HIDE_POSTS = held_hide
    degree_now = {n.id: n.degree for n in now.nodes}
    falls = [degree_now[n.id] - n.degree for n in after.nodes if n.id in degree_now and n.degree < degree_now[n.id]]
    now_ids = {n.id for n in now.nodes}
    left = [pid for pid in rows if pid in now_ids]
    left_visible = [pid for pid in left if str(posts[pid].frontmatter.get("status") or "active").lower() not in ARCHIVED]

    return {
        "pages": len(pages), "media_pages": len(media),
        "posts": len(posts), "works": len(works),
        "posts_by_site": dict(sorted(Counter(verdict.state.sites.get(pid) or "none" for pid in posts).items())),
        "posts_by_door": dict(sorted(Counter(door(p) for p in posts.values()).items())),
        "works_by_kind": dict(sorted(Counter(kind_of(p.frontmatter) or "none" for p in works).items())),
        "works_by_door": dict(sorted(Counter(door(p) for p in works).items())),
        "earned": len(verdict.earned), "rows": len(rows),
        "earned_by_sign": dict(sorted(by_sign.items())),
        "earned_with_several_signs": sum(1 for pid in verdict.earned if len(verdict.signs[pid]) > 1),
        "would_leave": {"graph_nodes": len(left), "graph_nodes_not_archived": len(left_visible),
                        "clusters_media": _clusters_media(now.nodes) - _clusters_media(after.nodes),
                        "clusters_media_now": _clusters_media(now.nodes),
                        "clusters_media_after": _clusters_media(after.nodes),
                        "graph_nodes_now": len(now.nodes), "graph_nodes_after": len(after.nodes),
                        "graph_links_now": len(now.links), "graph_links_after": len(after.links)},
        "degree": {"pages_whose_degree_falls": len(falls), "largest_fall": max(falls, default=0)},
        "doors_without_a_list": {"posts": sum(doors_without.values()), "rows": sum(doors_without_rows.values()),
                                 "by_door": dict(sorted(doors_without.items()))},
        "saved_another_way": another_way,
        "links_on_two_pages": {"links": doubled, "pages_beyond_the_first": extra},
        "related_lines": {"filtered": related_lines, "pages_carrying_them": related_pages},
        "old_shape_episodes": old_shape,
        "timing_ms": {"graph_build_cold_before": now_cold, "graph_build_warm_before": now_warm,
                      "graph_build_cold_after": after_cold, "graph_build_warm_after": after_warm,
                      "etag_cold_before": etag_off_cold, "etag_warm_before": etag_off_warm,
                      "etag_cold_after": etag_on_cold, "etag_warm_after": etag_on_warm},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="saved_posts_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="the bank directory (holds entities/ and episodes/)")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    print(json.dumps(measure(bank), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

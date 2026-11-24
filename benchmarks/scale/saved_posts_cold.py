"""The graph route's change check on a cold start, with saved posts drawn as rows (G246, ruling 81).

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.saved_posts_cold build --bank <dir>/bank
    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.saved_posts_cold measure --bank <dir>/bank [--reps 3]

``build`` writes a synthetic bank of the shape measured on a real memory (counts only, every name, link and sentence
synthetic): ~9,500 pages, ~5,000 of them saved items, ~450 of those posts, ~9,500 save and conversation records, a
handful of posts that earned a page and a handful of saves that carry a why-answer or a note.

``measure`` runs each case in a FRESH process (a cold start is a process's first call, and the cached headers are
process-local), once with ``saved_posts.HIDE_POSTS`` off and once on, and prints one JSON object: the milliseconds of

* ``check``: the graph route's change check, as the route computes it (the posts stamp and the ETag over one listing of
  each folder) — ``cold`` the first call in the process, ``warm`` the next, ``warm_stream`` the next while the app's
  stream holds the last walk's listings (``sync_ticker.reusable_listings``: no request lists a folder then);
* ``build``: ``graph_builder.build_graph`` — ``cold`` and ``warm``.

Each is the median of ``--reps`` fresh processes (cold) and of ``--reps * 5`` repeats inside one (warm).
``--after-restart`` adds a cold start that finds the digest a previous process stored (``saved_posts``, ``derived_store``).

Nothing touches a real bank, ``~/.cicada`` or ``HOME``: ``isolate`` pins every root to the scratch directory first.
"""
from __future__ import annotations

from . import isolate  # noqa: F401  - first: pins HOME and CICADA_HOME to the scratch directory

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import yaml

N_PAGES = 9500
N_SAVED = 5000
N_POSTS = 450
N_EPISODES = 9500
N_INBOX = 700
EARNED = 12           # posts that earned a page: a why-answer, a note, kept, named
SEED = 20261124

POST_URLS = (
    ("https://x.com/user_{u}/status/{n}", "x-bookmarks", 0.55),
    ("https://twitter.com/user_{u}/status/{n}", "x-likes", 0.10),
    ("https://www.instagram.com/p/C{n}/", "instagram-saved", 0.11),
    ("https://www.linkedin.com/feed/update/urn:li:activity:{n}/", "linkedin-saved", 0.09),
    ("https://www.reddit.com/r/example{u}/comments/{n}/a_thread/", "reddit-saved", 0.07),
    ("https://www.pinterest.com/pin/{n}/", "pinterest-saved", 0.06),
    ("https://x.com/user_{u}/status/{n}", "saved-link", 0.01),     # a pasted link: on no list
    ("https://x.com/user_{u}/status/{n}", "chrome-bookmark", 0.01),
)
WORK_URLS = (
    ("https://example.com/articles/{n}", "chrome-bookmark"),
    ("https://example.org/{u}/page-{n}", "saved-link"),
    ("https://www.youtube.com/watch?v={n:011d}", "youtube-playlist"),
    ("https://github.com/alpha-org-{u}/repo-{n}", "github-starred"),
    ("https://example.net/posts/{n}", "chrome-bookmark"),
)
TYPES = ("person", "concept", "project", "tool", "organization", "event", "place", "decision")
WORDS = ("signal graph memory sleep decay claim span evidence vector index lexical prose fence batch drain resolve "
         "ledger trailer session harness backend frontend render decode parse cache page bank owner").split()


def _doc(fm: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body


def _sentence(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def build(bank: Path, *, pages: int = N_PAGES, saved: int = N_SAVED, posts: int = N_POSTS,
          episodes: int = N_EPISODES, earned: int = EARNED) -> dict:
    from api.services import claims

    rng = random.Random(SEED)
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    (bank / "episodes").mkdir(parents=True, exist_ok=True)
    (bank / "hubs").mkdir(exist_ok=True)
    (bank / "_bank.yaml").write_text("name: synthetic-scale-bank\n", encoding="utf-8")

    day = lambda i: f"2026-{1 + (i * 10) // max(1, episodes):02d}-{1 + i % 28:02d}"   # noqa: E731
    save_ids: list[str] = []
    talk_ids: list[str] = []
    for i in range(episodes):
        (save_ids if i < saved else talk_ids).append(f"ep_{day(i)}_{i:05d}")

    # saved items: the first `posts` are posts, the rest works
    kinds = [spec for spec in POST_URLS for _ in range(max(1, round(spec[2] * posts)))][:posts]
    post_ids: list[str] = []
    for i, eid in enumerate(save_ids):
        pid = f"media-saved-item-{i:05d}"
        if i < posts:
            template, origin, _ = kinds[i % len(kinds)]
            url = template.format(u=i % 83, n=1000000000 + i * 7)
            post_ids.append(pid)
        else:
            template, origin = WORK_URLS[i % len(WORK_URLS)]
            url = template.format(u=i % 83, n=i * 13)
        mine = {}
        if i < earned:    # a why-answer, a note, kept, named: what earns a page
            mine = [{"saved_why": {"answer": "to build alpha"}}, {"has_note": True},
                    {"kept_as_page": {"at": "2026-11-22"}}, {"named": {"why": "title", "at": "2026-11-21"}}][i % 4]
        efm = {"id": eid, "source": "url", "timestamp": f"{day(i)}T10:00:00+00:00", "origin": origin, "url": url,
               "title": f"Synthetic saved item {i}", "media_entity_id": pid, "processed": i % 3 != 0, "saved_at": day(i),
               **mine}
        if efm["processed"]:
            efm["processed_by"] = "sleep"
        (bank / "episodes" / f"{eid}.md").write_text(
            _doc(efm, f"# Synthetic saved item {i}\n\n{_sentence(rng, 40)}\n"), encoding="utf-8")
        pfm = {"name": f"Synthetic saved item {i}", "type": "media", "status": "active", "confidence": 0.5,
               "decay_class": "active", "origin": origin, "created": day(i), "last_referenced": day(i),
               "source_episodes": [eid], "tags": ["saved"], "media": {"url": url, "media_type": "url"}}
        body = f"## Summary\n\n{_sentence(rng, 30)}\n"
        if i < posts:
            body = claims.write_claims(body, [claims.Claim(
                id=f"c{i:05d}", text=_sentence(rng, 12), subject=pid, observer="external:sleep",
                evidence=[claims.Evidence(episode=eid, start=0, end=4, kind="reasoning")])])
        (bank / "entities" / f"{pid}.md").write_text(_doc(pfm, body), encoding="utf-8")

    # conversations and the pages they made
    others = pages - saved
    for i, eid in enumerate(talk_ids):
        turns = [{"speaker": "user" if t % 2 == 0 else "assistant", "text": _sentence(rng, 30)} for t in range(6)]
        efm = {"id": eid, "source": "claude-code", "timestamp": f"{day(saved + i)}T09:00:00+00:00",
               "origin": "claude-code", "title": f"Synthetic conversation {i}", "session_id": f"ses_synth_{i:05d}",
               "processed": True, "processed_by": "sleep", "turns": turns}
        (bank / "episodes" / f"{eid}.md").write_text(_doc(efm, f"user: {_sentence(rng, 20)}\n"), encoding="utf-8")
    for i in range(others):
        pid = f"synthetic-page-{i:05d}"
        eps = [talk_ids[(i * 3 + k) % len(talk_ids)] for k in range(rng.randint(1, 3))]
        pfm = {"name": f"Synthetic page {i}", "type": TYPES[i % len(TYPES)], "status": "active", "confidence": 0.7,
               "decay_class": "durable", "created": day(i), "last_referenced": day(i), "source_episodes": eps,
               "aliases": [f"alias {i}"], "tags": [rng.choice(WORDS)]}
        if i % 40 == 0:
            pfm["type"] = "project"
            pfm["entities_added"] = [post_ids[(i // 40) % len(post_ids)]] if i % 400 == 0 else []
        if i % 25 == 0:
            pfm["sources"] = [{"url": f"https://example.com/{i}", "title": "a source"}]
        body = f"## Summary\n\n{_sentence(rng, 40)}\n"
        if i % 5 == 0:
            body = claims.write_claims(body, [claims.Claim(
                id=f"c-{i:05d}", text=_sentence(rng, 12), subject=pid, predicate="uses", object="a tool",
                observer="agent", evidence=[claims.Evidence(episode=eps[0], start=0, end=4, kind="user")])])
        (bank / "entities" / f"{pid}.md").write_text(_doc(pfm, body), encoding="utf-8")
    (bank / "inbox").mkdir(exist_ok=True)
    for i in range(N_INBOX):   # the ETag's inbox component reads these on a cold start, with the constant off too
        ifm = {"id": f"inbox-{i:05d}", "type": "clarification", "status": "pending", "kind": "same-name",
               "created": day(i), "entities": [f"synthetic-page-{i:05d}"], "priority": 0.5}
        (bank / "inbox" / f"inbox-{i:05d}.md").write_text(_doc(ifm, f"{_sentence(rng, 12)}\n"), encoding="utf-8")
    (bank / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": f"synthetic-page-{i:05d}", "target": f"synthetic-page-{i + 1:05d}", "label": "related to"}
        for i in range(0, 2000, 2)]}), encoding="utf-8")
    lists = _write_list_pages(bank)
    return {"pages": pages, "saved": saved, "posts": posts, "episodes": episodes, "earned": earned, "lists": lists}


def _write_list_pages(bank: Path) -> int:
    """The page each list that holds something has once the flip is on (``list_pages.sync`` writes them; written here
    straight, with no commit, so a bank that is not a git repository serves)."""
    from api.services import bank_index, list_pages, saved_posts

    held = saved_posts.HIDE_POSTS
    saved_posts.HIDE_POSTS = True
    try:
        bank_index.invalidate()
        wanted = list_pages.wanted(bank)
        for w in wanted:
            (bank / "entities" / f"{w.id}.md").write_text(
                _doc(list_pages._frontmatter(w, "2026-11-24"), list_pages._body(w)), encoding="utf-8")
        return len(wanted)
    finally:
        saved_posts.HIDE_POSTS = held
        bank_index.invalidate()


# ----------------------------------------------------------------------------------------------------- one case


def _ms(fn) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def case(bank: Path, on: bool, keep_digest: bool, warm_reps: int) -> dict:
    """One fresh process: the check cold and warm, then the build cold and warm, with the constant ``on`` or off."""
    import api.main  # noqa: F401  - a backend has every module imported before its first request
    from api.routers import graph as route
    from api.services import bank_index, graph_builder, saved_posts, sync_service

    keys = getattr(route, "_ETAG_KEYS", ("entities", "edges", "hubs", "inbox", "logos", "photos"))
    forget = getattr(saved_posts, "forget", lambda _bank, **_k: None)       # absent before the digest existed
    persist = getattr(saved_posts, "persist_now", lambda _bank: None)

    bank = bank.resolve()
    saved_posts.HIDE_POSTS = on
    if not keep_digest:
        forget(bank)    # a cold start that finds nothing stored
    bank_index.invalidate()
    graph_builder.reset_cache()

    def check():
        """What the route does. With the flip on: one block over the stamp and the ETag (``_etag_with_posts``); before the
        digest, the stamp and the ETag each listed the pages folder."""
        if saved_posts.HIDE_POSTS:
            if hasattr(route, "_etag_with_posts"):
                return route._etag_with_posts(bank, "x|y|z", False)
            return sync_service.etag_for(bank, *keys, extra=f"x|y|z|posts:False:{route._posts_stamp(bank)}")
        return sync_service.etag_for(bank, *keys, extra="x|y|z")

    cold = _ms(check)
    warm = statistics.median(_ms(check) for _ in range(warm_reps))
    # The running app keeps a stream open; its tick's listings answer a request while nothing moved (``sync_ticker``).
    with bank_index.shared_scans() as memo:
        check()
    walked = dict(memo)

    def seeded():
        with bank_index.shared_scans(seed=walked):
            return check()

    warm_stream = statistics.median(_ms(seeded) for _ in range(warm_reps))
    bank_index.invalidate()
    graph_builder.reset_cache()
    build_cold = _ms(lambda: graph_builder.build_graph(bank))
    build_warm = statistics.median(_ms(lambda: graph_builder.build_graph(bank)) for _ in range(warm_reps))
    if on:
        persist(bank)    # what a long-lived backend has stored by now: the next process starts from it
    return {"check_cold": round(cold, 1), "check_warm": round(warm, 2), "check_warm_stream": round(warm_stream, 2),
            "build_cold": round(build_cold, 1), "build_warm": round(build_warm, 2)}


def _run(bank: Path, *flags: str) -> dict:
    proc = subprocess.run([sys.executable, "-m", "benchmarks.scale.saved_posts_cold", "one", "--bank", str(bank), *flags],
                          check=True, capture_output=True, text=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def measure(bank: Path, reps: int, after_restart: bool) -> dict:
    out: dict = {}
    plan = [("off", False, False), ("on", True, False)]
    if after_restart:
        plan.append(("on_after_restart", True, True))
    for label, on, keep in plan:
        rows = []
        for _ in range(reps):
            if keep:    # one process leaves its record, the next is the cold start that finds it
                _run(bank, "--on", "--warm-reps", "1")
            rows.append(_run(bank, "--warm-reps", str(reps * 5), *(["--on"] if on else []),
                             *(["--keep-digest"] if keep else [])))
        out[label] = {k: round(statistics.median(r[k] for r in rows), 2) for k in rows[0]}
    if "on" in out and "off" in out:
        out["ratio_check_cold_on_over_off"] = round(out["on"]["check_cold"] / max(0.1, out["off"]["check_cold"]), 2)
        out["ratio_check_warm_on_over_off"] = round(out["on"]["check_warm"] / max(0.01, out["off"]["check_warm"]), 2)
        out["ratio_check_warm_stream_on_over_off"] = round(
            out["on"]["check_warm_stream"] / max(0.01, out["off"]["check_warm_stream"]), 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("build", "measure", "one"))
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--warm-reps", type=int, default=10)
    ap.add_argument("--on", action="store_true")
    ap.add_argument("--keep-digest", action="store_true")
    ap.add_argument("--after-restart", action="store_true")
    a = ap.parse_args()
    isolate.pin_bank(a.bank.resolve())
    if a.action == "build":
        print(json.dumps(build(a.bank.resolve())))
    elif a.action == "one":
        print(json.dumps(case(a.bank, a.on, a.keep_digest, a.warm_reps)))
    else:
        print(json.dumps(measure(a.bank, a.reps, a.after_restart), indent=1))


if __name__ == "__main__":
    main()

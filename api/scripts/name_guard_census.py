"""How much does the settling step's guard block on this bank? Counts only, for a fixed list of synthetic queries and links
(ruling 54; `name_guard`). Read-only: no model, no network, nothing written.

    api/.venv/bin/python -m api.scripts.name_guard_census --memory <bank>

It builds the guard as a Sleep run would, then asks it about :data:`QUERIES` and :data:`LINKS`, which name nobody from any
bank (``Bea Example`` and ``bex42`` are synthetic and are passed as the question's own cleared name and handle). It prints
per-kind pass and block counts by reason, each synthetic item with its verdict, how many ties and name-shaped words the guard
holds, and why the bank's open handle questions stand as they do (reason enums). It never prints a word from the bank.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

NAME, HANDLE = "Bea Example", "bex42"
#: What a model naturally writes about a public handle.
QUERIES = (
    "who is bex42", "bex42", "@bex42", "bex42 github", "bex42 twitter", "bex42 real name", "is bex42 a developer",
    "Bea Example", "Bea Example github profile", "Bea Example software engineer", "Bea Example bex42",
    "\"Bea Example\" bex42", "bex42 Bea Example account", "Bea Example personal website", "Bea Example blog",
    "Bea Example linkedin", "bex42 on X", "bex42 engineer on X", "Bea Example interview podcast", "bex42 open source projects",
    "Bea Example talk on agents", "Bea Example conference talk", "who runs the bex42 account", "bex42 profile bio",
)
#: What a search naturally returns.
LINKS = (
    "https://github.com/bex42", "https://bex42.github.io/", "https://x.com/bex42", "https://www.linkedin.com/in/bea-example",
    "https://news.ycombinator.com/item?id=12345678", "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://stackoverflow.com/users/1234567/bex42", "https://en.wikipedia.org/wiki/Bea_Example",
    "https://www.reddit.com/r/programming/comments/abc123/understanding_how_agents_work/",
    "https://medium.com/@bex42/how-i-think-about-statecharts-1a2b3c", "https://dev.to/bex42/writing-better-tools",
    "https://lobste.rs/s/abc123/the_comments_page", "https://pypi.org/user/bex42/", "https://www.npmjs.com/~bex42",
    "https://example.org/blog/2026/10/please-watch-this-item", "https://example.org/people/team/about-our-engineers",
    "https://conf.example.org/2026/speakers/bea-example", "https://gist.github.com/bex42/abcdef0123456789",
)


def census(memory: Path) -> dict:
    from api.services import inbox_service, markdown_parser, name_guard, public_handle, web_settle

    facts = web_settle.bank_facts(memory)
    started = time.monotonic()
    guard = name_guard.build(memory, facts)
    out: dict = {"build_seconds": round(time.monotonic() - started, 1), "ties": len(guard.ties),
                 "name_like_words": len(guard.name_like)}
    allowed = (NAME, HANDLE)
    query_rows = {q: guard.check(q, allowed=allowed) for q in QUERIES}
    link_rows = {u: guard.check_url(u, allowed=allowed) for u in LINKS}
    out["queries"] = {"total": len(QUERIES), "passed": sum(v is None for v in query_rows.values()),
                      "blocked": dict(Counter(v for v in query_rows.values() if v)), "each": query_rows}
    out["links"] = {"total": len(LINKS), "passed": sum(v is None for v in link_rows.values()),
                    "blocked": dict(Counter(v for v in link_rows.values() if v)), "each": link_rows}
    reasons: Counter = Counter()
    visible = {i.id for i in inbox_service.load_inbox(memory)}
    for path in sorted((memory / "inbox").glob("inbox-*.md")):
        if path.stem not in visible:
            continue
        fm = markdown_parser.parse(path).frontmatter
        if fm.get("kind") == "merge_suggestion":
            pair = public_handle.test(memory, fm, facts)
            reasons[f"{pair.reason}:searchable" if pair.public and pair.searchable else pair.reason] += 1
    out["open_same_person_questions_by_reason"] = dict(reasons)
    name_guard.release()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, required=True, help="the bank to read")
    args = parser.parse_args()
    if not (args.memory / "episodes").is_dir():
        print(f"{args.memory} holds no episodes/", file=sys.stderr)
        return 2
    json.dump(census(args.memory), sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

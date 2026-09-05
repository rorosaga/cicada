"""G117 — a checked-in synthetic demo bank: fictional people/projects/tools,
placeholder names only (`bob-example`, `alpha-project`, `example.com` — the
standing privacy rule), so a fresh viewer can try Sleep/Inbox/decay/graph
before wiring their own life in.

R7 (binding): fully deterministic, no LLM call and no `random` anywhere in
this module — every id, sentence and count below is a Python literal or a
plain deterministic loop over one, so `test_demo_bank.py` can assert exact
counts and exact filenames and get the same answer on every run, on every
machine. The one non-literal piece is `date.today()` itself: episode/entity
dates are relative to "today" so a demo bank always looks freshly captured
rather than visibly stale the day after it ships.

Reuses production writers end to end rather than hand-rolling shapes that
would drift from them:
  - `episode_ids.next_episode_id` / `utc_now_iso` (G114) for episode ids —
    the same collision-free rule every real capture writer uses.
  - `entity_body.compose_body_v2` + `decay_policy.frontmatter_fields` for
    entity pages — byte-identical structure to a Stage-1-created page.
  - `owner_identity.ensure_owner_entity` for the placeholder owner
    (`bob-example`) — so the demo bank's owner page and a real onboarded
    bank's owner page are ONE code path, not two things to keep in sync.
  - `agentic_write.write_claim` for the handful of claims below — the G118
    evidence-span verification (`api.services.evidence`) runs for real
    against the episode bodies just written, exactly as it would for a live
    bank, instead of a hand-rolled offset that could silently drift from
    what `evidence.locate` actually does.
"""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path

from api.services import decay_policy, entity_body, episode_ids, git_service, markdown_parser, owner_identity
from api.services.agentic_write import write_claim

# --- Entity roster (~60 total + the owner page `ensure_owner_entity` adds) --
#
# `bob-example` is deliberately ABSENT from `_PEOPLE`: it is reserved for
# `ensure_owner_entity` below, which either creates a fresh evergreen owner
# page or (Task 1's R3) merges into an existing one — a name that already has
# a generic `_write_entities` page would take the WRONG branch and end up
# `decay_class: active` instead of the owner's `evergreen`, breaking the
# byte-identical-to-a-real-bank promise R7 asks for.
_PEOPLE = [
    "carol-example", "dana-example", "erin-example", "frank-example", "grace-example",
    "henry-example", "iris-example", "jack-example", "karen-example", "leo-example",
    "maria-example", "nina-example", "oscar-example", "paula-example", "quinn-example",
]  # 15
_PROJECTS = [
    "alpha-project", "beta-project", "gamma-project", "delta-project", "epsilon-project",
    "zeta-project", "eta-project", "theta-project", "iota-project", "kappa-project",
    "lambda-project", "mu-project",
]  # 12
_TOOLS = [f"tool-example-{c}" for c in "abcdefghij"]  # 10
_COMPANIES = [
    "acme-example", "globex-example", "initech-example", "umbrella-example",
    "stark-example", "wayne-example", "hooli-example", "soylent-example",
]  # 8
_CONCEPTS = [
    "deep-work", "spaced-repetition", "code-review", "pair-programming", "dark-mode",
    "minimalism", "morning-routine", "note-taking", "remote-work", "open-source",
    "async-communication", "first-principles", "design-systems", "test-driven-development",
    "knowledge-management",
]  # 15

_ALL_ENTITIES = _PEOPLE + _PROJECTS + _TOOLS + _COMPANIES + _CONCEPTS  # 60

_ORIGINS = ("claude-code", "safari-tab", "telegram", "rss")

# One sentence skeleton per episode "slot" (i % len), each naming three
# entities by DISPLAY NAME only — episodes are raw, unlinked text per the
# Awake/Sleep split (CLAUDE.md), never a `[[wikilink]]`. Cycling through a
# fixed, small set of literal templates over a fixed entity rotation is what
# keeps this deterministic (R7) without hand-typing 40 unique paragraphs.
_EPISODE_SENTENCES = [
    "Spent the afternoon pairing on {a} with {b} — {c} kept coming up as the thing to fix next.",
    "Quick sync about {a}: {b} is blocking progress, so we talked through using {c} instead.",
    "{a} and {b} were the whole conversation today, with {c} left as the open question.",
    "Caught up on {a}. {b} is going well; still deciding whether {c} is worth adopting.",
    "Read through notes on {a} before deciding {b} needs {c} to move forward.",
    "Debated {a} versus {b} for a while, then circled back to {c} as the practical answer.",
    "{a} shipped a small update today, and {b} noticed it now depends on {c}.",
    "Long thread about {a}: {b} thinks {c} is the missing piece.",
    "Reviewed {a} with {b}; the takeaway was that {c} needs more attention.",
    "Planning session for {a}, where {b} and {c} both came up as dependencies.",
]


def populate(bank_dir: Path) -> None:
    """Fill an already-scaffolded (``bank_registry.scaffold_bank``) empty
    bank directory with the full synthetic graph: entities, episodes, inbox
    items, the placeholder owner, a handful of evidenced claims, and real git
    history. Idempotent only in the trivial sense that every write here is a
    fresh-file write — calling this twice on the same dir just re-stamps the
    same content (the router's ``POST /banks/demo`` refuses a second call by
    checking bank existence first, so this never needs to guard itself)."""
    bank_dir = Path(bank_dir)
    _write_entities(bank_dir)
    episodes = _write_episodes(bank_dir)
    _write_inbox(bank_dir, episodes)
    owner_identity.ensure_owner_entity(bank_dir, "Bob Example")
    _write_claims_with_evidence(bank_dir, episodes)
    _commit_history(bank_dir)


def _write_entities(bank_dir: Path) -> None:
    today = str(date.today())
    for kind, ids in (
        ("person", _PEOPLE),
        ("project", _PROJECTS),
        ("tool", _TOOLS),
        ("company", _COMPANIES),
        ("concept", _CONCEPTS),
    ):
        for entity_id in ids:
            fm = {
                "name": entity_id.replace("-", " ").title(),
                "type": kind,
                "status": "active",
                "confidence": 0.7,
                "created": today,
                "last_referenced": today,
                **decay_policy.frontmatter_fields(decay_policy.default_class_for(kind)),
                "source_episodes": [],
                "tags": [],
                "related": [],
                "version": 1,
                "layout_version": 2,
            }
            body = entity_body.compose_body_v2(
                summary=f"A synthetic {kind} for trying Cicada.",
                key_facts=[], history_entries=[], related=[], links=[], open_questions=[],
            )
            markdown_parser.write(bank_dir / "entities" / f"{entity_id}.md", fm, body)


def _write_episodes(bank_dir: Path) -> list[dict]:
    """~40 episodes across the four capture origins the plan names, dated
    over the last ~30 days. Returns the written records (id, sentence, the
    three entities it names) so ``_write_inbox``/``_write_claims_with_evidence``
    can cite REAL episode ids and REAL verbatim substrings rather than
    inventing their own — the same "cite what was actually written" shape a
    live bank's Sleep cycle produces.
    """
    episodes_dir = bank_dir / "episodes"
    today = date.today()
    n = len(_ALL_ENTITIES)
    records: list[dict] = []
    for i in range(40):
        day_offset = i % 30
        ep_date = today - timedelta(days=day_offset)
        ep_date_str = str(ep_date)
        ep_id = episode_ids.next_episode_id(episodes_dir, ep_date_str)

        a_id, b_id, c_id = (
            _ALL_ENTITIES[(i * 3) % n],
            _ALL_ENTITIES[(i * 3 + 7) % n],
            _ALL_ENTITIES[(i * 3 + 13) % n],
        )
        a, b, c = (x.replace("-", " ").title() for x in (a_id, b_id, c_id))
        sentence = _EPISODE_SENTENCES[i % len(_EPISODE_SENTENCES)].format(a=a, b=b, c=c)
        origin = _ORIGINS[i % len(_ORIGINS)]
        # Older episodes read as already consolidated by a past Sleep cycle;
        # the most recent ~6 days' worth are left `processed: false` so a
        # fresh viewer's Sleep/Inbox pages have a real, non-empty queue to
        # show rather than every episode already settled.
        processed = day_offset > 5

        fm: dict = {
            "id": ep_id,
            "timestamp": f"{ep_date_str}T09:00:00+00:00",
            "processed": processed,
            "origin": origin,
            "title": f"Notes on {a}",
        }
        if processed:
            fm["processed_by"] = "sleep"
        if origin == "claude-code":
            fm["harness"] = "claude-code"
            fm["session_id"] = f"ses_demo_{i:03d}"

        body = f"user: {sentence}"
        markdown_parser.write(episodes_dir / f"{ep_id}.md", fm, body)
        records.append({"id": ep_id, "sentence": sentence, "entities": (a_id, b_id, c_id), "date": ep_date_str})
    return records


# --- Inbox: 6 items across the four `kind`s (G60 question-object shape) ----


def _write_inbox(bank_dir: Path, episodes: list[dict]) -> None:
    inbox_dir = bank_dir / "inbox"
    today = str(date.today())
    stale = str(date.today() - timedelta(days=45))
    merge_source = episodes[0]

    # Two `decay` items: minimal shape (CLAUDE.md — decay is SERVED as a
    # question, synthesised at read from the subject's own `last_referenced`,
    # and must never be WRITTEN with an `options`/`question` payload — G115
    # R5). `beta-project`/`gamma-project` both exist as real entity pages.
    markdown_parser.write(
        inbox_dir / "inbox-001.md",
        {
            "kind": "decay", "status": "pending", "priority": 0.3,
            "entity_id": "beta-project", "entity_name": "Beta Project",
            "title": "No recent mentions of Beta Project", "created_date": stale,
        },
        "No recent mentions.",
    )
    markdown_parser.write(
        inbox_dir / "inbox-002.md",
        {
            "kind": "decay", "status": "pending", "priority": 0.25,
            "entity_id": "gamma-project", "entity_name": "Gamma Project",
            "title": "No recent mentions of Gamma Project", "created_date": stale,
        },
        "No recent mentions.",
    )

    # Two `conflict` items: full G60 question-object shape, modelled on
    # `test_inbox_questions.py`'s `_conflict_fm` fixture.
    markdown_parser.write(
        inbox_dir / "inbox-003.md",
        {
            "kind": "conflict", "required_input": "choice", "status": "pending",
            "entity_id": "dana-example", "entity_name": "Dana Example",
            "title": "Where does Dana Example work now?",
            "question": "Where does Dana Example work now?",
            "predicate": "works-at", "created_date": today, "claim_id": "clm_demo_new",
            "options": [
                {"key": "a", "label": "Acme Example", "claim_id": "clm_demo_old"},
                {"key": "b", "label": "Globex Example", "claim_id": "clm_demo_new"},
                {"key": "both", "label": "Both are true (different contexts)"},
            ],
        },
        "Conflicting employer claims.",
    )
    markdown_parser.write(
        inbox_dir / "inbox-004.md",
        {
            "kind": "conflict", "required_input": "choice", "status": "pending",
            "entity_id": "alpha-project", "entity_name": "Alpha Project",
            "title": "What does Alpha Project use now?",
            "question": "What does Alpha Project use now?",
            "predicate": "uses", "created_date": today, "claim_id": "clm_demo_new2",
            "options": [
                {"key": "a", "label": "Tool Example A", "claim_id": "clm_demo_old2"},
                {"key": "b", "label": "Tool Example B", "claim_id": "clm_demo_new2"},
                {"key": "both", "label": "Both are true (different contexts)"},
            ],
        },
        "Conflicting tooling claims.",
    )

    # One `clarification`: an ambiguous mention with no page yet — modelled
    # on `test_inbox_load_gate.py`'s clarification fixture (`entity_id` need
    # not resolve to a real page; a clarification is never gated on one).
    markdown_parser.write(
        inbox_dir / "inbox-005.md",
        {
            "kind": "clarification", "status": "pending",
            "entity_id": "sam-unclear", "entity_name": "Sam",
            "title": "Who is Sam?", "uncertainty_type": "who is this",
            "options": [], "created_date": today,
        },
        "A name came up with no existing page to attach it to.",
    )

    # One `merge_suggestion`: modelled on
    # `test_merge_direction_and_location.py`'s fixture — a mention that looks
    # like a near-duplicate of an existing tool page.
    markdown_parser.write(
        inbox_dir / "inbox-006.md",
        {
            "kind": "merge_suggestion", "required_input": "merge", "status": "pending",
            "entity_name": "Tool Example A (CLI)", "entity_id": "tool-example-a-cli",
            "merge_target_hint": "tool-example-a",
            "source_episode": merge_source["id"], "source_episode_timestamp": f"{merge_source['date']}T09:00:00+00:00",
            "created_date": today,
        },
        "Possible duplicate of an existing tool page.",
    )


# --- Claims: ~10 write_claim calls with real, verbatim evidence quotes -----

# (subject entity id, predicate, object, index into `episodes` to cite).
# Every subject here is a real page from `_write_entities`/`ensure_owner_entity`
# so `write_claim`'s `resolve_entity_file` hits its rung-1 exact-slug match —
# no near-match/ambiguous-subject branch, no incidental new page.
_CLAIM_SPECS: tuple[tuple[str, str, str, int], ...] = (
    ("carol-example", "uses", "Tool Example A", 0),
    ("alpha-project", "depends-on", "Tool Example B", 1),
    ("dana-example", "works-at", "Globex Example", 2),
    ("beta-project", "part-of", "Alpha Project", 3),
    ("erin-example", "prefers", "Dark Mode", 4),
    ("gamma-project", "uses", "Tool Example C", 5),
    ("frank-example", "works-with", "Grace Example", 6),
    ("deep-work", "description", "protecting long blocks of focused time", 7),
    ("acme-example", "located-in", "a remote-first office", 8),
    ("bob-example", "works-on", "Alpha Project", 9),
)


def _write_claims_with_evidence(bank_dir: Path, episodes: list[dict]) -> None:
    """Every subject but the owner's own is written with ``observer="agent"``
    — these read as Stage-1 extraction, matching the `Cicada-Author:
    <model>` "Sleep cycle" commits `_commit_history` folds them into below.
    `bob-example` (the placeholder owner) gets the portable ``"owner"``
    keyword instead, so its ONE claim resolves to `source_trust:
    "user_stated"` (`agentic_write.py`'s trust gate) and lands, honestly, in
    the dedicated `Cicada-Author: user` commit — the demo bank's one visible
    example of the two claim provenances the app actually distinguishes.
    """
    for subject, predicate, obj, idx in _CLAIM_SPECS:
        record = episodes[idx]
        observer = owner_identity.DEFAULT_OBSERVER if subject == "bob-example" else "agent"
        write_claim(
            bank_dir, subject, predicate, obj,
            observer=observer,
            confidence=0.75,
            source_episode=record["id"],
            evidence=[{"episode": record["id"], "quote": record["sentence"]}],
        )


# --- Git history: real Cicada-Author/Cicada-Engine trailers ---------------


def _run_commit(bank_dir: Path, message: str, paths: list[str]) -> None:
    """Run one `git_service.commit_paths` to completion from this module's
    plain-sync call sites.

    CORRECTNESS TRAP (why this wrapper exists at all): `commit_paths` is
    `async def` — it shells out via `asyncio.create_subprocess_exec`
    (`git_service.py`'s `_run_git`) — while `populate()` above is plain sync,
    called unawaited by `test_demo_bank.py` and via `run_in_threadpool`'s
    dedicated worker thread from `POST /banks/demo`. Calling the coroutine
    without awaiting it would silently create-and-drop a coroutine object and
    commit nothing. This is the exact guarded pattern already established at
    `calendar_registry.py:452-455` for a sync caller that needs one of these
    coroutines to actually run; the `except RuntimeError` branch (no loop
    running) is the only one either of this module's two call sites ever
    hits — `run_in_threadpool`'s worker thread has no event loop of its own.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(git_service.commit_paths(bank_dir, message, paths))


def _commit_history(bank_dir: Path) -> None:
    """A handful of commits grouped roughly the way a real Sleep cycle would
    write them, so `GET /contributors` and entity-history views have
    something real to show on a bank that has never actually run Sleep.

    `scaffold_bank` (called by the router before `populate`) already ran
    `git init`, but sets no commit identity — a fresh CI or install machine
    may have none configured globally, and this bank's history must be
    reproducible independent of whatever happens to be in the operator's
    `~/.gitconfig` (R7). Placeholder identity only, same class of value as
    every other name in this module.
    """
    subprocess.run(
        ["git", "-C", str(bank_dir), "config", "user.email", "demo@cicada.example"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(bank_dir), "config", "user.name", "Cicada Demo"],
        check=True, capture_output=True,
    )

    today = str(date.today())
    earlier = str(date.today() - timedelta(days=1))

    people_and_projects = [f"entities/{eid}.md" for eid in _PEOPLE + _PROJECTS]
    # Episode paths are re-derived from disk rather than threaded through as
    # a parameter — this function only needs paths to commit, not the record
    # dicts `_write_claims_with_evidence` needed for their sentence text.
    all_episode_paths = sorted(p.relative_to(bank_dir).as_posix() for p in (bank_dir / "episodes").glob("*.md"))
    first_half_episodes = all_episode_paths[:20]
    second_half_episodes = all_episode_paths[20:]

    _run_commit(
        bank_dir,
        git_service.build_commit_message(
            f"Sleep cycle {earlier}",
            [f"{p}: created (source: n/a, trigger: sleep/extraction)" for p in people_and_projects + first_half_episodes],
            authors=["gpt-5.4-mini"],
            engine="litellm",
        ),
        people_and_projects + first_half_episodes,
    )

    tools_companies_concepts = [f"entities/{eid}.md" for eid in _TOOLS + _COMPANIES + _CONCEPTS]
    inbox_paths = sorted(p.relative_to(bank_dir).as_posix() for p in (bank_dir / "inbox").glob("*.md"))
    _run_commit(
        bank_dir,
        git_service.build_commit_message(
            f"Sleep cycle {today}",
            [f"{p}: created (source: n/a, trigger: sleep/extraction)"
             for p in tools_companies_concepts + second_half_episodes + inbox_paths],
            authors=["claude-sonnet-5"],
            engine="claude-cli",
        ),
        tools_companies_concepts + second_half_episodes + inbox_paths,
    )

    # The owner page ONLY. `entities/bob-example.md` is never referenced by
    # the two commits above (`bob-example` is excluded from `_PEOPLE` — see
    # that list's docstring) and its ONE claim (`bob-example works-on Alpha
    # Project`) is the only `_CLAIM_SPECS` row written with
    # `observer=owner_identity.DEFAULT_OBSERVER` rather than `"agent"` — so
    # this file's entire diff is genuinely `Cicada-Author: user` content,
    # not a relabelled slice of what the two Sleep-cycle commits already
    # cover (folding an already-committed, unchanged path into a second
    # commit would stage nothing for it and silently understate what that
    # commit's own manifest claims to contain).
    owner_path = ["entities/bob-example.md"]
    _run_commit(
        bank_dir,
        git_service.build_commit_message(
            "Owner identity + starter claim",
            [f"{p}: created (trigger: user/companion_app)" for p in owner_path],
            authors=["user"],
        ),
        owner_path,
    )

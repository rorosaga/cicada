"""The recall hook's topic leg (2026-10-29): a message that names no page gets at most three current claims its words
find, ending with the pointer to ``cicada_recall(query)``.

A labelled set over a synthetic bank (placeholders and made-up syllables only — no real bank, no model, no network):
``TOPIC`` prompts each name the claim(s) that answer them; ``GENERIC`` prompts are everyday coding and writing asks
that must get nothing; ``NAMED`` prompts name a page, so the named note answers and the topic leg never runs. Run with
``-s`` for the numbers the PR reports: the share of topic prompts whose needed fact reached the note, and the
unrelated lines per note."""
from __future__ import annotations

import random
import time

import pytest

from api.services import bank_index, hook_recall, markdown_parser, recall_text, search_index

_SYLLABLES = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
              "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]
#: Everyday words a real bank's claims are full of, so they read as common here too (rarity is over the claims).
_COMMON = ["project", "meeting", "review", "test", "build", "plan", "week", "work", "team", "call", "notes", "app",
           "release", "list", "update", "email", "data", "model", "version", "issue"]


def _claim(cid, text, *, since="2026-09-01", until=None):
    row = f"- id: {cid}\n  text: \"{text}\"\n  predicate: note\n  object: x\n  valid_from: '{since}'\n"
    return row + (f"  valid_to: '{until}'\n" if until else "")


def _page(memory, eid, name, etype, claims, *, summary="", status="active"):
    body = (f"## Summary\n{summary}\n\n" if summary else "") + "```claims\n" + "".join(claims) + "```\n"
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": etype, "status": status, "confidence": 0.8, "aliases": [],
                           "tags": []}, body)


#: (page id, name, type, [(claim id, text)]) — the facts the labelled prompts ask about.
PAGES = [
    ("pat-owner", "Pat Owner", "person", [
        ("p1", "Pat runs along the river three mornings a week"),
        ("p2", "Pat is vegetarian and skips dairy at breakfast"),
        ("p3", "Pat prefers squash merges with one commit per pull request"),
        ("p4", "Pat's thesis defense presentation is on November 12"),
        ("p5", "Pat writes commit messages in the imperative mood"),
        ("p6", "Pat is allergic to penicillin"),
    ]),
    ("alpha-project", "Alpha Project", "project", [
        ("a1", "The onboarding redesign ships behind a feature flag on Friday"),
        ("a2", "The billing ledger moved from Mongo to Postgres in August"),
    ]),
    ("bob-example", "Bob Example", "person", [
        ("b1", "Bob Example prefers async standups over video calls"),
        ("b2", "Bob Example's daughter starts kindergarten in September"),
    ]),
    ("flat-hunt", "Flat Hunt", "concept", [
        ("f1", "The apartment search covers two-bedroom flats near the old town"),
        ("f2", "The landlord viewing for the canal apartment is on Tuesday"),
    ]),
    ("summer-trip", "Holiday Twenty", "event", [
        ("t1", "The summer trip budget is 2,000 euros including flights"),
        ("t2", "The trip itinerary starts in Lisbon and ends in Porto"),
    ]),
    ("sleep-cycle", "Sleep Cycle", "concept", [
        ("s1", "Consolidation runs nightly at 3am on the subscription plan"),
    ]),
    ("search-stack", "Search Stack", "tool", [
        ("x1", "The search index embeds passages with an on-device embedding model"),
    ]),
    ("example-corp", "Example Corp", "company", [
        ("e1", "The interview loop at Example Corp ends with a system design round"),
    ]),
    ("garden-plot", "Garden Plot", "location", [
        ("g1", "The tomato seedlings need repotting in early March"),
    ]),
    ("guitar-practice", "Evening Practice", "concept", [
        ("u1", "Pat practices fingerstyle guitar scales every evening"),
    ]),
    ("car-insurance", "Vehicle Cover", "concept", [
        ("c1", "The car insurance renewal is due in December"),
        ("c2", "The old car insurance policy was cancelled", ),
    ]),
    ("dentist", "Dentist", "concept", [
        ("d1", "The next dental cleaning appointment is booked for January"),
    ]),
    ("tax-return", "Freelance Paperwork", "concept", [
        ("r1", "The tax return needs the freelance invoices from the accountant"),
    ]),
    ("marathon-goal", "Marathon Goal", "concept", [
        ("m1", "The marathon training plan peaks at 32 kilometres in October"),
    ]),
]
#: A claim that is history, never recall: closed on the page it sits on.
CLOSED = ("car-insurance", "c2")

#: (prompt, the claim ids that answer it). None of these says a page's name.
TOPIC = [
    ("how many mornings a week do I go along the river", {"p1"}),
    ("remind me what I skip at breakfast", {"p2"}),
    ("how do I like pull requests merged, squash or rebase?", {"p3"}),
    ("when is my thesis defense presentation", {"p4"}),
    ("what mood should commit messages use for me", {"p5"}),
    ("am I allergic to any antibiotics like penicillin", {"p6"}),
    ("when does the onboarding redesign ship", {"a1"}),
    ("did the billing ledger move to postgres already", {"a2"}),
    ("does anyone prefer async standups to video calls", {"b1"}),
    ("when does the kindergarten start for the little one", {"b2"}),
    ("what size flats is the apartment search looking at", {"f1"}),
    ("when is the landlord viewing", {"f2"}),
    ("what's the budget for the summer trip", {"t1"}),
    ("where does the trip itinerary start and end", {"t2"}),
    ("what time does consolidation run at night", {"s1"}),
    ("which embedding model does the search index use", {"x1"}),
    ("what's the last round of the interview loop", {"e1"}),
    ("when should the tomato seedlings be repotted", {"g1"}),
    ("what guitar scales am I practicing", {"u1"}),
    ("when is the car insurance renewal due", {"c1"}),
    ("when is my next dental cleaning", {"d1"}),
    ("what does the accountant need for the tax return", {"r1"}),
    ("how far does the marathon training plan peak", {"m1"}),
]
#: Everyday asks about the work in front of the agent: nothing in the bank is what they are about.
GENERIC = [
    "Fix the failing test in the parser", "Summarize this error log for me", "Write a function that parses dates",
    "What does this stack trace mean", "Rename the variables to be clearer", "Make the button bigger on mobile",
    "Explain how async iterators work", "Why is the build slow today", "Draft a polite reply to this email",
    "Convert this list into a table", "Add type hints to this module", "Review the diff before I merge",
    "set up a github action that runs pytest on every push", "the release notes for this version need an update",
    "plan the data model for the team notes app", "write a regex that matches ISO dates",
]
#: Messages that name a page: the named note answers them, never the topic leg.
NAMED = [
    ("How is the Alpha Project going?", "alpha-project"),
    ("what does Bob Example think about the onboarding redesign", "bob-example"),
]


def _filler(rng: random.Random, n: int) -> list[str]:
    out = []
    for _ in range(n):
        words = ["".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4))) for _ in range(rng.randint(4, 8))]
        words.insert(rng.randrange(len(words)), rng.choice(_COMMON))
        if rng.random() < 0.5:
            words.insert(rng.randrange(len(words)), rng.choice(_COMMON))
        out.append(" ".join(words).capitalize())
    return out


def write_topic_bank(memory, *, filler: int = 1200) -> None:
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for eid, name, etype, claims in PAGES:
        rows = [_claim(cid, text, until="2026-08-01" if (eid, cid) == CLOSED else None) for cid, text in claims]
        _page(memory, eid, name, etype, rows, summary=f"About {name.lower()}.")
    rng = random.Random(11)
    texts = _filler(rng, filler)
    for i in range(0, len(texts), 12):
        eid = f"filler-{i // 12}"
        _page(memory, eid, f"Filler {i // 12}", "concept",
              [_claim(f"z{i + j}", t) for j, t in enumerate(texts[i:i + 12])])
    markdown_parser.write(memory / "_state.md", {"type": "state", "owner_id": "pat-owner"}, "")
    bank_index.invalidate()
    search_index.reset()
    search_index.rebuild(memory)


@pytest.fixture(autouse=True)
def _clean():
    hook_recall.reset()
    yield
    hook_recall.reset()
    search_index.reset()
    bank_index.invalidate()


@pytest.fixture(scope="module")
def topic_bank(tmp_path_factory):
    memory = tmp_path_factory.mktemp("topic") / "memory"
    write_topic_bank(memory)
    return memory


_TEXTS = {cid: text for _eid, _n, _t, claims in PAGES for cid, text in claims}


def _shown(note: str | None) -> set[str]:
    """The labelled claim ids whose words a note carries."""
    return {cid for cid, text in _TEXTS.items() if note and hook_recall.clip(text, hook_recall.CLAIM_CHARS) in note}


def _lines(note: str | None) -> int:
    return sum(1 for ln in (note or "").splitlines() if ln.startswith(("- ", "  · ")))


def score(memory) -> dict:
    """The labelled set's numbers: topic hits (needed fact in the note), unrelated lines per note, generic notes."""
    hits, notes, unrelated = 0, 0, 0
    for prompt, wanted in TOPIC:
        hook_recall.reset()
        r = hook_recall.prompt_context(memory, prompt)
        got = _shown(r.text)
        hits += bool(got & wanted)
        if r.text:
            notes += 1
            unrelated += _lines(r.text) - len(got & wanted)
    generic_notes = generic_lines = 0
    for prompt in GENERIC:
        hook_recall.reset()
        r = hook_recall.prompt_context(memory, prompt)
        if r.text:
            generic_notes += 1
            generic_lines += _lines(r.text)
    return {"topic": len(TOPIC), "hits": hits, "notes": notes, "unrelated": unrelated,
            "generic": len(GENERIC), "generic_notes": generic_notes, "generic_lines": generic_lines}


def _say(label: str, s: dict) -> str:
    return (f"{label}: {s['hits']}/{s['topic']} topic prompts got the needed fact; "
            f"{s['unrelated']} unrelated line(s) over {s['notes']} note(s); "
            f"{s['generic_notes']}/{s['generic']} generic prompts got a note ({s['generic_lines']} lines)")


def test_the_labelled_set(topic_bank, capsys, monkeypatch):
    s = score(topic_bank)
    with monkeypatch.context() as m:
        m.setattr(hook_recall, "topic_lines", lambda *_a, **_k: [])
        before = score(topic_bank)
    with capsys.disabled():
        print("\n" + _say("without the topic leg", before) + "\n" + _say("with the topic leg", s))
    assert before["hits"] == 0, "the labelled topic prompts name no page"
    assert s["hits"] >= 0.6 * s["topic"]
    assert s["unrelated"] <= 0.5 * max(1, s["notes"])
    assert s["generic_notes"] == 0


def test_a_topic_note_says_where_it_came_from_and_points_at_recall(topic_bank):
    r = hook_recall.prompt_context(topic_bank, "what's the budget for the summer trip")
    assert r.reason == "topic"
    assert r.injected == ("summer-trip",)
    assert recall_text.is_injection(r.text)            # Cicada's own note: never captured as the person's words
    assert r.text.startswith(recall_text.TOPIC_HEADER)
    assert r.text.rstrip().endswith(recall_text.TOPIC_FOOTER)
    assert "`cicada_recall(query)`" in r.text
    assert r.tokens <= hook_recall.MAX_TOKENS


def test_a_named_page_answers_and_the_topic_leg_never_runs(topic_bank, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("the topic leg ran for a named page")

    monkeypatch.setattr(hook_recall, "topic_lines", boom)
    for prompt, page in NAMED:
        hook_recall.reset()
        r = hook_recall.prompt_context(topic_bank, prompt)
        assert r.reason == "injected" and page in r.injected, prompt


def test_a_closed_claim_never_rides(topic_bank):
    r = hook_recall.prompt_context(topic_bank, "was the old car insurance policy cancelled")
    assert "cancelled" not in (r.text or "")


def test_a_claim_closed_on_disk_after_the_index_read_never_rides(tmp_path):
    memory = tmp_path / "memory"
    write_topic_bank(memory, filler=120)
    assert "summer trip budget" in (hook_recall.prompt_context(memory, "what's the budget for the summer trip").text
                                    or "")
    # The page changes on disk; the index has not caught up (no invalidate, no rebuild).
    _page(memory, "summer-trip", "Holiday Twenty", "event",
          [_claim("t1", "The summer trip budget is 2,000 euros including flights", until="2026-09-02"),
           _claim("t2", "The trip itinerary starts in Lisbon and ends in Porto")])
    hook_recall.reset()
    r = hook_recall.prompt_context(memory, "what's the budget for the summer trip")
    assert "summer trip budget" not in (r.text or "")


def test_a_page_the_session_was_just_shown_steps_aside(topic_bank):
    first = hook_recall.prompt_context(topic_bank, "when is the landlord viewing")
    assert first.injected == ("flat-hunt",)
    again = hook_recall.prompt_context(topic_bank, "when is the landlord viewing", recent=frozenset(first.injected))
    assert again.text is None


def test_no_time_left_means_no_topic_note(topic_bank):
    r = hook_recall.prompt_context(topic_bank, "what's the budget for the summer trip", deadline=time.monotonic())
    assert r.text is None and r.reason == "no_match"


def test_the_vectors_order_what_the_words_found_never_add(topic_bank, monkeypatch):
    """R-H4 on the topic leg: with a warm embedder the stored claim vectors re-order lines the words found, and a
    claim only the vectors rank never rides."""
    monkeypatch.setattr(hook_recall, "_semantic_claim_ranks", lambda *_a, **_k: {"z5": 0, "f2": 1, "f1": 2})
    r = hook_recall.prompt_context(topic_bank, "the apartment search and the landlord viewing for flats",
                                   deadline=time.monotonic() + 5)
    assert "Z5" not in (r.text or "") and r.reason in ("topic", "no_match")


def test_the_prompt_is_never_logged(topic_bank, monkeypatch):
    seen: list[str] = []
    from loguru import logger

    sink = logger.add(lambda m: seen.append(str(m)), level="DEBUG")
    try:
        monkeypatch.setattr(hook_recall, "topic_lines", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        r = hook_recall.prompt_context(topic_bank, "secret-word-qx what's the budget for the summer trip")
    finally:
        logger.remove(sink)
    assert r.text is None
    assert not any("secret-word-qx" in line or "boom" in line for line in seen)

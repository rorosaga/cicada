"""G149 — the recall hook's engine: which pages a prompt NAMES (R-H2), what a
note says about them (R-H5), the session window (R-H7) and the on-device-only
re-rank (R-H4). Synthetic bank only (alpha-project, bob-example, example.com);
no real bank, no ~/.cicada, no model, no network."""
from __future__ import annotations

import numpy as np
import pytest

from api.services import (
    bank_index, hook_recall, markdown_parser, mcp_tools, providers, recall_text, search_index,
)


def _claim(cid: str, text: str, *, subject: str, since: str | None = None, until: str | None = None) -> str:
    row = f"- id: {cid}\n  text: \"{text}\"\n  subject: {subject}\n  predicate: note\n  object: x\n"
    if since:
        row += f"  valid_from: '{since}'\n"
    if until:
        row += f"  valid_to: '{until}'\n"
    return row


def _page(memory, eid, name, etype, *, aliases=(), summary="", claims=(), status="active", confidence=0.7,
          extra_body=""):
    body = (f"## Summary\n{summary}\n\n" if summary else "") + extra_body
    if claims:
        body += "```claims\n" + "".join(claims) + "```\n"
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": etype, "status": status, "confidence": confidence,
                           "aliases": list(aliases), "tags": []}, body)


def _index(memory):
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


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    _page(memory, "alpha-project", "Alpha Project", "project", aliases=["Alpha"], confidence=0.9,
          summary="Rebuilding the onboarding flow for the beta.",
          claims=[_claim("c1", "The beta ships on October 1.", subject="alpha-project", since="2026-09-01"),
                  _claim("c2", "Bob Example reviews the designs.", subject="alpha-project", since="2026-08-20"),
                  _claim("c3", "The beta ships in September.", subject="alpha-project", since="2026-07-01",
                         until="2026-09-01"),
                  _claim("c4", "The team uses a shared board.", subject="alpha-project", since="2026-06-01")])
    _page(memory, "bob-example", "Bob Example", "person", aliases=["Bob"], summary="Designer on the alpha project.",
          claims=[_claim("c5", "Works at Example Corp.", subject="bob-example", since="2026-05-01")])
    _page(memory, "example-corp", "Example Corp", "company", summary="A design studio.")
    _page(memory, "memory-concept", "Memory", "concept", summary="How recall works.")
    _page(memory, "temporal-decay", "Temporal Decay", "concept", summary="Silence is a signal.")
    _page(memory, "python-tool", "Python", "tool", summary="Prefers uv over pip.")
    _page(memory, "zurich", "Zürich", "location", summary="Where the studio is.")
    _page(memory, "old-project", "Old Project", "project", status="archived", summary="Wound down.")
    _page(memory, "pat-owner", "Pat Owner", "person", aliases=["Pat"], summary="The person this memory is for.")
    _page(memory, "gamma-thing", "Gamma Thing", "concept")                      # nothing to say
    _page(memory, "cicada-api", "Cicada Api", "directory", summary="A checkout.")
    _page(memory, "delta-zero", "Delta Zero", "concept", summary="Mentions alpha in its body only.")
    markdown_parser.write(memory / "_state.md", {"type": "state", "owner_id": "pat-owner"}, "")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "question": "Is the beta still on October 1?",
                           "priority": 0.5}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "bob-example",
                           "entity_name": "Bob Example", "question": "Which studio?",
                           "remind_after": "2099-01-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-003.md",
                          {"kind": "normalization", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "question": "Fold a predicate?"}, "ctx")
    _index(memory)
    return memory


# R-H2's table: the floor, decided on these and recorded as the ruling.
CASES = [
    ("How is the Alpha Project going?", ["alpha-project"]),
    ("can you ask bob about the designs", ["bob-example"]),
    ("Draft an email to Bob Example and cc the alpha team", ["bob-example", "alpha-project"]),
    ("What did we decide about temporal decay?", ["temporal-decay"]),
    ("Is Example Corp still a client?", ["example-corp"]),
    ("write a python script to rename files", ["python-tool"]),
    ("ALPHA PROJECT status?", ["alpha-project"]),
    ("book a desk at the zurich office", ["zurich"]),
    ("fix the failing test in the parser", []),
    ("there's a memory leak in the app", []),            # a one-word concept name is never a mention
    ("let's decay the learning rate", []),               # half of a two-word name is not the name
    ("the example in the docs is wrong", []),            # "example" alone names neither Example page
    ("what happened to the old project", []),            # archived
    ("Pat, remember to push", []),                       # the owner is the primer's, not a note's
    ("open cicada api in the editor", []),               # a directory never
    ("tell me about gamma thing", []),                   # a page with nothing to say
    ("thanks!", []),
    ("ok", []),
]


@pytest.mark.parametrize("prompt,expected", CASES, ids=[c[0][:32] for c in CASES])
def test_the_floor_injects_only_what_the_message_names(bank, prompt, expected):
    result = hook_recall.prompt_context(bank, prompt)
    assert list(result.injected) == expected, result.reason
    assert (result.text is None) == (not expected)


def test_a_miss_says_why_in_an_enum(bank):
    assert hook_recall.prompt_context(bank, "ok").reason == "no_terms"
    assert hook_recall.prompt_context(bank, "fix the failing test").reason == "no_match"
    assert hook_recall.prompt_context(bank, "alpha project?").reason == "injected"
    assert set(hook_recall.REASONS) >= {"injected", "primer", "no_terms", "no_match", "recently_shown",
                                        "index_not_ready", "no_bank", "timeout", "error"}


def test_the_note_says_what_the_page_holds_and_nothing_stale(bank):
    result = hook_recall.prompt_context(bank, "How is the Alpha Project going?")
    text = result.text
    assert text.startswith(recall_text.RECALL_HEADER) and text.endswith(recall_text.RECALL_FOOTER)
    assert "- Alpha Project (project, `alpha-project`): Rebuilding the onboarding flow for the beta." in text
    assert "  · The beta ships on October 1. (since 2026-09-01)" in text
    assert "  · Bob Example reviews the designs. (since 2026-08-20)" in text
    assert "September" not in text, "a closed claim is history, not recall"
    assert "shared board" not in text, "at most two current claims, newest first"
    assert "`inbox-001`" in text and "Is the beta still on October 1?" in text
    assert "inbox-003" not in text, "normalization items are app-only (check_nudges' filter)"
    assert 'cicada_check_nudges(entity_ids=["alpha-project"])' in text
    assert result.inbox_id == "inbox-001" and result.tokens <= hook_recall.MAX_TOKENS


def test_a_deferred_question_is_never_pointed_at(bank):
    result = hook_recall.prompt_context(bank, "can you ask bob about it")
    assert result.injected == ("bob-example",) and "inbox-002" not in result.text and result.inbox_id is None


def test_the_body_never_names_a_page(bank):
    with search_index.Reader(bank) as reader:
        docs = reader.docs([d for d, _ in reader.name_candidates(["alpha"], 40)])
    assert "delta-zero" not in {d.ref for d in docs.values()}, "R-H3: title and aliases only"


def test_the_note_never_exceeds_its_budget(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    long = "word " * 400
    for n in range(3):
        _page(memory, f"huge-{n}", f"Huge {n} " + "x" * 190, "project", aliases=[f"Hugealias{n}"], summary=long,
              claims=[_claim(f"h{n}{k}", long[:390], subject=f"huge-{n}", since=f"2026-09-0{k + 1}")
                      for k in range(3)])
    _index(memory)
    result = hook_recall.prompt_context(memory, "hugealias0 hugealias1 hugealias2")
    assert result.text and result.tokens <= hook_recall.MAX_TOKENS
    assert result.injected and result.injected[0] in {"huge-0", "huge-1", "huge-2"}
    for page_id in result.injected:
        assert f"`{page_id}`" in result.text, "the ledger and the window record only what was shown"


def test_recently_shown_pages_step_aside_for_two_firings(bank):
    session = "s-1"

    def fire(prompt):
        result = hook_recall.prompt_context(bank, prompt, recent=hook_recall.RECENT.recent(session))
        hook_recall.RECENT.remember(session, result.injected)
        return result

    assert fire("Alpha Project?").injected == ("alpha-project",)                    # t1
    assert fire("and the alpha project budget?").reason == "recently_shown"          # t2: t1 is in the window
    assert fire("alpha project again").reason == "recently_shown", "t3: the window [t1, t2] still holds t1"
    assert fire("alpha project, once more").injected == ("alpha-project",), "t4: the window is [t2, t3]"
    assert fire("fix the failing test").reason == "no_match"                        # a miss ages the window too
    hook_recall.RECENT.reset(session)
    assert fire("alpha project").injected == ("alpha-project",), "SessionStart resets the window"


def test_the_window_is_bounded():
    window = hook_recall.RecentPages(turns=2, sessions=3)
    for n in range(5):
        window.remember(f"s{n}", ["alpha-project"])
    assert window.recent("s0") == frozenset() and window.recent("s4") == {"alpha-project"}


def test_a_long_prompt_reads_its_head_and_its_tail(bank):
    pasted = "lorem ipsum dolor " * 1500
    assert hook_recall.prompt_context(bank, pasted + " so how is the alpha project?").injected == ("alpha-project",)
    middle = "lorem " * 1200 + "alpha project " + "ipsum " * 3000
    assert hook_recall.prompt_context(bank, middle).injected == ()
    window = hook_recall.prompt_window("a" * 20_000)
    assert len(window) == hook_recall.HEAD_CHARS + 1 + hook_recall.TAIL_CHARS


def test_no_usable_index_injects_nothing(bank, monkeypatch):
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    assert hook_recall.prompt_context(bank, "alpha project").reason == "index_not_ready"


def test_the_session_primer_fits_both_harness_caps(bank):
    for harness in ("claude-code", "codex"):
        result = hook_recall.session_primer(bank, harness)
        assert result.reason == "primer" and result.injected == ()
        assert result.text.startswith(recall_text.PRIMER_HEADER)
        assert "# Cicada — personal memory for this person" in result.text
        assert len(result.text) <= 9_500, "Claude Code caps a hook string at 10,000 chars; Codex at 2,500 tokens"
    assert recall_text.is_injection(hook_recall.session_primer(bank, "codex").text)


def test_nudge_visible_is_check_nudges_filter():
    today = "2026-09-24"
    base = {"kind": "conflict", "entity_id": "alpha-project"}
    assert mcp_tools.nudge_visible(base, wanted={"alpha-project"}, today=today)
    assert not mcp_tools.nudge_visible({**base, "kind": "normalization"}, wanted=set(), today=today)
    assert not mcp_tools.nudge_visible(base, wanted={"bob-example"}, today=today)
    assert not mcp_tools.nudge_visible({**base, "remind_after": "2099-01-01"}, wanted=set(), today=today)
    assert not mcp_tools.nudge_visible(base, wanted=set(), today=today, skipped={"inbox-9"}, stem="inbox-9")
    assert mcp_tools.nudge_visible(base, wanted=set(), today=today), "no ids = no entity filter (check_nudges)"


# --- R-H4: the stored vectors re-order named pages, only on-device and already loaded ---

MODEL = "test/on-device-model"


def _one_hot(texts, *, is_query=False):
    rows = np.zeros((len(texts), 8), dtype=np.float32)
    for i, text in enumerate(texts):
        rows[i, 0] = 0.01
        for k in range(1, 6):
            if f"k{k}" in text.lower().split():
                rows[i, k] = 1.0
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


@pytest.fixture
def five(tmp_path):
    from api.services.vector_index import SqliteVecIndexer

    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    words = ["One", "Two", "Three", "Four", "Five"]
    for n, word in enumerate(words, 1):
        _page(memory, f"alpha-{word.lower()}", f"Alpha {word}", "project", aliases=["Alpha"],
              confidence=1.0 - n / 10, summary=f"Marker k{n} lives here.")
    _page(memory, "zeta-page", "Zeta Page", "project", summary="Marker k5 k5 k5.")   # the vectors' favourite
    _index(memory)
    SqliteVecIndexer(memory, embed_fn=_one_hot, model_name=MODEL).index_entities()
    return memory


def test_the_vectors_reorder_pages_the_message_named_when_the_model_is_warm(five, monkeypatch):
    calls = []

    def embed(texts, *, is_query=False):
        calls.append(is_query)
        return _one_hot(texts, is_query=is_query)

    monkeypatch.setitem(providers._EMBED_CACHE, MODEL, (embed, MODEL))
    result = hook_recall.prompt_context(five, "what about alpha k5", deadline=10**9, clock=lambda: 0.0)
    assert result.injected[0] == "alpha-five" and len(result.injected) == 3
    assert "zeta-page" not in result.injected, "R-H4: the vectors never add a page the message did not name"
    assert calls == [True]


def test_a_cold_or_hosted_model_is_never_loaded_or_called(five, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the hook must never build or call an embedder here")

    monkeypatch.setattr(providers, "cached_embed_fn_for_model", boom)
    monkeypatch.setattr(providers, "resolve_embed_fn_for_model", boom)
    lexical = ("alpha-one", "alpha-two", "alpha-three")
    assert hook_recall.prompt_context(five, "alpha k5", deadline=10**9, clock=lambda: 0.0).injected == lexical
    hook_recall.reset()
    monkeypatch.setattr(hook_recall, "_recorded_model", lambda _m: "text-embedding-3-small")
    monkeypatch.setitem(providers._EMBED_CACHE, "text-embedding-3-small", (boom, "text-embedding-3-small"))
    assert hook_recall.prompt_context(five, "alpha k5", deadline=10**9, clock=lambda: 0.0).injected == lexical
    assert providers.warm_local_embed_fn("openrouter/google/gemini-embedding") is None
    assert providers.warm_local_embed_fn(None) is None and providers.warm_local_embed_fn("unknown") is None


def test_no_time_left_means_no_rerank(five, monkeypatch):
    monkeypatch.setitem(providers._EMBED_CACHE, MODEL, (_one_hot, MODEL))
    result = hook_recall.prompt_context(five, "alpha k5", deadline=0.1, clock=lambda: 0.0)
    assert result.injected == ("alpha-one", "alpha-two", "alpha-three")

"""G235, ruling 60: the one door to every engine. Made-up values only."""
from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import (agent_engine, bank_index, cli_engines, episode_revision, markdown_parser, providers,
                          revision_prose, sensitive_flags as sf, sensitive_hold as hold, sensitive_text as st, turn_signals)
from api.services.connections.base import CliResult

VALUE = "Zebra7-lantern"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh():
    hold.forget()
    bank_index.invalidate()
    yield
    hold.forget()


def _ep(bank: Path, ep: str, body: str, **fm) -> None:
    (bank / "episodes").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(bank / "episodes" / f"{ep}.md", {"id": ep, "processed": False, "source": "chatgpt", **fm}, body)
    bank_index.invalidate()


@pytest.fixture
def bank(tmp_path) -> Path:
    _ep(tmp_path, "ep_2026-11-01_001", f"user: my password is {VALUE}\nassistant: Logged in with {VALUE}.")
    return tmp_path


def _user(text: str) -> list[dict]:
    return [{"role": "system", "content": "Be useful."}, {"role": "user", "content": text}]


def test_a_value_on_record_is_held_wherever_it_stands_in_any_prompt(bank):
    """Reply notes, a question's evidence, a web query, a page's prose: the door does not ask what a line is."""
    for line in (f'[s1: speaker:Ana loved user "the wifi password is {VALUE}"]',
                 f"Evidence: 2026-11-01: Logged in with {VALUE}.",
                 f"Search the web for: {VALUE}",
                 f"[[{VALUE}]] is on the page",
                 json.dumps({"object": VALUE})):
        out = hold.hold_back(_user(line), bank)[1]["content"]
        assert VALUE not in out and "[held back: password]" in out


def test_a_value_cut_in_two_by_a_length_limit_is_covered(bank):
    assert "Zebra7" not in hold.hold_back(_user('reply to "Zebra7-la…" said'), bank)[1]["content"]
    assert "Zebra7-lan" not in hold.hold_back(_user("the last line ends in Zebra7-lan"), bank)[1]["content"]


def test_a_non_ascii_value_and_a_reformatted_card_are_the_same_value(tmp_path):
    _ep(tmp_path, "ep_1", "user: my password is Añoranza7\nuser: my card is 4539 1488 0343 6467")
    for sent, gone in (('{"object": "A\\u00f1oranza7"}', "oranza7"), ("charged 4539-1488-0343-6467 today", "6467")):
        assert gone not in hold.hold_back(_user(sent), tmp_path)[1]["content"]


def test_system_text_is_not_read_by_itself_but_a_value_on_record_goes(bank):
    messages = [{"role": "system", "content": f"my password is Other9value then {VALUE}"}]
    out = hold.hold_back(messages, bank)[0]["content"]
    assert "Other9value" in out and VALUE not in out


def test_a_prompt_is_read_by_itself_for_words_no_conversation_holds_yet(tmp_path):
    """A saved reason or a page's prose: no episode to find it in."""
    assert "Other9value" not in hold.hold_back(_user("I saved it because my password is Other9value"), tmp_path)[1]["content"]
    assert hold.hold_back(_user("Search for the password reset page"), tmp_path)[1]["content"].endswith("reset page")


def test_nothing_to_hold_returns_the_callers_own_list_and_never_touches_it(bank, tmp_path):
    clean = _user("the trip was fine")
    assert hold.hold_back(clean, bank) is clean
    dirty = _user(f"said {VALUE}")
    assert hold.hold_back(dirty, bank) is not dirty
    assert VALUE in dirty[1]["content"]          # a retry starts from what the caller built


def test_a_multipart_message_is_held_too(bank):
    out = hold.hold_back([{"role": "user", "content": [{"type": "text", "text": f"said {VALUE}"}]}], bank)
    assert VALUE not in out[0]["content"][0]["text"]


def test_what_the_person_left_is_read_again(tmp_path):
    _ep(tmp_path, "ep_1", f"user: my password is {VALUE}", sensitive={"kept": {"password": 1}})
    assert VALUE in hold.hold_back(_user(f"my password is {VALUE}"), tmp_path)[1]["content"]


def test_an_unsure_value_is_read(tmp_path):
    _ep(tmp_path, "ep_1", "user: my password is lanternfish.")
    assert "lanternfish" in hold.hold_back(_user("my password is lanternfish."), tmp_path)[1]["content"]


def test_a_short_confident_value_goes_only_on_a_line_that_speaks_of_a_secret(tmp_path):
    _ep(tmp_path, "ep_1", "user: my password is 4821")
    out = hold.hold_back(_user("the port is 4821\nthe password was 4821"), tmp_path)[1]["content"]
    assert out == "the port is 4821\nthe password was [held back: password]"


def test_a_change_in_the_bank_is_seen_on_the_next_call(tmp_path):
    _ep(tmp_path, "ep_1", "user: nothing here")
    assert VALUE in hold.hold_back(_user(f"said {VALUE}"), tmp_path)[1]["content"]
    _ep(tmp_path, "ep_1", f"user: my password is {VALUE} now, and a longer line")
    assert VALUE not in hold.hold_back(_user(f"said {VALUE}"), tmp_path)[1]["content"]


def test_a_broken_bank_never_fails_a_read_and_a_prompt_is_still_read_by_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(hold, "on_record", lambda _p: 1 / 0)
    (tmp_path / "episodes").mkdir()
    out = hold.hold_back(_user(f"my password is {VALUE}"), tmp_path)[1]["content"]
    assert VALUE not in out


# ------------------------------------------------------------------ every engine, through the real resolver


def _settings(bank: Path, mode: str) -> Settings:
    return Settings(CICADA_MEMORY_ROOT=bank, llm_mode=mode, litellm_model="fake-engine")


def _ok_runner(seen: list):
    def run(argv, *, stdin=None, **_kw):
        seen.append(" ".join(map(str, argv)) + (stdin or ""))
        event = {"type": "result", "subtype": "success", "is_error": False, "result": "{}", "usage": {}}
        return CliResult(returncode=0, stdout=json.dumps(event) + "\n", stderr="")

    return run


@pytest.mark.parametrize("mode", ["agent", "codex", "cursor", "opencode", "grok"])
def test_the_wire_of_every_plan_engine(bank, mode, monkeypatch):
    seen: list[str] = []

    def by_cli(*_a, messages, **_kw):        # the tool is not installed here; this is the last thing it is handed
        seen.append(json.dumps(messages))
        raise RuntimeError("stop")

    monkeypatch.setattr(cli_engines, "complete", by_cli)
    with agent_engine.use_scope(f"t:{mode}"):
        fn = providers.resolve_llm_fn(_settings(bank, mode), stage="t", runner=_ok_runner(seen), sink=lambda _e: None,
                                      is_async=False)
        try:
            fn(messages=_user(f"Logged in with {VALUE}"))
        except Exception:  # noqa: BLE001 - a fake envelope may not parse; what reached the wire is the point
            pass
    assert seen and all(VALUE not in s for s in seen)


def test_the_wire_of_a_metered_engine_sync_and_awaited(bank):
    seen: list[str] = []

    def sync_completion(**kw):
        seen.append(json.dumps(kw["messages"]))
        return SimpleNamespace(choices=[], usage=None, model="m")

    async def async_completion(**kw):
        return sync_completion(**kw)

    settings = _settings(bank, "byok")
    providers.resolve_llm_fn(settings, completion=sync_completion, sink=lambda _e: None)(messages=_user(f"said {VALUE}"))
    asyncio.run(providers.resolve_llm_fn(settings, completion=async_completion, sink=lambda _e: None)(
        messages=_user(f"said {VALUE}")))
    assert len(seen) == 2 and all(VALUE not in s for s in seen)


def test_a_hosted_embedding_model_is_behind_the_door_and_a_local_one_has_none(bank, monkeypatch):
    seen: list = []

    class Client:
        class embeddings:     # noqa: N801
            @staticmethod
            def create(model, input):     # noqa: A002
                seen.extend(input)
                return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0]) for _ in input])

    fn, _name = providers.resolve_embed_fn_for_model("text-embedding-3-small", _settings(bank, "byok"),
                                                     openai_client_factory=lambda: Client)
    fn([f"passage with {VALUE}"])
    assert seen and VALUE not in seen[0]


# ------------------------------------------------------------------ nothing reaches a model another way


MODEL_ATTRS = {"completion", "acompletion", "responses", "aresponses", "embedding", "aembedding"}
SEND_OWNERS = {"agent_engine", "codex_engine", "cli_engines"}


def _bypasses(source: str) -> list[str]:
    """Every way this file could reach a model without `providers.resolve_llm_fn`: calling a completion function itself,
    calling an engine's own ``complete``, or building the plan CLI's argv. A reference may only be handed to the resolver
    (``completion=...``) or named ``completion`` on its way there."""
    tree = ast.parse(source)
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            allowed.update(id(k.value) for k in node.keywords if k.arg == "completion")
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "completion" for t in node.targets):
            allowed.add(id(node.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in MODEL_ATTRS and id(node) not in allowed:
            owner = node.value
            named = owner.id if isinstance(owner, ast.Name) else (owner.func.id if isinstance(owner, ast.Call)
                                                                  and isinstance(owner.func, ast.Name) else "")
            if "litellm" in named or named in ("anthropic", "openai", "client"):
                out.append(f"{named}.{node.attr}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (isinstance(owner, ast.Name) and owner.id in SEND_OWNERS and node.func.attr in ("complete", "build_argv")):
                out.append(f"{owner.id}.{node.func.attr}")
    return out


def _sources():
    for root in ("api", "mcp", "scripts"):
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if ".venv" in rel or "/tests/" in rel or "__pycache__" in rel:
                continue
            yield rel, path


def test_every_model_call_goes_through_the_one_door():
    """A new call site fails here. ``providers.py`` is the door; the three engines define what it calls."""
    owners = {"api/services/providers.py", "api/services/agent_engine.py", "api/services/codex_engine.py",
              "api/services/cli_engines.py", "api/services/telemetry.py"}
    found = {rel: hits for rel, path in _sources() if rel not in owners
             for hits in [_bypasses(path.read_text(encoding="utf-8"))] if hits}
    assert found == {}


def test_the_bypass_check_itself_catches_each_way_round():
    for sneaky in ("import litellm\nasync def f(): return await litellm.acompletion(model='m', messages=[])",
                   "import litellm\nfn = litellm.completion\nfn(model='m', messages=[])",
                   "def f(): return _litellm().acompletion(model='m')",
                   "from api.services import agent_engine\nagent_engine.complete(messages=[], model='m')",
                   "from api.services import cli_engines\ncli_engines.complete(None, messages=[])"):
        assert _bypasses(sneaky), sneaky
    assert not _bypasses("x = resolve_llm_fn(s, completion=litellm.acompletion)\ncompletion = litellm.completion\n"
                         "y = resolve_llm_fn(s, completion=completion)")


def test_every_returned_callable_is_the_door(tmp_path):
    fn = providers.resolve_llm_fn(_settings(tmp_path, "byok"), completion=lambda **_k: None, sink=lambda _e: None)
    assert fn.__qualname__.startswith("_held_back")
    run = providers.resolve_llm_fn(_settings(tmp_path, "agent"), runner=lambda *_a, **_k: None, sink=lambda _e: None)
    assert run.__qualname__.startswith("_held_back")


# ------------------------------------------------------------------ the callers the review reproduced


def test_stage_1s_own_prompt_masks_the_other_line_by_offset_so_spans_stay_exact():
    content = f"user: my password is {VALUE}\nassistant: Logged in with {VALUE}."
    episode = {"id": "ep_1", "content": content}
    guard = sf.Guard.of(episode, [(0, len(content))])
    chunk = guard.chunk(content, 0, len(content))
    assert VALUE not in chunk and chunk.count("[held back: password]") == 2
    assert guard.kinds() == {"password": 1}       # the report counts what was found, not its echoes


def test_a_value_flagged_in_another_window_is_masked_in_this_one():
    first = f"user: my password is {VALUE}\n"
    content = first + f"assistant: Logged in with {VALUE}."
    guard = sf.Guard.of({"id": "ep_1", "content": content}, [(len(first), len(content))])
    assert VALUE not in guard.chunk(content, len(first), len(content))
    assert guard.hits == ()                       # read in this window: nothing to report for it


def test_a_reply_note_is_clean_on_the_wire_cut_or_whole(tmp_path):
    """The note is built from the body outside the Guard: the door is what covers it, and a note cuts a line short."""
    padding = "x" * 200
    for said in (f"the wifi password is {VALUE}", f"{padding} the wifi password is {VALUE}"):
        body = f"user: {said}\nspeaker:Ana: lovely\nuser: {said}"
        _ep(tmp_path, "ep_1", body)
        fm = {"turn_extras": [{"offset": body.index("speaker:Ana"), "reply_to": 0,
                               "reactions": [{"kind": "like", "by": "Ana"}]}]}
        note = turn_signals.chunk_note(turn_signals.signals(fm, body), 0, len(body))
        assert note
        assert "Zebra7" not in hold.hold_back(_user(note), tmp_path)[1]["content"]


def test_a_revision_does_not_quote_a_removed_value_to_a_model():
    """After Remove the door no longer knows the value, and a conversation that only repeated it has no hit of its own."""
    prior = f"user: alpha\nassistant: Logged in with {VALUE}.\nuser: beta\n"
    body = "user: alpha\nassistant: Logged in with [removed: password].\nuser: beta\n"
    rev = episode_revision.build({"id": "ep_1", "content": body, sf.KEY: {"removed": {"kinds": ["password"], "pending": True}}},
                                 prior)
    assert revision_prose.changes_of(rev) == []
    assert rev.windows == ()                      # all that changed is the removal: no read at all


def test_an_edit_beside_a_removal_is_still_a_revision_and_quotes_no_value():
    prior = f"user: my password is {VALUE}\nuser: the trip is on Friday\n"
    body = "user: my password is [removed: password]\nuser: the trip is on Monday\n"
    rev = episode_revision.build({"id": "ep_1", "content": body, sf.KEY: {"removed": {"kinds": ["password"], "pending": True}}},
                                 prior)
    assert rev.windows
    changes = revision_prose.changes_of(rev)
    assert changes and all(VALUE not in c.before and VALUE not in c.after for c in changes)


def test_same_after_removal_asks_the_texts():
    prior = f"a {VALUE} b {VALUE} c"
    assert sf.same_after_removal(prior, "a [removed: password] b [removed: password] c")
    assert not sf.same_after_removal(prior, "a [removed: password] b [removed: password] d")
    assert not sf.same_after_removal(prior, prior)


def test_st_distinctive():
    for yes in (VALUE, "A1B2C3", "4539 1488 0343 6467", "12345678", "blue-Moon!"):
        assert st.distinctive(yes), yes
    for no in ("guatemala", "Bitwarden", "4821", "A1B2", "Añoranza"):
        assert not st.distinctive(no), no

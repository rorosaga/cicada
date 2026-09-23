"""G135 R-R15 — the remote primer is chosen by an explicit parameter, names only
the tools its connection holds, and promises nothing a remote client can't do."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pytest

from _synthetic_bank import _bank, _ok_repo, _settings
from api.services import handshake, state_dictionary

TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
SEARCH_ONLY = frozenset({"cicada_handshake", "cicada_recall", "cicada_open_hub"})
DEFAULT = SEARCH_ONLY | {"cicada_recall_detail", "cicada_get_perspective", "cicada_check_nudges",
                         "cicada_save_episode", "cicada_write_claim", "cicada_save_url"}
EVERYTHING = DEFAULT | {"cicada_sources", "cicada_resolve_inbox", "cicada_ask"}
BANNED = ("claude --resume", "CICADA_SESSION_ID", "cicada_repo_context", "/episodes/{id}/span",
          "~/.claude", "~/src/alpha-project", "GET /state", "127.0.0.1")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _state(tmp_path):
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    return memory, state_dictionary.read_state(memory)


@pytest.mark.parametrize("tools", [SEARCH_ONLY, DEFAULT, EVERYTHING], ids=["search", "default", "all"])
def test_the_remote_primer_names_only_the_tools_it_was_given(tmp_path, tools):
    _, state = _state(tmp_path)
    for st in (state, None):
        text = handshake.build_remote(st, tools=tools, bank="memory")
        assert set(re.findall(r"cicada_[a-z_]+", text)) <= tools
        for banned in BANNED:
            assert banned not in text, banned
        assert "reference data" in text and handshake.CONVERSATION_SLOT in text
        assert len(text) // 4 <= handshake.MAX_TOKENS


def test_the_can_sentence_matches_the_app_footer(tmp_path):
    text = handshake.build_remote(None, tools=DEFAULT, bank="memory")
    assert "Can search, read and record. Can't delete or rewrite." in text


def test_answering_is_only_offered_with_the_answer_tool(tmp_path):
    without = handshake.build_remote(None, tools=DEFAULT, bank="memory")
    with_answer = handshake.build_remote(None, tools=DEFAULT | {"cicada_resolve_inbox"}, bank="memory")
    assert "skip=true" not in without and "only the person can answer them" in without
    assert "cicada_resolve_inbox(id, skip=true)" in with_answer


def test_the_variant_is_the_callers_choice_never_the_client_name(tmp_path):
    memory, _ = _state(tmp_path)
    cache = tmp_path / "home" / "handshake"
    text, meta = handshake.load_or_build(memory, "claude-ai", variant="remote", tools=DEFAULT, cache_dir=cache)
    assert meta["variant"] == "remote" and "## Claude Code" not in text and "claude --resume" not in text
    local, local_meta = handshake.load_or_build(memory, "claude-code", cache_dir=cache)
    assert local_meta["variant"] == "claude-code" and "claude --resume" in local


def test_the_remote_cache_is_keyed_by_the_tool_set(tmp_path):
    memory, _ = _state(tmp_path)
    cache = tmp_path / "home" / "handshake"
    a, _ = handshake.load_or_build(memory, variant="remote", tools=SEARCH_ONLY, cache_dir=cache)
    b, _ = handshake.load_or_build(memory, variant="remote", tools=DEFAULT, cache_dir=cache)
    assert a != b and len(list(cache.glob("memory.remote-*.json"))) == 2
    again, meta = handshake.load_or_build(memory, variant="remote", tools=SEARCH_ONLY, cache_dir=cache)
    assert again == a and meta["cached"] is True


def test_the_remote_variant_needs_its_tools(tmp_path):
    memory, _ = _state(tmp_path)
    with pytest.raises(ValueError):
        handshake.load_or_build(memory, variant="remote", cache_dir=tmp_path / "c")


def test_the_three_local_variants_are_untouched():
    assert handshake.VARIANTS == ("claude-code", "codex", "generic")
    assert handshake.variant_for("claude-ai") == "claude-code", "stdio keeps its rule (R-R2)"

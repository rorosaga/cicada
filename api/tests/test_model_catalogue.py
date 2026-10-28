"""The model catalogue (vision item 4, 2026-10-28): each harness's own list, with where and when, and a format change
said in words — never an empty list.

Fixtures (``fixtures/model_lists/``), one per harness: ``claude_help.txt`` is the ``--model`` region of
``claude --help`` (Claude Code 2.1.312, captured 2026-10-28); ``cursor_models.txt``, ``opencode_models.txt`` and
``grok_models.txt`` are the listing shapes ``cli_engines``' parser and its stubs were written against (the tools were
not installed where these were recorded — replace each with a live capture when one is at hand);
``codex_model_list.json`` is the app-server's ``model/list`` reply shape. A drift test per harness mutates its fixture
into a plausible new format and expects ``drift``, not an empty list.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from api.services import cli_engines, codex_app_server, model_catalogue
from api.services.connections.base import CliResult

FIX = Path(__file__).parent / "fixtures" / "model_lists"


def _text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---- one fixture per harness -------------------------------------------------------------------------------------


def test_claude_help_names_the_aliases_it_accepts():
    assert model_catalogue.parse_claude_help(_text("claude_help.txt")) == ["fable", "opus", "sonnet"]


@pytest.mark.parametrize("mutate", [
    lambda t: t.replace("--model <model>", "--engine <model>"),          # the option renamed
    lambda t: t.replace("'fable', 'opus', or 'sonnet'", "fable, opus or sonnet"),   # the aliases unquoted
])
def test_claude_help_drift_raises_instead_of_listing_nothing(mutate):
    with pytest.raises(model_catalogue.FormatDrift):
        model_catalogue.parse_claude_help(mutate(_text("claude_help.txt")))


@pytest.mark.parametrize("name, keep", [
    ("cursor_models.txt", lambda m: True),
    ("opencode_models.txt", lambda m: "/" in m),
    ("grok_models.txt", cli_engines.grok_is_builtin),
])
def test_each_cli_listing_parses_to_models(name, keep):
    found = [m for m in cli_engines.parse_model_lines(_text(name)) if keep(m)]
    assert found, name
    assert not cli_engines.listing_drifted(_text(name), 0, found)


@pytest.mark.parametrize("name", ["cursor_models.txt", "opencode_models.txt", "grok_models.txt"])
def test_a_cli_listing_in_a_new_format_is_drift(name):
    # A tool that starts printing JSON: every line starts with a brace or a quote, so no id is read.
    moved = json.dumps({"models": [{"id": line.strip()} for line in _text(name).splitlines() if line.strip()]},
                       indent=2)
    found = cli_engines.parse_model_lines(moved)
    assert cli_engines.listing_drifted(moved, 0, found)


def test_a_signed_out_or_empty_listing_is_not_drift():
    assert not cli_engines.listing_drifted("", 0, [])
    assert not cli_engines.listing_drifted("Not logged in. Run agent login.", 0, [])
    assert not cli_engines.listing_drifted("{}", 1, [])


def test_codex_model_list_parses_and_a_new_shape_is_drift():
    reply = json.loads(_text("codex_model_list.json"))
    snap = codex_app_server.parse_snapshot({"model/list": reply})
    assert snap.models == ("gpt-5.5", "gpt-5.5-mini") and not snap.models_drift
    renamed = {"result": {"items": reply["result"]["data"]}}
    assert codex_app_server.parse_snapshot({"model/list": renamed}).models_drift
    keys_moved = {"result": {"data": [{"slug": m["model"]} for m in reply["result"]["data"]]}}
    assert codex_app_server.parse_snapshot({"model/list": keys_moved}).models_drift
    # An error reply (no result) and a genuinely empty roster are not drift.
    assert not codex_app_server.parse_snapshot({"model/list": {"error": {"code": -1}}}).models_drift
    assert not codex_app_server.parse_snapshot({"model/list": {"result": {"data": []}}}).models_drift


def test_a_cli_probe_that_cannot_read_its_listing_says_so(monkeypatch, tmp_path):
    binary = tmp_path / "opencode"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("CICADA_OPENCODE_CLI", str(binary))
    moved = '{"models": [{"id": "github-copilot/gpt-5.5"}]}'
    runner = lambda argv, **kw: CliResult(rc=0, stdout=moved, stderr="")  # noqa: E731
    monkeypatch.setattr(cli_engines, "resolve_binary", lambda spec: str(binary))
    st = cli_engines.probe_now(cli_engines.OPENCODE, runner=runner)
    assert st.drift and not st.connected and "changed shape" in st.detail


# ---- the Claude plan's list --------------------------------------------------------------------------------------


@pytest.fixture
def claude(monkeypatch, tmp_path):
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("CICADA_CLAUDE_CLI", str(binary))
    seen = []

    def runner(text, rc=0):
        def run(argv, **kw):
            seen.append((argv, kw.get("env_overrides")))
            return CliResult(rc=rc, stdout=text, stderr="")
        return run

    return runner, seen


def test_the_claude_list_follows_the_harness_and_keeps_the_first_model(claude):
    runner, seen = claude
    entry = model_catalogue.refresh_claude(runner=runner(_text("claude_help.txt")))
    assert entry["aliases"] == ["fable", "opus", "sonnet"] and entry["drift"] is False
    assert seen[0][0][1:] == ["--help"] and seen[0][1] == {"CICADA_CAPTURE": "off", "CICADA_RECALL": "off"}
    ids, cat = model_catalogue.claude_plan()
    # R-HS7: a tap writes the card's first model, so the documented first never moves; a new alias joins after.
    assert ids == ["sonnet", "haiku", "opus", "fable"]
    how = {m["id"]: m["source"] for m in cat["models"]}
    assert how == {"sonnet": "harness", "haiku": "documented", "opus": "harness", "fable": "harness"}
    assert cat["source"] == "claude --help" and cat["asOf"] and cat["drift"] is None


def test_a_drifted_help_keeps_the_last_list_and_says_so(claude):
    runner, _ = claude
    model_catalogue.refresh_claude(runner=runner(_text("claude_help.txt")))
    model_catalogue.refresh_claude(runner=runner("Usage: claude [options]\n  --engine <x>  Pick one.\n"))
    ids, cat = model_catalogue.claude_plan()
    assert "fable" in ids, "the last good list stays"
    assert cat["drift"] == model_catalogue.DRIFT_SENTENCE


def test_no_tool_and_no_cache_is_the_documented_list(monkeypatch):
    monkeypatch.setenv("CICADA_CLAUDE_CLI", "/nonexistent/claude")
    monkeypatch.setattr("api.services.connections.base.shutil.which", lambda name: None)
    monkeypatch.setattr("api.services.connections.base._CLI_FALLBACK_DIRS", ())
    ids, cat = model_catalogue.claude_plan()
    assert ids == ["sonnet", "haiku", "opus"] and cat["source"] == "documented"


def test_a_saved_model_no_list_names_stays_listed(claude):
    ids, cat = model_catalogue.claude_plan("claude-opus-4-1")
    assert ids[-1] == "claude-opus-4-1" and cat["models"][-1]["source"] == "saved"


def test_what_an_alias_resolved_to_is_noted_from_a_run(claude):
    from api.services import agent_engine

    runner, _ = claude
    model_catalogue.refresh_claude(runner=runner(_text("claude_help.txt")))
    agent_engine.response_shim({"result": "ok", "modelUsage": {"claude-fable-1": {"outputTokens": 9}}}, "fable")
    _, cat = model_catalogue.claude_plan()
    row = next(m for m in cat["models"] if m["id"] == "fable")
    assert row["resolvesTo"] == "claude-fable-1" and row["resolvedAt"]


def test_first_seen_marks_only_models_that_arrive_later():
    first = model_catalogue.catalogue("cursor-cli", [("auto", "harness")], as_of=1.0, source="agent models",
                                      today=date(2026, 10, 1))
    assert first["models"][0]["firstSeen"] is None and not first["models"][0]["new"]
    later = model_catalogue.catalogue("cursor-cli", [("auto", "harness"), ("sonnet-5", "harness")], as_of=2.0,
                                      source="agent models", today=date(2026, 10, 20))
    row = {m["id"]: m for m in later["models"]}
    assert row["sonnet-5"]["firstSeen"] == "2026-10-20" and row["sonnet-5"]["new"]
    aged = model_catalogue.catalogue("cursor-cli", [("sonnet-5", "harness")], as_of=3.0, source="agent models",
                                     today=date(2026, 11, 20))
    assert not aged["models"][0]["new"]
    assert row["sonnet-5"]["family"] == "sonnet"


@pytest.mark.parametrize("model_id, fam", [("github-copilot/gpt-5.5", "gpt"), ("claude-opus-5-5", "opus"),
                                           ("grok-4.6-mini", "grok"), ("auto", "auto"), ("kimi-k3", "kimi")])
def test_family(model_id, fam):
    assert model_catalogue.family(model_id) == fam


def test_the_view_never_waits_and_a_hook_never_refreshes(monkeypatch, claude):
    """A stale cache starts one background refresh (off in the suite) and answers at once from what is stored."""
    started = []
    monkeypatch.setattr(model_catalogue.threading, "Thread", lambda **kw: started.append(kw) or type(
        "T", (), {"start": lambda self: None})())
    monkeypatch.setenv("CICADA_MODEL_CATALOGUE_REFRESH", "on")
    model_catalogue._REFRESHING.clear()
    ids, _ = model_catalogue.claude_plan()
    assert ids == ["sonnet", "haiku", "opus"] and len(started) == 1
    model_catalogue._REFRESHING.clear()
    import api.hooks as hooks_pkg

    hooks_dir = Path(hooks_pkg.__file__).parent
    assert not any("model_catalogue" in p.read_text(encoding="utf-8") for p in hooks_dir.rglob("*.py"))

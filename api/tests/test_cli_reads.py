"""G180 — `cicada recall` and `cicada status`: the same bodies as the MCP, the bank pinned,
generated actions gated to what the command line holds, and memory's own text untouched."""
from __future__ import annotations

import json
import os
import re

import pytest

from _cli import cli_env, envelope, health_server, run_cli
from _synthetic_bank import _bank, _entity
from api.services import mcp_tools

HINTS = re.compile(r"```cicada-hints\n(.*?)\n```", re.S)


@pytest.fixture
def inprocess(monkeypatch):
    from api.config import Settings, get_settings

    before = Settings.model_config.get("env_file")
    monkeypatch.setenv("LITELLM_MODE", "PRODUCTION")
    monkeypatch.delenv("CICADA_MEMORY_ROOT", raising=False)
    yield
    Settings.model_config["env_file"] = before
    get_settings.cache_clear()


# --- gating at the rendering seam (stdio and remote unchanged) -------------------------------------

def _payload(block: str) -> dict:
    return json.loads(HINTS.search(block).group(1))


def test_hints_block_gates_every_named_tool():
    full = _payload(mcp_tools._hints_block(["alpha-project"], "projects", []))
    assert full["next_tool"] == "cicada_recall_detail" and "cicada_open_hub" in full["note"]
    remote = _payload(mcp_tools._hints_block(["alpha-project"], "projects", [], can_read_detail=False))
    assert remote["next_tool"] == "cicada_open_hub" and "cicada_recall_detail" not in remote["note"]
    detail_only = _payload(mcp_tools._hints_block(["alpha-project"], None, [], can_open_hub=False))
    assert detail_only["next_tool"] == "cicada_recall_detail" and "cicada_open_hub" not in detail_only["note"]
    neither = _payload(mcp_tools._hints_block(["alpha-project"], None, [], can_read_detail=False,
                                              can_open_hub=False))
    assert "next_tool" not in neither and "note" not in neither
    assert neither["suggested_entities"] == ["alpha-project"]


def test_hints_block_bytes_are_unchanged_for_a_caller_holding_every_tool():
    # The pre-G180 rendering, spelled out: stdio and remote replies must not move a byte.
    block = mcp_tools._hints_block(["alpha-project"], "projects", ["bob-example"], state={"pending": 1})
    expected = "```cicada-hints\n" + json.dumps({
        "suggested_entities": ["alpha-project"], "relevant_hub": "projects", "hub_members_preview": ["bob-example"],
        "next_tool": "cicada_recall_detail",
        "note": "Call cicada_recall_detail with each suggested_entity id for full pages, or cicada_open_hub with "
                "relevant_hub for a topic index.",
        "state": {"pending": 1}}, indent=2) + "\n```"
    assert block == expected


def test_recall_drops_the_state_cursors_handshake_pointer_only_when_the_caller_lacks_it(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=False)
    monkeypatch.setattr(mcp_tools, "_state_hint", lambda _m: {"pending": 2, "next_tool": "cicada_handshake"})

    def ctx(available):
        return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown",
                                     available=available)

    stdio = _payload(mcp_tools.recall(ctx(None), "alpha project"))
    assert stdio["state"]["next_tool"] == "cicada_handshake"
    cli_only = _payload(mcp_tools.recall(ctx(frozenset({"cicada_recall"})), "alpha project"))
    assert "next_tool" not in cli_only["state"] and cli_only["state"]["pending"] == 2


# --- the command, in process ----------------------------------------------------------------------

def _run(argv, capsys):
    from api import cli

    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out


def test_cli_recall_is_the_mcp_body_with_actions_gated(tmp_path, monkeypatch, capsys, inprocess):
    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    code, out = _run(["recall", "alpha project", "--json"], capsys)
    assert code == 0 and out.err == ""
    env_ = json.loads(out.out)
    text = env_["text"]
    stdio = mcp_tools.recall(mcp_tools.ToolContext(memory_path=lambda: memory.resolve(), session_id="s",
                                                   harness="unknown"), "alpha project")
    # Identical outside the hints block; inside it, no action the CLI does not hold.
    assert HINTS.sub("", text) == HINTS.sub("", stdio)
    hints = _payload(text)
    assert "cicada_" not in json.dumps({k: v for k, v in hints.items() if k != "suggested_entities"})
    assert env_["data"]["suggested_entities"] == hints["suggested_entities"]
    assert "alpha-project" in env_["data"]["suggested_entities"]
    assert env_["command"] == "recall" and env_["ok"] is True


def test_memorys_own_text_is_returned_unchanged(tmp_path, monkeypatch, capsys, inprocess):
    memory = _bank(tmp_path, git=False)
    odd = "Notes say cicada_write_claim(subject, predicate, object) and `cicada nonexistent --flag`."
    _entity(memory, "delta-notes", body=f"## Summary\n{odd}\n")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    code, out = _run(["recall", "delta notes", "--json"], capsys)
    assert code == 0
    assert odd in json.loads(out.out)["text"]


def test_a_missing_vector_index_is_a_disclosed_degradation(tmp_path, monkeypatch, capsys, inprocess):
    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    _code, out = _run(["recall", "alpha", "--json"], capsys)
    assert "degraded:vector" in json.loads(out.out)["warnings"]


def test_bank_assertion_refuses_before_reading(tmp_path, monkeypatch, capsys, inprocess):
    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    called = []
    monkeypatch.setattr(mcp_tools, "recall", lambda *a, **k: called.append(1) or "")
    code, out = _run(["recall", "alpha", "--bank", "not-this-one", "--json"], capsys)
    env_ = json.loads(out.out)
    assert code == 3 and env_["code"] == "bank_mismatch" and env_["ok"] is False and called == []
    code, out = _run(["recall", "alpha", "--bank", "default", "--json"], capsys)
    assert code == 0 and called == [1]


def test_the_pin_holds_through_a_switch_during_the_command(tmp_path, monkeypatch, capsys, inprocess):
    from api.services import bank_registry

    root = tmp_path / "root"
    root.mkdir()
    bank_registry.create_bank(root, "alpha", seed_owner=False)
    bank_registry.create_bank(root, "beta", seed_owner=False)
    reg = bank_registry.load_registry(root)
    reg["active"] = "alpha"
    bank_registry.save_registry(root, reg)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    seen = []

    def body(ctx, query):
        reg = bank_registry.load_registry(root)
        reg["active"] = "beta"
        bank_registry.save_registry(root, reg)
        from api.config import get_settings

        seen.append((ctx.memory_path(), get_settings().memory_path))
        return "ok"

    monkeypatch.setattr(mcp_tools, "recall", body)
    code, out = _run(["recall", "alpha", "--json"], capsys)
    assert code == 0, out
    ctx_path, settings_path = seen[0]
    assert ctx_path.name == "alpha" and settings_path == ctx_path
    assert json.loads(out.out)["bank"] == "alpha"


# --- status --------------------------------------------------------------------------------------

def test_status_with_the_backend_down(tmp_path):
    memory = _bank(tmp_path, git=False)
    env = cli_env(tmp_path, memory)
    work = tmp_path / "w"
    work.mkdir()
    out = envelope(run_cli(["status", "--json"], env, cwd=work))
    data = out["data"]
    assert data["root"] == {"path": os.path.realpath(memory), "source": "env", "verified": "backend_down"}
    assert data["bank"] == {"name": out["bank"], "path": os.path.realpath(memory), "demo": False}
    assert data["episodes"] == {"unprocessed": 1}
    assert data["backend"] == {"state": "backend_down"}
    assert data["index"] == {"vector": "absent"}
    assert data["distribution"] == "other"
    text = run_cli(["status"], env, cwd=work).stdout
    assert os.path.realpath(memory) in text and "not running" in text


def test_status_with_a_confirming_backend(tmp_path):
    memory = _bank(tmp_path, git=False)
    work = tmp_path / "w"
    work.mkdir()
    with health_server(memory_root=str(memory), version="1.2.3", writing=True) as port:
        env = cli_env(tmp_path, memory, CICADA_PORT=str(port))
        data = envelope(run_cli(["status", "--json"], env, cwd=work))["data"]
    assert data["root"]["verified"] == "confirmed"
    assert data["backend"] == {"state": "confirmed", "version": "1.2.3", "writing": True}


def test_status_names_a_demo_bank(tmp_path):
    from api.services import demo_guard

    memory = _bank(tmp_path, git=False)
    demo_guard.write_manifest(memory)
    env = cli_env(tmp_path, memory)
    work = tmp_path / "w"
    work.mkdir()
    assert envelope(run_cli(["status", "--json"], env, cwd=work))["data"]["bank"]["demo"] is True

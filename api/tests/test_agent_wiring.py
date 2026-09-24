"""Track I T3 — GET /agents/wiring is read-only and hands back the exact
commands install.sh would run (design §9.3, R-IA15). Fake HOME, fake binaries,
fake CLI runner: nothing here reads the real ~/.claude or runs a real CLI."""
from __future__ import annotations

import asyncio
import json
import re
import shlex
from pathlib import Path

from api import config
from api.hooks import registry as hook_registry
from api.services import agent_wiring
from api.services.connections import base

REPO = Path("/R/cicada")
PY = "/R/cicada/api/.venv/bin/python"
MEM = Path("/M/memory")


def _runner(rc: int):
    async def run(argv, *, timeout):
        assert timeout == agent_wiring.PROBE_TIMEOUT_S
        return base.CliResult(rc, "", "")
    return run


def _probe(home: Path, rc: int = 1, resolve=lambda name: name if name in ("claude", "codex") else None):
    return asyncio.run(agent_wiring.probe(home=home, memory_root=MEM, repo=REPO, python=PY,
                                          runner=_runner(rc), resolve=resolve))


def _row(data, agent_id):
    return next(a for a in data["agents"] if a["id"] == agent_id)


def test_an_unwired_harness_gets_install_sh_s_exact_commands(tmp_path):
    data = _probe(tmp_path)
    row = _row(data, "claude-code")
    assert (row["installed"], row["recall"], row["autosave"]) == (True, "off", "off")
    [mcp, hook] = row["connect"]
    assert mcp["argv"] == ["claude", "mcp", "add", "cicada", "--scope", "user", "--env",
                           f"CICADA_MEMORY_PATH={MEM}", "--", PY, f"{REPO}/mcp/server.py"]
    assert hook["argv"] == [PY, f"{REPO}/api/hooks/registry.py", "install", "--settings",
                            str(tmp_path / ".claude/settings.json"), "--event", "Stop", "--command",
                            f'"{PY}" "{REPO}/api/hooks/capture.py" --harness claude-code']
    assert hook["touches"] == ["~/.claude/settings.json"] and mcp["touches"] == ["~/.claude.json"]
    for step in row["connect"]:
        assert step["display"] == shlex.join(step["argv"]), "the disclosure can never show one thing and run another"
    assert data["python"] == PY and data["repo"] == str(REPO) and data["memory"] == str(MEM)


def test_a_wired_harness_reads_on_and_offers_nothing(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    hook_registry.install(settings, event="Stop", command=agent_wiring.hook_command(PY, REPO, "claude-code"))
    row = _row(_probe(tmp_path, rc=0), "claude-code")
    assert (row["recall"], row["autosave"], row["connect"]) == ("on", "on", [])


def test_a_stale_hook_is_offered_the_update(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    hook_registry.install(settings, event="Stop", command='"/old/python" "/old/api/hooks/capture.py" --harness claude-code')
    row = _row(_probe(tmp_path, rc=0), "claude-code")
    assert row["autosave"] == "stale" and [s["step"] for s in row["connect"]] == ["hook"]


def test_an_unparseable_settings_file_is_invalid_and_never_touched(tmp_path):
    settings = tmp_path / ".codex/hooks.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    row = _row(_probe(tmp_path), "codex")
    assert row["autosave"] == "invalid", "F8: registry.status alone would have said 'off'"
    assert [s["step"] for s in row["connect"]] == ["mcp"] and "valid JSON" in row["detail"]
    assert settings.read_text(encoding="utf-8") == "{not json"


def test_a_probe_that_times_out_is_unknown_never_off(tmp_path):
    row = _row(_probe(tmp_path, rc=124), "claude-code")
    assert row["recall"] == "unknown" and "mcp" not in [s["step"] for s in row["connect"]]


def test_a_missing_binary_is_not_installed(tmp_path):
    data = _probe(tmp_path, resolve=lambda name: None)
    for row in data["agents"]:
        assert (row["installed"], row["autosave"], row["connect"]) == (False, "n/a", [])


def test_gemini_cli_is_read_only(tmp_path):
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini/settings.json").write_text(json.dumps({"mcpServers": {"cicada": {}}}), encoding="utf-8")
    row = _row(_probe(tmp_path, resolve=lambda name: name), "gemini-cli")
    assert (row["recall"], row["autosave"], row["connect"]) == ("on", "n/a", [])


def test_the_probe_never_writes(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    hook_registry.install(settings, event="Stop", command="x api/hooks/capture.py")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _probe(tmp_path)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_no_author_machine_path_is_baked_in():
    source = Path(agent_wiring.__file__).read_text(encoding="utf-8")
    assert "/Users/" not in source and "/home/" not in source, "portability: no author-machine path"


def test_the_shared_argv_fixture_matches():
    """Task 8's AgentWiringCatalogTests reads the same file: the copy-paste snippets
    in Settings → Agents and the commands the app runs cannot drift apart."""
    fixture = json.loads((Path(__file__).parent / "fixtures/agent_wiring_argv.json").read_text())
    data = asyncio.run(agent_wiring.probe(home=Path("/nonexistent-home"), memory_root=Path(fixture["memory"]),
                                          repo=Path(fixture["root"]), python=f"{fixture['root']}/api/.venv/bin/python",
                                          runner=_runner(1), resolve=lambda name: name))
    for case in fixture["cases"]:
        steps = {s["step"]: s["argv"] for s in _row(data, case["agent"])["connect"]}
        assert steps[case["step"]] == case["argv"], case["agent"]


def test_the_route_serves_the_probe(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    async def fake_probe(*, home, memory_root):
        return {"agents": [], "python": PY, "repo": str(REPO), "memory": str(memory_root)}

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    monkeypatch.setattr(agent_wiring, "probe", fake_probe)
    r = TestClient(main.app).get("/agents/wiring")
    assert r.status_code == 200 and r.json()["memory"] == str(tmp_path)
    config.get_settings.cache_clear()


RECALL_CMD = f'"{PY}" "{REPO}/api/hooks/recall.py" --harness claude-code'


def _recall_on(settings: Path, command: str = RECALL_CMD, events=("SessionStart", "UserPromptSubmit")):
    for ev in events:
        hook_registry.install(settings, event=ev, command=command)


def test_recall_is_its_own_two_steps_and_connect_is_unchanged(tmp_path):
    row = _row(_probe(tmp_path), "claude-code")
    settings = str(tmp_path / ".claude/settings.json")
    assert row["autorecall"] == "off" and row["autorecall_off"] == []
    assert [s["argv"] for s in row["autorecall_on"]] == [
        [PY, f"{REPO}/api/hooks/registry.py", "install", "--settings", settings, "--event", ev, "--command", RECALL_CMD]
        for ev in ("SessionStart", "UserPromptSubmit")]
    for step in row["autorecall_on"]:
        assert step["step"] == "autorecall" and step["display"] == shlex.join(step["argv"])
        assert step["touches"] == ["~/.claude/settings.json"]
    assert [s["step"] for s in row["connect"]] == ["mcp", "hook"], "R-H11: onboarding's Turn on runs what it ran"


def test_recall_on_offers_only_turn_off(tmp_path):
    _recall_on(tmp_path / ".claude/settings.json")
    row = _row(_probe(tmp_path), "claude-code")
    assert (row["autorecall"], row["autorecall_on"]) == ("on", [])
    assert [s["argv"] for s in row["autorecall_off"]] == [
        [PY, f"{REPO}/api/hooks/registry.py", "uninstall", "--settings", str(tmp_path / ".claude/settings.json"),
         "--hook", "recall"]]


def test_half_registered_or_moved_recall_is_stale_and_offers_both(tmp_path):
    _recall_on(tmp_path / ".claude/settings.json", events=("SessionStart",))
    row = _row(_probe(tmp_path), "claude-code")
    assert row["autorecall"] == "stale" and len(row["autorecall_on"]) == 2 and len(row["autorecall_off"]) == 1
    _recall_on(tmp_path / ".codex/hooks.json", command='"/old/python" "/old/api/hooks/recall.py" --harness codex')
    assert _row(_probe(tmp_path), "codex")["autorecall"] == "stale"


def test_an_unparseable_settings_file_offers_no_recall_step(tmp_path):
    settings = tmp_path / ".codex/hooks.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    row = _row(_probe(tmp_path), "codex")
    assert (row["autorecall"], row["autorecall_on"], row["autorecall_off"]) == ("invalid", [], [])


def test_a_missing_binary_carries_no_recall_fields(tmp_path):
    for row in _probe(tmp_path, resolve=lambda name: None)["agents"]:
        assert "autorecall" not in row, "the schema's default (n/a) speaks for it"


def test_install_sh_and_the_wiring_spell_the_recall_command_identically():
    text = (Path(agent_wiring.__file__).resolve().parents[2] / "install.sh").read_text(encoding="utf-8")
    fmt = re.search(r"recall_command\(\) \{ printf '([^']+)' ", text).group(1)
    assert fmt % (PY, f"{REPO}/api/hooks/recall.py", "claude-code") == RECALL_CMD
    assert 'RECALL_SCRIPT="$REPO/api/hooks/recall.py"' in text


def test_the_shared_autorecall_fixture_matches():
    """AutoRecallTests.swift reads the same file: the argv the backend serves
    and the argv the app's allowlist runs cannot drift apart."""
    fixture = json.loads((Path(__file__).parent / "fixtures/agent_autorecall_argv.json").read_text())
    root, home = Path(fixture["root"]), Path(fixture["home"])
    python = f"{fixture['root']}/api/.venv/bin/python"
    by_id = {h.id: h for h in agent_wiring.HARNESSES}
    for case in fixture["cases"]:
        argv = agent_wiring.autorecall_argv(by_id[case["agent"]], home=home, repo=root, python=python)
        assert [s["argv"] for s in argv[case["list"]]][case["index"]] == case["argv"], case


def test_the_route_serves_the_recall_fields_in_camel_case(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    step = {"step": "autorecall", "display": "x", "argv": ["x"], "touches": []}

    async def fake_probe(*, home, memory_root):
        return {"agents": [{"id": "codex", "installed": True, "autorecall": "off", "autorecall_on": [step]}],
                "python": PY, "repo": str(REPO), "memory": str(memory_root)}

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    monkeypatch.setattr(agent_wiring, "probe", fake_probe)
    agent = TestClient(main.app).get("/agents/wiring").json()["agents"][0]
    config.get_settings.cache_clear()
    assert agent["autorecall"] == "off" and agent["autorecallOn"][0]["step"] == "autorecall"
    assert agent["autorecallOff"] == []

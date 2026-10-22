"""G201 slice (a), TODO ruling 35 (2026-10-22): the Skills inventory sees Claude Code's plugins read-only from their own
manifests, tags every skill about-you / generic / unknown by a rule with no model call, lets the person flip a kind
(one small file outside every bank, written by ``skill_store``), and reports the installed set's weight per agent.

Every home here is synthetic (a fixture built from Claude Code's documented layout); no test reads a real
``~/.claude``, and no plugin or skill name here is anyone's real install."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.services import mcp_tools, skill_catalog, skill_inventory, skill_kind, skill_plugins, skill_store


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".codex").mkdir()
    monkeypatch.setattr(skill_catalog, "agent_home", lambda: h)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    return h


def skill_md(folder: Path, name: str, description: str, *, user_only: bool = False, body: str = "Steps.") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    extra = "disable-model-invocation: true\n" if user_only else ""
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}\n",
                                     encoding="utf-8")
    return folder


def plugin(home: Path, name: str, market: str, version: str, *, manifest: dict | None = None) -> Path:
    root = home / ".claude/plugins/cache" / market / name / version
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin/plugin.json").write_text(json.dumps({"name": name, "version": version,
                                                                 **(manifest or {})}), encoding="utf-8")
    return root


def installed(home: Path, table: dict, enabled: dict | None = None) -> None:
    (home / ".claude/plugins").mkdir(parents=True, exist_ok=True)
    (home / ".claude/plugins/installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": table}),
                                                                 encoding="utf-8")
    if enabled is not None:
        (home / ".claude/settings.json").write_text(json.dumps({"enabledPlugins": enabled}), encoding="utf-8")


def entry(root: Path, version: str, scope: str = "user") -> dict:
    return {"scope": scope, "installPath": str(root), "version": version, "installedAt": "2026-10-01T00:00:00.000Z",
            "lastUpdated": "2026-10-02T00:00:00.000Z"}


def snap(bank: Path | None = None) -> dict:
    return asyncio.run(skill_inventory.snapshot(bank=bank, run_tools=False))


def _two_plugins(home: Path) -> None:
    alpha = plugin(home, "alpha-kit", "market-a", "1.2.0", manifest={"skills": "./extra"})
    skill_md(alpha / "skills/plan-it", "plan-it", "Plan before you code.")
    skill_md(alpha / "skills/ship-it", "ship-it", "Ship the release.", user_only=True)
    skill_md(alpha / "extra", "bonus", "A skill in the manifest's own folder.")
    beta = plugin(home, "beta-lsp", "market-b", "0.1.0")
    installed(home, {"alpha-kit@market-a": [entry(alpha, "1.2.0")], "beta-lsp@market-b": [entry(beta, "0.1.0")]},
              enabled={"alpha-kit@market-a": True, "beta-lsp@market-b": False})


# --------------------------------------------------------------------------- the manifest reader


def test_plugins_are_read_with_version_switch_and_skills(home):
    _two_plugins(home)
    found = {p.id: p for p in skill_plugins.read(home)}
    alpha = found["alpha-kit@market-a"]
    assert (alpha.name, alpha.marketplace, alpha.version, alpha.enabled) == ("alpha-kit", "market-a", "1.2.0", True)
    assert [(s.name, s.user_only) for s in alpha.skills] == [("plan-it", False), ("ship-it", True), ("bonus", False)]
    assert found["beta-lsp@market-b"].enabled is False and found["beta-lsp@market-b"].skills == []


@pytest.mark.parametrize("content", [None, "", "{not json", "[]", '{"plugins": "nope"}', '{"plugins": {"../x": 1}}'])
def test_a_missing_or_corrupt_file_is_empty_never_an_error(home, content):
    if content is not None:
        (home / ".claude/plugins").mkdir(parents=True)
        (home / ".claude/plugins/installed_plugins.json").write_text(content, encoding="utf-8")
    assert skill_plugins.read(home) == []
    assert snap()["plugins"] == []


def test_a_corrupt_manifest_settings_or_skill_still_lists_the_plugin(home):
    root = plugin(home, "gamma", "market-c", "2.0.0")
    (root / ".claude-plugin/plugin.json").write_text("{broken", encoding="utf-8")
    (root / "skills/odd").mkdir(parents=True)
    (root / "skills/odd/SKILL.md").write_text("no frontmatter at all", encoding="utf-8")
    installed(home, {"gamma@market-c": [entry(root, "2.0.0")]})
    (home / ".claude/settings.json").write_text("{broken", encoding="utf-8")
    [p] = skill_plugins.read(home)
    assert (p.version, p.enabled) == ("2.0.0", None)
    assert [(s.name, s.description) for s in p.skills] == [("odd", "")]


def test_an_install_path_outside_the_plugins_folder_is_never_followed(home, tmp_path):
    outside = tmp_path / "elsewhere"
    skill_md(outside / "skills/leak", "leak", "Should never be read.")
    (home / ".claude/plugins").mkdir(parents=True)
    installed(home, {"evil@market-x": [entry(outside, "9.9.9")]})
    [p] = skill_plugins.read(home)
    assert p.skills == []


def test_a_manifest_path_that_escapes_the_plugin_is_skipped(home, tmp_path):
    root = plugin(home, "delta", "market-d", "1.0.0", manifest={"skills": ["../../../../../../outside", "/abs"]})
    skill_md(tmp_path / "outside/peek", "peek", "Should never be read.")
    installed(home, {"delta@market-d": [entry(root, "1.0.0")]})
    [p] = skill_plugins.read(home)
    assert p.skills == []


def test_a_project_scoped_install_says_its_switch_is_elsewhere(home):
    root = plugin(home, "eps", "market-e", "1.0.0")
    installed(home, {"eps@market-e": [{**entry(root, "1.0.0", scope="project"), "projectPath": "/somewhere"}]},
              enabled={"eps@market-e": True})
    page = snap()
    [row] = page["plugins"]
    assert row["enabled"] is None and row["note"] == skill_plugins.PROJECT_NOTE and row["canToggle"] is False


def test_the_older_flat_shape_reads_too(home):
    root = plugin(home, "zeta", "market-z", "0.0.1")
    (home / ".claude/plugins/installed_plugins.json").write_text(
        json.dumps({"zeta@market-z": entry(root, "0.0.1")}), encoding="utf-8")
    assert [p.id for p in skill_plugins.read(home)] == ["zeta@market-z"]


def test_reading_plugins_writes_nothing_into_them(home):
    _two_plugins(home)
    before = sorted((p.as_posix(), p.stat().st_mtime_ns) for p in (home / ".claude").rglob("*"))
    snap()
    after = sorted((p.as_posix(), p.stat().st_mtime_ns) for p in (home / ".claude").rglob("*"))
    assert before == after


def test_plugins_show_only_when_claude_code_is_on_this_mac(home):
    _two_plugins(home)
    assert [p["id"] for p in snap()["plugins"]] == ["alpha-kit@market-a", "beta-lsp@market-b"]
    # Claude Code not on this Mac (its home gone): no plugin section, as with every other agent.
    (home / ".claude").rename(home / ".claude-gone")
    assert snap()["plugins"] == []


# --------------------------------------------------------------------------- the kind rule and the person's override


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    pages = {"me": "type: person\nowner: true", "alpha-project": "type: project", "bob-example": "type: person",
             "some-tool": "type: tool", "vendor-co": "type: company",
             "weekly-review": "type: skill\nstatus: active\nname: Weekly review\nsummary: How the week is reviewed."
                              "\nrelated: [alpha-project]\nsource_episodes: [ep_1, ep_2]",
             "lint-fix": "type: skill\nstatus: active\nname: Lint fix\nsummary: Fix lint before commit."
                         "\nrelated: [some-tool, vendor-co]\nsource_episodes: [ep_1, ep_2]"}
    for stem, fm in pages.items():
        (bank / "entities" / f"{stem}.md").write_text(f"---\n{fm}\n---\n\nText.\n", encoding="utf-8")
    (bank / "pending_skills.jsonl").write_text(
        json.dumps({"name": "Call planning", "description": "d", "confidence": 0.6, "source_episode": "ep_3",
                    "evidence_ids": ["bob-example"]}) + "\n"
        + json.dumps({"name": "Retry loop", "description": "d", "confidence": 0.6, "source_episode": "ep_4",
                      "evidence_ids": ["some-tool"]}) + "\n", encoding="utf-8")
    return bank


def test_kinds_follow_the_rule(home, tmp_path):
    _two_plugins(home)
    bank = _bank(tmp_path)
    skill_md(home / ".claude/skills/my-own", "my-own", "Something I wrote.")
    skill_store.save_draft("standup-notes", "Notes for the standup.", "Use [[alpha-project]] and [[me]].",
                           author="codex")
    skill_store.save_draft("regex-help", "Regex tips.", "See [[some-tool]].", author="codex")
    page = snap(bank)
    kinds = {r["name"]: r["kind"] for r in page["installed"]}
    assert kinds["my-own"] == "unknown"                       # a local folder of unknown origin may be the person's
    plugin_kinds = {s["name"]: (s["kind"], s["kindBy"]) for p in page["plugins"] for s in p["skills"]}
    assert set(plugin_kinds.values()) == {("generic", "cicada")}
    assert {d["name"]: d["kind"] for d in page["drafts"]} == {"standup-notes": "about-you", "regex-help": "unknown"}
    noticed = {n["name"]: n["kind"] for n in page["noticed"]}
    assert noticed == {"Call planning": "about-you", "Retry loop": "unknown", "Weekly review": "about-you",
                       "Lint fix": "unknown"}                  # a company or a tool alone is not about the person


def test_third_party_and_cicadas_own_skills_are_generic():
    for origin in ("github", "npx", "catalog", "tool", "cicada"):
        assert skill_kind.by_origin(origin) == "generic"
    for origin in ("local", "copied", ""):
        assert skill_kind.by_origin(origin) == "unknown"


def test_the_person_flips_a_kind_and_can_clear_it(home, tmp_path):
    _two_plugins(home)
    page = snap()
    key = next(s["kindKey"] for p in page["plugins"] for s in p["skills"] if s["name"] == "plan-it")
    assert key == "plugin:alpha-kit@market-a/plan-it"
    skill_store.set_kind(key, "about-you")
    flipped = next(s for p in snap()["plugins"] for s in p["skills"] if s["name"] == "plan-it")
    assert (flipped["kind"], flipped["kindBy"]) == ("about-you", "person")
    skill_store.set_kind(key, None)
    cleared = next(s for p in snap()["plugins"] for s in p["skills"] if s["name"] == "plan-it")
    assert (cleared["kind"], cleared["kindBy"]) == ("generic", "cicada")
    stored = tmp_path / "cicada/skills/kinds.json"
    assert stored.is_file() and json.loads(stored.read_text())["kinds"] == {}


@pytest.mark.parametrize("key, kind", [("../etc:x", "generic"), ("installed:x", "personal"), ("", "generic"),
                                       ("other:x", "generic")])
def test_a_bad_kind_or_key_is_refused(home, key, kind):
    with pytest.raises(skill_store.StoreError):
        skill_store.set_kind(key, kind)


def test_a_corrupt_kinds_file_is_no_choice(home, tmp_path):
    path = tmp_path / "cicada/skills"
    path.mkdir(parents=True)
    (path / "kinds.json").write_text("{nope", encoding="utf-8")
    assert skill_store.kinds() == {}
    (path / "kinds.json").write_text(json.dumps({"kinds": {"installed:a": "weird", "installed:b": "generic"}}),
                                     encoding="utf-8")
    assert skill_store.kinds() == {"installed:b": "generic"}


def test_the_kind_route_writes_outside_the_bank(home, tmp_path):
    from fastapi.testclient import TestClient

    from api import main

    with TestClient(main.app) as client:
        ok = client.put("/skills/kinds", json={"key": "installed:notes-helper", "kind": "generic"})
        bad = client.put("/skills/kinds", json={"key": "installed:notes-helper", "kind": "nope"})
    assert ok.status_code == 200 and bad.status_code == 409
    assert skill_store.kinds() == {"installed:notes-helper": "generic"}


# --------------------------------------------------------------------------- weight


def test_the_weight_counts_what_each_agent_loads_as_an_estimate(home):
    _two_plugins(home)
    skill_md(home / ".claude/skills/notes-helper", "notes-helper", "Keeps notes tidy.")   # 12 + 17 = 29 chars
    skill_md(home / ".codex/skills/by-hand", "by-hand", "Only when asked.", user_only=True)
    weight = {w["id"]: w for w in snap()["weight"]["agents"]}
    # Claude Code: notes-helper + the switched-on plugin's three skills (ship-it is the person's to run; beta is off).
    cc = weight["claude-code"]
    assert (cc["skills"], cc["fromPlugins"], cc["userOnly"]) == (4, 3, 1)
    chars = 29 + len("plan-it") + len("Plan before you code.") + len("bonus") + \
        len("A skill in the manifest's own folder.")
    assert cc["descriptionTokens"] == -(-chars // 4)
    codex = weight["codex"]
    assert (codex["skills"], codex["fromPlugins"], codex["userOnly"], codex["descriptionTokens"]) == (1, 0, 1, 0)
    assert "estimate" in snap()["weight"]["basis"].lower()


# --------------------------------------------------------------------------- the MCP tool


def test_the_list_tool_names_plugins_kinds_and_weight(home, tmp_path):
    _two_plugins(home)
    skill_md(home / ".claude/skills/notes-helper", "notes-helper", "Keeps notes tidy.")
    bank = tmp_path / "bank"
    bank.mkdir()
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="sess-1", harness="codex")
    out = str(mcp_tools.skills(ctx))
    assert "- alpha-kit@market-a 1.2.0 · on · skills: plan-it, ship-it (the person runs it), bonus" in out
    assert "- beta-lsp@market-b 0.1.0 · off · no skills" in out
    assert "kind unknown" in out
    assert "Claude Code 4 skill(s), ~" in out and "estimate" in out
    assert list(bank.iterdir()) == []

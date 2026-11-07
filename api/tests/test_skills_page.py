"""The Skills page (owner 2026-10-15): discovery across the agents' folders, versions and updates, a tool skill's
text older than its tool, adding a skill by link or by `npx skills add`, per-agent toggles, onboarding's default
and decline, and an agent's skill drafted then held. Every home here is synthetic, every command and every fetch
is a fake (conftest): no test reads a real agent folder, runs a real tool or reaches the network."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import pytest

from api.services import (mcp_tools, page_editors, skill_actions, skill_catalog, skill_folders, skill_inventory,
                          skill_sources, skill_store, skill_tools)
from api.services.connections import base

SHA_OLD = "a" * 40
SHA_NEW = "b" * 40
SHA_PATH = "c" * 40


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    for agent_home in (".claude", ".codex"):    # Claude Code and Codex are installed on this synthetic Mac
        (h / agent_home).mkdir()
    monkeypatch.setattr(skill_catalog, "agent_home", lambda: h)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    return h


def skill(folder: Path, name: str, description: str = "Does a thing.", body: str = "Steps.") -> Path:
    path = folder / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
                                   encoding="utf-8")
    return path


def run(coro):
    return asyncio.run(coro)


def rows(snapshot: dict) -> dict[str, dict]:
    return {r["name"]: r for r in snapshot["installed"]}


def agent(row: dict, agent_id: str) -> dict:
    return next(a for a in row["agents"] if a["id"] == agent_id)


# --------------------------------------------------------------------------- a fake GitHub


class FakeGitHub:
    """Answers exactly the URLs a test registers; anything else is a 404 (and is recorded)."""

    def __init__(self):
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.seen: list[str] = []

    def json(self, url: str, data, status: int = 200):
        self.routes[url] = (status, json.dumps(data).encode())

    def raw(self, url: str, body: bytes | str, status: int = 200):
        self.routes[url] = (status, body.encode() if isinstance(body, str) else body)

    async def __call__(self, url: str, accept=None):
        self.seen.append(url)
        status, body = self.routes.get(url, (404, b"{}"))
        return skill_sources.Response(status, body)


API = skill_sources.API
RAW = skill_sources.RAW


def github_skill_repo(gh: FakeGitHub, *, owner="alice-example", repo="handy-skills", sha=SHA_OLD,
                      folder="skills/release-notes", skill_md="---\nname: release-notes\ndescription: Writes "
                      "release notes from merged work.\n---\n\nRead the log, group by area.\n", ref="main"):
    gh.json(f"{API}/repos/{owner}/{repo}", {"default_branch": "main", "private": False,
                                           "license": {"spdx_id": "MIT"},
                                           "html_url": f"https://github.com/{owner}/{repo}"})
    gh.raw(f"{API}/repos/{owner}/{repo}/commits/{ref}", sha)
    gh.json(f"{API}/repos/{owner}/{repo}/contents?ref={sha}",
            [{"name": "skills", "path": "skills", "type": "dir"}, {"name": "README.md", "path": "README.md",
                                                                    "type": "file", "size": 10}])
    gh.json(f"{API}/repos/{owner}/{repo}/contents/skills?ref={sha}",
            [{"name": folder.rsplit("/", 1)[-1], "path": folder, "type": "dir"}])
    gh.json(f"{API}/repos/{owner}/{repo}/contents/{folder}?ref={sha}",
            [{"name": "SKILL.md", "path": f"{folder}/SKILL.md", "type": "file", "size": len(skill_md)},
             {"name": "scripts", "path": f"{folder}/scripts", "type": "dir"}])
    gh.json(f"{API}/repos/{owner}/{repo}/contents/{folder}/scripts?ref={sha}",
            [{"name": "collect.sh", "path": f"{folder}/scripts/collect.sh", "type": "file", "size": 20}])
    gh.raw(f"{RAW}/{owner}/{repo}/{sha}/{folder}/SKILL.md", skill_md)
    gh.raw(f"{RAW}/{owner}/{repo}/{sha}/{folder}/scripts/collect.sh", "#!/bin/sh\ngit log --oneline\n")
    gh.json(f"{API}/repos/{owner}/{repo}/commits?sha={sha}&per_page=1&path={folder}",
            [{"sha": SHA_PATH, "commit": {"committer": {"date": "2026-10-01T00:00:00Z"}}}])


@pytest.fixture
def gh(monkeypatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(skill_sources, "FETCH", fake)
    return fake


# --------------------------------------------------------------------------- a fake uv and fake tools


class FakeTools:
    def __init__(self):
        self.versions: dict[str, str] = {}
        self.texts: dict[str, str] = {}
        self.doctor: dict[str, dict] = {}
        self.calls: list[list[str]] = []

    async def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ["uv", "tool", "list"]:
            out = "".join(f"{p} v{v}\n- {p}\n" for p, v in self.versions.items())
            return base.CliResult(0, out, "")
        if argv[:3] == ["uv", "tool", "install"]:
            package = argv[-1].split("/")[-1].split("@")[0]
            self.versions[package] = self.versions.get(f"next:{package}", "9.9.9")
            return base.CliResult(0, "Installed", "")
        if len(argv) >= 2 and argv[1] == "skill" and argv[0] in self.texts:
            return base.CliResult(0, self.texts[argv[0]], "")
        if len(argv) >= 2 and argv[1] == "doctor" and argv[0] in self.doctor:
            return base.CliResult(0, json.dumps(self.doctor[argv[0]]), "")
        return base.CliResult(127, "", "not found")


@pytest.fixture
def tools(monkeypatch) -> FakeTools:
    fake = FakeTools()
    monkeypatch.setattr(skill_tools, "RUNNER", fake)
    monkeypatch.setattr(skill_tools, "WHICH",
                        lambda name: f"/fake/bin/{name}" if name == "uv" or name in fake.texts else None)
    skill_tools.clear_cache()
    return fake


# --------------------------------------------------------------------------- discovery


def test_discovery_reads_every_agent_folder_and_says_who_sees_what(home):
    skill(home / ".claude/skills", "pdf-tidy")
    skill(home / ".codex/skills", "repo-map")
    skill(home / ".agents/skills", "shared-one")
    (home / ".cursor").mkdir()          # Cursor is here; Gemini CLI and OpenCode are not
    snap = run(skill_inventory.snapshot(run_tools=False))
    assert [a["id"] for a in snap["agents"]] == ["claude-code", "codex", "cursor"]
    found = rows(snap)
    assert set(found) == {"pdf-tidy", "repo-map", "shared-one"}
    assert agent(found["pdf-tidy"], "claude-code")["state"] == "on"
    assert agent(found["pdf-tidy"], "codex")["state"] == "off"
    cursor = agent(found["pdf-tidy"], "cursor")
    assert cursor["state"] == "through" and not cursor["canToggle"] and "Claude Code's folder" in cursor["note"]
    assert agent(found["shared-one"], "codex")["state"] == "through"
    assert agent(found["shared-one"], "claude-code")["state"] == "off"
    assert found["pdf-tidy"]["description"] == "Does a thing."
    assert found["pdf-tidy"]["source"]["kind"] == "local"


def test_a_skill_from_npx_skills_shows_its_repo_from_the_lock(home):
    skill(home / ".agents/skills", "web-design-guidelines")
    (home / ".agents" / ".skill-lock.json").write_text(json.dumps({"version": 3, "skills": {
        "web-design-guidelines": {"source": "alice-example/agent-skills", "sourceType": "github",
                                  "sourceUrl": "https://github.com/alice-example/agent-skills.git",
                                  "skillPath": "skills/web-design-guidelines/SKILL.md", "skillFolderHash": "x",
                                  "installedAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-10-01T00:00:00Z"}}}))
    row = rows(run(skill_inventory.snapshot(run_tools=False)))["web-design-guidelines"]
    assert row["source"] == {"kind": "github", "label": "alice-example/agent-skills",
                             "repo": "alice-example/agent-skills", "via": "npx skills",
                             "url": "https://github.com/alice-example/agent-skills/tree/HEAD/skills/web-design-guidelines"}
    assert row["update"]["state"] == "unchecked"


# --------------------------------------------------------------------------- adding by link or npx line


@pytest.mark.parametrize("text, want", [
    ("alice-example/handy-skills", ("alice-example", "handy-skills", None, None, None)),
    ("alice-example/handy-skills@release-notes", ("alice-example", "handy-skills", None, None, "release-notes")),
    ("alice-example/handy-skills/skills/release-notes",
     ("alice-example", "handy-skills", None, "skills/release-notes", None)),
    ("https://github.com/alice-example/handy-skills", ("alice-example", "handy-skills", None, None, None)),
    ("https://github.com/alice-example/handy-skills.git", ("alice-example", "handy-skills", None, None, None)),
    ("github.com/alice-example/handy-skills/tree/v1.2/skills/release-notes",
     ("alice-example", "handy-skills", "v1.2", "skills/release-notes", None)),
    ("https://github.com/alice-example/handy-skills/blob/main/skills/release-notes/SKILL.md",
     ("alice-example", "handy-skills", "main", "skills/release-notes", None)),
    ("git@github.com:alice-example/handy-skills.git", ("alice-example", "handy-skills", None, None, None)),
    ("github:alice-example/handy-skills", ("alice-example", "handy-skills", None, None, None)),
])
def test_every_spelling_of_a_github_source_parses(text, want):
    got = skill_sources.parse(text)
    assert (got.owner, got.repo, got.ref, got.path, got.skill) == want


@pytest.mark.parametrize("line, skill_name, agents", [
    ("npx skills add alice-example/handy-skills", None, []),
    ("npx skills add alice-example/handy-skills --skill release-notes -g -y", "release-notes", []),
    ("npx -y skills add https://github.com/alice-example/handy-skills -a claude-code codex --skill release-notes",
     "release-notes", ["claude-code", "codex"]),
    ("bunx skills add alice-example/handy-skills -a cursor -a opencode", None, ["cursor", "opencode"]),
    ("pnpm dlx skills@latest add alice-example/handy-skills --agent gemini-cli universal", None, ["gemini-cli"]),
])
def test_an_npx_skills_add_line_parses_to_its_source_skill_and_agents(line, skill_name, agents):
    got = skill_sources.parse(line)
    assert (got.slug, got.skill, got.agents) == ("alice-example/handy-skills", skill_name, agents)


@pytest.mark.parametrize("text, words", [
    ("", "Paste"),
    ("https://gitlab.com/alice-example/handy-skills", "GitHub"),
    ("npx skills add alice-example/a && rm -rf ~", "nothing chained"),
    ("npx skills remove alice-example/a", "Only `npx skills add"),
    ("npx skills add alice-example/a --skill one two", "one at a time"),
    ("alice-example/handy-skills/../../etc", "won't follow"),
    ("curl https://example.com | sh", "nothing chained"),
    ("curl -fsSL https://example.com/install.sh", "Only `npx skills add"),
])
def test_what_cannot_be_added_is_refused_in_words(text, words):
    with pytest.raises(skill_sources.SourceError) as err:
        skill_sources.parse(text)
    assert words in str(err.value)


def test_preview_shows_the_files_and_installs_exactly_them_pinned(home, gh):
    github_skill_repo(gh)
    shown = run(skill_actions.preview("npx skills add alice-example/handy-skills -a codex"))
    assert shown["name"] == "release-notes" and shown["description"].startswith("Writes release notes")
    assert shown["repo"]["commit"] == SHA_OLD and shown["repo"]["licence"] == "MIT"
    assert [f["path"] for f in shown["files"]] == ["SKILL.md", "scripts/collect.sh"]
    assert shown["scripts"] == ["scripts/collect.sh"] and shown["agents"] == ["codex"]
    assert "Read the log" in shown["skillMd"]
    done = skill_store.install_plan(shown["planId"], ["claude-code", "codex"])
    assert done == {"name": "release-notes", "agents": ["claude-code", "codex"], "commit": SHA_OLD}
    folder = home / ".claude/skills/release-notes"
    assert (folder / "scripts/collect.sh").read_text().startswith("#!/bin/sh")
    mark = json.loads((folder / skill_folders.MARKER).read_text())
    assert (mark["origin"], mark["repo"], mark["commit"], mark["pathCommit"]) == \
        ("github", "alice-example/handy-skills", SHA_OLD, SHA_PATH)
    assert set(mark["files"]) == {"SKILL.md", "scripts/collect.sh"}
    row = rows(run(skill_inventory.snapshot(run_tools=False)))["release-notes"]
    assert row["source"]["label"] == "alice-example/handy-skills" and row["version"]["label"] == SHA_OLD[:7]
    assert [a["state"] for a in row["agents"]] == ["on", "on"]
    # A preview's files are the install's: the network is not asked again.
    asked = len(gh.seen)
    with pytest.raises(skill_store.StoreError):
        skill_store.install_plan("not-a-plan", ["claude-code"])
    assert len(gh.seen) == asked


def test_a_repo_with_several_skills_asks_which(home, gh):
    github_skill_repo(gh)
    gh.json(f"{API}/repos/alice-example/handy-skills/contents/skills?ref={SHA_OLD}",
            [{"name": "release-notes", "path": "skills/release-notes", "type": "dir"},
             {"name": "triage", "path": "skills/triage", "type": "dir"}])
    gh.json(f"{API}/repos/alice-example/handy-skills/contents/skills/triage?ref={SHA_OLD}",
            [{"name": "SKILL.md", "path": "skills/triage/SKILL.md", "type": "file", "size": 5}])
    shown = run(skill_actions.preview("alice-example/handy-skills"))
    assert [c["path"] for c in shown["choices"]] == ["skills/release-notes", "skills/triage"]
    picked = run(skill_actions.preview("alice-example/handy-skills", "skills/release-notes"))
    assert picked["name"] == "release-notes"


def test_github_trouble_is_said_in_words(home, gh):
    with pytest.raises(skill_sources.SourceError, match="nothing public there"):
        run(skill_actions.preview("alice-example/missing"))


# --------------------------------------------------------------------------- versions and updates


def _install_from_github(gh, home):
    github_skill_repo(gh)
    shown = run(skill_actions.preview("alice-example/handy-skills"))
    skill_store.install_plan(shown["planId"], ["claude-code"])


def test_an_update_is_found_and_lists_what_changed(home, gh):
    _install_from_github(gh, home)
    newest = f"{API}/repos/alice-example/handy-skills/commits?sha=main&per_page=20&path=skills/release-notes"

    def commit(sha, day, message):
        return {"sha": sha, "html_url": f"https://github.com/alice-example/handy-skills/commit/{sha}",
                "commit": {"message": message, "committer": {"date": f"2026-10-{day}T00:00:00Z"}}}

    gh.json(newest, [commit(SHA_PATH, "01", "First version")])
    saved = run(skill_inventory.check_updates())
    assert saved["results"]["release-notes"]["state"] == "current"
    gh.json(newest, [commit(SHA_NEW, "14", "Group notes by area\n\nLonger body."),
                     commit("d" * 40, "10", "Fix the date line"), commit(SHA_PATH, "01", "First version")])
    run(skill_inventory.check_updates())
    row = rows(run(skill_inventory.snapshot(run_tools=False)))["release-notes"]
    assert row["update"]["state"] == "available" and row["status"] == "update"
    assert row["update"]["from"] == SHA_OLD[:7]
    assert [c["title"] for c in row["update"]["changes"]] == ["Group notes by area", "Fix the date line"]
    assert row["update"]["changes"][0]["date"] == "2026-10-14"
    assert row["update"]["link"] == (f"https://github.com/alice-example/handy-skills/compare/"
                                     f"{SHA_PATH[:12]}...{SHA_NEW[:12]}")


def test_update_installs_upstreams_newest_pinned_in_every_agent_that_has_it(home, gh):
    _install_from_github(gh, home)
    skill_store.turn_on("release-notes", "codex")
    new_md = "---\nname: release-notes\ndescription: Writes better release notes.\n---\n\nv2\n"
    github_skill_repo(gh, sha=SHA_NEW, skill_md=new_md)
    run(skill_actions.update("release-notes"))
    for folder in (".claude/skills", ".codex/skills"):
        mark = json.loads((home / folder / "release-notes" / skill_folders.MARKER).read_text())
        assert mark["commit"] == SHA_NEW
        assert (home / folder / "release-notes/SKILL.md").read_text() == new_md


def test_a_tool_release_newer_than_the_installed_tool_is_an_update(home, gh, tools):
    skill(home / ".claude/skills", "macos-harness")
    tools.versions["macos-harness"] = "0.1.2"
    gh.json(f"{API}/repos/browser-use/macos-harness/releases?per_page=10", [
        {"tag_name": "v0.2.1", "html_url": "https://github.com/browser-use/macos-harness/releases/tag/v0.2.1",
         "published_at": "2026-10-15T03:51:02Z", "body": "Fixes the stop button."},
        {"tag_name": "v0.2.0", "html_url": "https://github.com/browser-use/macos-harness/releases/tag/v0.2.0",
         "published_at": "2026-10-14T18:57:14Z", "body": "Adds install and uninstall."},
        {"tag_name": "v0.1.2", "published_at": "2026-08-17T16:48:22Z", "body": "Old."}])
    saved = run(skill_inventory.check_updates())
    hit = saved["results"]["macos-harness"]
    assert (hit["state"], hit["latest"], hit["linkLabel"]) == ("available", "v0.2.1", "Release notes")
    assert [(c["title"], c["detail"]) for c in hit["changes"]] == [("v0.2.1", "Fixes the stop button."),
                                                                  ("v0.2.0", "Adds install and uninstall.")]
    tools.versions["macos-harness"] = "0.2.1"
    assert run(skill_inventory.check_updates())["results"]["macos-harness"]["state"] == "current"


def test_checks_never_run_twice_in_a_minute_and_the_open_page_waits_an_hour(home, gh, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    calls = []

    async def fake_check(**kwargs):
        calls.append(1)
        return skill_store.save_updates({})

    monkeypatch.setattr(skill_inventory, "check_updates", fake_check)
    with TestClient(main.app) as client:
        assert client.post("/skills/check", json={}).status_code == 200
        assert client.post("/skills/check", json={}).json().get("skipped") is True
        assert client.post("/skills/check", json={"auto": True}).json().get("skipped") is True
    assert len(calls) == 1


# --------------------------------------------------------------------------- a tool's skill text


def test_skill_text_older_than_its_tool_is_detected_and_refreshed(home, tools):
    old = home / ".claude/skills/macos-harness"
    skill(home / ".claude/skills", "macos-harness", body="old 0.1 text")
    tools.versions["macos-harness"] = "0.2.1"
    tools.texts["macos-harness"] = "---\nname: macos-harness\ndescription: Use apps.\n---\n\nnew 0.2 text\n"
    tools.doctor["macos-harness"] = {"ready": False, "app": "Terminal",
                                     "granted": {"accessibility": True, "screen_recording": False}}
    row = rows(run(skill_inventory.snapshot()))["macos-harness"]
    assert row["tool"]["text"] == "older" and row["tool"]["version"] == "0.2.1" and row["status"] == "refresh"
    assert row["details"]["excerpt"] == "old 0.1 text"
    assert row["version"]["label"] == "v0.2.1"
    assert row["permissions"]["line"] == "Not allowed yet: Screen Recording."
    run(skill_actions.refresh("macos-harness"))
    assert "new 0.2 text" in (old / "SKILL.md").read_text()
    kept = list((skill_store.state_dir() / "removed").iterdir())
    assert len(kept) == 1 and "old 0.1 text" in (kept[0] / "SKILL.md").read_text(), "the old text is kept"
    skill_tools.clear_cache()
    assert rows(run(skill_inventory.snapshot()))["macos-harness"]["tool"]["text"] == "current"


def test_cicadas_own_copy_knows_its_tool_version_without_running_the_tool(home, tools):
    skill_store.write_tool_text("macos-harness", "---\nname: macos-harness\ndescription: x\n---\nold\n",
                                "macos-harness", "0.1.2", "browser-use/macos-harness", ["claude-code"])
    tools.versions["macos-harness"] = "0.2.1"
    row = rows(run(skill_inventory.snapshot()))["macos-harness"]
    assert row["tool"]["text"] == "older" and row["tool"]["textVersion"] == "0.1.2"
    assert not any(c[1:2] == ["skill"] for c in tools.calls), "the marker answered; the tool was not run"


def test_a_tool_install_runs_uv_pinned_then_writes_the_text_it_prints(home, tools):
    tools.texts["macos-harness"] = "---\nname: macos-harness\ndescription: Use apps.\n---\n\nbody\n"
    tools.versions["next:macos-harness"] = "0.2.1"
    entry = skill_actions.catalog_entry("macos-harness")
    result = run(skill_store.install_tool(entry, ["claude-code", "codex"]))
    install = next(c for c in tools.calls if c[:3] == ["uv", "tool", "install"])
    assert install[-1] == f"git+https://github.com/browser-use/macos-harness@{entry['pin']['sha']}"
    assert result["version"] == "0.2.1"
    for folder in (".claude/skills", ".codex/skills"):
        mark = json.loads((home / folder / "macos-harness" / skill_folders.MARKER).read_text())
        assert (mark["origin"], mark["tool"], mark["toolVersion"]) == ("tool", "macos-harness", "0.2.1")


def test_without_uv_a_tool_install_says_so(home):
    with pytest.raises(skill_store.StoreError, match="needs uv"):
        run(skill_store.install_tool(skill_actions.catalog_entry("browser-harness"), ["claude-code"]))


# --------------------------------------------------------------------------- per-agent toggles


def test_toggles_copy_from_the_library_and_keep_what_cicada_did_not_write(home):
    skill(home / ".claude/skills", "notes-helper", body="mine")
    skill_store.turn_on("notes-helper", "codex")
    assert (home / ".codex/skills/notes-helper/SKILL.md").read_text().endswith("mine\n")
    skill_store.turn_off("notes-helper", "claude-code")      # the person's own copy: kept aside, not deleted
    assert not (home / ".claude/skills/notes-helper").exists()
    kept = list((skill_store.state_dir() / "removed").iterdir())
    assert [p.name.split("-off-")[0] for p in kept] == ["notes-helper"]
    skill_store.turn_off("notes-helper", "codex")            # Cicada's own copy: deleted, the library keeps one
    assert not (home / ".codex/skills/notes-helper").exists()
    row = rows(run(skill_inventory.snapshot(run_tools=False)))["notes-helper"]
    assert [a["state"] for a in row["agents"]] == ["off", "off"] and agent(row, "codex")["canToggle"]
    skill_store.turn_on("notes-helper", "claude-code")
    assert (home / ".claude/skills/notes-helper/SKILL.md").exists()


def test_a_linked_skill_is_unlinked_never_followed(home, tmp_path):
    target = skill(tmp_path / "elsewhere", "linked-one")
    (home / ".claude/skills").mkdir(parents=True)
    (home / ".claude/skills/linked-one").symlink_to(target)
    skill_store.turn_off("linked-one", "claude-code")
    assert not (home / ".claude/skills/linked-one").exists() and (target / "SKILL.md").exists()


def test_a_file_the_person_added_makes_a_copy_theirs(home):
    skill_store.install_files("tidy", {"SKILL.md": b"---\nname: tidy\ndescription: d\n---\n"}, {"origin": "local"},
                              ["claude-code"])
    (home / ".claude/skills/tidy/notes.txt").write_text("my notes")
    skill_store.remove("tidy")
    kept = list((skill_store.state_dir() / "removed").iterdir())
    assert [(p / "notes.txt").read_text() for p in kept if (p / "notes.txt").exists()] == ["my notes"]


def test_toggle_routes_and_refusals(home):
    from fastapi.testclient import TestClient

    from api import main

    skill(home / ".claude/skills", "notes-helper")
    with TestClient(main.app) as client:
        assert client.put("/skills/notes-helper/agents/codex", json={"on": True}).status_code == 200
        assert (home / ".codex/skills/notes-helper/SKILL.md").exists()
        bad = client.put("/skills/notes-helper/agents/emacs", json={"on": True})
        assert bad.status_code == 409 and "doesn't know an agent" in bad.json()["detail"]
        assert client.put("/skills/..%2Fescape/agents/codex", json={"on": True}).status_code in (404, 409)


# --------------------------------------------------------------------------- onboarding


def test_onboarding_offers_the_two_harnesses_ticked_and_the_video_one_not(home):
    offer = skill_actions.onboarding_offer()
    by_id = {s["id"]: s for s in offer["suggestions"]}
    assert list(by_id) == ["browser-harness", "macos-harness", "watch", "hoff-harness"]
    assert by_id["browser-harness"]["default"] and by_id["macos-harness"]["default"]
    assert not by_id["watch"]["default"] and not by_id["hoff-harness"]["default"]
    assert [s["title"] for s in offer["suggestions"]] == ["Websites", "Mac apps", "Videos", "Show me"]
    # hoff (G220): its permissions are said plainly, and Cicada is not the one asking for them.
    assert "Accessibility and Screen Recording" in by_id["hoff-harness"]["asks"]
    assert "Cicada never asks" in by_id["hoff-harness"]["asks"]
    assert not by_id["hoff-harness"]["needsUv"]   # a pinned folder copy; uv is what the skill itself runs with
    assert "any page" in by_id["browser-harness"]["line"]
    assert "apps on this Mac" in by_id["macos-harness"]["line"]
    assert "Accessibility and Screen Recording" in by_id["macos-harness"]["asks"]
    assert by_id["macos-harness"]["needsUv"] and not by_id["watch"]["needsUv"]
    assert offer["uv"]["present"] is False and offer["uv"]["installUrl"].startswith("https://docs.astral.sh/uv")
    assert offer["answer"] is None


def test_no_thanks_is_recorded_and_installs_nothing(home):
    from fastapi.testclient import TestClient

    from api import main

    with TestClient(main.app) as client:
        answer = client.post("/skills/onboarding", json={"install": []}).json()
        assert answer["job"] is None
        assert answer["answer"]["declined"] == ["browser-harness", "hoff-harness", "macos-harness", "watch"]
        assert client.get("/skills/onboarding").json()["answer"]["install"] == []
    assert not (home / ".claude/skills").exists()


def test_continuing_installs_what_stayed_ticked(home, tools):
    from fastapi.testclient import TestClient

    from api import main

    tools.texts["macos-harness"] = "---\nname: macos-harness\ndescription: Use apps.\n---\n"
    tools.texts["browser-harness"] = "---\nname: browser-harness\ndescription: Use Chrome.\n---\n"
    with TestClient(main.app) as client:
        answer = client.post("/skills/onboarding",
                             json={"install": ["browser-harness", "macos-harness", "not-offered"],
                                   "agents": ["claude-code"]}).json()
        assert answer["answer"]["install"] == ["browser-harness", "macos-harness"]
        assert answer["answer"]["declined"] == ["hoff-harness", "watch"]
        job = answer["job"]
        deadline = time.monotonic() + 10
        while job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            job = client.get(f"/skills/jobs/{job['id']}").json()
        assert job["state"] == "done" and job["result"]["installed"] == ["browser-harness", "macos-harness"]
    assert (home / ".claude/skills/macos-harness/SKILL.md").exists()
    assert (home / ".claude/skills/browser-harness/SKILL.md").exists()


# --------------------------------------------------------------------------- a suggestion copied at its reviewed pin


_PINNED_MD = "---\nname: release-notes\ndescription: Writes release notes from merged work.\n---\n\nRead the log.\n"
_PINNED_SCRIPT = "#!/bin/sh\ngit log --oneline\n"


def _pinned_entry(script_sha: str) -> dict:
    """A copy-method suggestion shaped like hoff's (G220): a folder with a script, every file's hash pinned."""
    import hashlib

    return {"id": "release-notes", "kind": "skill", "rank": 99, "title": "Release notes",
            "pin": {"repo": "alice-example/handy-skills", "ref": "main", "sha": SHA_OLD,
                    "path": "skills/release-notes",
                    "skillMdSha256": hashlib.sha256(_PINNED_MD.encode()).hexdigest(),
                    "files": {"scripts/collect.sh": script_sha}},
            "agents": {"claude-code": {"method": "skills-cli"}},
            "detect": {"skillDirs": ["release-notes"]}}


def test_a_suggestion_installs_its_reviewed_folder_with_scripts_runnable_and_no_hooks(home, gh, monkeypatch):
    import hashlib

    github_skill_repo(gh, ref=SHA_OLD, skill_md=_PINNED_MD)
    entry = _pinned_entry(hashlib.sha256(_PINNED_SCRIPT.encode()).hexdigest())
    monkeypatch.setattr(skill_actions, "catalog_entry", lambda _id: entry)
    out = run(skill_actions.install_suggested("release-notes", ["claude-code"]))
    assert out["agents"] == ["claude-code"] and out["commit"] == SHA_OLD
    folder = home / ".claude/skills/release-notes"
    assert (folder / "SKILL.md").read_text() == _PINNED_MD
    assert (folder / "scripts/collect.sh").stat().st_mode & 0o111      # the script stays runnable
    # The skills rail: a skill is text and its own files — no agent settings, no hooks (G138, G220).
    assert not (home / ".claude/settings.json").exists()
    assert not (home / ".claude/hooks").exists()


def test_a_suggestion_whose_bytes_differ_from_the_review_installs_nothing(home, gh, monkeypatch):
    github_skill_repo(gh, ref=SHA_OLD, skill_md=_PINNED_MD)
    monkeypatch.setattr(skill_actions, "catalog_entry", lambda _id: _pinned_entry("0" * 64))
    with pytest.raises(skill_store.StoreError, match="doesn't match the version Cicada reviewed"):
        run(skill_actions.install_suggested("release-notes", ["claude-code"]))
    assert not (home / ".claude/skills/release-notes").exists()
    assert skill_store.library() == {}


# --------------------------------------------------------------------------- agents: ask, draft, hold


def _ctx(tmp_path, harness: str):
    bank = tmp_path / "bank"
    bank.mkdir(exist_ok=True)
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="sess-1", harness=harness)


def test_an_agent_drafts_a_skill_that_is_held_until_the_person_publishes_it(home, tmp_path):
    ctx = _ctx(tmp_path, "codex")
    out = mcp_tools.create_skill(ctx, "release-notes", "Write release notes from merged work.",
                                 "1. Read the log.\n2. Group by area.", "We do this every Friday.")
    assert "held" in out and "Made by your agents" in out
    assert not (home / ".claude/skills/release-notes").exists() and not (home / ".codex/skills").exists()
    snap = run(skill_inventory.snapshot(run_tools=False))
    assert snap["installed"] == []
    draft = snap["drafts"][0]
    assert (draft["name"], draft["author"], draft["authorLabel"], draft["state"]) == \
        ("release-notes", "codex", "Codex", "held")
    assert "name: release-notes" in draft["text"] and "Group by area" in draft["text"]
    assert "Another agent" in mcp_tools.create_skill(_ctx(tmp_path, "claude-code"), "release-notes", "d", "b")
    skill_store.publish_draft("release-notes", ["claude-code"])
    mark = json.loads((home / ".claude/skills/release-notes" / skill_folders.MARKER).read_text())
    assert (mark["origin"], mark["author"]) == ("draft", "codex")
    row = rows(run(skill_inventory.snapshot(run_tools=False)))["release-notes"]
    assert row["source"]["label"] == "Made by Codex" and snap["drafts"] and \
        run(skill_inventory.snapshot(run_tools=False))["drafts"] == []


def test_an_install_is_always_a_request_even_from_a_trusted_agent(home, tmp_path):
    ctx = _ctx(tmp_path, "claude-code")
    assert page_editors.is_trusted("claude-code")
    out = mcp_tools.propose_skill(ctx, "install", source="npx skills add alice-example/handy-skills -a codex",
                                  reason="You asked for release notes help.")
    assert out.startswith("Filed for the person") and "see the source and the files" in out
    (req,) = skill_store.requests()
    assert (req["action"], req["author"], req["agents"]) == ("install", "claude-code", ["codex"])
    assert not (home / ".codex/skills").exists(), "nothing installed"
    assert "Not filed" in mcp_tools.propose_skill(ctx, "install", source="ftp://x", reason="r")
    assert "say why" in mcp_tools.propose_skill(ctx, "update", name="x", reason="")


def test_turning_on_applies_at_once_only_for_a_trusted_agent(home, tmp_path):
    skill(home / ".claude/skills", "notes-helper")
    out = mcp_tools.propose_skill(_ctx(tmp_path, "cursor"), "on", name="notes-helper", agents=["codex"],
                                  reason="The person uses Codex too.")
    assert out.startswith("Filed for the person") and "not on the person's trusted list" in out
    assert not (home / ".codex/skills/notes-helper").exists()
    out = mcp_tools.propose_skill(_ctx(tmp_path, "claude-code"), "on", name="notes-helper", agents=["codex"],
                                  reason="The person uses Codex too.")
    assert out.startswith("Done") and (home / ".codex/skills/notes-helper/SKILL.md").exists()


def test_the_list_tool_reports_without_fetching(home, tmp_path, gh):
    skill(home / ".claude/skills", "notes-helper", description="Keeps notes tidy.")
    out = mcp_tools.skills(_ctx(tmp_path, "codex"))
    assert out.startswith(mcp_tools.REFERENCE_HEADER)
    assert "- notes-helper — Keeps notes tidy." in out and "in Claude Code" in out
    assert gh.seen == []


def test_nothing_is_written_into_a_bank(home, tmp_path, gh):
    ctx = _ctx(tmp_path, "codex")
    bank = ctx.memory_path()
    mcp_tools.create_skill(ctx, "x-skill", "d", "b")
    mcp_tools.propose_skill(ctx, "install", source="alice-example/handy-skills", reason="r")
    _install_from_github(gh, home)
    assert list(bank.iterdir()) == []


def test_the_skills_route_answers_with_every_section(home):
    from fastapi.testclient import TestClient

    from api import main

    skill(home / ".claude/skills", "notes-helper")
    with TestClient(main.app) as client:
        page = client.get("/skills").json()
    assert set(page) >= {"agents", "installed", "suggested", "drafts", "noticed", "requests", "checkedAt", "uv",
                         "jobs"}
    methods = {s["id"]: s["method"] for s in page["suggested"]}
    assert methods["macos-harness"] == "tool" and methods["watch"] == "copy" and methods["pdf"] == "manual"
    assert methods["cicada"] == "own"
    assert all(s.get("manual") for s in page["suggested"] if s["method"] == "manual")


# --------------------------------------------------------------------------- the one writer


FOLDER_LITERAL = re.compile(r"[\"'][~/]*\.(claude|codex|agents|cursor|gemini|config/opencode)/skills[\"']"
                            r"|\"\.(claude|codex|agents|cursor|gemini)\"\s*/\s*\"skills\"")
# `agent.own` (a skills folder), never `device_tokens.own` or a `.own()` call.
FOLDER_BUILDER = re.compile(r"(?<!device_tokens)\.own\b(?!\s*\()|skill_folders\.(SHARED|roots)")


def test_only_skill_store_writes_into_an_agents_skill_folder():
    """Every module that names an agent's skills folder and also writes files is skill_store."""
    root = Path(__file__).resolve().parents[1]
    writes = ("write_text(", "write_bytes(", "shutil.move(", "shutil.rmtree(", "os.rename(", "os.replace(",
              ".unlink(", "copytree(")
    offenders = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        names_folder = FOLDER_LITERAL.search(text) or FOLDER_BUILDER.search(text)
        if names_folder and any(w in text for w in writes):
            offenders.append(path.relative_to(root).as_posix())
    assert offenders == ["services/skill_store.py"]


def test_the_agent_list_is_one_place():
    """Owner 2026-10-15: adding or removing an agent is one change. The skills table, the MCP schema's enum and the
    agents `agent_wiring` wires all come from `agent_wiring.AGENTS`."""
    from _stdio_server import stdio_server
    from api.services import agent_wiring

    ids = [a.id for a in agent_wiring.AGENTS]
    assert ids == ["claude-code", "codex", "cursor", "opencode", "hermes", "openclaw", "gemini-cli"]
    assert [a.id for a in skill_folders.AGENTS] == [a.id for a in agent_wiring.AGENTS if a.skills]
    wired = {h.id for h in agent_wiring.HARNESSES} | set(agent_wiring.CONFIG_AGENT_BINARIES) | {"cursor"}
    assert wired <= set(ids), "an agent the wiring knows is missing from the one list"
    srv = stdio_server()
    tool = next(t for t in srv.TOOLS if t["name"] == "cicada_propose_skill")
    assert tool["inputSchema"]["properties"]["agents"]["items"]["enum"] == [a.id for a in skill_folders.AGENTS]


def test_an_agent_that_is_not_installed_is_hidden(home):
    skill(home / ".claude/skills", "notes-helper")
    (home / ".hermes").mkdir()
    snap = run(skill_inventory.snapshot(run_tools=False))
    assert [a["id"] for a in snap["agents"]] == ["claude-code", "codex", "hermes"]
    assert [a["id"] for a in rows(snap)["notes-helper"]["agents"]] == ["claude-code", "codex", "hermes"]


# --------------------------------------------------------------------------- review blockers (2026-10-15)


def test_remove_never_deletes_a_skills_only_text(home, tmp_path):
    """Draft → publish → turn on → remove: the published draft's only text survives in removed/, restorable."""
    mcp_tools.create_skill(_ctx(tmp_path, "codex"), "release-notes", "Writes release notes.", "Only copy of this.")
    skill_store.publish_draft("release-notes", ["claude-code"])
    skill_store.turn_on("release-notes", "codex")
    skill_store.remove("release-notes")
    assert not (home / ".claude/skills/release-notes").exists() and not (home / ".codex/skills/release-notes").exists()
    assert "release-notes" not in skill_store.library() and skill_store.drafts() == []
    kept = [p for p in skill_store.removed_dir().iterdir() if (p / "SKILL.md").is_file()]
    assert kept and all("Only copy of this." in (p / "SKILL.md").read_text() for p in kept)


def test_remove_keeps_a_copy_cicada_never_had_in_its_library(home):
    skill(home / ".claude/skills", "hand-made", body="Mine alone.")
    skill_store.remove("hand-made")
    kept = list(skill_store.removed_dir().iterdir())
    assert kept and "Mine alone." in (kept[0] / "SKILL.md").read_text()


def test_no_skill_is_written_for_an_agent_that_is_not_on_this_mac(home, tmp_path):
    skill(home / ".claude/skills", "notes-helper")
    with pytest.raises(skill_store.StoreError, match="Hermes isn't installed"):
        skill_store.turn_on("notes-helper", "hermes")
    with pytest.raises(skill_store.StoreError, match="isn't installed"):
        skill_store.install_files("other", {"SKILL.md": b"---\nname: other\n---\n"}, {"origin": "local"},
                                  ["claude-code", "hermes"])
    out = mcp_tools.propose_skill(_ctx(tmp_path, "claude-code"), "on", name="notes-helper", agents=["hermes"],
                                  reason="Hermes too.")
    assert out.startswith("Not done") and "isn't installed" in out
    assert not (home / ".hermes").exists(), "nothing created, so Hermes never looks installed"
    assert not (home / ".claude/skills/other").exists(), "a refused install writes nothing at all"
    assert [a["id"] for a in run(skill_inventory.snapshot(run_tools=False))["agents"]] == ["claude-code", "codex"]


def test_a_saved_no_thanks_is_where_a_later_onboarding_starts(home):
    from fastapi.testclient import TestClient

    from api import main

    with TestClient(main.app) as client:
        client.post("/skills/onboarding", json={"install": []})
        again = {s["id"]: s for s in client.get("/skills/onboarding").json()["suggestions"]}
    assert not any(s["default"] for s in again.values()), "declined starts off on every later run"
    assert all(s["declined"] for s in again.values())

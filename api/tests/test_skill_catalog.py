"""G138 — the recommended-skill catalog is reviewed data, install state is read
per request without opening any agent config, and a bridge names only a tool
that exists (R-O23…R-O28). Every home here is a tmp dir (conftest)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.services import skill_catalog

CATALOG = skill_catalog.load()
SKILLS = CATALOG["skills"]
BY_ID = {s["id"]: s for s in SKILLS}
LOGOS = Path(__file__).resolve().parents[2] / "app/CicadaApp/Sources/CicadaApp/Resources/logos"


def test_the_brief_s_list_is_the_catalog():
    assert set(BY_ID) == {"watch", "skill-creator", "pdf", "paper-lookup", "literature-review",
                          "arxiv-mcp-server", "transcribe", "granola", "wispr-flow"}
    assert CATALOG["maxShown"] <= 5
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", CATALOG["reviewedAt"])


@pytest.mark.parametrize("entry", SKILLS, ids=lambda e: e["id"])
def test_every_entry_is_reviewable(entry):
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", entry["id"])
    assert entry["kind"] in skill_catalog.KINDS
    assert entry["sourceUrl"].startswith("https://") and entry["licence"]
    assert entry["title"] and entry["summary"] and entry["symbol"]
    assert set(entry["agents"]) <= set(skill_catalog.AGENTS) and entry["agents"]
    if entry["kind"] == "mcp-hosted":
        assert entry["endpoint"].startswith("https://") and entry["licence"] == "Hosted service"
    else:
        assert re.fullmatch(r"[0-9a-f]{40}", entry["pin"]["sha"]) and "/" in entry["pin"]["repo"]
        if "skillMdSha256" in entry["pin"]:
            assert re.fullmatch(r"[0-9a-f]{64}", entry["pin"]["skillMdSha256"])
    if entry["licence"] == "Proprietary":
        assert {a["method"] for a in entry["agents"].values()} == {"plugin"}, "never copied (R-O25)"
    for agent in entry["agents"]:
        plan = skill_catalog.install_plan(entry, agent)
        assert plan["env"]["CICADA_CAPTURE"] == "off"
        assert plan["steps"], f"{entry['id']} has no command for {agent}"
        for step in plan["steps"]:
            assert step["argv"][0] in skill_catalog.PROGRAMS, "only an agent's own installer (R-O24)"


def test_ranks_are_unique_and_the_catalog_names_no_person_or_machine():
    ranks = [s["rank"] for s in SKILLS]
    assert len(ranks) == len(set(ranks))
    text = skill_catalog.CATALOG_PATH.read_text(encoding="utf-8")
    assert "/Users/" not in text and "/home/" not in text


def test_watch_carries_its_terms_and_cicada_s_own_rail():
    watch = BY_ID["watch"]
    assert watch["terms"]["url"].startswith("https://www.youtube.com/t/terms")
    assert "never downloads video" in watch["cicadaNote"]
    assert watch["bridge"] == {"key": "video", "tool": "cicada_record_watch", "active": True}


def test_active_bridges_name_existing_tools_with_existing_arguments():
    tools = {t["name"]: t for t in stdio_server().TOOLS}
    for entry in SKILLS:
        bridge = entry.get("bridge")
        if not bridge or not bridge["active"]:
            continue
        text = skill_catalog.BRIDGE_TEXT[bridge["key"]]
        assert f"`{bridge['tool']}(" in text
    for key, text in skill_catalog.BRIDGE_TEXT.items():
        for name, args in re.findall(r"`(cicada_\w+)\(([^)]*)\)`", text):
            assert name in tools, f"{key} names {name}, which is not a tool (R12)"
            props = tools[name]["inputSchema"]["properties"]
            for arg in filter(None, (a.strip() for a in args.split(","))):
                assert arg in props, f"{name} has no argument {arg} (R12)"


def test_every_mark_is_committed_or_pending():
    for entry in SKILLS:
        mark = entry.get("mark")
        if mark is None:
            continue
        assert (LOGOS / f"{mark}.png").exists() or mark in skill_catalog.PENDING_MARKS, mark


# --- install state (R-O27) ---------------------------------------------------


def _skill(home: Path, root: str, name: str):
    folder = home / root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")


def test_the_suite_never_reads_the_real_home():
    assert skill_catalog.agent_home() != Path.home()


def test_skill_folders_and_plugin_ids(tmp_path):
    home = tmp_path / "h"
    _skill(home, ".claude/skills", "paper-lookup")
    _skill(home, ".agents/skills", "watch")
    state = skill_catalog.installed_state(BY_ID["paper-lookup"], home)
    assert state == {"claude-code": "installed", "codex": "not_installed"}
    assert skill_catalog.installed_state(BY_ID["watch"], home)["codex"] == "installed"
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"watch@claude-video": [{"scope": "user"}]}}))
    assert skill_catalog.installed_state(BY_ID["watch"], home)["claude-code"] == "installed"
    (plugins / "installed_plugins.json").write_text(json.dumps({"document-skills@anthropic-agent-skills": {}}))
    assert skill_catalog.installed_state(BY_ID["pdf"], home)["claude-code"] == "installed", "the flat shape too"
    (plugins / "installed_plugins.json").write_text("not json")
    assert skill_catalog.claude_plugin_ids(home) == frozenset()


def test_mcp_entries_are_unknown_never_installed(tmp_path):
    assert set(skill_catalog.installed_state(BY_ID["granola"], tmp_path).values()) == {"unknown"}
    assert set(skill_catalog.installed_state(BY_ID["arxiv-mcp-server"], tmp_path).values()) == {"unknown"}


# --- install plans (R-O24) ---------------------------------------------------


def test_plans_follow_upstream():
    plugin = skill_catalog.install_plan(BY_ID["watch"], "claude-code")
    assert [s["argv"] for s in plugin["steps"]] == [
        ["claude", "plugin", "marketplace", "add", "bradautomates/claude-video"],
        ["claude", "plugin", "install", "watch@claude-video", "--scope", "user"],
    ]
    assert plugin["steps"][0]["tolerateFailure"] is True and plugin["runnable"] is True
    cli = skill_catalog.install_plan(BY_ID["watch"], "codex")
    assert cli["steps"][0]["argv"] == [
        "npx", "--yes", "skills", "add",
        "https://github.com/bradautomates/claude-video/tree/83da59fa78c3eee9e20f515fe75c438bb5166efd/skills/watch",
        "-g", "-a", "codex", "-y",
    ]
    assert cli["env"]["DISABLE_TELEMETRY"] == "1" and cli["env"]["DO_NOT_TRACK"] == "1"
    hosted = skill_catalog.install_plan(BY_ID["granola"], "claude-code")
    assert hosted["runnable"] is False, "OAuth belongs to the agent — copy only"
    assert hosted["steps"][0]["argv"][-1] == "https://mcp.granola.ai/mcp"


# --- the recommended list ----------------------------------------------------


def test_at_most_five_by_rank_and_installed_ones_step_aside(tmp_path):
    home = tmp_path / "h"
    fresh = skill_catalog.recommended(home=home)
    assert [s["id"] for s in fresh["recommended"]] == ["watch", "paper-lookup", "wispr-flow", "granola", "skill-creator"]
    assert fresh["installed"] == [] and fresh["catalogSize"] == 9
    _skill(home, ".claude/skills", "watch")
    after = skill_catalog.recommended(home=home)
    assert [s["id"] for s in after["installed"]] == ["watch"]
    assert [s["id"] for s in after["recommended"]][-1] == "arxiv-mcp-server"
    assert len(after["recommended"]) == 5


# --- bridges -----------------------------------------------------------------


def test_bridge_lines_only_for_installed_active_bridges_in_that_agent(tmp_path):
    home = tmp_path / "h"
    assert skill_catalog.bridge_lines("claude-code", home=home) == []
    _skill(home, ".claude/skills", "paper-lookup")
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True)
    # `pdf` is installed, but its `documents` bridge stays inactive (R-B14).
    (plugins / "installed_plugins.json").write_text(json.dumps({"document-skills@anthropic-agent-skills": {}}))
    lines = skill_catalog.bridge_lines("claude-code", home=home)
    assert len(lines) == 1 and "`paper-lookup` is installed" in lines[0] and "cicada_save_url(url)" in lines[0]
    assert skill_catalog.bridge_lines("codex", home=home) == []
    assert skill_catalog.bridge_lines("generic", home=home) == []
    _skill(home, ".claude/skills", "literature-review")
    both = skill_catalog.bridge_lines("claude-code", home=home)
    assert len(both) == 1 and "are installed" in both[0], "one line per bridge key"


def test_the_video_and_meeting_bridges_are_active_and_documents_is_not():
    """R-B14: the watch record (G140) and speaker-aware evidence (G134) shipped, so
    these bridges name tools that work; nothing yet says who wrote a document."""
    active = {e["id"]: (e["bridge"] or {}).get("active") for e in SKILLS}
    assert active["watch"] is True
    assert (active["wispr-flow"], active["granola"], active["transcribe"]) == (True, True, True)
    assert active["pdf"] is False
    assert set(skill_catalog.BRIDGE_TEXT) == {"papers", "video", "meetings"}


def test_a_watch_skill_gets_the_watch_record_line(tmp_path):
    home = tmp_path / "h"
    _skill(home, ".claude/skills", "watch")
    (line,) = skill_catalog.bridge_lines("claude-code", home=home)
    assert "`watch` is installed" in line and "`cicada_record_watch(url, summary, excerpts)`" in line


def test_a_transcription_skill_gets_the_speaker_line(tmp_path):
    home = tmp_path / "h"
    _skill(home, ".codex/skills", "transcribe")
    (line,) = skill_catalog.bridge_lines("codex", home=home)
    assert "`cicada_save_episode(content, title)`" in line
    assert "speaker:<name>:" in line and "never `user:`" in line


def test_a_meeting_saved_the_bridges_way_is_never_the_persons_words():
    """The line's promise, checked against the one marker grammar (R-N2)."""
    from api.services import evidence

    body = "speaker:Alex Example: we ship alpha-project on Friday\nspeaker:unknown: sounds good"
    assert {evidence.speaker_kind(body, 0), evidence.speaker_kind(body, body.index("sounds"))} == {"speaker"}

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
                          "arxiv-mcp-server", "transcribe", "granola", "wispr-flow", "browser-harness",
                          "macos-harness"}
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
        if entry["agents"][agent]["method"] == "agent-prompt":
            # copy-only: a text for the person's own agent, no command anywhere (R-O24, R-O26)
            assert plan["steps"] == [] and plan["runnable"] is False
            assert 0 < len(plan["prompt"]) <= 1200 and "/Users/" not in plan["prompt"]
        else:
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
    assert fresh["installed"] == [] and fresh["catalogSize"] == 11
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


# --- the role skills (G166: how your agent reads / watches) -----------------------------------------


ROLE_SKILLS = ("browser-harness", "macos-harness")


def test_roles_are_known_jobs_and_need_an_invoke_name():
    for entry in SKILLS:
        roles = entry.get("roles") or []
        assert set(roles) <= skill_catalog.ROLES, entry["id"]
        if roles:
            assert entry["kind"] == "skill" and entry.get("invoke") and entry.get("pageName")
            assert entry.get("pageSummary") or entry.get("summary")
            assert "reach" in entry
        if "watching" in roles:
            assert entry.get("terms"), "an entry offered for watching carries its terms sentence"
    from api.services import agent_methods

    assert set(agent_methods.JOBS) <= skill_catalog.ROLES


def test_the_three_role_skills_are_pinned_to_a_real_sha_and_hash():
    assert BY_ID["watch"]["roles"] == ["watching"]
    for sid in ROLE_SKILLS:
        pin = BY_ID[sid]["pin"]
        assert re.fullmatch(r"[0-9a-f]{40}", pin["sha"]) and re.fullmatch(r"[0-9a-f]{64}", pin["skillMdSha256"])
        assert BY_ID[sid]["roles"] == ["reading", "watching"]
    # the values the reviewer verified with scripts/verify-skills.sh
    assert BY_ID["browser-harness"]["pin"]["sha"] == "c24e5072ee66f8499bacd663f4f4bcb089bc4492"
    assert BY_ID["browser-harness"]["pin"]["path"] == ""
    assert BY_ID["macos-harness"]["pin"]["sha"] == "b88e4d77403bbcac35752eef4f4dd72db3663fd6"


def test_new_entries_do_not_displace_the_top_five():
    assert BY_ID["browser-harness"]["rank"] == 10 and BY_ID["macos-harness"]["rank"] == 11
    assert max(s["rank"] for s in SKILLS if s["id"] not in ROLE_SKILLS) < 10


def test_agent_prompt_plans_are_copy_only_and_run_nothing():
    before = set(skill_catalog.PROGRAMS)
    for sid in ROLE_SKILLS:
        for agent in ("claude-code", "codex"):
            plan = skill_catalog.install_plan(BY_ID[sid], agent)
            assert plan["runnable"] is False and plan["steps"] == [] and plan["prompt"]
    assert skill_catalog.PROGRAMS == before and "uv" not in skill_catalog.PROGRAMS


def test_prompts_pin_the_reviewed_version_carry_no_global_trigger_and_ask_before_permissions():
    bh = skill_catalog.install_plan(BY_ID["browser-harness"], "claude-code")["prompt"]
    mh = skill_catalog.install_plan(BY_ID["macos-harness"], "claude-code")["prompt"]
    assert "browser-harness==0.1.13" in bh and "--upgrade" not in bh and "--force" not in bh
    assert "macos-harness==0.1.2" in mh and "--upgrade" not in mh and "--force" not in mh
    for prompt in (bh, mh):
        assert "Always use" not in prompt and "do not make it your default" in prompt
        assert "ask me" in prompt.lower()
    assert "recordings" in bh and "macOS permission" in bh
    assert "permission" in mh and "telemetry disable" in mh


def test_symlinked_skill_folder_counts_as_installed(tmp_path):
    """macos-harness and browser-harness are symlinked into ~/.codex/skills; is_file() follows them."""
    home = tmp_path / "h"
    real = tmp_path / "elsewhere" / "browser-harness"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("---\nname: browser-harness\n---\n", encoding="utf-8")
    for root in (".claude/skills", ".codex/skills"):
        (home / root).mkdir(parents=True)
        (home / root / "browser-harness").symlink_to(real, target_is_directory=True)
    state = skill_catalog.installed_state(BY_ID["browser-harness"], home)
    assert state == {"claude-code": "installed", "codex": "installed"}


def test_the_role_fields_reach_the_wire_view(tmp_path):
    view = skill_catalog._view(BY_ID["browser-harness"], tmp_path, frozenset())
    assert view["roles"] == ["reading", "watching"] and view["invoke"] == "browser-harness" and view["reach"]
    assert view["install"]["claude-code"]["prompt"] and view["install"]["claude-code"]["steps"] == []

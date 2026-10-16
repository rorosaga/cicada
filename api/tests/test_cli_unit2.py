"""G180 slice 1, unit 2 — `cicada get | project | continue | save | handshake`.

Each command runs the same body as its MCP tool; generated actions are spelled as
commands the CLI holds and parse back through the real parser (R12 by construction);
memory's own text is never rewritten; `save` is the one write (Awake capture: scrub,
dedup, `episode_lock`, demo refusal, the pinned bank, the root cross-check, harness
provenance with no minted session)."""
from __future__ import annotations

import json
import os
import re
import shlex

import pytest

from _cli import cli_env, envelope, health_server, run_cli
from _continuity_fixtures import write_session
from _synthetic_bank import _bank, _entity
from api.services import continuity, markdown_parser, mcp_tools
from test_continuity import A_TURNS

UUID = "11111111-2222-4333-8444-555555555555"
TICKED = re.compile(r"`(cicada [^`]*)`")


@pytest.fixture
def inprocess(monkeypatch):
    from api.config import Settings, get_settings

    before = Settings.model_config.get("env_file")
    # `cli.main` probes the backend's /healthz: never the default port, where a real backend may run.
    from _cli import free_port

    monkeypatch.setenv("CICADA_PORT", str(free_port()))
    monkeypatch.setenv("LITELLM_MODE", "PRODUCTION")
    monkeypatch.delenv("CICADA_MEMORY_ROOT", raising=False)
    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR", "CICADA_SESSION_ID", "CICADA_SESSION_HARNESS"):
        monkeypatch.delenv(key, raising=False)
    yield
    Settings.model_config["env_file"] = before
    get_settings.cache_clear()


def _work(tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return work


def _env(tmp_path, memory, **extra):
    """A scratch environment with no harness identity unless the test gives one."""
    env = cli_env(tmp_path, memory)
    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR", "CICADA_SESSION_ID", "CICADA_SESSION_HARNESS"):
        env.pop(key, None)
    env.update(extra)
    return env


def assert_commands_parse(text: str) -> None:
    """Every command Cicada spells in a CLI reply parses with the real parser (placeholders filled)."""
    from api import cli

    for span in TICKED.findall(text):
        words = ["x" if re.fullmatch(r"<[^>]+>", w) else w for w in shlex.split(span)]
        try:
            cli.build_parser().parse_args(words[1:])
        except cli._HelpShown:                      # `cicada --help` is a command it holds too
            pass


# --- get --------------------------------------------------------------------------------------

def _long_page(memory):
    _entity(memory, "delta-notes", body="## Summary\n" + "\n".join(f"line {i}" for i in range(1, 21)) + "\n")
    _entity(memory, "alpha-beta", name="Alpha: Beta", body="## Summary\nThe colon page.\n")
    _entity(memory, "release-2", name="2026:10", body="## Summary\nA numeric-looking name.\n")


def test_get_reads_a_whole_page_like_the_mcp_tool(tmp_path):
    memory = _bank(tmp_path, git=False)
    out = envelope(run_cli(["get", "alpha-project", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    stdio = mcp_tools.recall_detail(mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s",
                                                          harness="unknown"), "alpha-project")
    assert out["ok"] is True and out["text"] == stdio                        # verbatim
    assert out["data"]["entity_id"] == "alpha-project" and out["data"]["type"] == "project"
    assert out["data"]["from"] == 1 and out["data"]["count"] == out["data"]["total_lines"]


@pytest.mark.parametrize("args, first, count", [
    (["delta-notes", "--from", "5", "--count", "3"], 5, 3),
    (["delta-notes:5:7"], 5, 3),           # the shorthand: lines 5 to 7
    (["delta-notes:20"], 20, None),        # from line 20 to the end
])
def test_get_bounded_reads(tmp_path, args, first, count):
    memory = _bank(tmp_path, git=False)
    _long_page(memory)
    out = envelope(run_cli(["get", *args, "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    data = out["data"]
    assert out["ok"] is True and data["from"] == first
    if count is not None:
        assert data["count"] == count and len(out["text"].splitlines()) == count
    else:
        assert data["from"] + data["count"] - 1 == data["total_lines"]


def test_get_line_numbers(tmp_path):
    memory = _bank(tmp_path, git=False)
    _long_page(memory)
    out = envelope(run_cli(["get", "delta-notes", "--from", "2", "--count", "2", "--line-numbers", "--json"],
                           _env(tmp_path, memory), cwd=_work(tmp_path)))
    lines = out["text"].splitlines()
    assert lines[0].startswith("2: ") and lines[1].startswith("3: ")


@pytest.mark.parametrize("name, expect", [("Alpha: Beta", "The colon page."), ("2026:10", "A numeric-looking name.")])
def test_a_name_with_a_colon_is_read_literally_first(tmp_path, name, expect):
    memory = _bank(tmp_path, git=False)
    _long_page(memory)
    out = envelope(run_cli(["get", name, "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    assert out["ok"] is True and expect in out["text"]


@pytest.mark.parametrize("args", [
    ["delta-notes", "--from", "0"], ["delta-notes", "--count", "0"], ["delta-notes", "--from", "99"],
    ["delta-notes:7:5"], ["delta-notes:0"], ["delta-notes:3", "--from", "2"],
])
def test_get_invalid_ranges_are_usage_errors(tmp_path, args):
    memory = _bank(tmp_path, git=False)
    _long_page(memory)
    proc = run_cli(["get", *args, "--json"], _env(tmp_path, memory), cwd=_work(tmp_path))
    assert proc.returncode == 2 and envelope(proc)["code"] == "usage"


def test_get_unknown_entity_is_not_found(tmp_path):
    memory = _bank(tmp_path, git=False)
    proc = run_cli(["get", "no-such-page", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path))
    out = envelope(proc)
    assert proc.returncode == 1 and out["code"] == "not_found" and out["ok"] is False


# --- project ------------------------------------------------------------------------------------

def test_project_is_the_mcp_body_with_actions_spelled_for_the_cli(tmp_path):
    memory = _bank(tmp_path, git=False)
    out = envelope(run_cli(["project", "alpha-project", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    assert out["ok"] is True and out["data"]["project_id"] == "alpha-project"
    assert "cicada_" not in out["text"]
    assert "`cicada get <entity-id>`" in out["text"]
    assert_commands_parse(out["text"])
    stdio = mcp_tools.project(mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown"),
                              "alpha-project")
    assert "cicada_recall_detail(entity_id)" in stdio                     # stdio unchanged


def test_project_not_found_is_typed_and_spelled(tmp_path):
    memory = _bank(tmp_path, git=False)
    proc = run_cli(["project", "bob-example", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path))
    out = envelope(proc)
    assert proc.returncode == 1 and out["code"] == "not_found"
    assert "cicada_" not in out["text"] and "`cicada project`" in out["text"]
    proc = run_cli(["project", "zz-nothing", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path))
    assert proc.returncode == 1 and envelope(proc)["code"] == "not_found"


# --- continue -----------------------------------------------------------------------------------

def _continue_bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    work = _work(tmp_path)
    write_session(memory, 1, A_TURNS, cwd=os.path.realpath(work))
    continuity.reset()
    return memory, work


def test_continue_reads_where_the_work_in_this_folder_stopped(tmp_path):
    memory, work = _continue_bank(tmp_path)
    out = envelope(run_cli(["continue", "--json"], _env(tmp_path, memory), cwd=work))
    assert out["ok"] is True
    text = out["text"]
    assert "episode `ep_2026-09-03_001`" in text and "Workspace state not checked" in text
    assert "Not X, it breaks the fixture loader — use Y." in text
    assert "cicada_continue" not in text
    assert_commands_parse(text)
    assert out["data"]["episode_id"] == "ep_2026-09-03_001"


def test_continue_from_another_folder_finds_nothing(tmp_path):
    memory, _ = _continue_bank(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = envelope(run_cli(["continue", "--json"], _env(tmp_path, memory), cwd=elsewhere))
    assert out["ok"] is True and "No captured session in this folder yet" in out["text"]
    assert out["data"]["episode_id"] is None


def test_continue_with_an_explicit_session_and_its_spelled_cursor_round_trips(tmp_path):
    memory, work = _continue_bank(tmp_path)
    many = [("user" if i % 2 == 0 else "assistant", f"turn {i} " + "words " * 300) for i in range(40)]
    write_session(memory, 2, many, cwd=os.path.realpath(work), start=60)
    continuity.reset()
    env = _env(tmp_path, memory)
    out = envelope(run_cli(["continue", "--session", "ep_2026-09-03_002", "--json"], env, cwd=work))
    spans = [s for s in TICKED.findall(out["text"]) if "--before" in s]
    assert spans, out["text"][:400]
    words = shlex.split(spans[0])
    again = envelope(run_cli(words[1:] + ["--json"], env, cwd=work))      # the printed call, run as printed
    assert again["ok"] is True and "episode `ep_2026-09-03_002`" in again["text"]


def test_continue_recognises_the_current_claude_code_conversation(tmp_path):
    memory, work = _continue_bank(tmp_path)
    from _continuity_fixtures import sid

    env = _env(tmp_path, memory, CLAUDE_CODE_SESSION_ID=sid(1))
    stdio_like = envelope(run_cli(["continue", "--json"], env, cwd=work))
    # Same selection rule as cicada_continue: whatever it decides, the CLI spells only commands it holds.
    assert "cicada_continue" not in stdio_like["text"]
    assert_commands_parse(stdio_like["text"])


def test_mcp_continue_bytes_are_unchanged():
    assert continuity.call("ep_2026-09-03_001") == '`cicada_continue(session="ep_2026-09-03_001")`'
    assert continuity.continue_call("ep_x", 3, "abcdef012345") == \
        '`cicada_continue(session="ep_x", before="3@abcdef012345")`'


# --- save ---------------------------------------------------------------------------------------

def _episodes(memory):
    return sorted((memory / "episodes").glob("*.md"))


def _new_episode(memory, before):
    new = [p for p in _episodes(memory) if p not in before]
    assert len(new) == 1, new
    return markdown_parser.parse(new[0])


def test_save_with_a_claude_code_session(tmp_path):
    memory = _bank(tmp_path, git=False)
    before = _episodes(memory)
    work = _work(tmp_path)
    secret = "sk-" + "A" * 24
    proc = run_cli(["save", f"Decided to ship alpha. key {secret}", "--title", "Alpha decision", "--json"],
                   _env(tmp_path, memory, CLAUDE_CODE_SESSION_ID=UUID), cwd=work)
    out = envelope(proc)
    assert proc.returncode == 0 and out["ok"] is True and out["warnings"] == []
    page = _new_episode(memory, before)
    fm = page.frontmatter
    assert out["data"] == {"episode_id": fm["id"], "duplicate": False}
    assert fm["session_id"] == UUID and fm["harness"] == "claude-code"
    assert fm["project_dir"] == os.path.realpath(work)
    assert fm["source"] == "cli" and fm["origin"] == "mcp" and fm["title"] == "Alpha decision"
    assert secret not in page.body and "Decided to ship alpha." in page.body


def test_save_without_a_harness_session_omits_it_and_says_so(tmp_path):
    memory = _bank(tmp_path, git=False)
    env = _env(tmp_path, memory)
    before = _episodes(memory)
    out = envelope(run_cli(["save", "First note.", "--json"], env, cwd=_work(tmp_path)))
    assert out["ok"] is True and "no_session" in out["warnings"] and "not grouped" in out["text"]
    first = _new_episode(memory, before)
    before = _episodes(memory)
    envelope(run_cli(["save", "Second note.", "--json"], env, cwd=_work(tmp_path)))
    second = _new_episode(memory, before)
    for page in (first, second):                       # two commands, no made-up shared or separate session
        assert "session_id" not in page.frontmatter and "harness" not in page.frontmatter
        assert page.frontmatter["title"] == "Agent note"


def test_save_keeps_a_named_harness_without_an_id(tmp_path):
    memory = _bank(tmp_path, git=False)
    before = _episodes(memory)
    envelope(run_cli(["save", "A note.", "--json"], _env(tmp_path, memory, CICADA_SESSION_HARNESS="codex"),
                     cwd=_work(tmp_path)))
    fm = _new_episode(memory, before).frontmatter
    assert fm["harness"] == "codex" and "session_id" not in fm


def test_save_from_stdin_and_duplicates(tmp_path):
    memory = _bank(tmp_path, git=False)
    env = _env(tmp_path, memory)
    text = "A plan:\nline two with 'quotes' and $dollars\n"
    first = envelope(run_cli(["save", "-", "--json"], env, cwd=_work(tmp_path), stdin=text))
    assert first["ok"] is True and first["data"]["duplicate"] is False
    again = run_cli(["save", "-", "--json"], env, cwd=_work(tmp_path), stdin=text)
    out = envelope(again)
    assert again.returncode == 0 and out["ok"] is True and out["code"] == "duplicate"
    assert out["data"] == {"episode_id": None, "duplicate": True}


@pytest.mark.parametrize("args, stdin", [(["save", "-"], ""), (["save", "   "], None), (["save", "-"], "  \n")])
def test_empty_content_is_a_usage_error(tmp_path, args, stdin):
    memory = _bank(tmp_path, git=False)
    before = _episodes(memory)
    proc = run_cli([*args, "--json"], _env(tmp_path, memory), cwd=_work(tmp_path), stdin=stdin)
    assert proc.returncode == 2 and envelope(proc)["code"] == "usage" and _episodes(memory) == before


def test_save_refuses_a_demo_bank(tmp_path):
    from api.services import demo_guard

    memory = _bank(tmp_path, git=False)
    demo_guard.write_manifest(memory)
    before = _episodes(memory)
    proc = run_cli(["save", "A note.", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path))
    assert proc.returncode == 4 and envelope(proc)["code"] == "demo_bank" and _episodes(memory) == before


def test_save_refuses_when_the_backend_serves_another_root(tmp_path):
    memory = _bank(tmp_path, git=False)
    before = _episodes(memory)
    with health_server(memory_root=str(tmp_path / "elsewhere")) as port:
        proc = run_cli(["save", "A note.", "--json"], _env(tmp_path, memory, CICADA_PORT=str(port)),
                       cwd=_work(tmp_path))
    out = envelope(proc)
    assert proc.returncode == 3 and out["code"] == "root_mismatch" and _episodes(memory) == before


def test_save_with_an_unverified_backend_saves_and_warns(tmp_path):
    memory = _bank(tmp_path, git=False)
    with health_server(memory_root=str(memory), status=500) as port:
        out = envelope(run_cli(["save", "A note.", "--json"], _env(tmp_path, memory, CICADA_PORT=str(port)),
                               cwd=_work(tmp_path)))
    assert out["ok"] is True and "root_unverified" in out["warnings"]


def test_save_into_a_read_only_episodes_folder_is_sandbox_denied(tmp_path):
    memory = _bank(tmp_path, git=False)
    episodes = memory / "episodes"
    episodes.chmod(0o555)
    try:
        proc = run_cli(["save", "A note.", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path))
    finally:
        episodes.chmod(0o755)
    out = envelope(proc)
    assert proc.returncode == 5 and out["code"] == "sandbox_denied"


def test_save_takes_the_episode_lock_and_stays_in_the_pinned_bank(tmp_path, monkeypatch, capsys, inprocess):
    from api import cli
    from api.services import bank_registry, episode_ids, episode_scrub

    root = tmp_path / "root"
    root.mkdir()
    bank_registry.create_bank(root, "alpha", seed_owner=False)
    bank_registry.create_bank(root, "beta", seed_owner=False)
    bank_registry.activate_bank(root, "alpha")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    real_scrub, real_lock, locked = episode_scrub.scrub_body, episode_ids.episode_lock, []

    def switching_scrub(text, **kw):
        bank_registry.activate_bank(root, "beta")          # the person switches banks mid-command
        return real_scrub(text, **kw)

    def spy_lock(path):
        locked.append(path)
        return real_lock(path)

    monkeypatch.setattr(episode_scrub, "scrub_body", switching_scrub)
    monkeypatch.setattr(episode_ids, "episode_lock", spy_lock)
    code = cli.main(["save", "Pinned note.", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["bank"] == "alpha"
    alpha = bank_registry.bank_dir(root, "alpha") / "episodes"
    beta = bank_registry.bank_dir(root, "beta") / "episodes"
    assert len(list(alpha.glob("*.md"))) == 1 and not list(beta.glob("*.md"))
    assert locked and locked[0].resolve() == alpha.resolve()


def test_the_mcp_save_reply_is_unchanged_and_typed(tmp_path):
    memory = _bank(tmp_path, git=False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_x", harness="unknown")
    reply = mcp_tools.save_episode(ctx, "Some fact.", None)
    assert reply.startswith("Episode saved as ep_") and reply.data["duplicate"] is False
    fm = markdown_parser.parse(memory / "episodes" / f"{reply.data['episode_id']}.md").frontmatter
    assert fm["source"] == "mcp" and fm["title"] == "MCP capture" and fm["session_id"] == "ses_x"
    dup = mcp_tools.save_episode(ctx, "Some fact.", None)
    assert dup == "Episode already exists (duplicate detected by content hash)." and dup.code == "duplicate"


# --- handshake ----------------------------------------------------------------------------------

def test_cli_handshake_names_only_commands_the_cli_holds(tmp_path):
    from _synthetic_bank import _ok_repo, _settings
    from api.services import state_dictionary

    memory = _bank(tmp_path, git=False)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    out = envelope(run_cli(["handshake", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    text = out["text"]
    assert out["ok"] is True and "cicada_" not in text
    assert "`cicada recall" in text and "`cicada save" in text and "`cicada continue" in text
    assert_commands_parse(text)
    assert len(text) // 4 <= 1800 and out["data"]["tokens_est"] == len(text) // 4


@pytest.mark.parametrize("state", [None, "synthetic"])
def test_build_cli_fits_and_parses(tmp_path, state):
    from _synthetic_bank import _ok_repo, _settings
    from api.services import cli_map, handshake, state_dictionary

    memory = _bank(tmp_path, git=False)
    st = None
    if state:
        state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
        st = state_dictionary.read_state(memory)
    text = handshake.build_cli(st, commands=frozenset(r.name for r in cli_map.exposed()), bank="memory")
    assert len(text) // 4 <= handshake.MAX_TOKENS and "cicada_" not in text
    assert_commands_parse(text)


# --- generated hints spell commands the CLI holds -------------------------------------------------

def test_recall_hints_spell_get_for_the_cli(tmp_path):
    memory = _bank(tmp_path, git=False)
    out = envelope(run_cli(["recall", "alpha project", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    hints = json.loads(re.search(r"```cicada-hints\n(.*?)\n```", out["text"], re.S).group(1))
    assert hints["next_tool"] == "cicada get"
    assert "`cicada get <entity-id>`" in hints["note"]
    assert_commands_parse(hints["note"])
    assert (hints.get("state") or {}).get("next_tool", "cicada handshake") == "cicada handshake"


def test_the_remote_package_never_imports_the_local_only_bodies():
    """G135 R-R3: `cicada_continue` never goes remote; its body lives where api/remote cannot reach it."""
    import ast
    from pathlib import Path

    remote = Path(__file__).resolve().parents[1] / "remote"
    for path in remote.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            assert not any(n.endswith("local_tools") for n in names), path


def _lineage_bank(tmp_path, monkeypatch):
    """Review finding (unit 2): an older session A holds the role and handoff; a newer session B in the same
    folder holds only current small talk, and the continuity registry records B's later start and that B
    continues A. Synthetic throughout; the registry lives in the scratch CICADA_HOME the CLI will use."""
    from _continuity_fixtures import at, sid
    from api.services import continuity_sessions

    memory, work = _continue_bank(tmp_path)                      # A = ep_2026-09-03_001, the role turns
    folder = os.path.realpath(work)
    write_session(memory, 2, [("user", "hi there, unrelated-small-talk"), ("assistant", "Hello. What next?")],
                  cwd=folder, start=60, harness="codex")
    env = _env(tmp_path, memory)
    monkeypatch.setenv("CICADA_HOME", env["CICADA_HOME"])
    paths = continuity_sessions.bank_paths_for(memory)
    assert continuity_sessions.apply(memory, bank_paths=paths, harness="claude-code", session_id=sid(1),
                                     events={"started_at": at(-1), "cwd_hash": continuity_sessions.cwd_hash(folder)},
                                     deadline=None) == "ok"
    assert continuity_sessions.apply(memory, bank_paths=paths, harness="codex", session_id=sid(2),
                                     events={"started_at": at(59), "cwd_hash": continuity_sessions.cwd_hash(folder),
                                             "continues": "ep_2026-09-03_001"}, deadline=None) == "ok"
    continuity.reset()
    return memory, work, env


def test_continue_without_identity_keeps_the_current_conversation_fallback(tmp_path, monkeypatch):
    from api.services import local_tools, session_identity

    memory, work, env = _lineage_bank(tmp_path, monkeypatch)
    out = envelope(run_cli(["continue", "--json"], env, cwd=work))
    text = out["text"]
    # It leads with the read of A (the role) and says B looks like the current conversation — never B's turns.
    assert text.startswith("`cicada continue --session ep_2026-09-03_001`"), text[:300]
    assert "This looks like the current conversation" in text
    assert "unrelated-small-talk" not in text and "# Where the work stopped" not in text
    assert_commands_parse(text)
    # The same selection as cicada_continue with the stdio server's own unknown identity (a minted id).
    stdio = session_identity.stdio_identity({})
    continuity.reset()
    mcp = local_tools.continue_text(memory, root=memory, cwd=os.path.realpath(work),
                                    identity=(stdio.harness, stdio.session_id))
    assert mcp.startswith('`cicada_continue(session="ep_2026-09-03_001")`')
    assert mcp.data["selection"] == out["data"]["selection"] and mcp.data["episode_id"] == out["data"]["episode_id"]


def test_continue_with_an_explicit_session_still_reads_that_history(tmp_path, monkeypatch):
    memory, work, env = _lineage_bank(tmp_path, monkeypatch)
    out = envelope(run_cli(["continue", "--session", "ep_2026-09-03_002", "--json"], env, cwd=work))
    assert "unrelated-small-talk" in out["text"] and "episode `ep_2026-09-03_002`" in out["text"]

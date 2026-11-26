"""Cicada's own agent (ruling 84): the two compartments, the grant, the init check, the gates on its answer, the one write,
the orphan reaper. (The signed-in compartment's tests are in test_harness_browse.py.)

Synthetic banks of invented people; the session is a fake `claude` or an injected session, so nothing reaches the plan or a
network. What needs the real permission engine (a refused secret, a refused host) is in `benchmarks/consolidation/harness_battery.py`."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from api.harness_tools import read_browser
from api.services import harness_agent as ha, harness_files as hf, harness_questions as hq, inbox_tend, markdown_parser, web_settle, write_admission
from benchmarks.consolidation import harness_battery as hb


def run(coro):
    return asyncio.run(coro)


def _session(*calls: ha.Call, answer: dict | None = None, stopped: str = "", compartment: str = ha.WEB) -> ha.Session:
    return ha.Session(calls=list(calls), answer=answer, stopped=stopped, model="fake-model", seconds=1.0, compartment=compartment)


def _page_call(url: str, text: str) -> ha.Call:
    return ha.Call("t1", "WebFetch", "address", url, result=text)


# --------------------------------------------------------------------------- the grant: two compartments, no tool that crosses


def test_a_private_session_reads_files_and_holds_nothing_that_can_send(tmp_path):
    policy = ha.Policy(ha.PRIVATE, roots=(str(tmp_path / "code"),), refused=(str(tmp_path / "bank"),))
    s = ha.settings_for(policy)["permissions"]
    assert {"Write", "Edit", "NotebookEdit", "Bash", "WebFetch", "WebSearch"} <= set(s["deny"])
    assert all(r.startswith(("Read(", "Glob(", "Grep(")) for r in s["allow"])           # nothing but file reads is allowed
    argv = ha.build_argv(model="haiku", system_prompt="x", policy=policy)
    assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk" and argv[argv.index("--permission-prompts") + 1] == "none"
    assert "--bare" not in argv and "--mcp-config" not in argv and argv[argv.index("--setting-sources") + 1] == ""
    assert any(r.endswith("/bank/**)") for r in s["deny"])      # the refusal names the path, for each file tool


def test_a_web_session_holds_no_file_tool_and_fetches_only_the_hosts_the_question_names(tmp_path):
    policy = ha.Policy(ha.WEB)
    s = ha.settings_for(policy)["permissions"]
    assert s["allow"] == ["WebSearch", "WebFetch"] and {"Read", "Glob", "Grep", "Bash", "Write"} <= set(s["deny"])
    assert ha.build_argv(model="haiku", system_prompt="x", policy=policy)[ha.build_argv(model="haiku", system_prompt="x", policy=policy).index("--tools") + 1] == "WebSearch,WebFetch"
    limited = ha.settings_for(ha.Policy(ha.WEB, domains=("site.example",)))["permissions"]["allow"]
    assert limited == ["WebSearch", "WebFetch(domain:site.example)"]
    assert ha.hosts_in("Which? A page at https://Site.Example:8443/x.html and http://b.example/y say") == ("site.example", "b.example")


def test_only_the_signed_in_compartment_holds_a_shell_and_only_as_one_command_and_no_compartment_shares_a_tool():
    for compartment, tools in ha.COMPARTMENT_TOOLS.items():
        assert ("Bash" in tools) == (compartment == ha.SIGNED_IN)
        for other, other_tools in ha.COMPARTMENT_TOOLS.items():
            assert compartment == other or not (tools & other_tools)
    for compartment in (ha.PRIVATE, ha.WEB):
        assert not any("Bash" in r for r in ha.settings_for(ha.Policy(compartment, roots=("/r",)))["permissions"]["allow"])
    assert all(r.startswith("Bash(/s/rb ") for r in ha.settings_for(ha.Policy(ha.SIGNED_IN, browse="/s/rb"))["permissions"]["allow"])


def test_a_private_grant_is_read_rules_only_and_the_kinds_that_are_not_documents_are_denied_for_every_tool(tmp_path):
    """Glob and Grep follow the Read rules (proved live, battery `canaries`): a rule named for either is not consulted, so none is written."""
    root = tmp_path / "notes"
    (root / "sub").mkdir(parents=True)
    for name in ("a.md", "sub/b.txt", "c.md", "d.md", "e.md", "sa.json", "config.yaml", "app.py", "kubeconfig", "x.PEM", ".env"):
        (root / name).write_text("x")
    g = hf.grant_for_roots((str(root),), refused=(str(tmp_path / "bank"),))
    assert g.roots == (str(root),)
    cfg = ha.settings_for(ha.Policy(ha.PRIVATE, roots=g.roots, refused=g.refused, deny=g.deny))["permissions"]
    assert all(r.startswith("Read(") for r in cfg["allow"]) and any(str(root) in r for r in cfg["allow"])
    deny = set(cfg["deny"])
    r = str(root)
    for rule in ("Read(//**/*.json)", "Read(//**/*.yaml)", "Read(//**/*.py)", "Read(//**/*.pem)", "Read(//**/kubeconfig)",
                 "Read(//**/.env*)", "Read(//**/id_*)", "Read(//**/credential*)", "Read(//**/*.key)",
                 f"Read(/{r}/**/.*)", f"Read(/{r}/**/secrets)", f"Read(/{r}/**/secrets/**)", f"Read(/{r}/**/credentials/**)"):
        assert rule in deny, rule
    assert "Read(//**/private)" not in deny and "Read(//**/.*)" not in deny    # a folder word is only ever meant inside a granted folder
    assert "Read(//**/*.md)" not in deny and "Read(//**/*.txt)" not in deny          # document kinds are not denied
    assert not any(r.startswith(("Glob(", "Grep(")) for r in cfg["allow"] + cfg["deny"] if r not in ha.NEVER)
    assert any(str((tmp_path / "bank").resolve()) in r for r in cfg["deny"])             # the refused path


def test_the_document_kinds_are_an_allow_list_and_nothing_else_is_one():
    assert {"md", "txt", "pdf", "docx", "csv", "html", "org", "tex", "rtf", "pages", "odt", "tsv"} <= hf.DOCUMENT_KINDS
    assert not ({"json", "yaml", "yml", "toml", "ini", "env", "pem", "key", "db", "sqlite", "zip", "py", "js", "swift", "p12", ""}
                & hf.DOCUMENT_KINDS)


def test_a_synthetic_home_with_one_of_each_kind_of_folder_grants_documents_and_nothing_else(tmp_path, monkeypatch):
    """One of each: the kinds a real install has. Names are invented; what decides is the name's words and what the walk finds."""
    home = tmp_path / "home"
    layout = {
        "Notes": ["a.md", "b.txt", "sa-notes.pdf"],                                  # documents
        "Papers": ["p1.pdf", "p2.docx", "data.csv"],                                 # documents
        "Photos": ["x.jpg", "y.png"],                                                # neither documents nor programs: granted, nothing readable
        "secrets": ["sa-key.json", "svc.json"],                                      # name says secrets (ordinary .json names)
        "API-Keys": ["a.txt"], "Credentials": ["a.txt"], "my_passwords": ["a.txt"], "Tokens": ["a.txt"], "certs": ["a.txt"],
        "Wallet": ["a.txt"], "PrivateStuff": ["a.txt"], "private": ["a.txt"],
        "go": ["a.txt"],                                                             # a known tool folder
        "webapp": [".git/HEAD", "README.md", "a.py"],                                # holds a repository
        "scripts": ["a.py", "b.py", "c.sh", "d.md"],                                 # more programs than documents
        "node-app": ["package.json", "readme.md"],                                   # a build manifest
        "cicada-bench": ["a.md"], "engine-scratch": ["a.md"],                        # Cicada's own
        "oldbank": ["entities/e.md", "episodes/x.md"],                               # holds a bank
        "Library": ["a.md"], "Documents": ["a.md"],                                  # protected
    }
    for folder, files in layout.items():
        for f in files:
            (home / folder / f).parent.mkdir(parents=True, exist_ok=True)
            (home / folder / f).write_text("x")
    (home / ".ssh").mkdir()
    (home / "link").symlink_to(home / "Notes")
    (home / "mounted").mkdir()
    monkeypatch.setattr(hf, "_same_device", lambda a, b: Path(a).name != "mounted")
    g = hf.grant_for_home(home, attended=False, refused=())
    assert sorted(Path(r).name for r in g.roots) == ["Notes", "Papers", "Photos"]
    why = dict(g.skipped)
    assert {why[n] for n in ("secrets", "API-Keys", "Credentials", "my_passwords", "Tokens", "certs", "Wallet", "PrivateStuff",
                             "private")} == {"secrets"}
    assert {why[n] for n in ("go", "webapp", "scripts", "node-app")} == {"tooling"}
    assert {why[n] for n in ("cicada-bench", "engine-scratch", "oldbank")} == {"cicada"}
    assert why["Library"] == why["Documents"] == "protected" and why["mounted"] == "mount"
    assert ".ssh" not in why and "link" not in why                                     # hidden folders and links are never candidates
    attended = hf.grant_for_home(home, attended=True, refused=())
    assert "Documents" in {Path(r).name for r in attended.roots} and "Library" not in {Path(r).name for r in attended.roots}
    assert "Read(//**/*.jpg)" in g.deny and "Read(//**/*.png)" in g.deny and "Read(//**/*.pdf)" not in g.deny


def test_a_folder_holding_the_bank_or_refused_or_too_large_to_walk_is_not_granted(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Notes" / "memory" / "entities").mkdir(parents=True)
    (home / "Notes" / "memory" / "episodes").mkdir()
    (home / "Plain").mkdir()
    (home / "Plain" / "a.md").write_text("x")
    (home / "Big").mkdir()
    for i in range(30):
        (home / "Big" / f"{i}.md").write_text("x")
    why = dict(hf.grant_for_home(home, attended=False, refused=(str(home / "Plain"),)).skipped)
    assert why == {"Notes": "cicada", "Plain": "cicada"}
    monkeypatch.setattr(hf, "MAX_ENTRIES", 10)
    again = hf.grant_for_home(home, attended=False, refused=())
    assert dict(again.skipped)["Big"] == "too_large" and not any(Path(r).name == "Big" for r in again.roots)


def test_the_scratch_folder_is_private_and_never_inside_a_denied_path_on_a_realistic_layout(tmp_path, monkeypatch):
    """Cicada's home under the user's home, the bank beside the person's folders: the copies are readable (not inside any refused path
    or granted folder) and a rule that denies Cicada's home does not cover them."""
    home = tmp_path / "user"
    (home / ".cicada" / "engine-scratch").mkdir(parents=True)
    (home / "Notes").mkdir()
    (home / "Notes" / "a.md").write_text("x")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CICADA_HOME", str(home / ".cicada"))
    bank = home / ".cicada" / "memory"
    bank.mkdir()
    grant = hq.home_grant(bank, attended=False, home=home)
    assert [Path(r).name for r in grant.roots] == ["Notes"]
    avoid = (*grant.refused, *grant.roots)
    base = hf.make_scratch(avoid)
    try:
        assert base is not None and oct(base.stat().st_mode & 0o777) == "0o700"
        files = base / "files"
        files.mkdir()
        for denied in ha.spellings(grant.refused):
            assert not hf.under(str(files), denied), denied
        assert not any(hf.under(str(files), r) for r in grant.roots)
        assert hf.under(str(base), str(base)) and not hf.under(str(base), str(home / ".cicada"))
        assert not any(part.startswith(".") for part in str(files.resolve()).split("/") if part)    # the dot-file rule does not cover it
        rules = ha.settings_for(ha.Policy(ha.PRIVATE, roots=(*grant.roots, str(files)), refused=grant.refused, deny=grant.deny))
        assert any(str(files.resolve()) in r for r in rules["permissions"]["allow"])
    finally:
        if base:
            ha.remove_scratch(base, None)
    # a temp folder that lies inside Cicada's home is never used
    (home / ".cicada" / "tmp").mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(home / ".cicada" / "tmp"))
    other = hf.make_scratch(avoid)
    try:
        assert other is None or not hf.under(str(other), str(home / ".cicada"))
    finally:
        if other:
            ha.remove_scratch(other, None)


def test_a_dead_backends_scratch_folder_is_removed_at_the_next_start_and_a_live_ones_is_not(tmp_path, scratch_home):
    dead = tmp_path / "cicada-harness-dead"
    live = tmp_path / "cicada-harness-live"
    elsewhere = tmp_path / "keep-me"
    for d in (dead, live, elsewhere):
        d.mkdir()
        (d / "ep.md").write_text("a masked copy")
    reg = scratch_home / "harness_sessions"
    reg.mkdir()
    (reg / "scratch-dead.json").write_text(json.dumps({"scratch": str(dead), "owner": 2, "owner_cmd": "gone"}))
    (reg / "scratch-else.json").write_text(json.dumps({"scratch": str(elsewhere), "owner": 2, "owner_cmd": "gone"}))
    (reg / "scratch-live.json").write_text(json.dumps({"scratch": str(live), "owner": os.getpid(), "owner_cmd": "x"}))
    ha.reap_orphans()
    assert not dead.exists() and live.exists() and elsewhere.exists()           # only `cicada-harness-*` of a dead owner
    assert not (reg / "scratch-dead.json").exists() and (reg / "scratch-live.json").exists()
    rec = ha.register_scratch(live)
    assert rec is not None and rec.exists()
    ha.remove_scratch(live, rec)
    assert not live.exists() and not rec.exists()


def test_key_material_is_recognised_and_ordinary_prose_is_not():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n-----END PRIVATE KEY-----"
    for text in (pem, "token: ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4", "key sk-ant-" + "x" * 30, "AKIA" + "ABCDEFGHIJKLMNOP",
                 "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N", "d41d8cd98f00b204e9800998ecf8427e",
                 "api_key = abcd1234efgh5678", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123", "CANARY_JSON_222",
                 "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MEFCQ0RFRkdISUo="):
        assert hf.looks_like_key(text), text
    for text in ("Zephyr's current stable release is 4.2, shipped in March.", "Glimmer: the in-house build cache service our team runs.",
                 "Meeting with the platform team on 2026-11-02 about the quarterly plan", "See /Users/someone/Notes/trip/itinerary.md"):
        assert not hf.looks_like_key(text), text


def test_a_path_is_storable_only_when_it_is_a_document_kind_under_a_granted_folder(tmp_path):
    root, other = tmp_path / "Notes", tmp_path / "Other"
    for d in (root / "sub", root / "secrets", root / ".hidden", other, tmp_path / "scratch"):
        d.mkdir(parents=True)
    for f in ("a.md", "sub/b.pdf", "sa.json", "app.py", "Makefile", "secrets/n.md", ".hidden/n.md", "credentials.txt", ".env.md"):
        (root / f).write_text("x")
    (other / "a.md").write_text("x")
    (tmp_path / "scratch" / "ep_1.md").write_text("x")
    ok = lambda p, **kw: hf.allowed_path(str(p), (str(root),), **kw)   # noqa: E731
    assert ok(root / "a.md") and ok(root / "sub" / "b.pdf")
    for bad in ("sa.json", "app.py", "Makefile", "secrets/n.md", ".hidden/n.md", "credentials.txt", ".env.md"):
        assert not ok(root / bad), bad
    assert not ok(other / "a.md") and not ok("relative/a.md") and not ok("")                    # not under a granted folder
    assert not ok(root / "a.md", refused=(str(root),))                                            # refused wins
    assert hf.allowed_path(str(tmp_path / "scratch" / "ep_1.md"), (str(root),), copies_dir=str(tmp_path / "scratch"))   # a conversation copy


# --------------------------------------------------------------------------- the audit and the init check


def test_every_call_is_one_audit_line():
    assert ha.classify("Read", {"file_path": "/a/b"}) == ("file", "/a/b")
    assert ha.classify("WebSearch", {"query": "q"}) == ("search", "q")
    assert ha.classify("WebFetch", {"url": "https://x.test"}) == ("address", "https://x.test")
    assert ha.classify("Bash", {"command": "rm -rf /"})[0] == "shell"


def _fake_claude(tmp_path: Path, events: list[dict], sleep: float = 0.0) -> str:
    script = tmp_path / "claude"
    script.write_text(f"#!{sys.executable}\nimport sys, time, json\nsys.stdin.read()\ntime.sleep({sleep})\n"
                      f"for e in json.loads({json.dumps(json.dumps(events))}):\n    print(json.dumps(e), flush=True)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _use(i: str, name: str, inp: dict) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}


def _res(i: str, text: str, error: bool = False) -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": text, "is_error": error}]}}


def _init(tools=("WebFetch", "WebSearch"), servers=()) -> dict:
    return {"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": list(servers)}


@pytest.fixture
def scratch_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    return tmp_path / "home"


def test_a_session_is_read_as_it_streams_and_a_refused_call_is_listed(tmp_path, scratch_home):
    events = [_init(), _use("a", "WebFetch", {"url": "http://x.test/p"}), _res("a", "Zephyr 4.2 is current"),
              _use("b", "Bash", {"command": "rm -rf *"}),
              _res("b", "Permission to use Bash has been denied because Claude Code is running in don't ask mode.", True),
              _use("c", "StructuredOutput", {}),
              {"type": "result", "structured_output": {"status": "answered", "confidence": 0.9, "why": "w", "evidence": []},
               "total_cost_usd": 0.01, "modelUsage": {"claude-haiku": {"outputTokens": 5}}}]
    session = ha.run([_fake_claude(tmp_path, events)], "prompt", cwd=str(tmp_path), env=dict(os.environ),
                     expected_tools=ha.COMPARTMENT_TOOLS[ha.WEB])
    assert [c.kind for c in session.calls] == ["address", "shell"] and [c.denied for c in session.calls] == [False, True]
    assert session.answer["status"] == "answered" and session.model == "claude-haiku" and session.stopped == ""
    assert session.audit[1] == {"tool": "shell", "what": "Bash", "denied": True}
    assert any("Zephyr 4.2" in t for t in session.transcript)


@pytest.mark.parametrize("init, why", [
    (_init(servers=[{"name": "claude_ai_Docs", "status": "connected"}]), "an account connector that loaded anyway"),
    (_init(tools=("WebFetch", "WebSearch", "Bash")), "a tool it was not given"),
    (_init(tools=("WebFetch",)), "a tool that is missing"),
    (_init(tools=("Read", "Glob", "Grep")), "the other compartment's tools"),
])
def test_a_session_that_does_not_hold_exactly_its_tools_is_killed_before_it_calls_anything(tmp_path, scratch_home, init, why):
    events = [init, _use("a", "WebFetch", {"url": "http://x.test/p"}), _res("a", "page"),
              {"type": "result", "structured_output": {"status": "answered", "confidence": 1, "why": "", "evidence": []}}]
    session = ha.run([_fake_claude(tmp_path, events)], "p", cwd=str(tmp_path), env=dict(os.environ),
                     expected_tools=ha.COMPARTMENT_TOOLS[ha.WEB])
    assert session.stopped == "unexpected_tools", why
    assert session.calls == [] and session.answer is None


def test_the_answer_tool_is_the_one_extra_tool_a_session_may_list_and_a_call_before_init_is_refused(tmp_path, scratch_home):
    ok = ha.run([_fake_claude(tmp_path, [_init(("Read", "Glob", "Grep", "StructuredOutput")),
                                         {"type": "result", "structured_output": {"status": "not_found", "confidence": 1, "why": "", "evidence": []}}])],
                "p", cwd=str(tmp_path), env=dict(os.environ), expected_tools=ha.COMPARTMENT_TOOLS[ha.PRIVATE])
    assert ok.stopped == "" and ok.answer["status"] == "not_found"
    early = ha.run([_fake_claude(tmp_path, [_use("a", "Read", {"file_path": "/x"})])], "p", cwd=str(tmp_path), env=dict(os.environ),
                   expected_tools=ha.COMPARTMENT_TOOLS[ha.PRIVATE])
    assert early.stopped == "no_init" and early.calls == []


def test_a_session_over_its_calls_or_its_clock_is_killed_and_answers_nothing(tmp_path, scratch_home):
    many = [_use(str(i), "Read", {"file_path": f"/a/{i}"}) for i in range(5)]
    over = ha.run([_fake_claude(tmp_path, many)], "p", cwd=str(tmp_path), env=dict(os.environ), max_calls=3)
    assert over.stopped == "too_many_calls" and over.answer is None
    slow = ha.run([_fake_claude(tmp_path, [], sleep=5)], "p", cwd=str(tmp_path), env=dict(os.environ), timeout=0.5)
    assert slow.stopped == "timeout" and slow.answer is None
    assert ha.run(["/nonexistent/claude"], "p", cwd=str(tmp_path), env=dict(os.environ)).stopped == "no_binary"


# --------------------------------------------------------------------------- a restart leaves no session running


def test_a_session_group_a_dead_backend_left_is_killed_at_the_next_start(tmp_path, scratch_home):
    proc = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        reg = scratch_home / "harness_sessions"
        reg.mkdir()
        (reg / f"{proc.pid}.json").write_text(json.dumps({
            "pgid": proc.pid, "owner": 2, "owner_cmd": "a backend that is gone", "cmd": ha._command_of(proc.pid), "at": time.time()}))
        assert ha.reap_orphans() == 1
        proc.wait(timeout=5)
        assert proc.returncode is not None and not list(reg.glob("*.json"))
    finally:
        if proc.poll() is None:
            proc.kill()


def test_a_recycled_pid_or_a_live_owner_is_never_reaped(tmp_path, scratch_home):
    other = subprocess.Popen(["sleep", "300"], start_new_session=True)
    mine = subprocess.Popen(["sleep", "301"], start_new_session=True)
    try:
        reg = scratch_home / "harness_sessions"
        reg.mkdir()
        (reg / f"{other.pid}.json").write_text(json.dumps({"pgid": other.pid, "owner": 2, "owner_cmd": "gone", "cmd": "claude -p something else"}))
        (reg / f"{mine.pid}.json").write_text(json.dumps({"pgid": mine.pid, "owner": os.getpid(), "owner_cmd": "x", "cmd": ha._command_of(mine.pid)}))
        assert ha.reap_orphans() == 0
        assert other.poll() is None and mine.poll() is None       # the pid's command line is not the recorded one; the owner is this process
    finally:
        other.kill()
        mine.kill()


def test_a_running_session_is_recorded_while_it_runs_and_forgotten_after(tmp_path, scratch_home):
    ha.run([_fake_claude(tmp_path, [_init()])], "p", cwd=str(tmp_path), env=dict(os.environ))
    assert not list((scratch_home / "harness_sessions").glob("*.json"))


# --------------------------------------------------------------------------- the gate on an answer


QUOTE = "The current stable release of the Zephyr tool is version 4.2, released on 2026-03-01."
ANSWER = {"status": "answered", "option": "b", "confidence": 0.9, "why": "stated",
          "evidence": [{"where": "http://x.test/p", "quote": QUOTE}]}


def test_evidence_counts_only_when_the_page_was_read_and_holds_the_quote_and_is_kept_as_the_source_spells_it():
    page = _page_call("http://x.test/p", f"Zephyr\n\n{QUOTE}\n")
    assert [e.where for e in ha.verify(ANSWER, _session(page))[0]] == ["http://x.test/p"]
    assert ha.verify(ANSWER, _session(_page_call("http://x.test/other", QUOTE)))[1] == "evidence_not_located"   # another page
    assert ha.verify(ANSWER, _session(_page_call("http://x.test/p", "nothing here")))[1] == "evidence_not_located"
    assert ha.verify({**ANSWER, "confidence": 0.5}, _session(page))[1] == "low_confidence"
    long = {**ANSWER, "evidence": [{"where": "http://x.test/p", "quote": QUOTE * 4}]}
    assert ha.verify(long, _session(_page_call("http://x.test/p", QUOTE * 4)))[1] == "evidence_not_located"
    assert ha.located("the  current STABLE release", "xx The current stable release yy")    # whitespace and case, never fuzzy
    assert not ha.located("the current stable relese", "The current stable release")
    shouted = {**ANSWER, "evidence": [{"where": "http://x.test/p", "quote": QUOTE.upper()}]}
    assert ha.verify(shouted, _session(page))[0][0].quote == QUOTE        # the source's own spelling, not the session's


def test_a_left_reason_is_always_an_enum_never_the_sessions_words():
    page = _page_call("http://x.test/p", QUOTE)
    assert ha.verify({"status": "SESSION-OWN-WORDS not found", "confidence": 1}, _session(page))[1] == "no_answer"
    assert ha.verify({"status": "not_found", "confidence": 1}, _session(page))[1] == "not_found"
    assert ha.verify("not a dict", _session(page))[1] == "no_answer"


def test_a_login_page_a_refused_call_or_a_search_summary_is_never_evidence():
    wall = _page_call("http://x.test/p", f"ADDRESS: x\nNEEDS A LOGIN: the page asks for a password.\n{QUOTE}")
    assert ha.verify(ANSWER, _session(wall))[1] == "evidence_not_located"
    refused = _page_call("http://x.test/p", QUOTE)
    refused.denied = True
    assert ha.verify(ANSWER, _session(refused))[1] == "evidence_not_located"
    summary = ha.Call("s", "WebSearch", "search", "zephyr stable", result=f"Links: http://x.test/p\n{QUOTE}")
    assert ha.verify(ANSWER, _session(summary))[1] == "evidence_not_located"


def test_a_file_is_evidence_by_the_path_it_was_read_even_when_written_shorter():
    read = ha.Call("r", "Read", "file", "/home/u/work/notes.txt", result="1\tVexor current stable is 3.2\n2\tmore\n")
    ans = {**ANSWER, "evidence": [{"where": "work/notes.txt, line 1", "quote": "Vexor current stable is 3.2"}]}
    out = ha.verify(ans, _session(read))[0]
    assert [(e.where, e.kind) for e in out] == [("/home/u/work/notes.txt", "file")]
    two_lines = {**ANSWER, "evidence": [{"where": "/home/u/work/notes.txt", "quote": "is 3.2 more"}]}
    assert ha.verify(two_lines, _session(read))[0]          # the harness's own line numbers are not part of the text


def test_a_line_a_search_printed_under_the_files_path_is_evidence_for_that_file_only():
    grep = ha.Call("g", "Grep", "file_search", "Glimmer in /w", result="/w/glossary.txt:2:Glimmer: the build cache service\n")
    ans = {**ANSWER, "evidence": [{"where": "/w/glossary.txt, line 2", "quote": "Glimmer: the build cache service"}]}
    found = ha.verify(ans, _session(grep))[0]
    assert [(e.where, e.kind, e.whole) for e in found] == [("/w/glossary.txt", "file", False)]
    other = {**ANSWER, "evidence": [{"where": "/w/another.txt", "quote": "Glimmer: the build cache service"}]}
    assert ha.verify(other, _session(grep))[1] == "evidence_not_located"           # the quote under another file's name


def test_a_cicada_bank_is_never_evidence(tmp_path):
    (tmp_path / "b" / "entities").mkdir(parents=True)
    (tmp_path / "b" / "episodes").mkdir()
    (tmp_path / "b" / "entities" / "p.md").write_text("x")
    (tmp_path / "plain").mkdir()
    assert ha.inside_a_bank(str(tmp_path / "b" / "entities" / "p.md")) and not ha.inside_a_bank(str(tmp_path / "plain"))


def test_the_sentence_gates():
    names = ["Zephyr"]
    assert ha.states_value("Zephyr's current stable release is 4.2.", names, "4.2", ["4.1"])
    assert not ha.states_value("The current stable release is 4.2.", names, "4.2", ["4.1"])           # the quote does not name the page
    assert not ha.states_value("Zephyr 4.1 is old. 4.2 is new.", names, "4.2", ["4.1"])                 # two sentences: the second names no page
    assert not ha.states_value("Zephyr is at 4.2, not 4.1.", names, "4.2", ["4.1"])                    # another option's value, and a negation
    assert not ha.states_value("Zephyr was 4.2 and is no longer current.", names, "4.2", ["4.1"])
    assert not ha.states_value("Zephyr 14.2 is out.", names, "4.2", ["4.1"])                           # a longer number
    assert ha.presents_as("Glimmer: the in-house build cache service our team runs.", ["Glimmer"], "build cache") == "build cache"
    assert ha.presents_as("Glimmer: the in-house build cache service our team runs.", ["Glimmer"], "team runs") is None
    assert ha.presents_as("Glimmer is slow because the cache is full.", ["Glimmer"], "cache is full") is None
    assert ha.presents_as("Glimmer is not a build cache.", ["Glimmer"], "build cache") is None
    assert ha.presents_as("Other: Glimmer.", ["Glimmer"], "Other") is None                              # before the name


def _brief(kind="conflict", options=None, bank="/b", compartment=ha.WEB, public=True, **kw):
    return hq.Brief("inbox-001", kind, "p", options or {"a": "4.1", "b": "4.2"}, "e", "Zephyr", "m", bank, compartment,
                    kw.pop("names", ["Zephyr"]), kw.pop("other_names", []), "", public, **kw)


def test_a_conflict_settles_only_on_a_sentence_that_names_the_page_and_states_the_option():
    page = _page_call("http://x.test/p", "Zephyr's current stable release is 4.2.\nOther text.")
    ans = {**ANSWER, "evidence": [{"where": "http://x.test/p", "quote": "Zephyr's current stable release is 4.2."}]}
    v = hq.decide(_brief(), ans, _session(page), {})
    assert (v.what, v.answer) == ("settle", "4.2") and v.evidence
    assert hq.decide(_brief(), ans | {"option": "a"}, _session(page), {}).what == "left"                  # 4.1 is not in the quote
    nameless = _page_call("http://x.test/p", QUOTE)
    assert hq.decide(_brief(names=["Quillbot"]), ANSWER, _session(nameless), {}).why == "quote_does_not_say_it"   # names another page
    assert hq.decide(_brief(), ANSWER, _session(nameless), {}).what == "settle"           # "the Zephyr tool is version 4.2": one sentence names both
    assert hq.decide(_brief(), {**ANSWER, "status": "needs_login"}, _session(page), {}).why == "needs_login"
    assert hq.decide(_brief(), ans, _session(page, stopped="timeout"), {}).why == "timeout"


def test_a_clarification_is_a_span_a_sentence_presents_as_what_the_name_is_never_any_substring():
    page = _page_call("http://x.test/g", "Glimmer: the in-house build cache service our team runs.")
    base = {"status": "answered", "confidence": 0.9, "why": "w", "evidence": [
        {"where": "http://x.test/g", "quote": "Glimmer: the in-house build cache service our team runs."}]}
    brief = _brief("clarification", {}, names=["Glimmer"])
    v = hq.decide(brief, {**base, "answer": "build cache"}, _session(page), {})
    assert (v.what, v.answer) == ("settle", "build cache")
    assert hq.decide(brief, {**base, "answer": "team runs"}, _session(page), {}).what == "left"        # a substring that is no definition
    assert hq.decide(brief, {**base, "answer": "a spaceship"}, _session(page), {}).what == "left"
    private_person = _brief("clarification", {}, names=["Glimmer"], public=False)
    assert hq.decide(private_person, {**base, "answer": "build cache"}, _session(page), {}).what == "note"   # a page never settles a private thing


def test_a_pair_is_settled_only_as_two_people_on_the_persons_own_line_for_each_side(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    ta = "user: My brother Marek is moving.\n\nassistant: Nice, Marek Voss would like that.\n"
    tb = "user: Marek Voss, my teammate and friend, came.\n\nassistant: Marek is a nice name.\n"
    ra = ha.Call("1", "Read", "file", str(files / "ep_a.md"), result=ta)
    rb = ha.Call("2", "Read", "file", str(files / "ep_b.md"), result=tb)
    brief = _brief("merge_suggestion", {}, bank=str(tmp_path / "bank"), compartment=ha.PRIVATE, public=False,
                   names=["Marek"], other_names=["Marek Voss"], copies=("ep_a", "ep_b"), copies_dir=str(files),
                   copy_texts={"ep_a": ta, "ep_b": tb})
    ans = {"status": "answered", "option": "different", "confidence": 0.85, "why": "relations differ", "evidence": [
        {"where": str(files / "ep_a.md"), "side": "a", "quote": "My brother Marek is moving."},
        {"where": str(files / "ep_b.md"), "side": "b", "quote": "Marek Voss, my teammate and friend, came."}]}
    sess = lambda *c: _session(*c, compartment=ha.PRIVATE)    # noqa: E731
    assert hq.decide(brief, ans, sess(ra, rb), {}).what == "settle"
    assert hq.decide(brief, {**ans, "confidence": 0.75}, sess(ra, rb), {}).what != "settle"          # the floor is 0.8
    assistant = {**ans, "evidence": [ans["evidence"][0], {**ans["evidence"][1], "quote": "Marek is a nice name."}]}
    assert hq.decide(brief, assistant, sess(ra, rb), {}).what != "settle"                             # an assistant's turn
    wrong_side = {**ans, "evidence": [{**ans["evidence"][0], "quote": "Marek Voss would like that."}, ans["evidence"][1]]}
    assert hq.decide(brief, wrong_side, sess(ra, rb), {}).what != "settle"
    one_side = {**ans, "evidence": ans["evidence"][:1]}
    assert hq.decide(brief, one_side, sess(ra, rb), {}).what in ("note", "left")                     # never settled on one side
    same = {"status": "cannot_tell", "confidence": 0.8, "why": "SESSION-OWN-WORDS", "found": "SESSION-OWN-FOUND",
            "evidence": [{"where": str(files / "ep_a.md"), "quote": "My brother Marek is moving."}]}
    v = hq.decide(brief, same, sess(ra, rb), {})
    assert v.what == "note" and "SESSION-OWN" not in v.note and v.note.startswith("Cicada's agent read: ep_a:")   # built by code
    outside = {**ans, "evidence": [{**ans["evidence"][0], "where": str(tmp_path / "x.txt")}, ans["evidence"][1]]}
    assert hq.decide(brief, outside, sess(ra, rb), {}).what != "settle"
    # a search that printed relative paths: the file is found from the folder it ran in, the turn is read from the copy the code wrote
    g_ok = ha.Call("3", "Grep", "file_search", f"Marek in {files}",
                   result="ep_a.md:1:user: My brother Marek is moving.\nep_b.md:1:user: Marek Voss, my teammate and friend, came.\n")
    session = _session(g_ok, compartment=ha.PRIVATE)
    session.cwd = str(files)
    assert hq.decide(brief, ans, session, {}).what == "settle"
    g_assistant = ha.Call("4", "Grep", "file_search", f"Marek in {files}", result="ep_b.md:2:assistant: Marek is a nice name.\n")
    bad = _session(g_ok, g_assistant, compartment=ha.PRIVATE)
    bad.cwd = str(files)
    assert hq.decide(brief, assistant, bad, {}).what != "settle"                       # the copy says it is an assistant's turn


# --------------------------------------------------------------------------- the conversations a private session is given


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("api.services.pair_evidence.FRESH_S", 0.0)
    m = hb.new_bank(tmp_path)
    hb.git(m, "add", "-A")
    hb.git(m, "commit", "-qm", "seed")
    return m


def _episode(m: Path, eid: str, text: str, **fm) -> None:
    markdown_parser.write(m / "episodes" / f"{eid}.md", {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": True,
                                                          "title": "t", "source": "claude-code", **fm}, text)


def test_a_private_session_is_given_masked_copies_of_only_the_conversations_that_bear_on_the_question(bank):
    _episode(bank, "ep_2026-10-01_001", "user: Marek is my brother.\n")
    _episode(bank, "ep_2026-10-02_001", "user: Marek Voss is on my team.\n")
    _episode(bank, "ep_2026-10-03_001", "user: Marek watched videos.\n", source="watch-history")          # index-only
    _episode(bank, "ep_2026-10-04_001", "user: Marek saved page.\n", origin="bookmark")                    # a saved article
    _episode(bank, "ep_2026-10-05_001", "assistant: Marek, an agent's saved note.\n", source="mcp")        # an agent's note
    _episode(bank, "ep_2026-10-06_001", "assistant: cited Marek.\n", source="web-check", origin="harness-agent")   # an earlier run's
    _episode(bank, "ep_2026-10-07_001", "user: Marek locked.\n", locked_note=True)
    _episode(bank, "ep_2026-10-08_001", "user: unrelated talk.\n")                                          # does not bear on either page
    ids = [f"ep_2026-10-0{i}_001" for i in range(1, 8)]
    hb.page(bank, "marek", "Marek", "A person.", source_episodes=ids[:1] + ids[2:])
    hb.page(bank, "marek-voss", "Marek Voss", "A person.", source_episodes=ids[1:2])
    path = hb.pair(bank, ("marek", "Marek"), ("marek-voss", "Marek Voss"), "Same?")
    fm = dict(markdown_parser.parse(path).frontmatter)
    copies = hq.copies_for(bank, "merge_suggestion", fm)
    assert not set(copies) & {"ep_2026-10-03_001", "ep_2026-10-04_001", "ep_2026-10-05_001", "ep_2026-10-06_001",
                              "ep_2026-10-07_001", "ep_2026-10-08_001"}
    assert {"ep_2026-10-01_001", "ep_2026-10-02_001"} <= set(copies)


def test_a_copy_is_masked_by_value_exactly_as_an_engine_would_see_it(bank, monkeypatch):
    _episode(bank, "ep_2026-10-01_001", "user: My code word is SECRET-VALUE-XYZ and Marek knows.\n")
    hb.page(bank, "marek", "Marek", "A person.", source_episodes=["ep_2026-10-01_001"])
    hb.page(bank, "marek-voss", "Marek Voss", "A person.", source_episodes=[])
    path = hb.pair(bank, ("marek", "Marek"), ("marek-voss", "Marek Voss"), "Same?")
    monkeypatch.setattr("api.services.sensitive_hold.hold_back",
                        lambda messages, mp: [{**m, "content": m["content"].replace("SECRET-VALUE-XYZ", "[withheld]")} for m in messages])
    copies = hq.copies_for(bank, "merge_suggestion", dict(markdown_parser.parse(path).frontmatter))
    assert "SECRET-VALUE-XYZ" not in copies["ep_2026-10-01_001"] and "[withheld]" in copies["ep_2026-10-01_001"]


def test_a_web_brief_carries_only_the_questions_words_and_never_what_a_private_session_read(bank, scratch_home):
    canary = "PRIVATE-CANARY-4417"
    path = hb.conflict(bank, "zephyr", "Zephyr", "tool", "version", "Which version is current?", "4.1", "4.2")
    page = markdown_parser.parse(bank / "entities" / "zephyr.md")
    markdown_parser.write(bank / "entities" / "zephyr.md", {**page.frontmatter, "aliases": ["Zeph"]},
                          f"## Summary\n{canary} lives in this page's prose.\n" + page.body)
    fm = dict(markdown_parser.parse(path).frontmatter)
    fm["agent_found"] = {"note": f"Cicada's agent read: {canary}", "evidence": [{"where": "/x", "quote": canary}], "trail": []}
    fm["question"] = "Which version is current? See https://docs.example/changelog"
    web = hq.brief_for(bank, path, fm, ha.WEB, public=True)
    assert web is not None and canary not in web.prompt and "agent_found" not in web.prompt
    assert "Zephyr" in web.prompt and "Which version is current?" in web.prompt and "docs.example" in web.prompt
    assert "What the memory holds" not in web.prompt and "episodes" not in web.prompt       # no excerpt, no conversation folder
    private = hq.brief_for(bank, path, fm, ha.PRIVATE, public=True, roots=("/home/u/code",), copies={}, copies_dir="/s/files")
    assert canary in private.prompt and "You have no web tool" in private.prompt
    assert hq.brief_for(bank, path, fm, ha.WEB, public=True).names == private.names
    ppath = hb.pair(bank, ("zephyr", "Zephyr"), ("owner-example", "Owner Example"), "Same?")
    assert hq.brief_for(bank, ppath, dict(markdown_parser.parse(ppath).frontmatter), ha.WEB) is None   # a pair is private only


def test_the_plan_never_hands_a_pair_to_the_web_and_a_non_public_conflict_never_either():
    assert hq.plan_for("merge_suggestion", True) == (ha.PRIVATE,)
    assert hq.plan_for("conflict", False) == (ha.PRIVATE,) and hq.plan_for("conflict", True) == (ha.PRIVATE, ha.WEB)
    assert hq.plan_for("clarification", False) == (ha.PRIVATE, ha.WEB)


# --------------------------------------------------------------------------- the one write


def _case(name):
    return next(c for c in hb.cases("http://x") if c.name == name)


def _runner(**by_compartment):
    """A fake harness: ``by_compartment[compartment](cwd)`` makes the session (or is one)."""
    seen = []

    def runner(argv, prompt, *, cwd, env=None, on_call=None, expected_tools=None, compartment="", folders=(), copies_dir=""):
        seen.append({"argv": argv, "prompt": prompt, "cwd": cwd, "compartment": compartment, "expected": expected_tools})
        spec = by_compartment.get(compartment)
        s = spec(cwd) if callable(spec) else (spec or ha.Session())
        s.compartment = compartment
        return s
    runner.seen = seen
    return runner


def _work(bank: Path, path: Path, runner, *, apply: bool = True, roots=(), public: bool = True, memo=None):
    fm = dict(markdown_parser.parse(path).frontmatter)
    return run(hq.work_one(bank, hb.Settings(bank), path, fm, "haiku", apply=apply, roots=roots, refused=(), public=public,
                           runner=runner, memo=memo))


def test_a_found_answer_is_settled_through_the_one_resolver_with_a_reason_built_by_code_and_undoes(bank):
    path = hb.conflict(bank, "zephyr", "Zephyr", "tool", "version", "Which version is current?", "4.1", "4.2")
    sentence = "Zephyr's current stable release is 4.2."
    answer = {"status": "answered", "option": "b", "confidence": 0.9, "why": "SESSION-OWN-WHY a long free text of its own",
              "evidence": [{"where": "https://x.test/p", "quote": sentence}]}
    web = lambda cwd: _session(_page_call("https://x.test/p", f"Changelog\n{sentence}\n"), answer=answer)   # noqa: E731
    runner = _runner(web=web)
    dry = _work(bank, path, runner, apply=False)
    assert dry.what == "would_settle" and path.exists()                                    # the dry run writes nothing
    assert [c["compartment"] for c in runner.seen] == ["web"]                              # no folder to read and no copies: no private session
    out = _work(bank, path, runner)
    assert out.what == "settled" and not path.exists()
    record = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-001.md").frontmatter["settled"]
    assert record["rule"] == "found_by_agent" and record["answer"] == "4.2"
    assert record["found"][0]["where"] == "https://x.test/p" and record["found"][0]["quote"] == sentence
    assert record["trail"][0] == {"tool": "address", "what": "https://x.test/p", "in": "web"}
    assert record["trail"][1]["tool"] == "scan"
    row = [r for r in web_settle.list_settled(bank) if r["rule"] == "found_by_agent"]
    assert row and row[0]["reason"].startswith('Read in x.test: "Zephyr')
    stored = hb.bank_text(bank)
    assert "SESSION-OWN-WHY" not in stored                                                 # the session's own words are never stored
    episodes = [p for p in (bank / "episodes").glob("*.md") if markdown_parser.parse(p).frontmatter.get("source") == "web-check"]
    assert len(episodes) == 1 and "> " + sentence in episodes[0].read_text()               # a citation episode, never the person's words
    assert not subprocess.run(["git", "-C", str(bank), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    restored, _paths, _lines, _rec = inbox_tend.undo(bank, "inbox-001")
    assert restored == "inbox-001" and (bank / "inbox" / "inbox-001.md").exists()


def test_private_then_web_and_nothing_the_private_session_read_reaches_the_web_brief(bank, scratch_home):
    canary = "PRIVATE-NOTE-CANARY-9921"
    (bank.parent / "work").mkdir()
    (bank.parent / "work" / "n.txt").write_text(f"{canary}\n")
    path = hb.conflict(bank, "zephyr", "Zephyr", "tool", "version", "Which version is current?", "4.1", "4.2")
    private = lambda cwd: _session(ha.Call("r", "Read", "file", str(bank.parent / "work" / "n.txt"), result=f"1\t{canary}\n"),   # noqa: E731
                                   answer={"status": "not_found", "confidence": 0.9, "why": canary, "found": canary, "evidence": []})
    web = lambda cwd: _session(answer={"status": "not_found", "confidence": 0.9, "why": "none", "evidence": []})   # noqa: E731
    runner = _runner(private=private, web=web)
    memo: dict = {}
    out = _work(bank, path, runner, roots=(str(bank.parent / "work"),), memo=memo)
    assert [c["compartment"] for c in runner.seen] == ["private", "web"] and out.what.startswith("left")
    web_seen = [c for c in runner.seen if c["compartment"] == "web"][0]
    assert canary not in web_seen["prompt"] and canary not in " ".join(web_seen["argv"])
    assert web_seen["expected"] == ha.COMPARTMENT_TOOLS[ha.WEB] and runner.seen[0]["expected"] == ha.COMPARTMENT_TOOLS[ha.PRIVATE]
    assert canary not in json.dumps(memo) and canary not in hb.bank_text(bank)               # not in the memo, not in the bank


def test_a_pair_read_as_two_people_is_rejected_as_the_persons_no_from_conversation_copies(bank):
    path = _case("pair_different").build(bank, bank, "http://x")
    ids = ("ep_2026-10-03_001", "ep_2026-10-20_001")

    def private(cwd):
        a, b = Path(cwd) / f"{ids[0]}.md", Path(cwd) / f"{ids[1]}.md"
        ra = ha.Call("1", "Read", "file", str(a), result=a.read_text())
        rb = ha.Call("2", "Read", "file", str(b), result=b.read_text())
        ans = {"status": "answered", "option": "different", "confidence": 0.85, "why": "relations differ", "evidence": [
            {"where": str(a), "side": "a", "quote": "My brother Marek is moving to Valencia next month"},
            {"where": str(b), "side": "b", "quote": "Marek Voss, my teammate and friend from the platform team"}]}
        return _session(ra, rb, answer=ans, compartment=ha.PRIVATE)
    out = _work(bank, path, _runner(private=private), public=False)
    assert out.what == "settled" and out.answer == "different"
    assert not (bank / "entities" / "marek.md").read_text().count("different")          # no page was rewritten
    assert inbox_tend.RULES["found_by_agent"]


def test_a_pair_that_reads_as_one_person_leaves_a_template_note_through_the_admitted_write_and_joins_nothing(bank):
    path = _case("pair_same").build(bank, bank, "http://x")

    def private(cwd):
        a = Path(cwd) / "ep_2026-10-03_001.md"
        ans = {"status": "cannot_tell", "confidence": 0.8, "why": "SESSION-OWN-WHY", "found": "SESSION-OWN-FOUND free text",
               "evidence": [{"where": str(a), "quote": "Teodor Brandt, called Teo, starts on the platform team"}],
               "mixed": {"a": ["ep_2026-10-03_001", "ep_not_given"]}}
        return _session(ha.Call("1", "Read", "file", str(a), result=a.read_text()), answer=ans, compartment=ha.PRIVATE)
    out = _work(bank, path, _runner(private=private), public=False)
    assert out.what == "noted" and path.exists()
    fm = markdown_parser.parse(path).frontmatter
    assert fm["agent_found"]["note"].startswith("Cicada's agent read: ep_2026-10-03_001:")
    assert fm["agent_found"]["mixed"] == {"a": ["ep_2026-10-03_001"]}
    assert "SESSION-OWN" not in hb.bank_text(bank)
    assert (bank / "entities" / "teo.md").exists() and (bank / "entities" / "teodor-brandt.md").exists()


def test_a_note_or_a_settle_waits_for_sleep_and_is_never_a_collision(bank, monkeypatch):
    path = _case("pair_same").build(bank, bank, "http://x")

    def private(cwd):
        a = Path(cwd) / "ep_2026-10-03_001.md"
        ans = {"status": "cannot_tell", "confidence": 0.8, "why": "w", "evidence": [
            {"where": str(a), "quote": "Teodor Brandt, called Teo, starts on the platform team"}]}
        return _session(ha.Call("1", "Read", "file", str(a), result=a.read_text()), answer=ans, compartment=ha.PRIVATE)
    monkeypatch.setattr(write_admission, "holding", lambda: True)           # Sleep holds the pages
    out = _work(bank, path, _runner(private=private), public=False)
    assert out.what == "left:sleep_running" and "agent_found" not in markdown_parser.parse(path).frontmatter


def test_the_persons_own_words_outrank_anything_found(bank):
    from api.services.claims import Claim, Evidence, write_claims

    own = Claim(id="clm_a", text="x", subject="zephyr", predicate="version", object="4.1", valid_from="2026-05-01",
                recorded_at="2026-05-01", evidence=[Evidence(episode="ep_2026-05-01_001", start=0, end=4, kind="user", hash="h")])
    other = Claim(id="clm_b", text="y", subject="zephyr", predicate="version", object="4.2", valid_from="2026-05-01",
                  recorded_at="2026-05-01")
    markdown_parser.write(bank / "entities" / "zephyr.md", {"name": "Zephyr", "type": "tool", "status": "active"},
                          write_claims("## Summary\nZ.\n", [own, other]))
    path = hb.item(bank, kind="conflict", entity_id="zephyr", entity_name="Zephyr", predicate="version", question="Which?",
                   options=[{"key": "a", "label": "4.1", "claim_id": "clm_a"}, {"key": "b", "label": "4.2", "claim_id": "clm_b"}])
    out = _work(bank, path, _runner(web=lambda cwd: _session(_page_call("http://x.test/p", QUOTE), answer=ANSWER)))
    assert out.what == "left:not_workable" and path.exists()


def test_candidates_leave_what_is_not_theirs(bank):
    hb.item(bank, kind="clarification", entity_id="owner-example", entity_name="Owner", asks="name", question="What is the name?")
    assert hq.candidates(bank) == []
    hb.item(bank, kind="clarification", entity_id="owner-example", entity_name="Owner", question="Who is Owner?", sleep_settle="undone")
    assert hq.candidates(bank) == []


def test_the_run_is_off_with_its_switch_and_for_a_demo(bank, monkeypatch):
    class Off(hb.Settings):
        harness_agent = False

    assert run(hq.run_tail(bank, Off(bank), user_triggered=True)).skipped == {"off": 1}
    assert hq.start_run(bank, Off(bank), user_triggered=True) is False


# --------------------------------------------------------------------------- the read-only browser


def test_the_browser_window_refuses_non_public_hosts_and_debug_ports(monkeypatch):
    monkeypatch.setattr(read_browser.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 443))])
    ok = read_browser.refused_reason
    assert ok("https://example.com/p") == ""
    for url in ("file:///etc/hosts", "javascript:alert(1)", "http://localhost/", "http://127.0.0.1/", "http://[::1]/", "http://10.0.0.5/",
                "http://192.168.1.1/", "http://169.254.169.254/latest/", "http://intranet/", "http://2130706433/", "http://printer.local/",
                "http://a.localhost/", "https://example.com:9222/json", "http://0.0.0.0/", "http://100.64.0.1/"):
        assert ok(url), url
    monkeypatch.setattr(read_browser.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("10.1.2.3", 80))])
    assert ok("https://rebinding.example.com/")                    # a public name that resolves to a private address
    monkeypatch.setattr(read_browser.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("127.0.0.1", 80))])
    assert ok("https://two-faced.example.com/")                    # any private address among the answers
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:9333")
    monkeypatch.setattr(read_browser.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert ok("https://example.com:9333/")                         # the harness's own debugging port


# The browser window's own tests (grant, state, links, tabs, the launcher) are in test_harness_browse.py.


# --------------------------------------------------------------------------- what is stored, what one question may scan, the listing


def _file_call(path, text, kind="file", denied=False):
    return ha.Call("f1", "Read", kind, str(path), result=text, denied=denied, error=denied)


def test_a_quote_from_a_file_is_stored_only_when_the_file_is_an_allowed_kind_under_a_granted_folder_and_never_key_material(tmp_path):
    root = tmp_path / "Notes"
    root.mkdir()
    sentence = "Zephyr's current stable release is 4.2."
    for name in ("notes.md", "app.py", "sa.json", "keys.md"):
        (root / name).write_text(sentence)
    ans = lambda f: {**ANSWER, "evidence": [{"where": str(root / f), "quote": sentence}]}   # noqa: E731
    brief = lambda: _brief(compartment=ha.PRIVATE, roots=(str(root.resolve()),), refused=(), bank=str(tmp_path / "bank"))   # noqa: E731
    v = hq.decide(brief(), ans("notes.md"), _session(_file_call((root / "notes.md").resolve(), sentence), compartment=ha.PRIVATE), {})
    assert v.what == "settle" and v.dropped == 0
    for name in ("app.py", "sa.json"):                      # a file of a kind that is not a document: the item is dropped and counted
        bad = hq.decide(brief(), ans(name), _session(_file_call((root / name).resolve(), sentence), compartment=ha.PRIVATE), {})
        assert bad.what == "left" and bad.dropped == 1 and bad.why == "evidence_dropped", name
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
    keyed = f"Zephyr's current stable release is 4.2. {token}"
    (root / "notes2.md").write_text(keyed)
    quote_with_key = {**ANSWER, "evidence": [{"where": str(root / "notes2.md"), "quote": keyed}]}
    dropped = hq.decide(brief(), quote_with_key, _session(_file_call((root / "notes2.md").resolve(), keyed), compartment=ha.PRIVATE), {})
    assert dropped.what == "left" and dropped.dropped == 1 and token not in repr(dropped)


def test_the_stored_audit_never_shows_a_path_the_grant_does_not_cover_nor_text_that_looks_like_a_key(tmp_path):
    root = tmp_path / "Notes"
    root.mkdir()
    (root / "a.md").write_text("x")
    brief = _brief(compartment=ha.PRIVATE, roots=(str(root.resolve()),), refused=(str(tmp_path / "bank"),), copies_dir=str(tmp_path / "f"))
    calls = [_file_call((root / "a.md").resolve(), "x"), _file_call(root / "sa.json", "refused", denied=True),
             ha.Call("2", "Grep", "file_search", f"needle in {root.resolve()}"), ha.Call("3", "Grep", "file_search", "needle in /etc"),
             ha.Call("4", "WebSearch", "search", "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"), ha.Call("5", "WebSearch", "search", "zephyr release")]
    session = _session(*calls, compartment=ha.PRIVATE)
    session.scan = {"files": 2, "bytes": 10, "folders": 1, "refused": 1}
    trail = hq._trail([session], brief)
    whats = [t["what"] for t in trail]
    assert whats[0].endswith("a.md") and "sa.json" not in " ".join(whats) and "/etc" not in " ".join(whats) and "ghp_" not in " ".join(whats)
    assert whats[1] == "(a file the grant does not cover)" and trail[1]["denied"] is True
    assert whats[2].startswith("needle in ") and whats[3] == "(a search the grant does not cover)"
    assert whats[4] == "(text that looks like a key)" and whats[5] == "zephyr release"
    assert trail[-1] == {"tool": "scan", "what": "files=2 bytes=10 folders=1 refused=1 redacted=3", "in": "private"}


def _reads(n, folder="/a"):
    return [_use(str(i), "Read", {"file_path": f"{folder}/{i}.md"}) for i in range(n)]


def test_a_question_may_open_only_so_many_files_read_so_many_bytes_and_search_so_many_folders(tmp_path, scratch_home):
    env = dict(os.environ)
    init = _init(("Read", "Glob", "Grep"))
    over = ha.run([_fake_claude(tmp_path, [init, *_reads(ha.MAX_FILES_OPENED + 1)])], "p", cwd=str(tmp_path), env=env,
                  max_calls=99, expected_tools=ha.COMPARTMENT_TOOLS[ha.PRIVATE], folders=("/a",))
    assert over.stopped == "scan_limit" and over.answer is None and over.scan["files"] == ha.MAX_FILES_OPENED + 1
    fine = ha.run([_fake_claude(tmp_path, [init, *_reads(ha.MAX_FILES_OPENED), {"type": "result", "structured_output": {"status": "not_found", "confidence": 1, "why": "", "evidence": []}}])],
                  "p", cwd=str(tmp_path), env=env, max_calls=99, expected_tools=ha.COMPARTMENT_TOOLS[ha.PRIVATE], folders=("/a",))
    assert fine.stopped == "" and fine.scan == {"files": ha.MAX_FILES_OPENED, "bytes": 0, "folders": 1, "refused": 0}
    big = [init, _use("a", "Read", {"file_path": "/a/x.md"}), _res("a", "y" * (ha.MAX_BYTES_READ + 1))]
    assert ha.run([_fake_claude(tmp_path, big)], "p", cwd=str(tmp_path), env=env, folders=("/a",),
                  expected_tools=ha.COMPARTMENT_TOOLS[ha.PRIVATE]).stopped == "scan_limit"
    many = [init] + [_use(str(i), "Grep", {"pattern": "x", "path": f"/f{i}"}) for i in range(ha.MAX_FOLDERS + 1)]
    folders = tuple(f"/f{i}" for i in range(ha.MAX_FOLDERS + 1))
    spread = ha.run([_fake_claude(tmp_path, many)], "p", cwd=str(tmp_path), env=env, max_calls=99, folders=folders,
                    expected_tools=ha.COMPARTMENT_TOOLS[ha.PRIVATE])
    assert spread.stopped == "scan_limit" and spread.scan["folders"] == ha.MAX_FOLDERS + 1


def _conflict_at(bank, n, pid, name, **kw):
    path = hb.conflict(bank, pid, name, kw.pop("ptype", "tool"), kw.pop("predicate", "license"), kw.pop("question", f"Which license does {name} use?"),
                       kw.pop("a", "MIT"), kw.pop("b", "Apache-2.0"))
    target = path.with_name(f"inbox-{n:03d}.md")
    path.rename(target)
    return target


def test_the_listing_counts_only_what_a_run_would_start_a_session_for_with_its_compartments_and_says_what_it_leaves(bank, tmp_path):
    from api.services import web_settle

    ok = _conflict_at(bank, 2, "zephyr", "Zephyr")
    mine = _conflict_at(bank, 3, "home-city", "Home City", ptype="location", predicate="lives-in", question="Where do you live these days?",
                        a="Lisbon", b="Porto")
    mine_tool = _conflict_at(bank, 5, "vexor", "Vexor", question="Which version of Vexor do you use?", a="3.1", b="3.2", predicate="version")
    pair = hb.pair(bank, ("owner-example", "Owner Example"), ("zephyr", "Zephyr"), "Same?")        # the owner's own page: never a pair
    pair.rename(pair.with_name("inbox-004.md"))
    from api.services import bank_index
    bank_index.invalidate(bank)
    rows = hq.candidates(bank)
    assert {p.stem for p, _fm in rows} == {"inbox-002", "inbox-003", "inbox-004", "inbox-005"}
    notes = tmp_path / "Notes"
    notes.mkdir()
    (notes / "a.md").write_text("x")
    grant = hf.grant_for_roots((str(notes),), ())
    ready, left = hq.plan_run(bank, rows, grant, memo={})
    by = {p.path.stem: p for p in ready}
    assert set(by) == {"inbox-002", "inbox-003", "inbox-005"} and left == {"not_two_separate_people": 1}
    # how a conflict is decided to be about a public thing (ruling 27's test): a tool's license is, the person's own life is not
    assert (by["inbox-002"].public, by["inbox-002"].why_public) == (True, "public") and by["inbox-002"].compartments == ("private", "web")
    assert by["inbox-003"].public is False and by["inbox-003"].why_public == "private_type" and by["inbox-003"].compartments == ("private",)
    assert by["inbox-005"].public is False and by["inbox-005"].why_public == "personal" and by["inbox-005"].compartments == ("private",)
    # a question the memo holds back is counted, not listed; a limit stops the listing early
    memo = {"inbox-002": {"d": hq._mark(bank, by["inbox-002"].fm), "at": date.today().isoformat(), "o": "left:x"}}
    ready2, left2 = hq.plan_run(bank, rows, grant, memo=memo)
    assert [p.path.stem for p in ready2] == ["inbox-003", "inbox-005"] and left2 == {"worked_already": 1, "not_two_separate_people": 1}
    assert len(hq.plan_run(bank, rows, grant, memo={}, limit=1)[0]) == 1
    # no folder to read and no copies: a private-only question has nothing to start on, a public one still has the web
    by_stem = {p.stem: (p, fm) for p, fm in rows}
    web_only, none_left = hq.plan_run(bank, [by_stem["inbox-002"], by_stem["inbox-003"]], hf.Grant(), memo={})
    assert [(p.path.stem, p.compartments) for p in web_only] == [("inbox-002", ("web",))] and none_left == {"nothing_to_read": 1}


def test_a_session_runs_in_a_private_temp_folder_outside_cicadas_home_removed_afterwards(bank, tmp_path, scratch_home):
    notes = tmp_path / "Notes"
    notes.mkdir()
    (notes / "a.md").write_text("x")
    path = hb.conflict(bank, "zephyr", "Zephyr", "tool", "version", "Which version?", "4.1", "4.2")
    seen = {}

    def private(cwd):
        seen["cwd"] = cwd
        seen["mode"] = oct(Path(cwd).parent.stat().st_mode & 0o777)
        seen["registered"] = len(list((scratch_home / "harness_sessions").glob("scratch-*.json")))
        return ha.Session()
    out = _work(bank, path, _runner(private=private), roots=(str(notes),), public=False)
    assert out.what.startswith("left")
    assert seen["mode"] == "0o700" and seen["registered"] == 1
    assert not Path(seen["cwd"]).parent.exists() and not list((scratch_home / "harness_sessions").glob("scratch-*.json"))
    assert not hf.under(seen["cwd"], str(scratch_home)) and not hf.under(seen["cwd"], str(bank)) and not hf.under(seen["cwd"], str(notes))


def test_a_conversation_copy_is_known_by_its_folder_however_the_session_spells_the_path(tmp_path):
    real = (tmp_path / "files").resolve()
    real.mkdir()
    (real / "ep_2026-10-03_001.md").write_text("user: My brother Marek is moving.\n")
    brief = _brief(compartment=ha.PRIVATE, copies=("ep_2026-10-03_001",), copies_dir=str(real))
    spelled = str(real / "ep_2026-10-03_001.md")
    short = spelled[len("/private"):] if spelled.startswith("/private/") else spelled          # a Mac's /var for /private/var
    for where in (spelled, short, str(tmp_path / "files" / ".." / "files" / "ep_2026-10-03_001.md")):
        assert hq._conversation_of(ha.Evidence(where, "file", "x"), brief) == "ep_2026-10-03_001", where
    assert hq._conversation_of(ha.Evidence(str(tmp_path / "ep_2026-10-03_001.md"), "file", "x"), brief) == ""     # another folder


def test_the_record_of_what_was_found_is_scrubbed_like_every_episode(tmp_path):
    """R-LS6: the web-check episode the agent's settle cites goes through `episode_scrub`, so a secret a quote still
    carries never reaches the bank."""
    from api.services import markdown_parser

    memory = tmp_path / "memory"
    secret = "sk-" + "Z" * 24
    evidence = [ha.Evidence("https://example.com/zephyr", "address", f"Zephyr 4.2 shipped; token {secret}")]
    path = hq._found_episode(memory, _brief(bank=str(memory)), evidence, "m")
    (written,) = (memory / "episodes").glob("*.md")
    body = markdown_parser.parse(written).body
    assert secret not in body and "Zephyr 4.2 shipped" in body
    assert str(path)


def test_a_run_that_has_not_started_leaves_quietly_when_the_process_is_going_down(tmp_path, monkeypatch):
    """A background run waiting out its delay must not start, or log, once the process is exiting: a daemon thread that
    logs during shutdown aborts the interpreter (exit 134 at the end of a test run)."""
    import subprocess as sp

    memory = tmp_path / "memory"
    memory.mkdir()
    sp.run(["git", "init", "-q", str(memory)], check=True)
    ran = []

    async def never(*a, **k):
        ran.append(1)
        return hq.Report()

    monkeypatch.setattr(hq, "run_tail", never)
    hq._STOPPING.clear()

    class S:
        harness_agent = True

    try:
        assert hq.start_run(memory, S(), user_triggered=True, delay_s=30.0) is True
        hq._stop_runs()                      # what `atexit` runs
        assert ran == [] and not any(t.is_alive() for t in hq._THREADS)
        assert hq.start_run(memory, S(), user_triggered=True) is False, "nothing starts once the process is stopping"
    finally:
        hq._STOPPING.clear()

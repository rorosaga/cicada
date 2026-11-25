"""Cicada's own agent (ruling 83): the two compartments, the grant, the init check, the gates on its answer, the one write,
the orphan reaper and the (unwired) read-only browser.

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
from pathlib import Path

import pytest

from api.harness_tools import read_browser
from api.services import harness_agent as ha, harness_questions as hq, inbox_tend, markdown_parser, web_settle, write_admission
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


def test_no_compartment_is_offered_a_shell_or_the_browser_and_the_browser_is_not_wired():
    for compartment, tools in ha.COMPARTMENT_TOOLS.items():
        assert "Bash" not in tools and not (ha.COMPARTMENT_TOOLS[ha.PRIVATE] & ha.COMPARTMENT_TOOLS[ha.WEB])
        assert not any("Bash" in r for r in ha.settings_for(ha.Policy(compartment, roots=("/r",)))["permissions"]["allow"])
    source = Path(ha.__file__).read_text() + Path(hq.__file__).read_text()
    assert "BROWSE_SCRIPT" not in source and "read_browser" not in source.replace("api/harness_tools/read_browser.py", "")


def test_secrets_are_denied_by_absolute_rules_for_every_root_and_every_tool(tmp_path):
    roots = (str(tmp_path / "code"), str(tmp_path / "notes"))
    deny = set(ha.settings_for(ha.Policy(ha.PRIVATE, roots=roots))["permissions"]["deny"])
    for root in roots:
        for tool in ("Read", "Grep", "Glob"):
            for name in (".env*", "*.env", "secrets*", "credentials*", ".netrc", ".pgpass", "id_*", "*.pem", "*.key", "*.p12",
                         "*.pfx", "*.jks", "*.kdbx"):
                assert f"{tool}(/{root}/**/{name})" in deny, (tool, root, name)
            for folder in (".aws", ".ssh", ".gnupg"):
                assert f"{tool}(/{root}/**/{folder}/**)" in deny
            assert f"{tool}(/{root}/**/.git/config)" in deny
    assert "Read(**/.env*)" in deny      # and the relative spelling


def test_read_roots_grant_plain_folders_and_never_hidden_library_links_or_mounts(tmp_path, monkeypatch):
    for name in (".ssh", ".cicada", ".claude", ".aws", "Library", "Documents", "Downloads", "Desktop", "Pictures", "Applications",
                 "code", "notes", "mounted"):
        (tmp_path / name).mkdir()
    (tmp_path / "loose.txt").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "code")
    names = lambda roots: sorted(Path(r).name for r in roots)   # noqa: E731
    monkeypatch.setattr(ha, "_same_device", lambda a, b: Path(a).name != "mounted")      # `mounted` is another volume
    assert names(ha.read_roots(tmp_path, attended=False)) == ["code", "notes"]
    assert names(ha.read_roots(tmp_path, attended=True)) == ["Desktop", "Documents", "Downloads", "Pictures", "code", "notes"]


def test_a_questions_roots_refuse_the_bank_and_cicadas_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "bank").mkdir()
    roots, refused = hq.home_roots(tmp_path / "bank", attended=False, home=tmp_path)
    assert str((tmp_path / "bank").resolve()) in refused and str((tmp_path / "home").resolve()) in refused
    rules = ha.settings_for(ha.Policy(ha.PRIVATE, roots=roots, refused=refused))["permissions"]["deny"]
    assert any(str((tmp_path / "bank").resolve()) in r for r in rules)


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


def _runner(**by_compartment):
    """A fake harness: ``by_compartment[compartment](cwd)`` makes the session (or is one)."""
    seen = []

    def runner(argv, prompt, *, cwd, env=None, on_call=None, expected_tools=None, compartment=""):
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
    assert record["trail"] == [{"tool": "address", "what": "https://x.test/p", "in": "web"}]
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
    path = hb.cases("http://x")[8].build(bank, bank, "http://x")
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
    path = hb.cases("http://x")[11].build(bank, bank, "http://x")

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
    path = hb.cases("http://x")[11].build(bank, bank, "http://x")

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


# --------------------------------------------------------------------------- the read-only browser (not wired in this PR)


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


def test_the_browser_window_honours_no_command_variable_and_reads_and_closes_only_its_own_tabs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CICADA_BROWSE_HARNESS", "/bin/false")
    monkeypatch.setenv("CICADA_BROWSE_STATE", str(tmp_path / "state.json"))
    assert not hasattr(read_browser, "HARNESS_ENV") and read_browser.HARNESS == "browser-harness"
    monkeypatch.setattr(read_browser.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 443))])
    ran: list[str] = []

    def fake_run(code):
        ran.append(code)
        if "new_tab" in code:
            return {"target": "T1", "url": "https://example.com/", "title": "t", "password": False, "text": "hello"}, ""
        if "switch_tab" in code:
            return {"url": "https://example.com/", "title": "t", "text": "hello again"}, ""
        return {"closed": True}, ""
    monkeypatch.setattr(read_browser, "_run", fake_run)
    assert read_browser.main(["rb", "text", "0"]) == 2 and not ran                       # no tab of this run yet
    assert read_browser.main(["rb", "open", "http://localhost:9/"]) == 2 and not ran       # refused before the harness is touched
    assert read_browser.main(["rb", "open", "https://example.com/"]) == 0
    assert read_browser.main(["rb", "text", "0"]) == 0
    assert "switch_tab" in ran[-1] and "T1" in ran[-1]                                      # it switches to the tab this run opened
    (tmp_path / "state.json").write_text(json.dumps({"targets": ["T1"], "last": "FOREIGN"}))
    assert read_browser.main(["rb", "text", "0"]) == 2                                      # `last` is not one of its tabs
    (tmp_path / "state.json").write_text(json.dumps({"targets": ["T1", "T2"], "last": "T2"}))
    assert read_browser.main(["rb", "close"]) == 0
    assert "T1" in ran[-1] and "T2" in ran[-1]
    capsys.readouterr()


def test_the_browser_window_has_no_verb_that_acts(tmp_path):
    script = str(read_browser.__file__)
    run_ = lambda *a: subprocess.run([sys.executable, script, *a], capture_output=True, text=True)   # noqa: E731
    assert run_("click", "1,2").returncode == 2 and run_("type", "x").returncode == 2
    source = Path(script).read_text()
    for acting in ("click_at_xy", "type_text", "press_key", "fill_input", "dispatch_key", "upload_file", "goto_url"):
        assert acting not in source, acting

"""Cicada's own agent (ruling 83): the grant, the audit, the gate on its answer, the one write, and the read-only browser.

Synthetic banks of invented people; the session is a fake `claude` or an injected session, so nothing reaches the plan or a
network."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from api.services import harness_agent as ha, harness_questions as hq, inbox_tend, markdown_parser, web_settle
from benchmarks.consolidation import harness_battery as hb


def run(coro):
    return asyncio.run(coro)


def _session(*calls: ha.Call, answer: dict | None = None, stopped: str = "") -> ha.Session:
    return ha.Session(calls=list(calls), answer=answer, stopped=stopped, model="fake-model", seconds=1.0)


def _page_call(url: str, text: str) -> ha.Call:
    return ha.Call("t1", "WebFetch", "address", url, result=text)


# --------------------------------------------------------------------------- the grant


def test_the_grant_holds_no_write_tool_and_one_bash_prefix(tmp_path):
    policy = ha.Policy(roots=(str(tmp_path / "code"),), refused=(str(tmp_path / "bank"),), browser=True)
    s = ha.settings_for(policy)["permissions"]
    assert {"Write", "Edit", "NotebookEdit"} <= set(s["deny"])
    bash = [r for r in s["allow"] if r.startswith("Bash")]
    assert bash == [f"Bash(python3 {ha.BROWSE_SCRIPT}:*)"]
    assert not any(r.startswith(("Write", "Edit")) for r in s["allow"])
    assert f"Read(/{tmp_path}/code/**)".replace("//", "//") in s["allow"] or any(r.startswith("Read(//") for r in s["allow"])
    assert any(r.endswith("/bank/**)") for r in s["deny"])      # the refusal names the path, for each file tool
    assert "Read(**/.env)" in s["deny"]
    argv = ha.build_argv(model="haiku", system_prompt="x", policy=policy)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk" and argv[argv.index("--permission-prompts") + 1] == "none"
    assert "--bare" not in argv and "--mcp-config" not in argv and argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch,Bash"
    no_browser = ha.build_argv(model="haiku", system_prompt="x", policy=ha.Policy(roots=(), browser=False))
    assert "Bash" not in no_browser[no_browser.index("--tools") + 1]


def test_read_roots_skip_dot_folders_and_protected_ones_unless_attended(tmp_path):
    for name in (".ssh", ".cicada", "Library", "Documents", "Downloads", "code", "notes"):
        (tmp_path / name).mkdir()
    (tmp_path / "loose.txt").write_text("x")
    names = lambda roots: sorted(Path(r).name for r in roots)   # noqa: E731
    assert names(ha.read_roots(tmp_path, attended=False)) == ["code", "notes"]
    assert names(ha.read_roots(tmp_path, attended=True)) == ["Documents", "Downloads", "code", "notes"]


def test_a_questions_policy_reads_the_bank_and_refuses_cicadas_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "bank").mkdir()
    policy = hq.make_policy(tmp_path / "bank", attended=False, home=tmp_path, browser=False)
    assert str((tmp_path / "bank").resolve()) in policy.roots
    assert str((tmp_path / "home").resolve()) in policy.refused


# --------------------------------------------------------------------------- the audit


def test_every_call_is_one_audit_line():
    browse = f"python3 {ha.BROWSE_SCRIPT} open http://127.0.0.1:1/p"
    assert ha.classify("Bash", {"command": browse}) == ("address", "http://127.0.0.1:1/p")
    assert ha.classify("Bash", {"command": f"python3 {ha.BROWSE_SCRIPT} text 6000"})[0] == "browser"
    assert ha.classify("Bash", {"command": "rm -rf /"})[0] == "shell"
    assert ha.classify("Read", {"file_path": "/a/b"}) == ("file", "/a/b")
    assert ha.classify("WebSearch", {"query": "q"}) == ("search", "q")


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


def test_a_session_is_read_as_it_streams_and_a_refused_call_is_listed(tmp_path):
    events = [_use("a", "WebFetch", {"url": "http://x.test/p"}), _res("a", "Zephyr 4.2 is current"),
              _use("b", "Bash", {"command": "rm -rf *"}),
              _res("b", "Permission to use Bash has been denied because Claude Code is running in don't ask mode.", True),
              _use("c", "StructuredOutput", {}),
              {"type": "result", "structured_output": {"status": "answered", "confidence": 0.9, "why": "w", "evidence": []},
               "total_cost_usd": 0.01, "modelUsage": {"claude-haiku": {"outputTokens": 5}}}]
    session = ha.run([_fake_claude(tmp_path, events)], "prompt", cwd=str(tmp_path), env=dict(os.environ))
    assert [c.kind for c in session.calls] == ["address", "shell"] and [c.denied for c in session.calls] == [False, True]
    assert session.answer["status"] == "answered" and session.model == "claude-haiku" and session.stopped == ""
    assert session.audit[1] == {"tool": "shell", "what": "rm -rf *", "denied": True}


def test_a_session_over_its_calls_or_its_clock_is_killed_and_answers_nothing(tmp_path):
    many = [_use(str(i), "Read", {"file_path": f"/a/{i}"}) for i in range(5)]
    over = ha.run([_fake_claude(tmp_path, many)], "p", cwd=str(tmp_path), env=dict(os.environ), max_calls=3)
    assert over.stopped == "too_many_calls" and over.answer is None
    slow = ha.run([_fake_claude(tmp_path, [], sleep=5)], "p", cwd=str(tmp_path), env=dict(os.environ), timeout=0.5)
    assert slow.stopped == "timeout" and slow.answer is None
    assert ha.run(["/nonexistent/claude"], "p", cwd=str(tmp_path), env=dict(os.environ)).stopped == "no_binary"


# --------------------------------------------------------------------------- the gate on an answer


QUOTE = "The current stable release of the Zephyr tool is version 4.2, released on 2026-03-01."
ANSWER = {"status": "answered", "option": "b", "confidence": 0.9, "why": "stated",
          "evidence": [{"where": "http://x.test/p", "quote": QUOTE}]}


def test_evidence_counts_only_when_the_page_was_read_and_holds_the_quote():
    page = _page_call("http://x.test/p", f"Zephyr\n\n{QUOTE}\n")
    assert [e.where for e in ha.verify(ANSWER, _session(page))[0]] == ["http://x.test/p"]
    assert ha.verify(ANSWER, _session(_page_call("http://x.test/other", QUOTE)))[1] == "evidence_not_located"   # another page
    assert ha.verify(ANSWER, _session(_page_call("http://x.test/p", "nothing here")))[1] == "evidence_not_located"
    assert ha.verify({**ANSWER, "confidence": 0.5}, _session(page))[1] == "low_confidence"
    long = {**ANSWER, "evidence": [{"where": "http://x.test/p", "quote": QUOTE * 4}]}
    assert ha.verify(long, _session(_page_call("http://x.test/p", QUOTE * 4)))[1] == "evidence_not_located"
    assert ha.located("the  current STABLE release", "xx The current stable release yy")    # whitespace and case, never fuzzy
    assert not ha.located("the current stable relese", "The current stable release")


def test_a_login_page_or_a_refused_call_is_never_evidence():
    wall = _page_call("http://x.test/p", f"ADDRESS: x\nNEEDS A LOGIN: the page asks for a password.\n{QUOTE}")
    assert ha.verify(ANSWER, _session(wall))[1] == "evidence_not_located"
    refused = _page_call("http://x.test/p", QUOTE)
    refused.denied = True
    assert ha.verify(ANSWER, _session(refused))[1] == "evidence_not_located"


def test_a_file_is_evidence_by_the_path_it_was_read_even_when_written_shorter():
    read = ha.Call("r", "Read", "file", "/home/u/work/notes.txt", result="1\tVexor current stable is 3.2\n")
    ans = {**ANSWER, "evidence": [{"where": "work/notes.txt, line 1", "quote": "Vexor current stable is 3.2"}]}
    out = ha.verify(ans, _session(read))[0]
    assert [(e.where, e.kind) for e in out] == [("/home/u/work/notes.txt", "file")]


def test_a_line_a_search_printed_under_the_files_path_is_evidence_for_that_file():
    grep = ha.Call("g", "Grep", "file_search", "Glimmer in /w", result="/w/glossary.txt:2:Glimmer: the build cache service\n")
    ans = {**ANSWER, "evidence": [{"where": "/w/glossary.txt, line 2", "quote": "Glimmer: the build cache service"}]}
    assert [(e.where, e.kind) for e in ha.verify(ans, _session(grep))[0]] == [("/w/glossary.txt", "file")]
    other = {**ANSWER, "evidence": [{"where": "/w/another.txt", "quote": "Glimmer: the build cache service"}]}
    assert ha.verify(other, _session(grep))[1] == "evidence_not_located"           # the quote under another file's name


def _brief(kind="conflict", options=None, bank="/b"):
    return hq.Brief("inbox-001", kind, "p", options or {"a": "4.1", "b": "4.2"}, "e", "E", "m", bank)


def test_a_conflict_settles_only_on_an_option_the_quote_itself_carries():
    page = _page_call("http://x.test/p", QUOTE)
    what, words, ev, _why = hq.decide(_brief(), ANSWER, _session(page), {})
    assert (what, words) == ("settle", "4.2") and ev
    wrong_key = {**ANSWER, "option": "a"}
    assert hq.decide(_brief(), wrong_key, _session(page), {})[0:2] == ("left", "")      # 4.1 is not in the quote's own words
    assert hq.decide(_brief(), {**ANSWER, "status": "needs_login"}, _session(page), {})[3] == "needs_login"
    assert hq.decide(_brief(), ANSWER, _session(page, stopped="timeout"), {})[3] == "timeout"


def test_a_pair_is_settled_only_as_two_people_on_a_located_line_for_each_side(tmp_path):
    bank = tmp_path / "bank"
    (bank / "episodes").mkdir(parents=True)
    a, b = bank / "episodes" / "ep_a.md", bank / "episodes" / "ep_b.md"
    ra = ha.Call("1", "Read", "file", str(a), result="user: My brother Marek is moving.\n")
    rb = ha.Call("2", "Read", "file", str(b), result="user: Marek Voss, my teammate and friend, came.\n")
    ans = {"status": "answered", "option": "different", "confidence": 0.75, "why": "relations differ", "evidence": [
        {"where": str(a), "side": "a", "quote": "My brother Marek is moving."},
        {"where": str(b), "side": "b", "quote": "Marek Voss, my teammate and friend, came."}]}
    brief = _brief("merge_suggestion", {}, str(bank))
    assert hq.decide(brief, ans, _session(ra, rb), {})[0] == "settle"
    one_side = {**ans, "evidence": ans["evidence"][:1]}
    assert hq.decide(brief, one_side, _session(ra, rb), {})[0] in ("note", "left")          # never settled on one side
    same = {"status": "cannot_tell", "confidence": 0.8, "why": "one", "found": "They read as one person.",
            "evidence": [{"where": str(a), "quote": "My brother Marek is moving."}]}
    assert hq.decide(brief, same, _session(ra, rb), {})[0] == "note"                         # one person: a note, never a join
    outside = {**ans, "evidence": [{**ans["evidence"][0], "where": str(tmp_path / "x.txt")}, ans["evidence"][1]]}
    assert hq.decide(brief, outside, _session(ra, rb), {})[0] != "settle"


# --------------------------------------------------------------------------- the one write


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("api.services.pair_evidence.FRESH_S", 0.0)
    m = hb.new_bank(tmp_path)
    hb.git(m, "add", "-A")
    hb.git(m, "commit", "-qm", "seed")
    return m


def _work(bank: Path, path: Path, session: ha.Session, apply: bool = True):
    fm = dict(markdown_parser.parse(path).frontmatter)
    policy = ha.Policy(roots=(str(bank),), browser=False)
    return run(hq.work_one(bank, hb.Settings(bank), path, fm, policy, "haiku", apply=apply, runner=lambda *a, **k: session))


def test_a_found_answer_is_settled_through_the_one_resolver_with_its_evidence_and_undoes(bank):
    path = hb.conflict(bank, "zephyr", "Zephyr", "tool", "version", "Which version is current?", "4.1", "4.2")
    session = _session(_page_call("http://x.test/p", QUOTE), answer=ANSWER)
    dry = _work(bank, path, session, apply=False)
    assert dry.what == "would_settle" and path.exists()                                  # the dry run writes nothing
    out = _work(bank, path, session)
    assert out.what == "settled" and not path.exists()
    record = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-001.md").frontmatter["settled"]
    assert record["rule"] == "found_by_agent" and record["answer"] == "4.2"
    assert record["found"][0]["where"] == "http://x.test/p" and record["trail"] == [{"tool": "address", "what": "http://x.test/p"}]
    row = [r for r in web_settle.list_settled(bank) if r["rule"] == "found_by_agent"]
    assert row and row[0]["reason"]
    episodes = [p for p in (bank / "episodes").glob("*.md") if markdown_parser.parse(p).frontmatter.get("source") == "web-check"]
    assert len(episodes) == 1 and "> " + QUOTE in episodes[0].read_text()               # a citation episode, never the person's words
    assert not subprocess.run(["git", "-C", str(bank), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    restored, paths, lines, _rec = inbox_tend.undo(bank, "inbox-001")
    assert restored == "inbox-001" and (bank / "inbox" / "inbox-001.md").exists()


def test_a_pair_read_as_two_people_is_rejected_as_the_persons_no_and_a_same_is_only_a_note(bank):
    a, b = bank / "episodes" / "ep_2026-10-03_001.md", bank / "episodes" / "ep_2026-10-20_001.md"
    path = hb.cases("http://x")[6].build(bank, bank, "http://x")
    ra = ha.Call("1", "Read", "file", str(a.resolve()), result=a.read_text())
    rb = ha.Call("2", "Read", "file", str(b.resolve()), result=b.read_text())
    ans = {"status": "answered", "option": "different", "confidence": 0.8, "why": "relations differ", "evidence": [
        {"where": str(a.resolve()), "side": "a", "quote": "My brother Marek is moving to Valencia next month"},
        {"where": str(b.resolve()), "side": "b", "quote": "Marek Voss, my teammate and friend from the platform team"}]}
    out = _work(bank, path, _session(ra, rb, answer=ans))
    assert out.what == "settled"
    assert not (bank / "entities" / "marek.md").read_text().count("different")          # no page was rewritten
    assert inbox_tend.RULES["found_by_agent"]


def test_a_pair_that_reads_as_one_person_leaves_a_note_on_the_question_and_joins_nothing(bank):
    path = hb.cases("http://x")[8].build(bank, bank, "http://x")
    a = bank / "episodes" / "ep_2026-10-03_001.md"
    ra = ha.Call("1", "Read", "file", str(a.resolve()), result=a.read_text())
    ans = {"status": "cannot_tell", "confidence": 0.8, "why": "one line equates them", "found": "One line calls him by both names.",
           "evidence": [{"where": str(a.resolve()), "quote": "Teodor Brandt, called Teo, starts on the platform team"}],
           "mixed": {"a": ["ep_2026-10-03_001", "ep_not_real"]}}
    out = _work(bank, path, _session(ra, answer=ans))
    assert out.what == "noted" and path.exists()
    fm = markdown_parser.parse(path).frontmatter
    assert fm["agent_found"]["note"].startswith("One line") and fm["agent_found"]["mixed"] == {"a": ["ep_2026-10-03_001"]}
    assert (bank / "entities" / "teo.md").exists() and (bank / "entities" / "teodor-brandt.md").exists()


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
    out = _work(bank, path, _session(_page_call("http://x.test/p", QUOTE), answer=ANSWER))
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


def test_the_browser_window_refuses_anything_but_http_and_has_no_verb_that_acts(tmp_path):
    script = str(ha.BROWSE_SCRIPT)
    env = {**os.environ, "CICADA_BROWSE_HARNESS": str(tmp_path / "missing-harness")}
    run_ = lambda *a: subprocess.run([sys.executable, script, *a], capture_output=True, text=True, env=env)   # noqa: E731
    assert "refused" in run_("open", "file:///etc/hosts").stdout
    assert "refused" in run_("open", "javascript:alert(1)").stdout
    assert run_("status").stdout.startswith("unavailable")                                    # no harness: skipped in words
    assert run_("click", "1,2").returncode == 2 and run_("type", "x").returncode == 2
    source = Path(script).read_text()
    for acting in ("click_at_xy", "type_text", "press_key", "fill_input", "dispatch_key", "upload_file", "goto_url"):
        assert acting not in source, acting

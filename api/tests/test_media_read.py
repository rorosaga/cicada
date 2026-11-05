"""Sleep, or the person's click, reads an added recording's words once for its page's Summary and Why it matters
(ROR-117 / G43, ruling 68): one bounded call, prose only, never over the person's or an agent's words.

Synthetic names and words only; a fake engine stands in for the model.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from _synthetic_bank import _bank, _entity
from api.services import demo_guard, engine_errors, markdown_parser, media_files, media_pages, media_read
from api.services import write_admission
from api.services.sleep_refusal import SleepWriting

WORDS = "We settled the crossing redesign budget on Tuesday. The crossing redesign needs a signal."
SETTINGS = SimpleNamespace(media_read_per_run=5)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    _entity(memory, "crossing-redesign", type="project", confidence=0.9,
            body="## Summary\nThe crossing redesign project plans a new signal for Main Street.\n")
    return memory


def sha(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


def add(bank, n=1, *, words=WORDS, kind="audio", segments=None, **kw):
    segs = segments if segments is not None else ([{"start": 0, "end": 4, "text": words}] if words else [])
    fid = media_files.record_media(bank, name=f"Standup {n}.m4a", kind=kind, sha256=sha(n), size=10, duration_s=65,
                                   language="en", segments=segs, transcribed_by="Speech model A" if segs else None,
                                   **kw)["id"]
    media_pages.sync(bank)
    return fid


def page(bank, fid):
    return markdown_parser.parse(bank / "entities" / f"{media_pages.page_for(bank, fid)}.md")


def reply(summary="The recording covers a budget decision for a street signal.", why="", model="claude-haiku-4-5"):
    return {"model": model, "choices": [{"message": {"content": json.dumps({"summary": summary, "why": why})}}]}


def engine():
    return (SimpleNamespace(llm_mode="agent"), "claude-cli", "ok")


def run(bank, fn, **kw):
    return asyncio.run(media_read.run_tail(bank, SETTINGS, user_triggered=True, llm_fn=fn, engine=engine(), **kw))


def git(bank, *args):
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def counting(answer):
    calls = []

    def fn(messages, **_kw):
        calls.append(messages)
        return answer(messages) if callable(answer) else answer

    fn.calls = calls
    return fn


# --------------------------------------------------------------------------- fills the sections


def test_a_read_fills_the_summary_and_a_why_that_names_a_page_memory_holds(bank):
    fid = add(bank)
    fn = counting(reply(why="It settles the budget of the Crossing Redesign project."))
    report = run(bank, fn)
    assert report.written == 1 and len(fn.calls) == 1
    parsed = page(bank, fid)
    assert media_read.section_text(parsed.body, "Summary") == "The recording covers a budget decision for a street signal."
    assert "Crossing Redesign" in media_read.section_text(parsed.body, "Why it matters")
    record = parsed.frontmatter["media"]["read"]
    assert record["by"] == "claude-haiku-4-5" and record["words"] and "covers_s" not in record
    user = fn.calls[0][1]["content"]
    assert "Crossing Redesign (project)" in user and "Standup 1" in user, "the view names the page the words find"
    assert media_pages.reader(parsed.frontmatter) == "claude-haiku-4-5"
    assert media_pages.transcriber(parsed.frontmatter) == "Speech model A"


def test_a_why_that_names_nothing_memory_holds_stays_empty(bank):
    fid = add(bank)
    run(bank, counting(reply(why="It matters because it is a nice recording about streets.")))
    parsed = page(bank, fid)
    assert media_read.section_text(parsed.body, "Summary")
    assert media_read.section_text(parsed.body, "Why it matters") == ""
    assert "why" not in parsed.frontmatter["media"]["read"]


def test_an_unrelated_recording_gets_a_summary_and_no_why(bank):
    fid = add(bank, words="Remember to water the ferns and move the kettle upstairs. The ferns like morning light.")
    fn = counting(reply("The recording lists household reminders about plants.", why=""))
    run(bank, fn)
    parsed = page(bank, fid)
    assert media_read.section_text(parsed.body, "Why it matters") == ""
    assert "Crossing Redesign" not in fn.calls[0][1]["content"], "the words find nothing, so the view shows nothing"


def test_the_cycles_step_commits_alone_under_the_model_and_leaves_a_dirty_page_to_its_owner(bank, monkeypatch):
    from api.services import sleep_cycle

    fid = add(bank)
    other = bank / "entities" / "crossing-redesign.md"
    other.write_text(other.read_text() + "\nunrelated edit\n")
    before = int(git(bank, "rev-list", "--count", "HEAD").strip())
    settings = SimpleNamespace(media_read_per_run=5)
    orig = media_read.run_tail

    async def with_engine(memory_path, settings_, **kw):
        return await orig(memory_path, settings_, llm_fn=counting(reply()), engine=engine(), **kw)

    monkeypatch.setattr(media_read, "run_tail", with_engine)
    asyncio.run(sleep_cycle._media_read_safely(bank, settings, user_triggered=True))
    rel = f"entities/{media_pages.page_for(bank, fid)}.md"
    assert git(bank, "show", "--name-only", "--format=", "HEAD").split() == [rel]
    assert "Cicada-Author: claude-haiku-4-5" in git(bank, "log", "-1", "--format=%B")
    assert int(git(bank, "rev-list", "--count", "HEAD").strip()) == before + 1
    assert "crossing-redesign" in git(bank, "status", "--porcelain"), "still the owner's, uncommitted"


# --------------------------------------------------------------------------- once per version


def test_the_same_words_are_read_once_and_changed_words_again(bank):
    fid = add(bank)
    fn = counting(reply())
    run(bank, fn)
    run(bank, fn)
    assert len(fn.calls) == 1, "once per version of the words"
    media_files.record_media(bank, name="Standup 1.m4a", kind="audio", sha256=sha(1), size=10, duration_s=65,
                             language="en", transcribed_by="Speech model A",
                             segments=[{"start": 0, "end": 4, "text": WORDS + " A new decision was added."}])
    run(bank, fn)
    assert len(fn.calls) == 2, "a changed transcript is a new version"
    assert page(bank, fid).frontmatter["media"]["read"]["words"]


def test_a_second_run_over_unchanged_words_commits_nothing_and_asks_no_engine(bank):
    add(bank)
    run(bank, counting(reply()))
    picked = []

    def engine_spy(*_a, **_k):
        picked.append(1)

    again = asyncio.run(media_read.run_tail(bank, SETTINGS, user_triggered=True, llm_fn=engine_spy, engine=None))
    assert again.reason == "nothing" and not picked


# --------------------------------------------------------------------------- the person's and agents' words win


def test_a_summary_the_person_wrote_is_never_overwritten_and_no_read_runs_when_both_are_theirs(bank):
    fid = add(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    parsed = markdown_parser.parse(path)
    body = media_read.set_section(media_read.set_section(parsed.body, "Summary", "My own note."),
                                  "Why it matters", "Mine too.")
    markdown_parser.write(path, parsed.frontmatter, body)
    fn = counting(reply())
    report = run(bank, fn)
    assert not fn.calls and report.reason == "nothing"
    assert media_read.section_text(page(bank, fid).body, "Summary") == "My own note."


def test_only_the_section_the_person_left_alone_is_written_and_the_other_stays(bank):
    fid = add(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, media_read.set_section(parsed.body, "Why it matters", "Mine."))
    fn = counting(reply(why="Ties to the Crossing Redesign project."))
    run(bank, fn)
    body = page(bank, fid).body
    assert media_read.section_text(body, "Why it matters") == "Mine."
    assert media_read.section_text(body, "Summary")


def test_an_agents_edit_after_our_write_makes_the_section_theirs_and_a_new_version_leaves_it(bank):
    fid = add(bank)
    run(bank, counting(reply()))
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    parsed = markdown_parser.parse(path)
    edited = parsed.body.replace("The recording covers a budget decision for a street signal.", "An agent's wording.")
    markdown_parser.write(path, parsed.frontmatter, edited)
    media_files.record_media(bank, name="Standup 1.m4a", kind="audio", sha256=sha(1), size=10, duration_s=65,
                             language="en", transcribed_by="Speech model A",
                             segments=[{"start": 0, "end": 4, "text": WORDS + " Something new was said."}])
    fn = counting(reply("Replaced."))
    run(bank, fn)
    assert media_read.section_text(page(bank, fid).body, "Summary") == "An agent's wording."


def test_our_own_earlier_text_is_replaced_when_the_words_change(bank):
    fid = add(bank)
    run(bank, counting(reply("First reading of the words.")))
    media_files.record_media(bank, name="Standup 1.m4a", kind="audio", sha256=sha(1), size=10, duration_s=65,
                             language="en", transcribed_by="Speech model A",
                             segments=[{"start": 0, "end": 4, "text": WORDS + " Something new was said."}])
    run(bank, counting(reply("Second reading of the words.")))
    assert media_read.section_text(page(bank, fid).body, "Summary") == "Second reading of the words."


def test_a_pinned_fix_is_applied_over_what_is_written(bank):
    fid = add(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["corrections"] = [{"old": "street signal", "new": "traffic light"}]
    markdown_parser.write(path, fm, parsed.body)
    run(bank, counting(reply()))
    assert "traffic light" in media_read.section_text(page(bank, fid).body, "Summary")


# --------------------------------------------------------------------------- failures and limits


def test_a_failing_read_changes_nothing_and_is_tried_a_bounded_number_of_times(bank):
    fid = add(bank)
    calls = []

    def boom(messages, **_kw):
        calls.append(1)
        raise RuntimeError("down")

    for _ in range(5):
        run(bank, boom)
        state = media_files.read_state(bank, fid)   # age the failure so the retry delay has passed
        media_files.write_read_state(bank, fid, {**state, "failed_at": (
            datetime.now(timezone.utc) - timedelta(hours=media_read.RETRY_H + 1)).isoformat()})
    assert len(calls) == media_read.MAX_FAILS
    assert media_read.section_text(page(bank, fid).body, "Summary") == ""
    assert "read" not in page(bank, fid).frontmatter["media"]


def test_a_failure_is_not_tried_again_within_the_delay(bank):
    add(bank)
    calls = []

    def boom(messages, **_kw):
        calls.append(1)
        raise RuntimeError("down")

    run(bank, boom)
    run(bank, boom)
    assert len(calls) == 1


def test_an_unusable_answer_is_a_failure_and_writes_nothing(bank):
    fid = add(bank)
    report = run(bank, counting({"model": "m", "choices": [{"message": {"content": "not json at all"}}]}))
    assert report.written == 0 and report.skipped.get("unusable") == 1
    assert media_read.section_text(page(bank, fid).body, "Summary") == ""


def test_a_plan_limit_is_a_pause_not_a_failure(bank):
    fid = add(bank)
    add(bank, 2)

    def limit(messages, **_kw):
        raise engine_errors.EngineThrottled("limit")

    report = run(bank, limit)
    assert report.skipped == {"plan_limit": 1} and report.looked == 1
    assert media_files.read_state(bank, fid).get("fails", 0) == 0


def test_at_most_the_cap_a_run(bank):
    for n in range(1, 5):
        add(bank, n, words=f"Words number {n} about the crossing redesign, said plainly and clearly.")
    fn = counting(reply())
    asyncio.run(media_read.run_tail(bank, SimpleNamespace(media_read_per_run=2), user_triggered=True, llm_fn=fn,
                                    engine=engine()))
    assert len(fn.calls) == 2


def test_a_scheduled_run_off_the_plan_switch_resolves_no_engine(bank, monkeypatch):
    add(bank)

    async def no(settings, *, user_triggered):
        return None, "claude-cli", "scheduled_plan"

    monkeypatch.setattr(media_read, "engine_for", no)
    report = asyncio.run(media_read.run_tail(bank, SETTINGS, user_triggered=False, llm_fn=counting(reply())))
    assert report.reason == "scheduled_plan" and report.written == 0


def test_off_and_demo_read_nothing(bank, monkeypatch):
    add(bank)
    fn = counting(reply())
    off = asyncio.run(media_read.run_tail(bank, SimpleNamespace(media_read_per_run=0), user_triggered=True, llm_fn=fn,
                                          engine=engine()))
    assert off.reason == "off"
    monkeypatch.setattr(demo_guard, "is_demo", lambda _p: True)
    demo = run(bank, fn)
    assert demo.reason == "demo" and not fn.calls


# --------------------------------------------------------------------------- the bound


def test_a_long_recording_is_read_from_the_start_and_the_page_says_how_much(bank):
    segs = [{"start": i * 10, "end": i * 10 + 9, "text": ("alpha beta gamma " * 20).strip() + f" {i}"}
            for i in range(0, 360)]       # one hour, about 120,000 characters
    fid = add(bank, segments=segs)
    fn = counting(reply())
    run(bank, fn)
    sent = fn.calls[0][1]["content"]
    assert len(sent) < media_read.READ_CHARS + 2_500, "one bounded call"
    body = media_read.section_text(page(bank, fid).body, "Summary")
    assert body.endswith("Read from the first 9 minutes.") or "Read from the first" in body
    record = page(bank, fid).frontmatter["media"]["read"]
    assert 0 < record["covers_s"] < 3600
    assert "only (the rest is not shown)" in sent


def test_a_short_recording_makes_no_claim_about_coverage(bank):
    fid = add(bank)
    run(bank, counting(reply()))
    assert "Read from the first" not in media_read.section_text(page(bank, fid).body, "Summary")


# --------------------------------------------------------------------------- no words, no read


def test_an_item_with_no_words_gets_no_read(bank):
    fid = add(bank, words="", kind="image")
    fn = counting(reply())
    assert run(bank, fn).reason == "nothing" and not fn.calls
    assert media_read.section_text(page(bank, fid).body, "Summary") == ""


def test_text_read_off_a_picture_counts_as_words(bank):
    fid = add(bank, words="", kind="video")
    import struct

    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 360, 640) + b"\x03" + b"\x00" * 9
    media_files.record_frames(bank, fid, [(3.0, b"\xff\xd8" + app0 + sof0 + b"\xff\xd9")])
    media_files.record_frame_text(bank, fid, [(3.0, "Quarterly crossing redesign review")])
    fn = counting(reply())
    run(bank, fn)
    assert len(fn.calls) == 1 and "on screen" in fn.calls[0][1]["content"]


# --------------------------------------------------------------------------- the rails


def test_a_held_value_never_reaches_the_page(bank):
    from api.config import Settings
    from api.services import providers

    value = "Zebra7-lantern"
    fid = add(bank, words=f"my password is {value} for the vault. The vault hosts crossing redesign files.")
    seen = []

    def completion(**kw):
        seen.append(json.dumps(kw["messages"]))
        text = kw["messages"][-1]["content"]
        # A model that repeats whatever stands where the value was: the door's mark, never the value.
        echoed = text[text.index("password"):][:40].replace("\n", " ")
        return {"model": "claude-haiku-4-5", "choices": [{"message": {"content": json.dumps(
            {"summary": f"The recording says {echoed}. It is about a shared vault.", "why": ""})}}]}

    settings = Settings(CICADA_MEMORY_ROOT=bank, llm_mode="byok", litellm_model="fake-engine")
    fn = providers.resolve_llm_fn(settings, stage="media_read", is_async=False, completion=completion)
    run(bank, fn)
    assert seen and not any(value in s for s in seen), "the door held it back from the engine"
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    assert value not in path.read_text() and "[held back" not in path.read_text()
    assert media_read.section_text(page(bank, fid).body, "Summary"), "the summary is written without the mark"


def test_the_read_writes_no_claim_no_episode_no_question_and_no_other_page(bank):
    add(bank)
    before = {p.name: p.read_bytes() for d in ("entities", "episodes", "inbox") for p in (bank / d).glob("*.md")}
    run(bank, counting(reply(why="Ties to the Crossing Redesign project.")))
    after = {p.name: p.read_bytes() for d in ("entities", "episodes", "inbox") for p in (bank / d).glob("*.md")}
    changed = {n for n in after if before.get(n) != after[n]}
    assert len(changed) == 1 and next(iter(changed)).startswith("file-")
    parsed = markdown_parser.parse(bank / "entities" / next(iter(changed)))
    assert "```claims" not in parsed.body and parsed.frontmatter["source_episodes"] == []
    assert "[[" not in parsed.body


def test_the_model_is_called_only_through_the_one_door():
    import inspect

    source = inspect.getsource(media_read)
    assert "litellm" not in source and "acompletion" not in source and "anthropic" not in source.replace(
        "anthropic_engine", "")
    assert "providers.resolve_llm_fn" in source


# --------------------------------------------------------------------------- the click


def click(bank, fid, fn, **kw):
    return asyncio.run(media_read.read_now(bank, SETTINGS, fid, llm_fn=fn, engine=engine(), **kw))


def test_the_click_runs_the_same_read_and_commits_it_alone(bank):
    fid = add(bank)
    before = int(git(bank, "rev-list", "--count", "HEAD").strip())
    out = click(bank, fid, counting(reply(why="Ties to the Crossing Redesign project.")))
    assert out["summary"] is True and out["why"] is True
    assert media_read.section_text(page(bank, fid).body, "Summary")
    assert int(git(bank, "rev-list", "--count", "HEAD").strip()) == before + 1
    assert git(bank, "show", "--name-only", "--format=", "HEAD").split() == [f"entities/{media_pages.page_for(bank, fid)}.md"]
    assert "Cicada-Author: claude-haiku-4-5" in git(bank, "log", "-1", "--format=%B")


def test_the_click_is_refused_while_sleep_runs_and_calls_no_engine(bank, monkeypatch):
    fid = add(bank)
    monkeypatch.setattr(write_admission, "holding", lambda: True)
    fn = counting(reply())
    with pytest.raises(SleepWriting):
        click(bank, fid, fn)
    assert not fn.calls


def test_the_click_is_refused_on_a_demo_bank_and_for_nothing_to_read(bank, monkeypatch):
    fid = add(bank)
    empty = add(bank, 2, words="", kind="image")
    with pytest.raises(media_read.Refused) as nothing:
        click(bank, empty, counting(reply()))
    assert nothing.value.status == 404
    monkeypatch.setattr(demo_guard, "is_demo", lambda _p: True)
    with pytest.raises(media_read.Refused) as demo:
        click(bank, fid, counting(reply()))
    assert demo.value.status == 409


def test_the_click_never_overwrites_a_summary_that_is_not_ours(bank):
    fid = add(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, media_read.set_section(parsed.body, "Summary", "Mine."))
    with pytest.raises(media_read.Refused):
        click(bank, fid, counting(reply()))
    assert media_read.section_text(page(bank, fid).body, "Summary") == "Mine."


def test_the_click_reports_a_plan_limit_in_words(bank):
    fid = add(bank)

    def limit(messages, **_kw):
        raise engine_errors.EngineExhausted("limit")

    with pytest.raises(media_read.Refused) as out:
        click(bank, fid, limit)
    assert out.value.status == 429 and "limit" in out.value.message


# --------------------------------------------------------------------------- the pieces


def test_the_section_writer_keeps_the_other_section_and_the_heading_shape():
    body = "## Summary\n\n## Why it matters\n"
    once = media_read.set_section(body, "Summary", "One.")
    assert once == "## Summary\n\nOne.\n\n## Why it matters\n"
    both = media_read.set_section(once, "Why it matters", "Two.")
    assert both == "## Summary\n\nOne.\n\n## Why it matters\n\nTwo.\n"
    assert media_read.set_section(both, "Why it matters", "") == "## Summary\n\nOne.\n\n## Why it matters\n\n"


def test_an_answer_with_a_link_a_heading_or_the_held_mark_is_refused():
    c = SimpleNamespace(writable={"Summary", "Why it matters"}, memory=[("Crossing Redesign", "x")], covered_s=None)
    for bad in ("See [[Crossing Redesign]] for more.", "# Heading", "- a list"):
        assert media_read.decide(c, {"summary": bad, "why": ""})[2] is False
    assert media_read.decide(c, {"summary": "A fine summary [held back: password] here.", "why": ""})[0] \
        == "A fine summary here."
    assert media_read.decide(c, {"summary": "A fine summary.", "why": "[[Crossing Redesign]] link."})[1] is None


# --------------------------------------------------------------------------- the route


def _client(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import image_index

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    monkeypatch.setattr(image_index, "start_refresh", lambda mp, **kw: True)
    monkeypatch.setattr(media_pages, "start_sync", lambda mp, **kw: True)
    return TestClient(main.app)


def test_the_route_answers_the_usual_refusals_and_reads_through_the_click(bank, monkeypatch):
    c = _client(bank, monkeypatch)
    with c:
        fid = add(bank)
        assert c.post("/files/0123456789abcdef/read").status_code == 404
        with monkeypatch.context() as sleeping:
            sleeping.setattr(write_admission, "holding", lambda: True)
            busy = c.post(f"/files/{fid}/read")
        assert busy.status_code == 409 and "Sleep" in busy.text
        seen = {}

        async def fake(memory_path, settings, file_id, **kw):
            seen["id"] = file_id
            return {"id": "page", "summary": True, "why": False}

        monkeypatch.setattr(media_read, "read_now", fake)
        done = c.post(f"/files/{fid}/read")
        assert done.status_code == 200 and seen["id"] == fid and done.json()["summary"] is True
        monkeypatch.setattr(demo_guard, "is_demo", lambda _p: True)
        assert c.post(f"/files/{fid}/read").status_code == 409

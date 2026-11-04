"""G235: Sleep tells the person what may be sensitive, and which engine read it; the person can take it out.

End to end through Sleep's real loader, Stage 1's real ``extract`` and Stage 3's claim write, with the model's answer
faked (`litellm.acompletion`) so it can repeat the value on purpose. The canaries are made up. They go through every door:
the prompt (a confident one never, ruling 60), the app's wire, logs, commits, telemetry, the inbox, claims and pages."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from loguru import logger

from api.config import Settings
from api.models.schemas import InboxResolveRequest
from api.services import (bank_index, demo_guard, entity_extractor, episode_revision, episode_staging, evidence,
                          inbox_catchup, inbox_service, markdown_parser, mcp_tools, revision_prose, search_index,
                          sensitive_flags as sf, sensitive_text as st, sleep_cycle, sleep_drain, sleep_runs,
                          transcript_capture)
from api.services.episode_scrub import REDACTED
from api.services.claims import parse_claims
from api.services.transcript_extract import Conversation, Turn
from api.tests.test_sleep_cycle_hold import _bank, _patch, _settings

CANARY = "Zebra7-lantern"
EP = "ep_2026-11-01_001"
BODY = f"user: alpha-project is on Friday. my password is {CANARY}\nassistant: Noted, I will not repeat it."
#: Letters only: it may be a word, so the engine reads it and the person is told (ruling 60).
UNSURE = "lanternfish"
UNSURE_BODY = f"user: alpha-project is on Friday. my password is {UNSURE}.\nassistant: Noted, I will not repeat it."


def _git(memory, *args) -> str:
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=memory,
                          check=True, capture_output=True, text=True).stdout


def _episode(memory, *, body=BODY, ep=EP, **fm):
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": False, "source": "chatgpt", "origin": "chatgpt", "title": "Plans",
                           "timestamp": "2026-11-01T10:00:00Z", "content_hash": episode_staging.content_hash(body), **fm},
                          body)


def _answer(chunk: str) -> dict:
    """A careless model: whatever it was shown, it writes down."""
    ents = [{"name": "alpha-project", "type": "project", "confidence": 0.9, "summary": "A synthetic project."}]
    vals = []
    if "on Friday" in chunk:
        vals.append({"entity": "alpha-project", "attribute": "day", "value": "Friday", "evidence_quote": "is on Friday"})
    for secret in (CANARY, UNSURE):
        if secret not in chunk:
            continue
        vals.append({"entity": "alpha-project", "attribute": "login", "value": "has one",
                     "evidence_quote": f"my password is {secret}"})
        ents[0]["summary"] += f" Its password is {secret}."
        ents[0]["key_facts"] = [f"password {secret}"]
        ents.append({"name": secret, "type": "concept", "confidence": 0.9, "summary": "x"})
        vals.append({"entity": "alpha-project", "attribute": "password", "value": secret, "evidence_quote": secret})
    return {"entities": ents, "relationships": [], "values": vals}


def _sleep(memory, monkeypatch, prompts=None):
    prompts = prompts if prompts is not None else []

    async def fake_acompletion(**kw):
        content = kw["messages"][1]["content"]
        prompts.append(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_answer(content))))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", CICADA_MEMORY_ROOT=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)
    bank_index.invalidate()
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g235"))
    bank_index.invalidate()
    # Sleep's own commit is stubbed in `_patch`: the test commits as it would.
    if (memory / ".git").exists():
        _git(memory, "add", "-A")
        _git(memory, "commit", "-qm", "Sleep cycle", "--allow-empty")
    return prompts


@pytest.fixture
def memory(tmp_path):
    bank = _bank(tmp_path)
    markdown_parser.write(bank / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.9},
                          "## Summary\nalpha-project is a synthetic project.\n")
    _git(bank, "init", "-q")
    return bank


def _commit(memory, message="capture"):
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", message)


def _review(memory):
    bank_index.invalidate()
    items = [f for f in sorted((memory / "inbox").glob("inbox-*.md"))
             if markdown_parser.parse(f).frontmatter.get("kind") == sf.KIND]
    return items


def _settings_for(memory):
    return SimpleNamespace(memory_path=memory, inbox_defer_days=30, litellm_model="test-model", inbox_stale_after_days=90)


def _resolve(memory, item_path, key, row=None, **kw):
    request = InboxResolveRequest(action="resolve", option_key=key, row=row, **kw)
    out = asyncio.run(inbox_service.resolve(item_path.stem, request, _settings_for(memory)))
    if sf._cleanup is not None:
        sf._cleanup.join(timeout=60)
    bank_index.invalidate()
    return out


def _everything_but_the_conversation(memory) -> dict[str, str]:
    out = {}
    for path in Path(memory).rglob("*"):
        if not path.is_file() or ".git" in path.parts or "episodes" in path.parts:
            continue
        try:
            out[path.relative_to(memory).as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return out


# ------------------------------------------------------------------------------ report only (the default)


def test_an_unsure_hit_the_engine_reads_the_review_says_so_and_nothing_repeats_it(memory, monkeypatch, capfd):
    _episode(memory, body=UNSURE_BODY)
    _commit(memory)
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    prompts = _sleep(memory, monkeypatch)
    logger.remove(sink)

    assert any(UNSURE in p for p in prompts)                     # unsure: the engine did read it. That is the point.
    # the record: kinds and the engine, nothing of the value and no hash of it
    fm = markdown_parser.parse(memory / "episodes" / f"{EP}.md").frontmatter
    (read,) = fm[sf.KEY]["read"]
    assert read["kinds"] == {"password": 1} and read["engine"] == "litellm" and not read.get("held")
    assert UNSURE not in json.dumps(fm)
    # one review, one row: which conversation, what kind, which engine
    (item,) = _review(memory)
    wire = next(i for i in inbox_service.load_inbox(memory) if i.id == item.stem)
    (row,) = wire.sensitive_rows
    assert (row.episode, row.title, row.kinds, row.read_by, row.day) == (EP, "Plans", ["password"], ["your API key"],
                                                                         "2026-11-01")
    # no door repeats it: pages, claims, the inbox, every file beside the conversation
    for rel, text in _everything_but_the_conversation(memory).items():
        assert UNSURE not in text, rel
    page = (memory / "entities" / "alpha-project.md").read_text()
    assert "Friday" in page                                       # the rest of the line's memory is kept
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
    assert not any(UNSURE in f"{c.text} {c.object}" for c in claims)
    assert not (memory / "entities" / f"{UNSURE.lower()}.md").exists()
    # logs, commits, the wire, and every file outside the bank (telemetry, run summaries)
    assert not any(UNSURE in line for line in logs)
    assert UNSURE not in "".join(capfd.readouterr())
    assert UNSURE not in _git(memory, "log", "--format=%B")
    assert UNSURE not in wire.model_dump_json()
    home = Path(os.environ["CICADA_HOME"])
    for path in home.rglob("*"):
        if path.is_file() and path.stat().st_size < 5_000_000:
            assert UNSURE.encode() not in path.read_bytes(), path.name


def test_a_title_holding_the_value_is_never_shown(memory, monkeypatch):
    _episode(memory, title=f"my password is {CANARY}")
    _commit(memory)
    _sleep(memory, monkeypatch)
    (item,) = _review(memory)
    assert CANARY not in item.read_text()
    (row,) = next(i for i in inbox_service.load_inbox(memory) if i.id == item.stem).sensitive_rows
    assert row.title == "my password is •••"


@pytest.mark.parametrize("title,shown", [
    ("Plans", "Plans"),
    (f"alpha ships. my password is {CANARY} for the st…", "alpha ships. my password is ••• for the st…"),
    (f"alpha ships. my password is {CANARY[:9]}…", "alpha ships. my password is •••…"),
    ("alpha ships. my password is Z…", "alpha ships. my password is •••"),
    (CANARY, "A conversation"),
    ("", "A conversation"),
])
def test_a_rows_title_never_holds_any_of_the_value(title, shown):
    hits = st.find(BODY)
    assert sf.safe_title({"title": title}, BODY, hits) == shown


def test_a_title_cut_through_the_value_goes_on_removal_and_never_reaches_an_agents_primer(memory, monkeypatch):
    from api.services import state_dictionary

    cut = f"alpha ships. my password is {CANARY[:9]}…"
    _episode(memory, title=cut, processed=True, processed_by="sleep", session_id="s-title", harness="cursor",
             capture_kind="transcript", source="cursor", last_seen="2026-11-01T10:00:00Z")
    _commit(memory)
    bank_index.invalidate()
    assert CANARY[:9] not in sf.title_for_others(cut) and "alpha ships" in sf.title_for_others(cut)
    for row in state_dictionary._conversations(memory, 5):
        assert CANARY[:9] not in row["title"]
    sf.remove_episode(memory, EP)
    title = markdown_parser.parse(memory / "episodes" / f"{EP}.md").frontmatter["title"]
    assert CANARY[:9] not in title and "alpha ships" in title


def test_a_conversation_with_only_code_talk_raises_nothing(memory, monkeypatch):
    _episode(memory, body="user: the password is required and the token is stored hashed\n"
                          "assistant: The password is Kp92mQzxL in the fixture.", harness="claude-code",
             source="claude-code", capture_kind="transcript")
    _commit(memory)
    _sleep(memory, monkeypatch)
    assert _review(memory) == []
    assert sf.KEY not in markdown_parser.parse(memory / "episodes" / f"{EP}.md").frontmatter


def test_many_conversations_are_one_item_never_one_question_each(memory, monkeypatch):
    for i in range(1, 6):
        _episode(memory, ep=f"ep_2026-11-01_00{i}", body=f"user: my password is Secre7word{i}")
    _commit(memory)
    _sleep(memory, monkeypatch)
    (item,) = _review(memory)
    assert len(markdown_parser.parse(item).frontmatter["rows"]) == 5


def test_the_run_summary_says_how_many_across_its_legs_and_carries_no_word(memory):
    ds = sleep_drain.DrainState(drain_id="d1")
    ds.sensitive = {EP: ["password"]}
    ds.replaced_ids = {"ep_2026-11-01_002"}
    summary = sleep_runs.record_leg(memory, ds, state="paused")
    ds2 = sleep_drain.DrainState(drain_id="d1")   # a Continue is a new leg
    ds2.sensitive = {"ep_2026-11-01_003": ["card", "password"]}
    summary = sleep_runs.record_leg(memory, ds2, state="finished")
    assert sleep_runs.to_run_ref(summary)["sensitive"] == {"conversations": 2, "kinds": ["password", "card"]}
    assert summary["replaced_ids"] == ["ep_2026-11-01_002"]
    assert CANARY not in json.dumps(summary)
    quiet = sleep_runs.record_leg(memory, sleep_drain.DrainState(drain_id="d2"), state="finished")
    assert sleep_runs.to_run_ref(quiet)["sensitive"] is None


def test_a_drain_counts_what_its_batches_read(memory, monkeypatch):
    _episode(memory)
    _episode(memory, ep="ep_2026-11-01_002", body=f"user: a key was {REDACTED} there")
    _commit(memory)
    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])
    prompts: list[str] = []

    async def fake_acompletion(**kw):
        prompts.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_answer(prompts[-1]))))])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", memory_path=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)
    bank_index.invalidate()
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g235_drain", drain=True))
    runs = sleep_runs.all_runs(memory)
    assert runs, "a drain records a run"
    summary = next(iter(runs.values()))
    assert sleep_runs.to_run_ref(summary)["sensitive"] == {"conversations": 1, "kinds": ["password"]}
    assert summary["replaced_ids"] == ["ep_2026-11-01_002"]
    assert CANARY not in json.dumps(summary)


# ------------------------------------------------------------------------------ held back (ruling 60)


def test_a_confident_hit_the_engine_reads_a_typed_mark_and_the_stored_body_is_untouched(memory, monkeypatch):
    _episode(memory)
    _commit(memory)
    prompts = _sleep(memory, monkeypatch)
    assert prompts and not any(CANARY in p for p in prompts)
    assert any("[held back: password]" in p for p in prompts)
    parsed = markdown_parser.parse(memory / "episodes" / f"{EP}.md")
    assert parsed.body == BODY and parsed.frontmatter["processed"] is True
    (read,) = parsed.frontmatter[sf.KEY]["read"]
    assert read["held"] == {"password": 1}
    (item,) = _review(memory)
    (row,) = next(i for i in inbox_service.load_inbox(memory) if i.id == item.stem).sensitive_rows
    assert row.held_kinds == ["password"] and row.held_from == ["your API key"] and row.read_by == []
    for rel, text in _everything_but_the_conversation(memory).items():
        assert CANARY not in text, rel
    # the memory the rest of the line holds survives, with a span on the stored body
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
    friday = next(c for c in claims if c.object == "Friday")
    (ev,) = friday.evidence
    assert BODY[ev.start:ev.end] == "is on Friday"


def test_a_conversation_holding_both_says_which_was_read_and_which_was_not(memory, monkeypatch):
    _episode(memory, body=f"user: my password is {CANARY}\nuser: and my other password is {UNSURE}.")
    _commit(memory)
    prompts = _sleep(memory, monkeypatch)
    assert any(UNSURE in p for p in prompts) and not any(CANARY in p for p in prompts)
    (item,) = _review(memory)
    (row,) = next(i for i in inbox_service.load_inbox(memory) if i.id == item.stem).sensitive_rows
    assert row.kinds == ["password"] and row.read_by == ["your API key"]    # the same kind, one of each: it was read


# ------------------------------------------------------------------------------ remove


def _slept(memory, monkeypatch, body=BODY):
    _episode(memory, body=body)
    _commit(memory)
    _sleep(memory, monkeypatch)
    (item,) = _review(memory)
    return item


def test_remove_takes_it_out_of_memory_and_git_history_keeps_the_old_version(memory, monkeypatch):
    # An older page that repeated it, written before this existed: a claim, prose and a ledger line.
    item = _slept(memory, monkeypatch)
    page = memory / "entities" / "alpha-project.md"
    page.write_text(page.read_text() + f"\nOld note: the password {CANARY} was mentioned.\n")
    (memory / "entities" / "alpha-project.claims.jsonl").write_text(json.dumps({"object": CANARY}) + "\n")
    (memory / "hubs").mkdir(exist_ok=True)
    (memory / "hubs" / "h.md").write_text(f"{CANARY}\n")
    _commit(memory, "older writes")

    assert _resolve(memory, item, sf.REMOVE)["status"] == "resolved"

    parsed = markdown_parser.parse(memory / "episodes" / f"{EP}.md")
    assert CANARY not in parsed.body and "[removed: password]" in parsed.body
    assert "is on Friday" in parsed.body                                   # only the value goes
    assert parsed.frontmatter["processed"] is False and "processed_by" not in parsed.frontmatter
    assert parsed.frontmatter["revised"]["count"] == 1                     # the revision path, not a second one
    assert parsed.frontmatter[sf.KEY]["removed"]["kinds"] == ["password"]
    for rel, text in _everything_but_the_conversation(memory).items():
        assert CANARY not in text, rel
    assert "[removed: password]" in page.read_text()
    assert _review(memory) == []
    # committed alone, as the person's, with nothing of the value in the message
    message = _git(memory, "log", "-1", "--grep=^Inbox resolution (sensitive)", "--format=%B")
    assert "Cicada-Author: user" in message and CANARY not in _git(memory, "log", "--format=%B")
    assert CANARY not in _git(memory, "show", "HEAD:episodes/" + EP + ".md")
    # git history is never rewritten: the older version is still there, which the copy says plainly
    assert CANARY in _git(memory, "log", "-p", "--format=", "--", f"episodes/{EP}.md")


def test_after_remove_sleep_reads_it_as_a_revision_with_no_call_and_never_resends_it(memory, monkeypatch):
    item = _slept(memory, monkeypatch, body=UNSURE_BODY)
    _resolve(memory, item, sf.REMOVE)
    prompts = _sleep(memory, monkeypatch)
    assert prompts == []
    fm = markdown_parser.parse(memory / "episodes" / f"{EP}.md").frontmatter
    assert fm["processed"] is True and not fm[sf.KEY]["removed"].get("pending")
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
    # A claim citing the removed words is closed, by a record, never deleted (G118: its span now reads stale)...
    login = next(c for c in claims if c.object == "has one")
    assert login.valid_to is not None and login.superseded_by
    # ...and one citing other words on the same line stands, its span moved onto the new body.
    friday = next(c for c in claims if c.object == "Friday")
    assert friday.valid_to is None
    body = evidence.source_text(memory, EP)
    (ev,) = [e for e in friday.evidence if e.is_span() and e.hash == "sha256:" + evidence.body_hash(body)] or friday.evidence
    assert body[ev.start:ev.end] == "is on Friday"
    assert not any(UNSURE in f"{c.text} {c.object}" for c in claims)


def test_what_a_revision_sends_a_model_never_holds_a_value():
    prior = f"user: notes\nmy password is {CANARY}\nthe review is on Friday"
    body = "user: notes\nmy password is [removed: password]\nthe review is on Friday"
    rev = episode_revision.build({"id": EP, "content": body}, prior)
    assert revision_prose.changes_of(rev) == []                            # nothing but the value went
    prior2 = f"user: notes\nmy password is {CANARY}\nthe review is on Friday"
    body2 = "user: notes\nthe review is on Friday"
    rev2 = episode_revision.build({"id": EP, "content": body2}, prior2)
    (change,) = revision_prose.changes_of(rev2)
    assert CANARY not in change.before and not any(CANARY.lower() in w.lower() for w in change.gone)


def test_only_a_removal_needs_no_window_but_a_new_line_beside_it_does():
    record = {"removed": {"kinds": ["password"], "pending": True}}
    prior = f"user: notes\nmy password is {CANARY}\nend"
    only = "user: notes\nmy password is [removed: password]\nend"
    rev = episode_revision.build({"id": EP, "content": only, sf.KEY: record}, prior)
    assert rev.windows == () and rev.closes
    more = only + "\nuser: a new line"
    rev2 = episode_revision.build({"id": EP, "content": more, sf.KEY: record}, prior)
    assert rev2.windows and CANARY not in "".join(more[a:b] for a, b in rev2.windows)
    # a transcript closes on the person's removal, and on nothing else
    rev3 = episode_revision.build({"id": EP, "content": only, sf.KEY: record, "capture_kind": "transcript"}, prior)
    assert rev3.closes
    rev4 = episode_revision.build({"id": EP, "content": only, "capture_kind": "transcript"}, prior)
    assert not rev4.closes


def test_offsets_move_with_the_removal():
    body = f"user: my password is {CANARY}\nassistant: ok\nuser: bye"
    second = body.index("assistant:")
    third = body.index("user: bye")
    fm = {"id": EP, "turns": [{"offset": 0, "ts": None, "speaker": "user"}, {"offset": second, "speaker": "assistant"},
                              {"offset": third, "speaker": "user"}], "capture_gap": {"offset": third},
          "content_hash": "x"}
    hits = st.find(body)
    new_fm, new_body, marks = sf._take_out(fm, body, hits, {"password"}, at="2026-11-04T00:00:00Z", pending=True)
    (a, b, c) = new_fm["turns"]
    assert a["offset"] == 0 and new_body[b["offset"]:].startswith("assistant:") and new_body[c["offset"]:] == "user: bye"
    assert new_body[new_fm["capture_gap"]["offset"]:] == "user: bye"
    assert list(new_fm)[-1] == "turns"
    assert marks == {CANARY: "[removed: password]"}


def test_a_source_sending_it_again_never_brings_it_back_and_an_unchanged_one_is_not_requeued(memory, monkeypatch):
    drafts = lambda extra="": [episode_staging.EpisodeDraft(  # noqa: E731
        title="Note", source_id="note:1", timestamp="2026-11-01T10:00:00Z", source="apple-notes", origin="apple-notes",
        body=f"my password is {CANARY}" + extra, writer="apple-notes", extra={"evidence_kind": "user"})]
    episodes = memory / "episodes"
    result = episode_staging.stage(drafts(), episodes, bank="t")
    ep = result.episode_ids["note:1"]
    path = episodes / f"{ep}.md"
    fm = dict(markdown_parser.parse(path).frontmatter)
    fm["processed"], fm["processed_by"] = True, "sleep"
    markdown_parser.write(path, fm, markdown_parser.parse(path).body)
    _commit(memory)
    bank_index.invalidate()

    sf.remove_episode(memory, ep)
    after = markdown_parser.parse(path)
    assert CANARY not in after.body
    fm = dict(after.frontmatter)
    fm["processed"], fm["processed_by"] = True, "sleep"     # Sleep read the revision
    markdown_parser.write(path, fm, after.body)
    bank_index.invalidate()

    again = episode_staging.stage(drafts(), episodes, bank="t")
    assert again.skipped == 1 and again.updated == 0
    assert markdown_parser.parse(path).frontmatter["processed"] is True

    bank_index.invalidate()
    edited = episode_staging.stage(drafts("\nand something new"), episodes, bank="t")
    assert edited.updated == 1
    parsed = markdown_parser.parse(path)
    assert CANARY not in parsed.body and "something new" in parsed.body and "[removed: password]" in parsed.body


def test_a_resumed_session_never_brings_it_back(memory):
    def conv(*more):
        return Conversation(harness="claude-code", session_id="s1", cwd=None, started_at="2026-11-01T10:00:00Z",
                            ended_at=None, turns=[Turn("user", f"my password is {CANARY}", "2026-11-01T10:00:00Z"),
                                                  Turn("assistant", "ok", "2026-11-01T10:00:05Z"), *more],
                            summary={"kept": {"user": 1, "assistant": 1}})

    kw = dict(harness="claude-code", session_id="s1", cwd=None, bank="t", effort=None, bank_paths=None, hook_event=None,
              registry_workspace=None)
    created = transcript_capture.write_session(memory, conv=conv(), existing=None, **kw)
    path = memory / "episodes" / f"{created.episode_id}.md"
    sf.remove_episode(memory, created.episode_id)
    parsed = markdown_parser.parse(path)
    assert CANARY not in parsed.body
    # the next Stop hook rebuilds the body from the transcript, which still says it
    same = transcript_capture.write_session(memory, conv=conv(), existing=path, **kw)
    assert same.status in ("unchanged", "metadata")
    more = transcript_capture.write_session(memory, conv=conv(Turn("user", "and another thing", "2026-11-01T10:01:00Z")),
                                            existing=path, **kw)
    assert more.status == "updated"
    parsed = markdown_parser.parse(path)
    assert CANARY not in parsed.body and "another thing" in parsed.body and "[removed: password]" in parsed.body
    stamps = evidence.turn_stamps(parsed.frontmatter)
    assert parsed.body[max(stamps):].startswith("user: and another thing")


def test_any_other_writer_bringing_it_back_is_caught_before_the_read(memory, monkeypatch):
    item = _slept(memory, monkeypatch)
    _resolve(memory, item, sf.REMOVE)
    path = memory / "episodes" / f"{EP}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, dict(parsed.frontmatter), BODY + "\nuser: and a new line")
    prompts = _sleep(memory, monkeypatch)
    assert prompts and not any(CANARY in p for p in prompts)
    assert CANARY not in markdown_parser.parse(path).body


def test_the_word_index_forgets_it(memory, monkeypatch):
    item = _slept(memory, monkeypatch)
    search_index.rebuild(memory)
    assert EP in (search_index.episodes_with_words(memory, CANARY.split("-")[0]) or set())
    _resolve(memory, item, sf.REMOVE)
    assert EP not in (search_index.episodes_with_words(memory, CANARY.split("-")[0]) or set())
    # Not only unsearchable: gone from the file. A dropped table's bytes would stay readable in place.
    raw = (search_index.db_path(memory)).read_bytes()
    assert CANARY.split("-")[0].encode() not in raw and b"zebra7" not in raw


# ------------------------------------------------------------------------------ leave it, and who may answer


def test_leave_it_remembers_and_only_a_new_one_asks_again(memory, monkeypatch):
    item = _slept(memory, monkeypatch)
    _resolve(memory, item, sf.KEEP)
    path = memory / "episodes" / f"{EP}.md"
    parsed = markdown_parser.parse(path)
    assert parsed.body == BODY and parsed.frontmatter[sf.KEY]["kept"] == {"password": 1}
    assert _review(memory) == []
    assert "Cicada-Author: user" in _git(memory, "log", "-1", "--grep=^Inbox resolution (sensitive)", "--format=%B")
    sf.sync_review(memory)
    assert _review(memory) == []
    markdown_parser.write(path, dict(parsed.frontmatter), BODY + "\nuser: and my password is Second9value")
    bank_index.invalidate()
    sf.sync_review(memory)
    assert len(_review(memory)) == 1


def test_a_wrong_alarm_left_alone_stops_costing_its_word_on_the_pages(memory, monkeypatch):
    """A flagged value is taken out of what a model wrote, so a wrong alarm loses that word on the pages (the conversation
    keeps it). Once the person leaves it, a later read keeps it."""
    item = _slept(memory, monkeypatch)
    assert CANARY not in (memory / "entities" / "alpha-project.md").read_text()
    _resolve(memory, item, sf.KEEP)
    path = memory / "episodes" / f"{EP}.md"
    parsed = markdown_parser.parse(path)
    fm = {**parsed.frontmatter, "processed": False}
    fm.pop("processed_by", None)
    markdown_parser.write(path, fm, parsed.body)     # read again, as a resumed session or an edit would
    prompts = _sleep(memory, monkeypatch)
    assert any(CANARY in p for p in prompts)         # left alone means not held back either
    assert CANARY in (memory / "entities" / "alpha-project.md").read_text()
    assert _review(memory) == []


def test_one_row_answered_leaves_the_others(memory, monkeypatch):
    _episode(memory)
    _episode(memory, ep="ep_2026-11-01_002", body="user: my password is Second9value")
    _commit(memory)
    _sleep(memory, monkeypatch)
    (item,) = _review(memory)
    rows = markdown_parser.parse(item).frontmatter["rows"]
    _resolve(memory, item, sf.KEEP, row=rows[0]["id"])
    (item,) = _review(memory)
    assert [r["id"] for r in markdown_parser.parse(item).frontmatter["rows"]] == [rows[1]["id"]]


def test_an_agent_can_neither_see_nor_answer_it(memory, monkeypatch):
    item = _slept(memory, monkeypatch)
    for kw in ({"via": "agent"}, {"relayed_by": "claude-code"}, {"quote": "yes remove it"}):
        request = InboxResolveRequest(action="resolve", option_key=sf.REMOVE, **kw)
        with pytest.raises(HTTPException) as err:
            asyncio.run(inbox_service.resolve(item.stem, request, _settings_for(memory)))
        assert err.value.status_code == 403
    assert CANARY in markdown_parser.parse(memory / "episodes" / f"{EP}.md").body
    assert sf.KIND in mcp_tools.APP_ONLY_INBOX_KINDS and sf.KIND in inbox_catchup.NEVER


def test_a_saved_page_is_someone_elses_words_and_never_flagged(memory, monkeypatch):
    _episode(memory, body=f"the password is {CANARY}", source="bookmark", origin="bookmark", url="https://example.com/a")
    _commit(memory)
    _sleep(memory, monkeypatch)
    assert _review(memory) == []


# ------------------------------------------------------------------------------ what was read before this existed


def test_the_sweep_reports_conversations_already_read_and_writes_nothing_on_them(memory):
    done = {"processed": True, "processed_by": "sleep"}
    _episode(memory, **done)
    _episode(memory, ep="ep_2026-11-01_002", body="user: nothing here", **done)
    _episode(memory, ep="ep_2026-11-01_003", body="user: a key was [redacted] there", **done)
    _episode(memory, ep="ep_2026-11-01_004", body="user: my password is Second9value")   # waits: flagged when read
    _commit(memory)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in (memory / "episodes").glob("*.md")}
    bank_index.invalidate()

    out = sf.sweep_read(memory)
    assert out["episodes"] == [EP] and out["replaced"] == 1
    assert CANARY not in json.dumps(out)
    report = sf.sync_review(memory)
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in (memory / "episodes").glob("*.md")}
    assert report.rows == 1
    (item,) = _review(memory)
    wire = next(i for i in inbox_service.load_inbox(memory) if i.id == item.stem)
    (row,) = wire.sensitive_rows
    assert row.earlier is True and row.read_by == []                       # which engine is omitted, not guessed
    assert wire.replaced == 1
    assert CANARY not in item.read_text()
    # once per detector version: a later run does not read every body again
    calls = []
    monkeypatch_files = bank_index.files
    bank_index.files = lambda *a, **k: calls.append(1) or monkeypatch_files(*a, **k)
    try:
        sf.sweep_read(memory)
    finally:
        bank_index.files = monkeypatch_files
    assert calls == []


def test_a_demo_bank_is_not_swept(memory):
    demo_guard.manifest_path(memory).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert demo_guard.is_demo(memory)
    _episode(memory, processed=True, processed_by="sleep")
    bank_index.invalidate()
    assert sf.sweep_read(memory) == {}


# ------------------------------------------------------------------------------ the dry run, and applying it


def _flagged_bank(memory):
    _episode(memory, processed=True, processed_by="sleep", title=f"my password is {CANARY}")
    _episode(memory, ep="ep_2026-11-01_002", body="user: nothing here", processed=True, processed_by="sleep")
    _episode(memory, ep="ep_2026-11-02_001", body=f"user: mi tarjeta es 4539 1488 0343 6467 y my password is {UNSURE}.",
             source="apple-notes", origin="apple-notes", timestamp="2026-11-02T10:00:00Z")
    _commit(memory)
    bank_index.invalidate()


def test_the_dry_run_lists_kind_source_and_date_and_never_a_word(memory):
    _flagged_bank(memory)
    before = _git(memory, "status", "--porcelain")
    script = Path(__file__).resolve().parents[2] / "scripts" / "sensitive_removal.py"
    out = subprocess.run([sys.executable, str(script), "--memory", str(memory)], capture_output=True, text=True, check=True).stdout
    assert CANARY not in out and UNSURE not in out and "4539" not in out and "Plans" not in out and str(memory) not in out
    assert sf.row_id(EP) in out and "password:1" in out and "2026-11-02" in out and "apple-notes" in out and "waiting" in out
    assert "conversations: 2  read: 1  waiting: 1" in out and "dry run" in out
    assert _git(memory, "status", "--porcelain") == before


def test_a_source_outside_the_known_list_never_prints_its_name(memory):
    _episode(memory, source="<private-folder-name>")
    bank_index.invalidate()
    (row,) = sf.plan(memory)
    assert row["source"] == "other"


def test_remove_planned_refuses_when_the_plan_moved_and_otherwise_removes_all_of_it(memory):
    _flagged_bank(memory)
    rows = sf.plan(memory)
    ids = [r["row"] for r in rows]
    with pytest.raises(ValueError):
        sf.remove_planned(memory, ids, stamp="something-else")
    with pytest.raises(ValueError):
        sf.remove_planned(memory, ["s-a-row-that-is-gone"], stamp=sf.plan_stamp(rows))
    assert CANARY in markdown_parser.parse(memory / "episodes" / f"{EP}.md").body     # refused before a word changed
    out = sf.remove_planned(memory, ids, stamp=sf.plan_stamp(rows))
    assert out == {"removed": 2, "failed": 0, "files": 2, "committed": True, "left": 0, "still_found": 0}
    for path in (memory / "episodes").glob("*.md"):
        text = path.read_text()
        assert CANARY not in text and UNSURE not in text and "4539" not in text
    assert "Cicada-Author: user" in _git(memory, "log", "-1", "--grep=^Sensitive removal", "--format=%B")
    assert CANARY in _git(memory, "log", "-p", "--format=", "--", f"episodes/{EP}.md")   # history stays


def test_remove_planned_takes_only_the_named_rows(memory):
    _flagged_bank(memory)
    one = [r for r in sf.plan(memory) if r["row"] == sf.row_id(EP)]
    out = sf.remove_planned(memory, [sf.row_id(EP)], stamp=sf.plan_stamp(one))
    assert out["removed"] == 1 and out["left"] == 1
    assert UNSURE in markdown_parser.parse(memory / "episodes" / "ep_2026-11-02_001.md").body


def test_the_route_refuses_an_agent_and_anything_but_what_the_dry_run_listed(memory):
    from api.routers import inbox as inbox_router

    _flagged_bank(memory)
    settings = _settings_for(memory)
    rows = sf.plan(memory)
    good = {"rows": [r["row"] for r in rows], "plan": sf.plan_stamp(rows)}
    for payload, code in (({**good, "via": "agent"}, 403), ({}, 400), ({"rows": good["rows"]}, 400),
                          ({**good, "plan": "other"}, 409)):
        with pytest.raises(HTTPException) as err:
            asyncio.run(inbox_router.remove_sensitive(payload, settings))
        assert err.value.status_code == code
    assert asyncio.run(inbox_router.remove_sensitive(good, settings))["left"] == 0

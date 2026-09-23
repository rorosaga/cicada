"""G141 PJ-6 (T7) — the engine-free `followup` inbox kind (spec §9).

A quiet thread, an overdue milestone or a passed `due` raises one follow-up —
at most one per project and three in the bank — written by Sleep's tail right
after expiry in its own `cicada` commit, served as a question at read (like
decay), answered through `progress` as the person, and graded against the
extractor, never the person (R-PJB24). Every test pins today to `T` on the
modules that read the clock: the demo is generated at `T`."""
import asyncio
import subprocess
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _demo_scenario import T, d, demo
from api import config, main
from api.services import (bank_index, claim_expiry, followups, git_service, handshake, inbox_service, markdown_parser,
                          mcp_tools, owner_identity, progress, sleep_cycle, telemetry)
from api.services.claims import Claim, parse_claims, write_claims

CAMERA = "Bob started calibrating the gripper camera"


class _T(date):
    today = classmethod(lambda cls: T)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    b = demo(tmp_path, followups=False)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(inbox_service, "date", _T)
    monkeypatch.setattr(mcp_tools, "date", _T)
    return b


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


# --------------------------------------------------------------------------- helpers


def _claims(bank, page):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{page}.md").body)


def _camera(bank):
    return next(c for c in _claims(bank, "rover-arm-project")
                if c.predicate == "happened" and c.text == CAMERA and c.valid_to is None)


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def _propose(bank, today=T, **kw):
    report = followups.propose(bank, today, tz_name="UTC", **kw)
    bank_index.invalidate()
    return report


def _open(bank) -> dict[str, dict]:
    return {p.name: fm for p in sorted((bank / "inbox").glob("inbox-*.md"))
            if (fm := markdown_parser.parse(p).frontmatter).get("kind") == "followup"}


def _project(bank, pid):
    markdown_parser.write(bank / "entities" / f"{pid}.md", {
        "type": "project", "name": pid.replace("-", " ").title(), "status": "active", "confidence": 0.8,
        "created": d(-100), "last_referenced": d(-100)}, f"# {pid.replace('-', ' ').title()}\n")
    bank_index.invalidate()


def _thread(bank, pid, quiet, text="Carol is testing the new sensor mount", origin="mcp", observer="agent",
            authored_by="claude-code"):
    day = T - timedelta(days=quiet)
    r = progress.record_happening(bank, subject=pid, text=text, status="ongoing", observer=observer,
                                  origin=origin, authored_by=authored_by, day=day, date_basis="person",
                                  today=day, tz_name="UTC")
    assert r["action"] == "written", r
    bank_index.invalidate()
    return r["claim_id"]


def _overdue(bank, pid, days, name="Soil probe install"):
    r = progress.set_milestone(bank, subject=pid, name=name, target=d(-days), observer="agent", origin="mcp",
                               authored_by="claude-code", today=T - timedelta(days=days + 7), tz_name="UTC")
    assert r["action"] == "written", r
    bank_index.invalidate()
    return r["claim_id"]


def _item(bank, claim_id):
    return next(name[:-3] for name, fm in _open(bank).items() if fm["claim_id"] == claim_id)


# --------------------------------------------------------------------------- 1. the proposer


def test_the_quiet_camera_thread_is_asked_once_and_the_file_holds_no_question(bank):
    report = _propose(bank)
    assert len(report.written) == 1 and report.removed == []
    fm = markdown_parser.parse(bank / report.written[0]).frontmatter
    assert (fm["kind"], fm["entity_id"], fm["predicate"]) == ("followup", "rover-arm-project", "happened")
    assert fm["claim_id"] == _camera(bank).id
    assert not {"question", "options", "source_episode"} & set(fm)
    assert _propose(bank).written == []                     # dedup on (entity_id, predicate, claim_id)


def test_a_thread_is_asked_from_21_quiet_days_and_the_fresh_s7_thread_never(bank):
    _project(bank, "orchard-a-project")
    _project(bank, "orchard-b-project")
    twenty = _thread(bank, "orchard-a-project", 20)
    twenty_one = _thread(bank, "orchard-b-project", 21)
    _propose(bank)
    asked = {fm["claim_id"] for fm in _open(bank).values()}
    assert asked == {_camera(bank).id, twenty_one}
    assert twenty not in asked
    assert not any(fm["entity_id"] == "pick-and-place-demo" for fm in _open(bank).values())


def test_a_milestone_is_asked_three_days_overdue(bank):
    _project(bank, "orchard-c-project")
    _project(bank, "orchard-e-project")
    two = _overdue(bank, "orchard-c-project", 2)
    three = _overdue(bank, "orchard-e-project", 3)
    _propose(bank)
    by_claim = {fm["claim_id"]: fm for fm in _open(bank).values()}
    assert three in by_claim and two not in by_claim
    assert by_claim[three]["predicate"] == "milestone"


def _due_project(bank, pid, days_ago):
    _project(bank, pid)
    page = bank / "entities" / f"{pid}.md"
    parsed = markdown_parser.parse(page)
    due = Claim(id=f"clm_{pid}_due", text=f"Orchard demo due {d(-days_ago)}", subject=pid, predicate="due",
                object=d(-days_ago), object_kind="literal", observer="agent", context="general",
                epistemic="explicit", source_trust="agent_extracted", confidence=0.8, valid_from=d(-40),
                recorded_at=d(-40), origin="mcp", authored_by="gpt-5.4-mini")
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, [due]))
    claim_expiry.expire(bank, T)
    bank_index.invalidate()
    return due.id


def test_a_passed_due_is_asked_once_and_cleared_when_a_milestone_replaces_it(bank):
    due = _due_project(bank, "orchard-f-project", 10)
    assert next(c for c in _claims(bank, "orchard-f-project") if c.id == due).valid_to == d(-10)
    first = _propose(bank)
    item = next(p for p in first.written if markdown_parser.parse(bank / p).frontmatter["claim_id"] == due)
    assert markdown_parser.parse(bank / item).frontmatter["predicate"] == "due"
    assert _propose(bank).written == []
    out = progress.advance(bank, subject="orchard-f-project", slug=f"due-{d(-10)}", status="done", on=T - timedelta(10),
                           observer="agent", origin="mcp", authored_by="claude-code", today=T, tz_name="UTC")
    assert out["action"] == "written", out
    bank_index.invalidate()
    again = _propose(bank)
    assert again.removed == [item] and again.written == []
    assert not (bank / item).exists()


def test_one_per_project_three_in_the_bank_and_a_deferred_item_still_counts(bank):
    for pid, quiet in (("orchard-g-project", 30), ("orchard-h-project", 25), ("orchard-i-project", 22)):
        _project(bank, pid)
        _thread(bank, pid, quiet)
    older = _thread(bank, "orchard-g-project", 40, text="Dana is rewiring the pump")
    first = _propose(bank)
    assert len(first.written) == 3                            # four eligible projects
    items = _open(bank)
    assert [fm["entity_id"] for fm in items.values()].count("orchard-g-project") == 1
    assert any(fm["claim_id"] == older for fm in items.values())    # the quietest thread in its project
    assert not any(fm["entity_id"] == "orchard-i-project" for fm in items.values())
    # Snooze one and answer another away: two open, one of them deferred.
    names = sorted(items)
    deferred = bank / "inbox" / names[0]
    parsed = markdown_parser.parse(deferred)
    markdown_parser.write(deferred, {**parsed.frontmatter, "remind_after": d(10)}, parsed.body)
    (bank / "inbox" / names[1]).unlink()
    bank_index.invalidate()
    again = _propose(bank)
    assert len(again.written) == 1 and len(_open(bank)) == 3
    deferred_project = parsed.frontmatter["entity_id"]
    assert [fm["entity_id"] for fm in _open(bank).values()].count(deferred_project) == 1


def test_a_page_dirty_before_the_run_is_skipped(bank):
    assert _propose(bank, skip=frozenset({"entities/rover-arm-project.md"})).written == []


# --------------------------------------------------------------------------- 2. served as a question


def test_the_inbox_serves_it_as_a_question_with_its_claim_as_the_cause(bank, client):
    _propose(bank)
    items = [i for i in client.get("/inbox").json() if i["kind"] == "followup"]
    assert len(items) == 1
    item = items[0]
    assert item["question"] == "“Bob started calibrating the gripper camera” — last heard 3 weeks ago. How did it go?"
    assert [o["key"] for o in item["options"]] == ["done", "still", "stopped", "didnt", "remind_later"]
    assert item["allowOther"] is True and item["allowDefer"] is False
    assert item["options"][-1]["label"] == "Not now — ask again in 30 days"
    assert item["recommendedKey"] is None
    assert item["cause"]["tier"] == "claim" and item["cause"]["spanKind"] == "asserted"
    assert [o["verdict"] for o in item["options"]] == ["agreed", "agreed", "neutral", "overruled", "neutral"]
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")
    out = mcp_tools.check_nudges(ctx, None, entity_ids=["rover-arm-project"])
    assert "How did it go?" in out and "Not now — ask again in 30 days" in out and item["id"] in out


def test_a_remote_relay_without_sources_never_reads_the_persons_own_thread(bank):
    _project(bank, "orchard-j-project")
    owner = owner_identity.resolve_observer(bank, None)
    _thread(bank, "orchard-j-project", 30, text="Planting the north rows", origin="companion_app", observer=owner,
            authored_by="user")
    _propose(bank)
    remote = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="rc_x", harness="claude-web",
                                   raw_excerpts=False)
    out = mcp_tools.check_nudges(remote, None, entity_ids=["orchard-j-project"])
    assert "A thread you logged on Orchard J Project" in out and "north rows" not in out
    local = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")
    assert "Planting the north rows" in mcp_tools.check_nudges(local, None, entity_ids=["orchard-j-project"])


# --------------------------------------------------------------------------- 3. answers


def _resolve(client, item, **body):
    return client.post(f"/inbox/{item}/resolve", json={"action": "resolve", **body})


def _ledger():
    return [e for e in telemetry.read_events() if e.kind == "resolution"]


@pytest.mark.parametrize("key,verdict", [("done", "agreed"), ("still", "agreed"), ("stopped", "neutral"),
                                         ("didnt", "overruled")])
def test_each_answer_writes_through_progress_and_grades_the_extractor(bank, client, monkeypatch, key, verdict):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    _propose(bank)
    camera = _camera(bank)
    item = _item(bank, camera.id)
    head = _git(bank, "rev-parse", "HEAD").strip()
    r = _resolve(client, item, optionKey=key)
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.text
    assert not (bank / "inbox" / f"{item}.md").exists()
    claims = _claims(bank, "rover-arm-project")
    thread = next(c for c in claims if c.id == camera.id and (c.valid_to is None or c.superseded_by))
    if key in ("done", "stopped"):
        closer = next(c for c in claims if c.id == thread.superseded_by)
        assert (closer.status, closer.valid_from, closer.valid_to) == ({"done": "done", "stopped": "dropped"}[key],
                                                                       d(0), d(0))
        assert (closer.origin, closer.authored_by, closer.source_trust) == ("clarification", "user", "user_stated")
    elif key == "still":
        assert thread.valid_to is None and thread.recorded_at == d(0)
    else:
        assert next(c for c in claims if c.id == thread.superseded_by).predicate == "retracts"
    authors = _git(bank, "log", "--format=%s|%(trailers:key=Cicada-Author,valueonly)", f"{head}..HEAD")
    mine = [line for line in authors.splitlines() if line.startswith("Inbox resolution (followup)")]
    assert len(mine) == 1 and mine[0].endswith("|user")     # the commit subject's date is git_service's own clock
    rows = _ledger()
    assert len(rows) == 1
    refs = rows[0].refs
    assert (refs["kind"], refs["verdict"], refs["authored_by"], refs["claim_id"]) == (
        "followup", verdict, "gpt-5.4-mini", camera.id)
    assert "date_basis" in refs
    ledger = "".join(p.read_text() for p in telemetry.telemetry_dir().glob("*.jsonl"))
    assert "gripper camera" not in ledger


def test_not_now_is_thirty_days_however_it_is_asked(bank, client):
    _propose(bank)
    item = _item(bank, _camera(bank).id)
    r = _resolve(client, item, optionKey="remind_later")
    assert r.json()["remindAfter"] == d(30)
    r = client.post(f"/inbox/{item}/resolve", json={"action": "defer", "remindDays": 7})
    assert r.json()["remindAfter"] == d(30)
    assert markdown_parser.parse(bank / "inbox" / f"{item}.md").frontmatter["remind_after"] == d(30)


def test_a_free_text_done_takes_its_day_from_the_words(bank, client):
    _propose(bank)
    camera = _camera(bank)
    r = _resolve(client, _item(bank, camera.id), answer="done last Friday")
    assert r.status_code == 200, r.text
    claims = _claims(bank, "rover-arm-project")
    closer = next(c for c in claims if c.id == next(x for x in claims if x.id == camera.id).superseded_by)
    assert (closer.valid_from, closer.date_basis, closer.status) == ("2026-09-18", "stated", "done")


def test_a_free_text_sentence_on_a_thread_is_the_persons_note(bank, client):
    _propose(bank)
    camera = _camera(bank)
    r = _resolve(client, _item(bank, camera.id), answer="It finally focused on the second try yesterday")
    assert r.status_code == 200, r.text
    claims = _claims(bank, "rover-arm-project")
    closer = next(c for c in claims if c.id == next(x for x in claims if x.id == camera.id).superseded_by)
    assert closer.text == "It finally focused on the second try" and closer.valid_from == d(-1)
    ep = next(e.episode for e in closer.evidence if e.episode)
    assert "second try yesterday" in (bank / "episodes" / f"{ep}.md").read_text()


def test_a_milestone_moves_by_its_words_and_refuses_what_it_cannot_read(bank, client):
    _project(bank, "orchard-k-project")
    ms = _overdue(bank, "orchard-k-project", 4)
    _propose(bank)
    item = _item(bank, ms)
    r = _resolve(client, item, answer="it was lovely")
    assert r.status_code == 400 and r.json()["detail"] == "Say done, missed, dropped, or 'move it to <date>'"
    assert (bank / "inbox" / f"{item}.md").exists()
    r = _resolve(client, item, answer="move it to Oct 20")
    assert r.status_code == 200, r.text
    heads = [c for c in _claims(bank, "orchard-k-project") if c.predicate == "milestone" and c.valid_to is None]
    assert [(h.target, h.status, h.supersedes) for h in heads] == [("2026-10-20", "planned", ms)]


def test_the_persons_own_thread_is_never_graded(bank, client, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    _project(bank, "orchard-l-project")
    owner = owner_identity.resolve_observer(bank, None)
    mine = _thread(bank, "orchard-l-project", 30, text="Planting the south rows", origin="companion_app",
                   observer=owner, authored_by="user")
    _propose(bank)
    item = [i for i in client.get("/inbox").json() if i.get("claimId") == mine][0]
    assert {o["verdict"] for o in item["options"]} == {"neutral"}
    assert _resolve(client, item["id"], optionKey="done").status_code == 200
    rows = _ledger()
    assert [(r.refs["verdict"], r.refs["authored_by"], r.refs["date_basis"]) for r in rows] == [
        ("neutral", "user", "person")]


# --------------------------------------------------------------------------- 4. Sleep's tail


def _spies(monkeypatch):
    order: list[str] = []

    def spy(name):
        async def _f(*a, **k):
            order.append(name)
        return _f

    for name in ("_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely",
                 "_poll_feeds_and_calendars_safely", "_backfill_links_safely", "_resolve_papers_safely",
                 "_replay_wispr_todos_safely", "_warm_logos_safely", "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, spy(name))
    real = git_service.commit_paths

    async def commit(memory_path, message, paths):
        order.append("commit:" + message.splitlines()[0])
        await real(memory_path, message, paths)

    monkeypatch.setattr(git_service, "commit_paths", commit)
    return order


def test_the_tail_asks_after_expiry_and_before_the_poll_in_its_own_commit(bank, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "date", _T)
    before = _git(bank, "status", "--porcelain")          # the scaffold's own untracked files, if any
    order = _spies(monkeypatch)
    asyncio.run(sleep_cycle._run_engine_independent_tail(
        bank, SimpleNamespace(), sleep_cycle._StageOutcome(committed=True, questions_refreshed=True)))
    assert order == ["_refresh_state_safely", "_expire_claims_safely", f"commit:Follow-ups {T}",
                     "_poll_connectors_safely", "_poll_feeds_and_calendars_safely", "_backfill_links_safely",
                     "_resolve_papers_safely", "_replay_wispr_todos_safely", "_warm_logos_safely"]
    message = _git(bank, "log", "-1", "--format=%B")
    item = next(iter(_open(bank)))
    assert f"inbox/{item}: created (source: n/a, trigger: sleep/followup)" in message
    assert "Cicada-Author: cicada" in message and "Cicada-Engine" not in message
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [f"inbox/{item}"]
    assert _git(bank, "status", "--porcelain") == before


def test_a_failed_commit_takes_back_what_it_wrote(bank, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "date", _T)

    async def boom(*a, **k):
        raise git_service.GitError("index.lock is held")

    before = _git(bank, "status", "--porcelain")
    monkeypatch.setattr(git_service, "commit_paths", boom)
    asyncio.run(sleep_cycle._propose_followups_safely(bank))
    assert _open(bank) == {}
    assert _git(bank, "status", "--porcelain") == before     # never left for the next `git add -A` writer


# --------------------------------------------------------------------------- 5. the list


def test_the_projects_list_counts_the_demos_follow_up(tmp_path, monkeypatch):
    b = demo(tmp_path)                                       # PJ-6's step on: one follow-up, committed
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(b))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        rows = {r["id"]: r for r in TestClient(main.app).get("/projects").json()["projects"]}
    finally:
        config.get_settings.cache_clear()
    assert rows["rover-arm-project"]["followups"] == 1
    assert _git(b, "log", "-1", "--format=%s") == f"Follow-ups {T}\n"

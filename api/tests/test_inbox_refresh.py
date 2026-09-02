"""G60 §2.3 — Stage-3 re-scoring of open questions + defer visibility."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from api.services import inbox_questions, inbox_service, markdown_parser
from api.services.claims import Claim


def _write_conflict(memory: Path, item_id: str, *, entity_id: str = "rodrigo",
                    predicate: str = "works-at", options: list[dict] | None = None,
                    created: str = "2026-02-20", priority: float = 0.8,
                    extra: dict | None = None) -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    fm = {
        "kind": "conflict",
        "required_input": "choice",
        "status": "pending",
        "priority": priority,
        "entity_id": entity_id,
        "entity_name": "Rodrigo",
        "title": "Where does Rodrigo work now?",
        "question": "Where does Rodrigo work now?",
        "created_date": created,
        "predicate": predicate,
        "allow_other": True,
        "allow_defer": True,
        "options": options if options is not None else [
            {"key": "a", "label": "mongodb", "claim_id": "clm_a",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
            {"key": "b", "label": "supahost", "claim_id": "clm_b",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
            {"key": "both", "label": "Both are true (different contexts)"},
        ],
    }
    fm.update(extra or {})
    path = inbox / f"{item_id}.md"
    markdown_parser.write(path, fm, "Conflicting beliefs.")
    return path


def _write_entity(memory: Path, entity_id: str, *, status: str = "active") -> Path:
    entities = memory / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    path = entities / f"{entity_id}.md"
    markdown_parser.write(
        path,
        {"name": entity_id.title(), "type": "person", "status": status, "confidence": 0.7},
        "A person.",
    )
    return path


def _claim(cid: str, obj: str, *, valid_from: str, valid_to: str | None = None,
           source_trust: str = "agent_extracted", recorded_at: str | None = None) -> Claim:
    return Claim(
        id=cid, text=f"Rodrigo works at {obj}", subject="rodrigo",
        predicate="works-at", object=obj, source_trust=source_trust,
        valid_from=valid_from, valid_to=valid_to,
        recorded_at=recorded_at or valid_from,
    )


def test_is_deferred_only_while_remind_after_is_in_the_future():
    assert inbox_questions.is_deferred({"remind_after": "2026-09-30"}, "2026-08-30") is True
    assert inbox_questions.is_deferred({"remind_after": "2026-08-30"}, "2026-08-30") is False
    assert inbox_questions.is_deferred({"remind_after": "2026-01-01"}, "2026-08-30") is False
    assert inbox_questions.is_deferred({}, "2026-08-30") is False
    assert inbox_questions.is_deferred({"remind_after": None}, "2026-08-30") is False


def test_load_inbox_hides_deferred_items_but_they_stay_on_disk(tmp_path):
    memory = tmp_path / "memory"
    _write_conflict(memory, "inbox-001")
    _write_conflict(memory, "inbox-002", predicate="uses",
                    extra={"remind_after": "2099-01-01"})
    _write_entity(memory, "rodrigo")  # G98: load_inbox now gates on a live subject

    visible = inbox_service.load_inbox(memory)
    assert [i.id for i in visible] == ["inbox-001"]

    everything = inbox_service.load_inbox(memory, include_deferred=True)
    assert {i.id for i in everything} == {"inbox-001", "inbox-002"}
    assert (memory / "inbox" / "inbox-002.md").exists()


def test_refresh_bumps_and_reorders_a_reinforced_option(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18", recorded_at="2026-08-25"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["bumped"] == 1
    assert result["organic_resolutions"] == 0
    fm = markdown_parser.parse(path).frontmatter
    # The freshly-reinforced value sorts first; the synthetic row stays last.
    assert [o["label"] for o in fm["options"]] == [
        "supahost", "mongodb", "Both are true (different contexts)",
    ]
    assert fm["options"][0]["last_referenced"] == "2026-08-25"
    assert fm["updated_date"] == "2026-08-30"


def test_refresh_resolves_organically_on_a_user_stated_claim(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
        _claim("clm_user", "acme", valid_from="2026-08-28",
               source_trust="user_stated"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 1
    assert result["resolved_paths"] == ["inbox/inbox-001.md"]
    assert not path.exists(), "a human answer in conversation closes the question"


def test_refresh_resolves_organically_when_an_option_claim_was_superseded(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18", valid_to="2026-08-20"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 1
    assert not path.exists()


def test_refresh_does_not_organically_resolve_on_a_stale_user_stated_claim(tmp_path):
    """Controller ruling: a `user_stated` claim recorded BEFORE the item was
    created must not close it. Those older human claims were already
    reconciled into the graph before this question ever opened, so they carry
    no new information about it — only a human answer given *after* the
    question opened counts as organic resolution.
    """
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001", created="2026-02-20")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
        _claim("clm_old_user", "acme", valid_from="2026-01-01",
               source_trust="user_stated"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 0
    assert path.exists()


def test_refresh_escalates_a_stale_question_and_inserts_neither(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(
        memory, claims, "2026-08-30", stale_after_days=90
    )

    assert result["escalated"] == 1
    fm = markdown_parser.parse(path).frontmatter
    assert fm["options"][0]["key"] == "neither"
    assert fm["options"][0]["label"] == "Neither anymore"
    assert "Close both" in fm["options"][0]["description"]
    assert fm["priority"] == 0.6
    assert "6 months" in fm["question"]
    assert "Rodrigo" in fm["question"]

    # Escalation is idempotent — a second pass must not stack a second `neither`.
    again = inbox_questions.refresh_open_questions(
        memory, claims, "2026-08-30", stale_after_days=90
    )
    assert again["escalated"] == 0
    fm2 = markdown_parser.parse(path).frontmatter
    assert [o["key"] for o in fm2["options"]].count("neither") == 1


def test_refresh_skips_deferred_items(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001", extra={"remind_after": "2099-01-01"})
    claims = {"rodrigo": [_claim("clm_user", "acme", valid_from="2026-08-28",
                                 source_trust="user_stated")]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result == {
        "bumped": 0, "organic_resolutions": 0, "escalated": 0,
        "resolved_paths": [], "rewritten_paths": [],
    }
    assert path.exists()


def test_refresh_ignores_non_conflict_kinds(tmp_path):
    memory = tmp_path / "memory"
    inbox = memory / "inbox"
    inbox.mkdir(parents=True)
    markdown_parser.write(
        inbox / "inbox-001.md",
        {"kind": "decay", "status": "pending", "entity_id": "rodrigo",
         "created_date": "2026-02-20", "options": None},
        "decaying",
    )
    result = inbox_questions.refresh_open_questions(memory, {}, "2026-08-30")
    assert result == {
        "bumped": 0, "organic_resolutions": 0, "escalated": 0,
        "resolved_paths": [], "rewritten_paths": [],
    }
    assert (inbox / "inbox-001.md").exists()


def test_sleep_state_carries_the_new_counters():
    from api.services.sleep_cycle import SleepState

    state = SleepState()
    assert state.organic_resolutions == 0
    assert state.questions_refreshed == 0


def _git(args, cwd):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_finalize_tags_organic_resolution_deletes_with_their_own_trigger(tmp_path):
    """G60 fix round 1: `_finalize` must not fall through to the generic
    `sleep/inbox_generation` trigger for an inbox file `refresh_open_questions`
    deleted this cycle -- it should carry `inbox/organic_resolution` so the
    commit-message provenance the spec promises actually shows up.
    """
    import asyncio
    import subprocess

    from api.services.sleep_cycle import _finalize

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    resolved = memory / "inbox" / "inbox-001.md"
    resolved.write_text("---\nkind: conflict\n---\nresolved\n")
    kept = memory / "inbox" / "inbox-002.md"
    kept.write_text("---\nkind: decay\n---\nstill open\n")

    _git(["init", "-q"], cwd=memory)
    _git(["config", "user.email", "t@t"], cwd=memory)
    _git(["config", "user.name", "t"], cwd=memory)
    _git(["add", "-A"], cwd=memory)
    _git(["commit", "-q", "-m", "seed"], cwd=memory)

    # Simulate what refresh_open_questions did this cycle: delete the
    # organically-resolved item, leave the other inbox file untouched.
    resolved.unlink()

    asyncio.run(_finalize(
        memory, "cyc1", [], None,
        organic_resolution_paths={"inbox/inbox-001.md"},
    ))

    message = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"], cwd=memory,
        check=True, capture_output=True, text=True,
    ).stdout

    assert "inbox/inbox-001.md: deleted (trigger: inbox/organic_resolution)" in message


def test_finalize_still_infers_the_generic_trigger_for_other_inbox_writes(tmp_path):
    """A plain inbox write NOT in `organic_resolution_paths` keeps the
    pre-existing generic `sleep/inbox_generation` trigger."""
    import asyncio
    import subprocess

    from api.services.sleep_cycle import _finalize

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    (memory / "inbox" / ".gitkeep").write_text("")
    _git(["init", "-q"], cwd=memory)
    _git(["config", "user.email", "t@t"], cwd=memory)
    _git(["config", "user.name", "t"], cwd=memory)
    _git(["add", "-A"], cwd=memory)
    _git(["commit", "-q", "-m", "seed"], cwd=memory)

    (memory / "inbox" / "inbox-003.md").write_text("---\nkind: decay\n---\nnew\n")

    asyncio.run(_finalize(memory, "cyc1", [], None, organic_resolution_paths=set()))

    message = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"], cwd=memory,
        check=True, capture_output=True, text=True,
    ).stdout

    assert "inbox/inbox-003.md: created (trigger: sleep/inbox_generation)" in message


def test_refresh_escalates_a_dateless_legacy_item_from_its_created_date(tmp_path):
    """H2 — options with no dates (every legacy pre-G60 item, and every
    entity-path question) must still be able to go stale: the item has been
    sitting open since ``created_date``, so that is the age of what it offers.
    """
    memory = tmp_path / "memory"
    path = _write_conflict(
        memory,
        "inbox-001",
        created="2026-02-20",
        options=[{"key": "a", "label": "mongodb"}, {"key": "b", "label": "supahost"}],
    )

    result = inbox_questions.refresh_open_questions(
        memory, {}, "2026-08-30", stale_after_days=90
    )

    assert result["escalated"] == 1
    fm = markdown_parser.parse(path).frontmatter
    assert fm["options"][0]["key"] == "neither"
    assert fm["priority"] == 0.6


def test_refresh_does_not_escalate_a_dateless_item_created_recently(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(
        memory,
        "inbox-001",
        created="2026-08-20",
        options=[{"key": "a", "label": "mongodb"}, {"key": "b", "label": "supahost"}],
    )

    result = inbox_questions.refresh_open_questions(
        memory, {}, "2026-08-30", stale_after_days=90
    )

    assert result["escalated"] == 0
    fm = markdown_parser.parse(path).frontmatter
    assert [o["key"] for o in fm["options"]] == ["a", "b"]


def test_refresh_ignores_a_supersession_by_the_same_value(tmp_path):
    """M1 — claim ids are date-keyed, so the SAME value re-extracted later
    supersedes its own predecessor. Nothing was answered; the question stays.
    """
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001", created="2026-08-25")
    closed = _claim("clm_a", "mongodb", valid_from="2026-02-18", valid_to="2026-08-28")
    closed.superseded_by = "clm_a2"
    claims = {"rodrigo": [
        closed,
        _claim("clm_a2", "mongodb", valid_from="2026-08-28"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 0
    assert path.exists()


def test_refresh_still_resolves_when_a_different_value_supersedes(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001", created="2026-08-25")
    closed = _claim("clm_a", "mongodb", valid_from="2026-02-18", valid_to="2026-08-28")
    closed.superseded_by = "clm_c"
    claims = {"rodrigo": [
        closed,
        _claim("clm_c", "acme", valid_from="2026-08-28"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 1
    assert not path.exists()


def test_refresh_reports_rewritten_paths_for_a_bumped_item(tmp_path):
    """D2's plumbing: `rewritten_paths` must list every item bumped/escalated
    IN PLACE, not just the ones removed by organic resolution — the idle-cycle
    committer needs the full touched-file set to scope its commit."""
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18", recorded_at="2026-08-25"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["bumped"] == 1
    assert result["rewritten_paths"] == ["inbox/inbox-001.md"]
    assert result["resolved_paths"] == []
    assert path.exists()


def _git(args, cwd):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_refresh_questions_safely_commits_only_touched_inbox_files(tmp_path):
    """D2: the idle-cycle commit used to pass the whole `inbox` directory as
    its pathspec, sweeping in ANY dirty file under `inbox/` — even one this
    sweep never touched. It must commit exactly the files it rewrote/deleted,
    mirroring the H2 pattern in `decay_migration._commit_backfill`: a
    pre-existing dirty inbox file must stay uncommitted."""
    import asyncio
    import subprocess

    from api.services.sleep_cycle import _refresh_questions_safely

    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)

    # A stale legacy conflict item: escalates purely from its own age (no
    # claims needed) — this IS the file the sweep is meant to touch.
    stale_created = (date.today() - timedelta(days=200)).isoformat()
    _write_conflict(
        memory, "inbox-001", created=stale_created,
        options=[{"key": "a", "label": "mongodb"}, {"key": "b", "label": "supahost"}],
    )

    _git(["init", "-q"], cwd=memory)
    _git(["config", "user.email", "t@t"], cwd=memory)
    _git(["config", "user.name", "t"], cwd=memory)
    _git(["add", "-A"], cwd=memory)
    _git(["commit", "-q", "-m", "seed"], cwd=memory)

    # An UNRELATED, pre-existing dirty edit under inbox/, made AFTER the seed
    # commit — a real uncommitted change sitting in the working tree during
    # the sweep, on an item this sweep never looks at (kind: decay).
    dirty = memory / "inbox" / "inbox-999.md"
    dirty.write_text("---\nkind: decay\nstatus: pending\n---\nsome other pending item\n")

    class _Settings:
        inbox_stale_after_days = 90

    asyncio.run(_refresh_questions_safely(memory, _Settings()))

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=memory,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "inbox-999.md" in status, "the unrelated dirty file must stay UNCOMMITTED"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"], cwd=memory,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "inbox-999" not in log, "the unrelated file must never be swept into this commit"
    assert "inbox/inbox-001.md" in log


def test_refresh_survives_a_file_that_vanishes_mid_sweep(tmp_path, monkeypatch):
    """L5 — a concurrently removed file must not abort the whole sweep."""
    memory = tmp_path / "memory"
    _write_conflict(memory, "inbox-001", created="2026-02-20")
    path2 = _write_conflict(memory, "inbox-002", created="2026-02-20",
                            predicate="uses")

    real_parse = markdown_parser.parse

    def _flaky(filepath, *args, **kwargs):
        if filepath.name == "inbox-001.md":
            raise FileNotFoundError(filepath)
        return real_parse(filepath, *args, **kwargs)

    monkeypatch.setattr(markdown_parser, "parse", _flaky)
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(
        memory, claims, "2026-08-30", stale_after_days=90
    )

    # inbox-001 was skipped; inbox-002 was still escalated.
    assert result["escalated"] == 1
    assert path2.exists()

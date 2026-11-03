"""G104 slice 2 (owner 2026-11-03): a page's prose follows a conversation that revised itself.

End to end through Sleep (`sleep_cycle.run`): the real episode loader, the git read of the version Sleep read, Stage 1's
real ``extract`` on the changed lines, Stage 2 and Stage 5's real page writes (Key Facts with their G118 rows), the
claim pipeline, and Stage 5.58 (`revision_prose`) with its real rails and writes. Fake: the model's answers
(``litellm.acompletion``: a rule per line for extraction, a scripted rewrite for the prose call), Stage 3's merge and
Stage 4, the vector index and Sleep's own commit (the test commits as Sleep's would). The person's pinned fix goes
through the person's own door (``POST /entities/{id}/edits``'s body, ``_person_edit``), committed as it is live."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import (bank_index, entity_extractor, episode_revision, evidence, markdown_parser, page_edits,
                          revision_prose, section_provenance, sleep_cycle)
from api.services.claims import Evidence
from api.tests.test_sleep_cycle_hold import _bank, _patch, _settings

HEAD = "user: Meeting notes for alpha-project."
V1 = {
    "a": f"{HEAD}\nThe alpha-project design review meeting is on Friday.\nalpha-project will use rustfft.",
    "b": f"{HEAD}\nalpha-project stores its spectrograms in SQLite.",
    "c": f"{HEAD}\nalpha-project uses tokio for async work.\nalpha-project targets Linux only.",
    "d": f"{HEAD}\nalpha-project is licensed under the MIT license.",
    "e": f"{HEAD}\nThe alpha-project public demo will be held in Lisbon.",
}
V2 = {
    "a": f"{HEAD}\nThe alpha-project design review meeting is on Thursday.\nalpha-project will use rustfft.",
    "b": f"{HEAD}\nalpha-project stores its spectrograms in SQLite.\nalpha-project ships its first release in December.",
    "c": f"{HEAD}\nalpha-project uses tokio for async work.",
    "d": f"{HEAD}\n\nalpha-project is licensed under  the MIT license.",
    "e": f"{HEAD}\nThe alpha-project public demo will be held in Porto.",
}
EP = {k: f"ep_2026-11-0{i + 1}_001" for i, k in enumerate("abcde")}
FACT = re.compile(r"^(?:user: )?(.*alpha-project.*)$")


def _answer(chunk: str) -> dict:
    """Extraction: each line is one Key Fact on alpha-project, and the day/platform/city lines a value too."""
    facts = [m[1].strip() for line in chunk.splitlines() if (m := FACT.match(line.strip()))
             and "Meeting notes" not in line and "[Revision" not in line]
    ents = [{"name": "alpha-project", "type": "project", "confidence": 0.9, "summary": "A project.",
             "key_facts": facts}]
    vals = []
    for line in chunk.splitlines():
        if m := re.search(r"design review meeting is on (\w+)", line):
            vals.append({"entity": "alpha-project", "attribute": "design review day", "value": m[1],
                         "evidence_quote": m[0]})
        if m := re.search(r"targets (Linux only)", line):
            vals.append({"entity": "alpha-project", "attribute": "platform", "value": m[1], "evidence_quote": m[0]})
    return {"entities": ents, "relationships": [], "values": vals}


def _rewrite(prompt: str) -> dict:
    """The prose call: rewrite each old passage the way a careful writer would, mark nothing else."""
    out, history = [], []
    for n, text in re.findall(r"^(\d+)\. \[[^\]]+\](?: \(held\))?(?: \(new\))? (.*)$", prompt, re.M):
        if "Friday" in text:
            out.append({"n": int(n), "text": ""})         # the Thursday fact is already on the page
        elif "Linux only" in text:
            out.append({"n": int(n), "text": ""})
        elif "Lisbon" in text:
            out.append({"n": int(n), "text": text.replace("Lisbon", "Porto")})
    changes = re.findall(r"^(\d+)\. before: (.*)\n   after: (.*)$", prompt, re.M)
    for i, before, after in changes:
        if "Friday" in before:
            history.append({"change": int(i), "event": "The design review meeting moved from Friday to Thursday."})
        elif "Linux" in before:
            history.append({"change": int(i), "event": "The notes no longer say alpha-project targets Linux only."})
        elif "Lisbon" in before:
            history.append({"change": int(i), "event": "The public demo moved from Lisbon to Porto."})
    return {"passages": out, "history": history}


def _git(memory, *args):
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=memory, check=True,
                   capture_output=True)


def _digest(body: str) -> str:
    return "sha256:" + evidence.body_hash(body)


def _write(memory, k, body, revised=None):
    fm = {"id": EP[k], "processed": False, "source": "note", "origin": "note", "source_id": f"note:test:{k}",
          "timestamp": f"{EP[k][3:13]}T10:00:00Z", "content_hash": _digest(body)}
    if revised:
        fm["revised"] = revised
    markdown_parser.write(memory / "episodes" / f"{EP[k]}.md", fm, body)


def _run(memory, monkeypatch, calls):
    async def fake_acompletion(**kw):
        system = kw["messages"][0]["content"]
        content = kw["messages"][1]["content"]
        calls.append(("prose" if system == revision_prose.SYSTEM else "extract", content))
        answer = _rewrite(content) if system == revision_prose.SYSTEM else _answer(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", memory_path=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.conflict_resolver._litellm",
                        lambda: SimpleNamespace(acompletion=fake_acompletion))
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)

    async def no_ids(_settings):
        return frozenset()
    monkeypatch.setattr("api.services.engine_identity.aidentities", no_ids)
    settings = _settings(memory)
    settings.effective_consolidation_model = "fake-engine"
    settings.litellm_mode = "byok"
    settings.llm_mode = "byok"
    bank_index.invalidate()
    asyncio.run(sleep_cycle.run(settings, cycle_id="g104_prose"))
    bank_index.invalidate()


def _prose(memory) -> str:
    return page_edits.split_prose(markdown_parser.parse(memory / "entities" / "alpha-project.md", ledger=False).body)[0]


def _setup(tmp_path, monkeypatch, pin=False):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.9},
                          "## Summary\nalpha-project is a synthetic project.\n")
    for k, body in V1.items():
        _write(memory, k, body)
    _git(memory, "init", "-q")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "capture")
    first: list = []
    _run(memory, monkeypatch, first)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "Sleep cycle")
    if pin:
        from api.routers.entities import _person_edit

        # ``pin="blame"``: the same edit unpinned — held by `git blame` alone (the line is a page-edit commit's).
        request = page_edits.parse_request([{"old": "public demo will be held in Lisbon.",
                                             "new": "public demo will be held in Lisbon, in the university hall.",
                                             "pin": pin is True}])
        _person_edit(memory, "alpha-project", request, "The venue is the university hall.")
        assert bool(page_edits.corrections(markdown_parser.parse(memory / "entities" / "alpha-project.md")
                                           .frontmatter)) is (pin is True)
    before = _prose(memory)
    for k, body in V2.items():
        _write(memory, k, body, revised={"count": 1, "at": "2026-11-03T12:00:00Z", "previous_hash": _digest(V1[k]),
                                         "consolidated_hash": _digest(V1[k])})
    return memory, first, before


def _facts(prose: str) -> list[str]:
    section = prose.split("## Key Facts", 1)[1].split("\n## ", 1)[0]
    return [line[2:] for line in section.strip().splitlines() if line.startswith("- ")]


def _history(prose: str) -> list[str]:
    section = prose.split("## History", 1)[1].split("\n## ", 1)[0] if "## History" in prose else ""
    return [line[2:] for line in section.strip().splitlines() if line.startswith("- ")]


def test_the_page_says_what_the_revised_conversations_say_now(tmp_path, monkeypatch):
    memory, first, before = _setup(tmp_path, monkeypatch)
    # The first read wrote one Key Fact per line, each with its G118 row into the version it was read from.
    facts = _facts(before)
    assert "The alpha-project design review meeting is on Friday." in facts
    assert "alpha-project targets Linux only." in facts
    calls: list = []
    _run(memory, monkeypatch, calls)
    prose = _prose(memory)
    facts, history = _facts(prose), _history(prose)

    # One prose call for the one page the revisions touched; extraction only where new words came (a, b, e).
    assert [kind for kind, _ in calls].count("prose") == 1
    assert [kind for kind, _ in calls].count("extract") == 3

    # (a) the changed fact appears once, current; History says it moved, dated the day the notes were edited.
    assert [f for f in facts if "design review" in f] == ["The alpha-project design review meeting is on Thursday."]
    assert "2026-11-03: The design review meeting moved from Friday to Thursday." in history
    # (b) an added line: nothing removed, the new fact simply joins.
    assert "alpha-project ships its first release in December." in facts
    # (c) the removed line's fact leaves the prose; History keeps that it was said.
    assert not [f for f in facts if "Linux" in f]
    assert "2026-11-03: The notes no longer say alpha-project targets Linux only." in history
    # (d) whitespace only: the fact stands as written.
    assert "alpha-project is licensed under the MIT license." in facts
    # (e) not pinned: the city follows the notes, once.
    assert [f for f in facts if "public demo" in f] == ["The alpha-project public demo will be held in Porto."]
    # Nothing outside History still says what the conversations stopped saying.
    outside = prose.split("## History", 1)[0]
    assert not re.search(r"Friday|Linux|Lisbon", outside)
    assert not list((memory / "inbox").rglob("*.md"))

    # Provenance: every row into a revised conversation is on its new body, none left on the old version.
    fm = markdown_parser.parse(memory / "entities" / "alpha-project.md", ledger=False).frontmatter
    rows = [ev for items in section_provenance.decode(fm[section_provenance.FIELD]).values()
            for _, evs in items.values() for ev in evs]
    current = {EP[k]: evidence.body_hash(evidence.source_text(memory, EP[k])) for k in EP}
    assert rows and all(ev.hash == current[ev.episode] for ev in rows if ev.episode in current)


@pytest.mark.parametrize("pin", [True, "blame"])
def test_a_pinned_fix_is_never_rewritten_and_asks_once(tmp_path, monkeypatch, pin):
    memory, _, before = _setup(tmp_path, monkeypatch, pin=pin)
    assert "The alpha-project public demo will be held in Lisbon, in the university hall." in _facts(before)
    calls: list = []
    _run(memory, monkeypatch, calls)
    prose = _prose(memory)
    facts = _facts(prose)
    # The person's words stand as they wrote them; the other passages still follow the notes.
    assert "The alpha-project public demo will be held in Lisbon, in the university hall." in facts
    assert [f for f in facts if "design review" in f] == ["The alpha-project design review meeting is on Thursday."]
    # One gentle question for the page: Cicada's own page_edit proposal carrying the rewrite, about this page.
    (item,) = list((memory / "inbox").rglob("*.md"))
    fm = markdown_parser.parse(item).frontmatter
    assert (fm["kind"], fm["origin"], fm["entity_id"], fm["status"]) == ("page_edit", "revision", "alpha-project",
                                                                         "pending")
    assert fm["edit"]["edits"] == [{"old": "The alpha-project public demo will be held in Lisbon, in the university "
                                           "hall.",
                                    "new": "The alpha-project public demo will be held in Porto, in the university "
                                           "hall.", "all": False, "pin": False}]
    assert "Lisbon to Porto" in fm["question"]
    assert "2026-11-03: The public demo moved from Lisbon to Porto." in _history(prose)


def test_a_revision_that_took_no_word_away_costs_no_call(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    rev = episode_revision.build({"id": EP["d"], "content": V2["d"]}, V1["d"])
    assert rev.noop and revision_prose.changes_of(rev) == []
    added = episode_revision.build({"id": EP["b"], "content": V2["b"]}, V1["b"])
    assert revision_prose.changes_of(added) == []
    calls: list = []

    async def boom(**_kw):
        calls.append(1)
        raise AssertionError("no call")
    monkeypatch.setattr("api.services.conflict_resolver._litellm", lambda: SimpleNamespace(acompletion=boom))
    report = asyncio.run(revision_prose.run(memory, _settings(memory), {EP["d"]: rev, EP["b"]: added}))
    assert (report.calls, calls) == (0, [])


def test_a_transcript_revision_rewrites_nothing():
    rev = episode_revision.build({"id": EP["c"], "content": V2["c"], "capture_kind": "transcript"}, V1["c"])
    assert not rev.closes and revision_prose.changes_of(rev) == []


def test_the_rails_refuse_a_rewrite_that_keeps_the_old_word_or_adds_a_name():
    rev = episode_revision.build({"id": EP["a"], "content": V2["a"]}, V1["a"])
    (change,) = revision_prose.changes_of(rev)
    assert change.gone == {"friday"} and change.fresh == {"thursday"}
    p = revision_prose.Passage(1, "key_facts", "The design review is on Friday.", ((0, 31),), [], "old",
                               gone=frozenset({"friday"}))
    lead = revision_prose.Passage(2, "summary", "alpha-project meets on Friday.", ((0, 30),), [], "old",
                                  gone=frozenset({"friday"}))
    job = revision_prose.Job("alpha-project", None, "alpha-project", {}, "", [p, lead], [change], [], {})
    edits, events, _ = revision_prose.decide(job, {"passages": [
        {"n": 1, "text": "The design review is on Friday, then Thursday."},   # keeps the old word
        {"n": 2, "text": ""},                                                 # a lead is never emptied
    ]})
    assert edits == {} and events == []
    edits, _, _ = revision_prose.decide(job, {"passages": [{"n": 1, "text": "The design review is on Thursday "
                                                                            "with Bob Example."}]})
    assert edits == {}                                                        # a name nobody gave
    edits, events, _ = revision_prose.decide(job, {"passages": [{"n": 1, "text": "The design review is on Thursday."}],
                                                   "history": [{"change": 1, "event": "It moved to Thursday."}]})
    assert edits == {1: "The design review is on Thursday."}
    # A History sentence that does not name what it was before gives way to Cicada's own plain line.
    assert events == ["An edited conversation changed “The alpha-project design review meeting is on Friday.” to "
                      "“The alpha-project design review meeting is on Thursday.”."]


def test_a_link_is_allowed_only_to_a_page_the_words_name(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "porto.md", {"name": "Porto", "type": "location"}, "## Summary\nA city.")
    rev = episode_revision.build({"id": EP["e"], "content": V2["e"]}, V1["e"])
    (change,) = revision_prose.changes_of(rev)
    p = revision_prose.Passage(1, "key_facts", "The demo is in [[Lisbon]].", ((0, 26),), [], "old",
                               gone=frozenset({"lisbon"}))
    job = revision_prose.Job("alpha-project", memory / "entities" / "alpha-project.md", "alpha-project", {}, "", [p],
                             [change], [], {})
    edits, _, _ = revision_prose.decide(job, {"passages": [{"n": 1, "text": "The demo is in [[Porto]]."}]})
    assert edits == {1: "The demo is in [[Porto]]."}
    job.refused.clear()
    edits, _, _ = revision_prose.decide(job, {"passages": [{"n": 1, "text": "The demo is in [[Porto]] at [[Gamma]]."}]})
    assert edits == {} and job.refused == {"new_name_or_link": 1}


def test_provenance_rows_move_onto_the_new_body(tmp_path):
    rev = episode_revision.build({"id": EP["d"], "content": V2["d"]}, V1["d"])
    start = V1["d"].index("licensed")
    span = Evidence(episode=EP["d"], start=start, end=start + 30, kind="user", hash=rev.prior_hash)
    whole = evidence.reasoning(EP["d"], hash=rev.prior_hash)
    moved = episode_revision.provenance_row(rev, span)
    assert moved.hash == rev.hash and V2["d"][moved.start:moved.end] == "licensed under  the MIT license"
    assert episode_revision.provenance_row(rev, whole) == evidence.reasoning(EP["d"], hash=rev.hash)
    assert episode_revision.provenance_row(rev, evidence.reasoning(EP["d"], hash="0" * 12)) is None


def test_a_held_claim_for_a_name_without_a_page_follows_its_words(tmp_path):
    """#581's "left" list: what a pending name holds keeps spans the revision still says, on the new body."""
    from api.services import pending_store
    from api.services.claims import Claim

    memory = _bank(tmp_path)
    rev = episode_revision.build({"id": EP["a"], "content": V2["a"]}, V1["a"])
    start = V1["a"].index("will use rustfft")
    span = Evidence(episode=EP["a"], start=start, end=start + 16, kind="user", hash=rev.prior_hash)
    held = Claim(id="clm_2026-11-01_aaaaaaaa", text="beta-tool uses rustfft", subject="beta-tool", predicate="uses",
                 object="rustfft", evidence=[span], source_episodes=[EP["a"]])
    line = pending_store.PendingEntity(name="beta-tool", type="tool", description="", source_episode=EP["a"],
                                       confidence=0.6, tags=[], history_entries=[], held_claims=[held.to_dict()])
    pending_store.save(memory, [line])
    moved = pending_store.reanchor_held(memory, lambda c: episode_revision.reanchor({"": c}, {EP["a"]: rev}).reanchored)
    assert moved == 1
    (ev,) = Claim.from_dict(pending_store.load(memory)[0].held_claims[0]).evidence
    assert ev.hash == rev.hash and V2["a"][ev.start:ev.end] == "will use rustfft"
    assert pending_store.reanchor_held(memory, lambda c: episode_revision.reanchor({"": c}, {EP["a"]: rev})
                                       .reanchored) == 0


def test_an_update_resting_only_on_a_correcting_revision_asks_no_contradiction(tmp_path, monkeypatch):
    """Stage 3: the source corrected itself, so the old page and the revision's words are no unresolvable conflict."""
    from datetime import datetime

    from api.services import conflict_resolver as cr
    from api.tests.test_sleep_call_batching import _answer as reply, _bank as pages, _updates

    root, existing = pages(tmp_path, 3)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    calls: list = []

    async def synth(**kw):
        return None

    async def engine(**kwargs):
        user = kwargs["messages"][-1]["content"]
        calls.append(user)
        blocks = user.split("ENTITY ")[1:]
        return reply(json.dumps({"results": [{"entity": k, "has_unresolvable_contradiction": True, "question": "Q?"}
                                             for k in range(1, len(blocks) + 1)]}))

    monkeypatch.setattr(cr, "_synthesize_entity_update", synth)
    monkeypatch.setattr(cr.litellm, "acompletion", engine)
    settings = Settings(_env_file=None, agent_max_concurrency=1, summary_synthesis_enabled=True)
    updates = _updates(3)
    for i, ep in ((1, "ep_2026-10-19_001"), (2, "ep_2026-10-18_002")):
        updates[i]["source_episode"] = ep
        updates[i]["source_episodes"] = [ep]
    changes = asyncio.run(cr.resolve_and_prune(updates, existing, settings, now=datetime(2026, 10, 20, 3),
                                               decay=False, tuning={},
                                               revised={"ep_2026-10-18_001": True, "ep_2026-10-18_002": False}))
    # page-0 rests only on a correcting revision: not checked. page-1 is another conversation, page-2 a revision that
    # only added lines: both asked as before.
    assert len(calls) == 1 and "Page 0" not in calls[0] and "Page 1" in calls[0] and "Page 2" in calls[0]
    assert [c["id"] for c in changes if c["action"] == "conflict_nudge"] == ["page-1", "page-2"]

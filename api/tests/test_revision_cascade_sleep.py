"""G104 slice 3 (T3), end to end through ``sleep_cycle.run``: a correction reaches what it touched.

Same harness as ``test_episode_revision_sleep``: Stage 1's real ``extract`` over a fake model, Stage 2/3/5 real, git and
the vector index faked. Synthetic names only."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from types import SimpleNamespace

from api.config import Settings
from api.services import bank_index, entity_extractor, evidence, markdown_parser, pending_store, sleep_cycle
from api.services.claims import parse_claims
from api.tests.test_sleep_cycle_hold import _bank, _patch, _settings

IDENT = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]


def _git(memory, *args):
    subprocess.run(["git", *args], cwd=memory, check=True, capture_output=True)


def _commit(memory, msg):
    _git(memory, *IDENT, "add", "-A")
    _git(memory, *IDENT, "commit", "-qm", msg, "--allow-empty")


def _digest(body: str) -> str:
    return "sha256:" + evidence.body_hash(body)


def _write(memory, ep, body, *, processed=False, revised=None, day=None):
    fm = {"id": ep, "processed": processed, "source": "note", "origin": "note", "source_id": f"note:test:{ep}",
          "timestamp": f"{ep[3:13]}T10:00:00Z", "content_hash": _digest(body)}
    if revised:
        fm["revised"] = revised
    markdown_parser.write(memory / "episodes" / f"{ep}.md", fm, body)


def _revise(memory, ep, old, new):
    _write(memory, ep, new, revised={"count": 1, "at": "2026-11-03T12:00:00Z", "previous_hash": _digest(old),
                                     "consolidated_hash": _digest(old)})


def _run(memory, monkeypatch, answer, prompts=None):
    async def fake_acompletion(**kw):
        content = kw["messages"][1]["content"]
        if prompts is not None:
            prompts.append(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer(content))))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", CICADA_MEMORY_PATH=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)
    bank_index.invalidate()
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g104_cascade"))
    bank_index.invalidate()


def _claims_of(memory, page):
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{page}.md").body)


# --------------------------------------------------------------------------- #
# the held-claim gap (benchmark U4): a date moves while its subject had no page
# --------------------------------------------------------------------------- #

EP_TRIP, EP_OTHER = "ep_2026-11-01_001", "ep_2026-11-02_001"
TRIP_V1 = "user: Notes.\nZed Unknown's trip starts on the 5th.\nalpha tasks continue."
TRIP_V2 = "user: Notes.\nZed Unknown's trip starts on the 12th.\nalpha tasks continue."
OTHER = "user: I met Zed Unknown again today."


def _trip_answer(chunk: str) -> dict:
    ents = {}
    vals = []
    if "Zed Unknown" in chunk:
        ents["Zed Unknown"] = {"name": "Zed Unknown", "type": "person", "confidence": 0.6, "summary": "A person."}
    if m := re.search(r"trip starts on the (\w+)", chunk):
        vals.append({"entity": "Zed Unknown", "attribute": "trip start", "value": m[1], "evidence_quote": m[0]})
    return {"entities": list(ents.values()), "relationships": [], "values": vals}


def test_a_held_claim_only_the_removed_text_said_does_not_reach_the_new_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _write(memory, EP_TRIP, TRIP_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _trip_answer)
    assert [e.name for e in pending_store.load(memory) if e.held_claims] == ["Zed Unknown"]
    _commit(memory, "Sleep cycle")                       # the version Sleep read is what git holds
    _revise(memory, EP_TRIP, TRIP_V1, TRIP_V2)           # the date moves; a second conversation names the subject
    _write(memory, EP_OTHER, OTHER)
    _run(memory, monkeypatch, _trip_answer)

    page = markdown_parser.parse(memory / "entities" / "zed-unknown.md")
    claims = parse_claims(page.body)
    open_values = sorted(c.object for c in claims if c.valid_to is None and c.predicate.startswith("value-of"))
    assert open_values == ["12th"]
    assert not [c for c in claims if c.object == "5th" and c.valid_to is None]
    assert pending_store.waiting(memory)[0] == 0


# --------------------------------------------------------------------------- a page only the removed text made

EP_MEET, EP_LUNCH = "ep_2026-11-03_001", "ep_2026-11-04_001"
ZED = "\n".join(f"user: Zed Unknown said thing {n} today.\nassistant: Noted {n}." for n in range(1, 6))
MEET_V1 = f"user: Notes.\nZed Unknown demoed the Gamma Board.\n{ZED}\nuser: alpha tasks continue."
MEET_V2 = "user: Notes.\nuser: alpha tasks continue."
LUNCH = "user: Zed Unknown came to lunch."


def _meet_answer(chunk: str) -> dict:
    ents, vals = {}, []
    if "Zed Unknown" in chunk:
        ents["Zed Unknown"] = {"name": "Zed Unknown", "type": "person", "confidence": 0.9, "summary": "A person."}
    if m := re.search(r"Zed Unknown demoed the Gamma Board", chunk):
        vals.append({"entity": "Zed Unknown", "attribute": "role", "value": "demoer", "evidence_quote": m[0]})
    return {"entities": list(ents.values()), "relationships": [], "values": vals}


def _meeting_bank(tmp_path, monkeypatch, *, lunch: bool = False):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    _write(memory, EP_MEET, MEET_V1)
    if lunch:
        _write(memory, EP_LUNCH, LUNCH)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _meet_answer)
    assert (memory / "entities" / "zed-unknown.md").is_file()
    _commit(memory, "Sleep cycle")
    return memory


def _ask(memory, item_id="inbox-050", **fm):
    base = {"kind": "clarification", "status": "pending", "priority": 0.5, "created_date": "2026-11-03",
            "entity_id": "zed-unknown", "entity_name": "Zed Unknown", "source_episode": EP_MEET}
    markdown_parser.write(memory / "inbox" / f"{item_id}.md", {**base, **fm}, "Who is Zed Unknown?")
    _commit(memory, "question")


def test_a_page_made_only_from_a_removed_line_is_archived_its_question_withdrawn_and_restoring_undoes_it(
        tmp_path, monkeypatch):
    memory = _meeting_bank(tmp_path, monkeypatch)
    _ask(memory)
    _revise(memory, EP_MEET, MEET_V1, MEET_V2)
    _run(memory, monkeypatch, _meet_answer)

    fm = markdown_parser.parse(memory / "entities" / "zed-unknown.md").frontmatter
    assert fm["status"] == "archived" and fm["archived_by"]["reason"] == "revision"
    assert fm["archived_by"]["episode"] == EP_MEET and fm["source_episodes"] == [EP_MEET]   # one conversation, once
    claims = _claims_of(memory, "zed-unknown")
    assert claims and all(c.valid_to is not None for c in claims)                          # closed, never deleted
    report = sleep_cycle._state.revision_cascade
    assert [r["page"] for r in report["pages_archived"]] == ["zed-unknown"]
    assert [q["item"] for q in report["questions"]] == ["inbox-050"]
    # The question was settled after the batch, by Sleep, through the person's own resolver.
    assert not (memory / "inbox" / "inbox-050.md").exists()
    record = markdown_parser.parse(memory / "inbox" / "settled" / "inbox-050.md").frontmatter["settled"]
    assert record["rule"] == "source_corrected"

    from api.services import revision_cascade

    revision_cascade.restore(memory, "zed-unknown")
    assert markdown_parser.parse(memory / "entities" / "zed-unknown.md").frontmatter["status"] == "active"


def test_the_same_page_with_a_second_conversation_is_kept(tmp_path, monkeypatch):
    memory = _meeting_bank(tmp_path, monkeypatch, lunch=True)
    _ask(memory)
    _revise(memory, EP_MEET, MEET_V1, MEET_V2)
    _run(memory, monkeypatch, _meet_answer)

    fm = markdown_parser.parse(memory / "entities" / "zed-unknown.md").frontmatter
    assert fm["status"] != "archived" and "archived_by" not in fm
    report = sleep_cycle._state.revision_cascade
    assert report["pages_archived"] == []
    assert [(r["page"], r["support"]) for r in report["pages_kept"]] == [("zed-unknown", "other_conversation")]
    assert report["pages_kept"][0]["claims"]
    assert (memory / "inbox" / "inbox-050.md").exists()          # the question stays: the page is not gone


# --------------------------------------------------------------------------- the held PROSE gap (benchmark, T6)

EP_PROSE, EP_PROSE_2 = "ep_2026-11-05_001", "ep_2026-11-06_001"
PROSE_V1 = "user: Notes.\nZed Unknown's trip starts on the 5th.\nZed Unknown is the sister of Dana Example.\nalpha tasks continue."
PROSE_V2 = "user: Notes.\nZed Unknown's trip starts on the 12th.\nZed Unknown is the sister of Dana Example.\nalpha tasks continue."


def _prose_answer(chunk: str) -> dict:
    """The first read says the old date in a summary, a key fact and a history entry; the unrelated fact is steady."""
    if "Zed Unknown" not in chunk:
        return {"entities": [], "relationships": [], "values": []}
    date = (re.search(r"trip starts on the (\w+)", chunk) or [None, ""])[1]
    facts = ["Zed Unknown is the sister of Dana Example."]
    history = []
    summary = "A person."
    if date:
        summary = f"Zed Unknown's trip starts on the {date}."
        facts.insert(0, f"The trip starts on the {date}.")
        history.append({"date": "2026-11-05", "event": f"Trip planned for the {date}."})
    return {"entities": [{"name": "Zed Unknown", "type": "person", "confidence": 0.6, "summary": summary,
                          "key_facts": facts, "history_entries": history}], "relationships": [], "values": []}


def test_held_prose_only_the_removed_text_said_does_not_seed_the_new_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _write(memory, EP_PROSE, PROSE_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _prose_answer)
    line = next(e for e in pending_store.load(memory) if e.name == "Zed Unknown")
    assert "5th" in line.summary and any("5th" in f for f in line.key_facts)    # the first read's prose is held
    assert any("5th" in h["event"] for h in line.history_entries)
    _commit(memory, "Sleep cycle")
    _revise(memory, EP_PROSE, PROSE_V1, PROSE_V2)
    _write(memory, EP_PROSE_2, OTHER, day=None)
    _run(memory, monkeypatch, _prose_answer)

    page = markdown_parser.parse(memory / "entities" / "zed-unknown.md")
    assert "5th" not in page.body and "5th" not in json.dumps(page.frontmatter, default=str)
    assert "12th" in page.body                                          # what the revision says now
    assert "sister of Dana Example" in page.body                        # an unchanged fact survives
    assert sleep_cycle._state.revision_cascade["held"]["prose_dropped"] == 3    # summary, key fact, history entry
    assert pending_store.waiting(memory)[0] == 0


# --------------------------------------------------------------------------- a date said on another line (benchmark U4)

EP_MOVE, EP_MOVE_2 = "ep_2026-11-07_001", "ep_2026-11-08_001"
MOVE_V1 = ("user: Mi hermana Lia Prueba se muda a Valencia para empezar un máster.\nassistant: Entiendo.\n"
           "user: El 5 de diciembre, cuando termine su contrato, se va.")
MOVE_V2 = MOVE_V1.replace("El 5 de diciembre", "El 12 de diciembre")
MOVE_OTHER = "user: Hablé otra vez con Lia Prueba hoy."


def _move_answer(chunk: str) -> dict:
    """The model puts the relationship's evidence on line 1 and its date from line 3 (what the benchmark measured)."""
    ents, rels = [], []
    if "Lia Prueba" in chunk:
        ents.append({"name": "Lia Prueba", "type": "person", "confidence": 0.6, "summary": "A person."})
    if "se muda a Valencia" in chunk:
        ents.append({"name": "Valencia", "type": "location", "confidence": 0.9, "summary": "A city."})
        rel = {"source": "Lia Prueba", "target": "Valencia", "label": "is moving to",
               "evidence_quote": "Lia Prueba se muda a Valencia"}
        if m := re.search(r"El (\d+) de diciembre", chunk):
            rel["starts"] = f"2026-12-{int(m[1]):02d}"
        rels.append(rel)
    return {"entities": ents, "relationships": rels, "values": []}


def _moving(memory):
    return [c for c in _claims_of(memory, "lia-prueba") if c.predicate == "is-moving-to"]


def _assert_redated(memory):
    claims = _moving(memory)
    open_ = [c for c in claims if c.valid_to is None]
    assert [c.valid_from for c in open_] == ["2026-12-12"]
    old = [c for c in claims if c.valid_from == "2026-12-05"]
    assert len(old) == 1 and old[0].valid_to is not None                  # closed, never deleted
    assert old[0].superseded_by == open_[0].id
    assert not [n for n in (memory / "inbox").glob("*.md") if "conflict" in n.read_text(encoding="utf-8")]


def test_a_date_said_on_another_line_than_its_evidence_is_corrected(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    for page, name, kind in (("lia-prueba", "Lia Prueba", "person"), ("valencia", "Valencia", "location")):
        markdown_parser.write(memory / "entities" / f"{page}.md",
                              {"name": name, "type": kind, "status": "active", "confidence": 0.9},
                              "## Summary\nSynthetic.\n")
    _write(memory, EP_MOVE, MOVE_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _move_answer)
    first = _moving(memory)
    assert [c.valid_from for c in first] == ["2026-12-05"]
    assert all(e.end <= len(MOVE_V1.split("\n", 1)[0]) for e in first[0].evidence if e.is_span())   # line 1 only
    _commit(memory, "Sleep cycle")
    _revise(memory, EP_MOVE, MOVE_V1, MOVE_V2)
    _run(memory, monkeypatch, _move_answer)
    _assert_redated(memory)


def test_a_held_claim_with_the_old_date_is_not_released_when_the_date_moved(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "valencia.md",
                          {"name": "Valencia", "type": "location", "status": "active", "confidence": 0.5},
                          "## Summary\nSynthetic.\n")
    _write(memory, EP_MOVE, MOVE_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _move_answer)
    held = [c for e in pending_store.load(memory) for c in e.held_claims]
    assert [c["valid_from"] for c in held] == ["2026-12-05"]                # held: Lia Prueba has no page yet
    _commit(memory, "Sleep cycle")
    _revise(memory, EP_MOVE, MOVE_V1, MOVE_V2)
    _write(memory, EP_MOVE_2, MOVE_OTHER)                                   # a second conversation births the page
    _run(memory, monkeypatch, _move_answer)
    assert (memory / "entities" / "lia-prueba.md").is_file()
    claims = _moving(memory)
    assert [c.valid_from for c in claims if c.valid_to is None] == ["2026-12-12"]
    assert not [c for c in claims if c.valid_from == "2026-12-05" and c.valid_to is None]
    assert pending_store.waiting(memory)[0] == 0


def test_a_held_claim_is_replaced_by_the_revisions_own_while_the_name_still_has_no_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "valencia.md",
                          {"name": "Valencia", "type": "location", "status": "active", "confidence": 0.5},
                          "## Summary\nSynthetic.\n")
    _write(memory, EP_MOVE, MOVE_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _move_answer)
    _commit(memory, "Sleep cycle")
    _revise(memory, EP_MOVE, MOVE_V1, MOVE_V2)
    _run(memory, monkeypatch, _move_answer)
    held = [c["valid_from"] for e in pending_store.load(memory) for c in e.held_claims]
    assert held == ["2026-12-12"]


def test_a_date_the_changed_lines_do_not_say_moves_nothing(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    for page, name, kind in (("lia-prueba", "Lia Prueba", "person"), ("valencia", "Valencia", "location")):
        markdown_parser.write(memory / "entities" / f"{page}.md",
                              {"name": name, "type": kind, "status": "active", "confidence": 0.9},
                              "## Summary\nSynthetic.\n")
    _write(memory, EP_MOVE, MOVE_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    _run(memory, monkeypatch, _move_answer)
    _commit(memory, "Sleep cycle")
    # The edit adds a line that says no date; the model (wrongly) still answers a date nothing changed says.
    _revise(memory, EP_MOVE, MOVE_V1, MOVE_V1 + "\nuser: Ya te cuento más.")

    def answer(chunk):
        out = _move_answer(chunk)
        for rel in out["relationships"]:
            rel["starts"] = "2026-12-19"
        return out

    _run(memory, monkeypatch, answer)
    assert [c.valid_from for c in _moving(memory) if c.valid_to is None] == ["2026-12-05"]


# --------------------------------------------------------------------------- a revision names the person the first read did

EP_SIS = "ep_2026-11-09_001"
SIS_V1 = ("user: Mi hermana Lucía se muda a Valencia para empezar un máster.\nassistant: Entiendo.\n"
          "user: El 5 de diciembre, cuando termine su contrato, se va.")
SIS_V2 = SIS_V1.replace("El 5 de diciembre", "El 12 de diciembre")


def _sister_answer(chunk: str, with_value: bool = True) -> dict:
    """The first read names her "Lucía"; the revision's re-read adds the model's trailing note, "Lucía (sister)".
    A value about the person is what the benchmark also held; one more line, it makes her page in this harness."""
    name = "Lucía (sister)" if "[Revision:" in chunk else "Lucía"
    ents, rels, vals = [], [], []
    if "Lucía" in chunk:
        ents.append({"name": name, "type": "person", "confidence": 0.6, "summary": "A person."})
    if "se muda a Valencia" in chunk:
        ents.append({"name": "Valencia", "type": "location", "confidence": 0.9, "summary": "A city."})
        rel = {"source": name, "target": "Valencia", "label": "is moving to",
               "evidence_quote": "Lucía se muda a Valencia"}
        if m := re.search(r"El (\d+) de diciembre", chunk):
            rel["starts"] = f"2026-12-{int(m[1]):02d}"
        rels.append(rel)
    if with_value and (m := re.search(r"El (\d+) de diciembre", chunk)):
        vals.append({"entity": name, "attribute": "move date", "value": f"{m[1]} December", "evidence_quote": m[0]})
    return {"entities": ents, "relationships": rels, "values": vals}


def _sister_moves(memory):
    return [c for c in _claims_of(memory, "lucía") if c.predicate == "is-moving-to"]


def _assert_sister_redated(memory):
    claims = _sister_moves(memory)
    open_ = [c for c in claims if c.valid_to is None]
    assert [c.valid_from for c in open_] == ["2026-12-12"]
    old = [c for c in claims if c.valid_from == "2026-12-05"]
    assert len(old) == 1 and old[0].valid_to is not None and old[0].superseded_by == open_[0].id
    assert not [e for e in pending_store.load(memory) if "sister" in e.name.casefold()]
    assert not [p for p in (memory / "entities").glob("*.md") if "sister" in p.stem]


def _sister_bank(tmp_path, *, page: bool):
    memory = _bank(tmp_path)
    pages = [("valencia", "Valencia", "location", 0.5)] + ([("lucía", "Lucía", "person", 0.9)] if page else [])
    for slug, name, kind, conf in pages:
        markdown_parser.write(memory / "entities" / f"{slug}.md",
                              {"name": name, "type": kind, "status": "active", "confidence": conf},
                              "## Summary\nSynthetic.\n")
    _write(memory, EP_SIS, SIS_V1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    return memory


def test_a_revision_naming_the_person_with_a_note_lands_on_the_page_the_first_read_made(tmp_path, monkeypatch):
    memory = _sister_bank(tmp_path, page=True)
    _run(memory, monkeypatch, _sister_answer)
    assert [c.valid_from for c in _sister_moves(memory)] == ["2026-12-05"]
    _commit(memory, "Sleep cycle")
    _revise(memory, EP_SIS, SIS_V1, SIS_V2)
    _run(memory, monkeypatch, _sister_answer)
    _assert_sister_redated(memory)


def test_a_revision_naming_a_held_person_with_a_note_replaces_the_held_claim(tmp_path, monkeypatch):
    memory = _sister_bank(tmp_path, page=False)
    _run(memory, monkeypatch, lambda chunk: _sister_answer(chunk, with_value=False))
    held = [(e.name, c["valid_from"]) for e in pending_store.load(memory) for c in e.held_claims
            if c.get("predicate") == "is-moving-to"]
    assert held == [("Lucía", "2026-12-05")]                                # held: no page yet
    _commit(memory, "Sleep cycle")
    _revise(memory, EP_SIS, SIS_V1, SIS_V2)
    _run(memory, monkeypatch, lambda chunk: _sister_answer(chunk, with_value=False))
    held = [(e.name, c["valid_from"]) for e in pending_store.load(memory) for c in e.held_claims
            if c.get("predicate") == "is-moving-to"]
    assert held == [("Lucía", "2026-12-12")]
    assert not [e for e in pending_store.load(memory) if "sister" in e.name.casefold()]

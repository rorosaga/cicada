"""An edited conversation's re-read words a claim's relationship under another predicate with the corrected day (G104,
2026-11-25, `revision_pairs`): the old claim is replaced only when the small judge and then the main model both call the
two the same relationship. Real Sleeps on a scratch bank; the extractor and both readers are scripted. Invented names."""
from __future__ import annotations

import re

import pytest

from api.services import markdown_parser, revision_pairs, telemetry
from api.services.claims import is_record
from api.tests.test_revision_cascade_sleep import _bank, _claims_of, _commit, _git, _revise, _run, _write

EP = "ep_2026-11-07_001"
OTHER = "ep_2026-11-08_001"
LIA = ("Date: 2026-11-07\nuser: My sister Lia Prueba moves to Valencia.\nassistant: Ok.\n"
       "user: She leaves on 5 December, when her contract ends.\nuser: Lia Prueba plays the piano.\nuser: Fin.")
MOVED = LIA.replace("5 December", "8 December")
VISIT = LIA.replace("She leaves on 5 December, when her contract ends.", "Her parents will visit Valencia on 12 December.")
GONE = LIA.replace("She leaves on 5 December, when her contract ends.", "She likes it there a lot.")


def _pages(memory):
    for page, name, kind in (("lia-prueba", "Lia Prueba", "person"), ("valencia", "Valencia", "location")):
        markdown_parser.write(memory / "entities" / f"{page}.md",
                              {"name": name, "type": kind, "status": "active", "confidence": 0.9}, "## Summary\nX.\n")


def lia(first="is moving to", reread="moves to", *, reread_empty=False, visit_label="visits"):
    """Night 1 reads the move under ``first``; a re-read (the chunk carries the revision note) words it ``reread``.
    A visit line, when the text has one, is read as its own relationship."""
    def answer(chunk: str) -> dict:
        is_reread = "[Revision:" in chunk
        if is_reread and reread_empty:
            return {"entities": [], "relationships": [], "values": []}
        ents, rels = [], []
        if "Lia Prueba" in chunk:
            ents.append({"name": "Lia Prueba", "type": "person", "confidence": 0.6, "summary": "A person."})
        if "Valencia" in chunk:
            ents.append({"name": "Valencia", "type": "location", "confidence": 0.9, "summary": "A city."})
        day = re.search(r"leaves on (\d+) December", chunk)
        if "moves to Valencia" in chunk and (day or not is_reread) and reread is not None:
            rel = {"source": "Lia Prueba", "target": "Valencia", "label": reread if is_reread else first,
                   "evidence_quote": "Lia Prueba moves to Valencia"}
            if day:
                rel["starts"] = f"2026-12-{int(day[1]):02d}"
            rels.append(rel)
        visit = re.search(r"visit Valencia on (\d+) December", chunk)
        if visit:
            rels.append({"source": "Lia Prueba", "target": "Valencia", "label": visit_label,
                         "starts": f"2026-12-{int(visit[1]):02d}",
                         "evidence_quote": f"Her parents will visit Valencia on {visit[1]} December"})
        vals = [{"entity": "Lia Prueba", "attribute": "instrument", "value": "piano",
                 "evidence_quote": "Lia Prueba plays the piano"}] if "plays the piano" in chunk else []
        return {"entities": ents, "relationships": rels, "values": vals}
    return answer


class Readers:
    """The two readers, scripted: ``small`` and ``main`` map a prompt's pair ids to an answer (or raise)."""

    def __init__(self, monkeypatch, small, main):
        self.small_calls: list[str] = []
        self.main_calls: list[str] = []
        self._small, self._main = small, main

        def judge_for(settings, *, main=False, stage="value_match"):
            if stage != revision_pairs.STAGE:
                return lambda prompt: {}
            calls, fn = (self.main_calls, self._main) if main else (self.small_calls, self._small)

            def judge(prompt):
                calls.append(prompt)
                return fn(prompt, re.findall(r"^(p\d+)$", prompt, re.M))
            return judge

        monkeypatch.setattr("api.services.value_alignment.judge_for", judge_for)


def always(answer):
    return lambda prompt, ids: {"pairs": [{"pair": p, "answer": answer} for p in ids]}


def raising(prompt, ids):
    raise RuntimeError("engine down")


def story(tmp_path, monkeypatch, nights, *, small=always("same"), main=always("same"), others=None):
    """``nights``: ``[(body, answer)]``; the first is read fresh, every later one is an edit of the one before."""
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    _pages(memory)
    body, answer = nights[0]
    _write(memory, EP, body)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    readers = Readers(monkeypatch, small, main)
    _run(memory, monkeypatch, answer)
    _commit(memory, "Sleep cycle")
    prior = body
    for i, (body, answer) in enumerate(nights[1:]):
        _revise(memory, EP, prior, body)
        if others and i in others:
            _write(memory, OTHER, others[i])
        _run(memory, monkeypatch, answer)
        _commit(memory, "Sleep cycle")
        prior = body
    return memory, readers


def _moves(memory):
    """(predicate, start, open, superseded_by) of every claim about Lia and Valencia, records left out."""
    return sorted((c.predicate, str(c.valid_from or "")[:10], c.valid_to is None, c.superseded_by, c.id)
                  for c in _claims_of(memory, "lia-prueba") if c.object == "valencia" and not is_record(c))


def _open_days(memory):
    return sorted(start for _p, start, is_open, _s, _i in _moves(memory) if is_open)


# --------------------------------------------------------------------------- #
# the shape this fixes, and each reading that must leave it alone
# --------------------------------------------------------------------------- #


def test_the_same_relationship_reworded_with_the_corrected_day_replaces_the_old_claim(tmp_path, monkeypatch):
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia())])
    rows = {p: (start, is_open, sup, cid) for p, start, is_open, sup, cid in _moves(memory)}
    assert rows["moves-to"][:3] == ("2026-12-08", True, None)
    assert rows["is-moving-to"][0] == "2026-12-05" and rows["is-moving-to"][1] is False
    assert rows["is-moving-to"][2] == rows["moves-to"][3]           # superseded by the re-read's own claim
    new = next(c for c in _claims_of(memory, "lia-prueba") if c.predicate == "moves-to")
    assert new.supersedes == rows["is-moving-to"][3]
    assert len(readers.small_calls) == 1 and len(readers.main_calls) == 1
    # A second run over the same state changes nothing and asks nothing.
    before = (memory / "entities" / "lia-prueba.md").read_text()
    _run(memory, monkeypatch, lia())
    assert (memory / "entities" / "lia-prueba.md").read_text() == before
    assert len(readers.small_calls) == 1


@pytest.mark.parametrize("small,main,main_called", [
    (always("different"), always("same"), False),
    (always("same"), always("different"), True),
    (always("Same."), always("same"), False),                                   # not exactly "same"
    (lambda p, ids: {"pairs": [{"pair": i, "answer": True} for i in ids]}, always("same"), False),
    (lambda p, ids: {"answers": "same"}, always("same"), False),
    (lambda p, ids: {"pairs": [{"pair": "p9", "answer": "same"}]}, always("same"), False),   # another pair's id
    (raising, always("same"), False),
    (always("same"), raising, True),
])
def test_anything_but_same_twice_leaves_both_claims_as_they_were(tmp_path, monkeypatch, small, main, main_called):
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia())], small=small, main=main)
    rows = {p: (start, is_open, sup) for p, start, is_open, sup, _i in _moves(memory)}
    assert rows == {"is-moving-to": ("2026-12-05", True, None), "moves-to": ("2026-12-08", True, None)}
    assert len(readers.small_calls) == 1
    assert bool(readers.main_calls) is main_called


def test_no_pair_makes_no_call(tmp_path, monkeypatch):
    # The same predicate again: the same-slot path replaces it, nothing is asked.
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia(reread="is moving to"))])
    assert _open_days(memory) == ["2026-12-08"]
    assert readers.small_calls == [] and readers.main_calls == []
    # The re-read wrote nothing for the move: nothing to pair, nothing closed (review 2, a3).
    memory, readers = story(tmp_path / "b", monkeypatch, [(LIA, lia()), (GONE, lia(reread_empty=True))])
    assert _open_days(memory) == ["2026-12-05"]
    assert readers.small_calls == []


def test_the_prompt_shows_both_facts_with_their_words_and_the_edit(tmp_path, monkeypatch):
    _memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia())], small=always("different"))
    (prompt,) = readers.small_calls
    assert prompt.startswith("[Edited conversation: same relationship?]")
    assert "EARLIER:" in prompt and "from 2026-12-05" in prompt and "NOW:" in prompt and "from 2026-12-08" in prompt
    assert 'recorded from: "Lia Prueba moves to Valencia"' in prompt
    assert "She leaves on 5 December" in prompt.split("WHAT THE EDIT PUT IN:")[0]
    assert "She leaves on 8 December" in prompt.split("WHAT THE EDIT PUT IN:")[1]


# --------------------------------------------------------------------------- #
# the reviewers' cases
# --------------------------------------------------------------------------- #


def test_a_visit_beside_a_move_stays_apart_on_an_honest_reading(tmp_path, monkeypatch):
    # review 2, b1: the day line becomes a visit to the same city; the re-read does not restate the move.
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (VISIT, lia())], small=always("different"))
    rows = {p: (start, is_open) for p, start, is_open, _s, _i in _moves(memory)}
    assert rows == {"is-moving-to": ("2026-12-05", True), "visits": ("2026-12-12", True)}
    assert len(readers.small_calls) == 1 and readers.main_calls == []


def test_a_visit_beside_a_move_under_readings_that_are_always_wrong_costs_one_superseded_claim(tmp_path, monkeypatch):
    # The worst case, bounded: the move is superseded by the visit claim of this same conversation about the same two
    # things, carrying a day the conversation states. Nothing else on the page or elsewhere moves.
    memory, _readers = story(tmp_path, monkeypatch, [(LIA, lia()), (VISIT, lia())])
    rows = {p: (start, is_open, sup, cid) for p, start, is_open, sup, cid in _moves(memory)}
    assert rows["visits"][:3] == ("2026-12-12", True, None)
    assert rows["is-moving-to"][1] is False and rows["is-moving-to"][2] == rows["visits"][3]
    piano = [c for c in _claims_of(memory, "lia-prueba") if "piano" in str(c.object)]
    assert piano and all(c.valid_to is None for c in piano)


def test_an_edit_and_its_undo_end_with_the_restored_day_current(tmp_path, monkeypatch):
    # review 3, s3 / s3b: the day line taken out (the re-read finds nothing), then the text restored.
    for name, undo in (("empty", lia(reread_empty=True)), ("full", lia()), ("original wording", lia(reread="is moving to"))):
        memory, _r = story(tmp_path / name.replace(" ", "_"), monkeypatch,
                           [(LIA, lia()), (GONE, lia(reread_empty=True)), (LIA, undo)])
        assert "2026-12-05" in _open_days(memory), name
        assert all(c.valid_from for c in _claims_of(memory, "lia-prueba") if c.object == "valencia")


def test_a_corrected_day_then_undone_in_another_wording_ends_on_the_restored_day(tmp_path, monkeypatch):
    # Night 2 rewords the move with the corrected day; night 3 restores the text and the re-read words it a third way.
    memory, _r = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia()), (LIA, lia(reread="relocates to"))])
    assert _open_days(memory) == ["2026-12-05"]


def test_a_conversation_read_the_same_night_that_says_the_old_relationship_keeps_it(tmp_path, monkeypatch):
    # review 3, s6: another conversation read in the same batch states the move with the old day.
    other = "Date: 2026-11-08\nuser: Lia Prueba moves to Valencia.\nuser: She leaves on 5 December.\nuser: Fin."
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia())], others={0: other})
    old = next(c for c in _claims_of(memory, "lia-prueba") if c.predicate == "is-moving-to")
    assert OTHER in old.source_episodes and old.valid_to is None and old.valid_from[:10] == "2026-12-05"
    assert len(readers.main_calls) == 1          # it was judged the same; the close was refused when applied


def test_a_held_claim_is_never_paired(tmp_path, monkeypatch):
    # review 3, s8: a name with no page holds its claim; the edit moves the day; nothing held changes or is asked.
    from api.services import pending_store

    z1 = "user: Notes.\nZed Unknown moves to Lisbon.\nHe leaves on 5 December.\nalpha tasks continue."
    z2 = z1.replace("5 December", "9 December")

    def zed(label):
        def answer(chunk):
            ents, rels = [], []
            if "Zed Unknown" in chunk:
                ents.append({"name": "Zed Unknown", "type": "person", "confidence": 0.6, "summary": "A person."})
            day = re.search(r"leaves on (\d+) December", chunk)
            if "moves to Lisbon" in chunk and day:
                rels.append({"source": "Zed Unknown", "target": "Lisbon", "starts": f"2026-12-{int(day[1]):02d}",
                             "label": label if "[Revision:" in chunk else "is moving to",
                             "evidence_quote": "Zed Unknown moves to Lisbon"})
            return {"entities": ents, "relationships": rels, "values": []}
        return answer

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    _write(memory, EP, z1)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    readers = Readers(monkeypatch, always("same"), always("same"))
    _run(memory, monkeypatch, zed("moves to"))
    _commit(memory, "c")
    held_before = [c for line in pending_store.load(memory) for c in line.held_claims]
    _revise(memory, EP, z1, z2)
    _run(memory, monkeypatch, zed("moves to"))
    assert readers.small_calls == []
    assert held_before, "the first night held the claim"


def test_forty_claims_dated_from_one_line_none_closed_without_a_reread_claim(tmp_path, monkeypatch):
    # review 2, f1: forty relationships dated from one line; the line changes; the re-read restates none of them.
    places = [f"Place{i}" for i in range(40)]
    body1 = "user: Lia Prueba visits " + ", ".join(places) + ".\nuser: All on 5 December.\nuser: Fin."
    body2 = body1.replace("5 December", "6 December")

    def answer(chunk):
        if "[Revision:" in chunk:
            return {"entities": [], "relationships": [], "values": []}
        ents = [{"name": "Lia Prueba", "type": "person", "confidence": 0.6, "summary": "A person."}]
        rels = [{"source": "Lia Prueba", "target": p, "label": "visits", "starts": "2026-12-05",
                 "evidence_quote": "Lia Prueba visits"} for p in places]
        return {"entities": ents, "relationships": rels, "values": []}

    memory, readers = story(tmp_path, monkeypatch, [(body1, answer), (body2, answer)])
    assert readers.small_calls == []
    claims = [c for c in _claims_of(memory, "lia-prueba") if c.predicate == "visits"]
    assert claims and all(c.valid_to is None for c in claims)


# --------------------------------------------------------------------------- #
# the replacement's own guards, engine-free
# --------------------------------------------------------------------------- #


def _claim(cid, predicate, start, *, episodes=(EP,), **kw):
    from api.services.claims import Claim, Evidence

    return Claim(id=cid, text=f"Lia {predicate} Valencia", subject="lia-prueba", predicate=predicate,
                 object="valencia", valid_from=start, source_episodes=list(episodes),
                 evidence=[Evidence(episode=e, start=0, end=5, kind="user", hash="h") for e in episodes], **kw)


def _rev():
    from api.services import episode_revision

    return episode_revision.build({"id": EP, "content": MOVED, "source": "note"}, LIA)


def _verdict(**kw):
    base = dict(episode=EP, old_id="old", subject="lia-prueba", context="general", observer="agent",
                predicate="moves-to", object="valencia", valid_from="2026-12-08", expected_end="")
    return revision_pairs.Verdict(**{**base, **kw})


def test_apply_replaces_only_with_an_open_claim_that_carries_the_judged_day():
    rev = _rev()
    assert rev is not None and rev.changed
    for label, new_kw, verdict_kw in [
        ("closed later", {"valid_to": "2026-12-09"}, {}),
        ("superseded", {"superseded_by": "x"}, {}),
        ("already replaces another", {"supersedes": "y"}, {}),
        ("another day", {}, {"valid_from": "2026-12-09"}),
        ("the new claim carries another day", {"start": "2026-12-05"}, {}),
        ("another object", {}, {"object": "madrid"}),
        ("another predicate", {}, {"predicate": "visits"}),
        ("not this conversation", {"episodes": (OTHER,)}, {}),
    ]:
        old = _claim("old", "is-moving-to", "2026-12-05")
        new = _claim("new", "moves-to", new_kw.pop("start", "2026-12-08"), **new_kw)
        audit: list[dict] = []
        assert revision_pairs.apply({"lia-prueba": [old, new]}, [_verdict(**verdict_kw)], {EP: rev}, audit) == {}, label
        assert old.valid_to is None and old.superseded_by is None, label
    old, new = _claim("old", "is-moving-to", "2026-12-05"), _claim("new", "moves-to", "2026-12-08")
    audit = []
    assert revision_pairs.apply({"lia-prueba": [old, new]}, [_verdict()], {EP: rev}, audit) == {"old": EP}
    assert (old.valid_to, old.superseded_by, new.supersedes) == ("2026-12-08", "new", "old")
    assert audit == [{"action": "revised", "closed": "old", "by": "new", "why": revision_pairs.WHY}]


def test_apply_never_closes_what_another_conversation_or_the_person_also_holds():
    rev = _rev()
    for label, old in [
        ("another conversation", _claim("old", "is-moving-to", "2026-12-05", episodes=(EP, OTHER))),
        ("the person's own", _claim("old", "is-moving-to", "2026-12-05", source_trust="user_stated",
                                    origin="manual_edit")),
        ("an agent's write", _claim("old", "is-moving-to", "2026-12-05", recorded_ts="2026-11-07T10:00:00Z")),
    ]:
        new = _claim("new", "moves-to", "2026-12-08")
        audit: list[dict] = []
        assert revision_pairs.apply({"lia-prueba": [old, new]}, [_verdict()], {EP: rev}, audit) == {}, label
        assert old.valid_to is None, label


def test_one_new_claim_replaces_one_old_claim_and_a_transcript_none():
    rev = _rev()
    a, b = _claim("a", "is-moving-to", "2026-12-05"), _claim("b", "relocates-to", "2026-12-05")
    new = _claim("new", "moves-to", "2026-12-08")
    out = revision_pairs.apply({"lia-prueba": [a, b, new]}, [_verdict(old_id="a"), _verdict(old_id="b")],
                               {EP: rev}, [])
    assert out == {"a": EP} and b.valid_to is None
    rev.closes = False
    a, new = _claim("a", "is-moving-to", "2026-12-05"), _claim("new", "moves-to", "2026-12-08")
    assert revision_pairs.apply({"lia-prueba": [a, new]}, [_verdict(old_id="a")], {EP: rev}, []) == {}


def test_the_replacement_is_kept_in_the_ledger_with_its_reason(monkeypatch):
    seen = []
    monkeypatch.setattr(telemetry, "record", lambda event: seen.append(event.refs))
    telemetry.record_audit([{"action": "revised", "closed": "old", "by": "new", "why": revision_pairs.WHY}],
                           subject_hint="lia-prueba", bank="b")
    assert seen == [{"action": "revised", "subject": "lia-prueba", "closed": "old", "by": "new",
                     "why": revision_pairs.WHY}]


def test_the_reading_is_metered_on_the_line():
    from api.services import sleep_spend

    assert revision_pairs.STAGE in sleep_spend.LINE_STAGES



@pytest.mark.xfail(strict=True, reason="An exact restatement of a closed claim folds into it (`_reread_twin`, a claim id "
                   "carries its day) and nothing may reopen it: the restored day stays closed. origin/dev leaves both "
                   "days current here; its own same-slot path ends like this when the re-read keeps its wording.")
def test_a_reworded_correction_undone_in_the_first_wording_ends_on_the_restored_day(tmp_path, monkeypatch):
    memory, _r = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia()), (LIA, lia(reread="is moving to"))])
    assert "2026-12-05" in _open_days(memory)


def test_a_rewording_with_the_day_it_already_had_asks_nothing(tmp_path, monkeypatch):
    reworded = LIA.replace("when her contract ends.", "when her contract ends, she says.")
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (reworded, lia())])
    assert readers.small_calls == []
    assert ("is-moving-to", "2026-12-05", True) in [r[:3] for r in _moves(memory)]


def test_a_day_the_changed_lines_do_not_say_moves_nothing(tmp_path, monkeypatch):
    # The re-read restates the move with a day nobody wrote (the edit only reworded the move's own line).
    reworded = LIA.replace("moves to Valencia.", "moves to Valencia soon.")

    def answer(chunk):
        out = lia()(chunk)
        for rel in out["relationships"]:
            if "[Revision:" in chunk:
                rel.update(label="moves to", starts="2026-12-06")
        return out

    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (reworded, answer)])
    assert readers.small_calls == []
    assert ("is-moving-to", "2026-12-05", True) in [r[:3] for r in _moves(memory)]


def test_the_pairs_a_revision_reads_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(revision_pairs, "MAX_PAIRS", 1)

    def twice(chunk):
        out = lia()(chunk)
        if "[Revision:" not in chunk:
            out["relationships"] += [{**r, "label": "relocates to"} for r in out["relationships"]]
        return out

    memory, readers = story(tmp_path, monkeypatch, [(LIA, twice), (MOVED, lia())])
    (prompt,) = readers.small_calls
    assert re.findall(r"^(p\d+)$", prompt, re.M) == ["p1"]
    assert len([r for r in _moves(memory) if r[2] and r[1] == "2026-12-05"]) == 1


def _run_drain(memory, monkeypatch, answer):
    """``_run`` as a drain: the write window opens at each batch's Stage 2, as on every real run."""
    import asyncio
    import json
    from types import SimpleNamespace

    from api.config import Settings
    from api.services import bank_index, entity_extractor, sleep_cycle
    from api.tests.test_sleep_cycle_hold import _patch, _settings

    async def fake_acompletion(**kw):
        content = kw["messages"][1]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer(content))))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", CICADA_MEMORY_PATH=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)
    bank_index.invalidate()
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g104_pairs", drain=True))
    bank_index.invalidate()


def test_the_readings_are_made_outside_the_write_window(tmp_path, monkeypatch):
    from api.services import sleep_cycle

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    _pages(memory)
    _write(memory, EP, LIA)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    writing: list[bool] = []

    def reader(prompt, ids):
        writing.append(sleep_cycle.is_writing())
        return always("same")(prompt, ids)

    Readers(monkeypatch, reader, reader)
    _run_drain(memory, monkeypatch, lia())
    _commit(memory, "Sleep cycle")
    _revise(memory, EP, LIA, MOVED)
    _run_drain(memory, monkeypatch, lia())
    assert writing == [False, False]
    assert _open_days(memory) == ["2026-12-08"]


def test_a_value_or_another_object_is_never_paired(tmp_path, monkeypatch):
    # The first read held the destination as a stated value, and the re-read dates a move to another city: neither is
    # the re-read claim's pair, so nothing is asked.
    def first(chunk):
        out = lia()(chunk)
        if "[Revision:" not in chunk:
            out["relationships"] = []
            out["values"].append({"entity": "Lia Prueba", "attribute": "destination", "value": "Valencia",
                                  "evidence_quote": "Lia Prueba moves to Valencia"})
        return out

    memory, readers = story(tmp_path, monkeypatch, [(LIA, first), (MOVED, lia())])
    assert readers.small_calls == []
    assert any(c.predicate.startswith("value-of-") and c.valid_to is None for c in _claims_of(memory, "lia-prueba"))

    def elsewhere(chunk):
        out = lia()(chunk)
        if "[Revision:" in chunk:
            for rel in out["relationships"]:
                rel["target"] = "Madrid"
            out["entities"].append({"name": "Madrid", "type": "location", "confidence": 0.9, "summary": "A city."})
        return out

    _memory, readers = story(tmp_path / "b", monkeypatch, [(LIA, lia()), (MOVED, elsewhere)])
    assert readers.small_calls == []

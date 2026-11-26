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
    return sorted(((c.predicate, str(c.valid_from or "")[:10], c.valid_to is None, c.superseded_by, c.id)
                   for c in _claims_of(memory, "lia-prueba") if c.object == "valencia" and not is_record(c)),
                  key=lambda row: tuple(str(x) for x in row))


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


# --------------------------------------------------------------------------- #
# a claim wherever it waits: held under a name with no page yet, or released onto its page in the same pass
# (the benchmark's U4: the person's page did not exist when the edit was read)
# --------------------------------------------------------------------------- #

Z1 = "user: Notes.\nZed Unknown moves to Lisbon.\nHe leaves on 5 December.\nalpha tasks continue."
Z2 = Z1.replace("5 December", "9 December")
Z_EMPTY = Z1.replace("He leaves on 5 December.", "He likes it there.")
Z_MET = "user: I met Zed Unknown again today."
Z_SAYS_OLD = "user: Zed Unknown moves to Lisbon.\nuser: He leaves on 5 December, he told me."
ZED_PAGE = "zed-unknown"


def zed(first="is moving to", reread="moves to", *, reread_empty=False):
    """Night 1 reads the move under ``first``; a re-read (the chunk carries the revision note) words it ``reread``."""
    def answer(chunk: str) -> dict:
        is_reread = "[Revision:" in chunk
        if is_reread and reread_empty:
            return {"entities": [], "relationships": [], "values": []}
        ents, rels = [], []
        if "Zed Unknown" in chunk:
            ents.append({"name": "Zed Unknown", "type": "person", "confidence": 0.6, "summary": "A person."})
        day = re.search(r"leaves on (\d+) December", chunk)
        if "moves to Lisbon" in chunk and day:
            rels.append({"source": "Zed Unknown", "target": "Lisbon", "starts": f"2026-12-{int(day[1]):02d}",
                         "label": reread if is_reread else first, "evidence_quote": "Zed Unknown moves to Lisbon"})
        return {"entities": ents, "relationships": rels, "values": []}
    return answer


class Ledger:
    """What the ledger keeps of a replacement (`telemetry.record_audit`), and the Corrections record each batch made."""

    def __init__(self, monkeypatch):
        from api.services import corrections_record

        self.rows: list[dict] = []
        self.records: list[dict] = []
        monkeypatch.setattr(telemetry, "record", lambda event: self.rows.append(dict(event.refs or {})))
        real = corrections_record.batch_entry

        def batch_entry(*a, **kw):
            entry = real(*a, **kw)
            if entry:
                self.records.append(entry)
            return entry
        monkeypatch.setattr(corrections_record, "batch_entry", batch_entry)

    def revised(self):
        return [r for r in self.rows if r.get("action") == "revised"]


def zed_story(tmp_path, monkeypatch, nights, *, small=always("same"), main=always("same"), others=None):
    """``nights``: ``[(body, answer)]``, the first read fresh and every later one an edit of the one before; ``others``:
    ``{night index: body}`` of a second conversation read that night (it names Zed again, so his page is made)."""
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    body, answer = nights[0]
    _write(memory, EP, body)
    _git(memory, "init", "-q")
    _commit(memory, "capture")
    readers = Readers(monkeypatch, small, main)
    ledger = Ledger(monkeypatch)
    _run(memory, monkeypatch, answer)
    _commit(memory, "Sleep cycle")
    prior = body
    for i, (body, answer) in enumerate(nights[1:], 1):
        if body != prior:
            _revise(memory, EP, prior, body)
        if others and i in others:
            _write(memory, f"ep_2026-11-0{7 + i}_002", others[i])
        _run(memory, monkeypatch, answer)
        _commit(memory, "Sleep cycle")
        prior = body
    return memory, readers, ledger


def _line(memory):
    from api.services import pending_store

    return next((e for e in pending_store.load(memory) if e.name == "Zed Unknown"), None)


def _held_moves(memory):
    """(predicate, start, episodes, id) of each claim the line holds about Lisbon."""
    line = _line(memory)
    return sorted((d["predicate"], str(d.get("valid_from") or "")[:10], tuple(d.get("source_episodes") or ()), d["id"])
                  for d in (line.held_claims if line else []) if d.get("object") == "lisbon")


def _page_moves(memory):
    """(predicate, start, open, superseded_by, id, supersedes, valid_to) of each claim Zed's page holds about Lisbon."""
    if not (memory / "entities" / f"{ZED_PAGE}.md").is_file():
        return []
    return sorted(((c.predicate, str(c.valid_from or "")[:10], c.valid_to is None, c.superseded_by, c.id, c.supersedes,
                    str(c.valid_to or "")[:10])
                   for c in _claims_of(memory, ZED_PAGE) if c.object == "lisbon" and not is_record(c)),
                  key=lambda row: tuple(str(x) for x in row))


def test_a_held_claim_reworded_with_the_corrected_day_gives_way_in_its_line(tmp_path, monkeypatch):
    # 6a, 6b and a second run: the name has no page; the re-read's claim is held in the same line, so the old one leaves.
    memory, readers, ledger = zed_story(tmp_path, monkeypatch, [(Z1, zed()), (Z2, zed())])
    assert not (memory / "entities" / f"{ZED_PAGE}.md").is_file(), "the name still has no page"
    (kept,) = _held_moves(memory)
    assert kept[:3] == ("moves-to", "2026-12-09", (EP,))
    assert len(readers.small_calls) == 1 and len(readers.main_calls) == 1
    # 6b: recorded where the page path's replacement is — the ledger, with its reason, and the Corrections record.
    (row,) = ledger.revised()
    assert row == {"action": "revised", "subject": ZED_PAGE, "closed": row["closed"], "by": kept[3],
                   "why": revision_pairs.WHY, "held": True}
    assert row["closed"].startswith("clm_2026-12-05_")
    assert ledger.records and ledger.records[-1]["claims_superseded"] == 1 and EP in ledger.records[-1]["revised"]
    # A second run over the same state changes nothing and asks nothing.
    store = (memory / "pending_entities.jsonl").read_text()
    _run(memory, monkeypatch, zed())
    assert (memory / "pending_entities.jsonl").read_text() == store and len(readers.small_calls) == 1
    # Promoted later (a second conversation names him): the page is born from the line as it now stands; the record
    # stays in the ledger, which a promotion never deletes; nothing is dated a day nobody said (6c).
    _write(memory, OTHER, Z_MET)
    _run(memory, monkeypatch, zed())
    _commit(memory, "Sleep cycle")
    moves = _page_moves(memory)
    assert [(p, start, is_open) for p, start, is_open, *_ in moves] == [("moves-to", "2026-12-09", True)]
    assert _line(memory) is None, "the line was released with its page"
    assert len(ledger.revised()) == 1
    page = (memory / "entities" / f"{ZED_PAGE}.md").read_text()
    _run(memory, monkeypatch, zed())
    assert (memory / "entities" / f"{ZED_PAGE}.md").read_text() == page


@pytest.mark.parametrize("small,main", [
    (always("different"), always("same")),
    (always("same"), always("different")),
    (lambda p, ids: {"pairs": "same"}, always("same")),
    (raising, always("same")),
    (always("same"), raising),
], ids=["first-different", "second-different", "unreadable", "first-raises", "second-raises"])
def test_a_held_claim_stays_held_on_anything_but_same_twice(tmp_path, monkeypatch, small, main):
    memory, readers, ledger = zed_story(tmp_path, monkeypatch, [(Z1, zed()), (Z2, zed())], small=small, main=main)
    assert [(p, start) for p, start, *_ in _held_moves(memory)] == [("is-moving-to", "2026-12-05"),
                                                                     ("moves-to", "2026-12-09")]
    assert not ledger.revised()


def test_a_held_claim_released_in_the_same_pass_gives_way_on_its_new_page(tmp_path, monkeypatch):
    # U4's shape: the edit is read the night the name gets its page; the old claim leaves the line and the re-read's
    # claim lands on the page in the same pass. 6c: the released claim keeps its own day; it is closed on the day the
    # conversation now states.
    memory, readers, ledger = zed_story(tmp_path, monkeypatch, [(Z1, zed()), (Z2, zed())], others={1: Z_MET})
    rows = {p: rest for p, *rest in _page_moves(memory)}
    assert set(rows) == {"is-moving-to", "moves-to"}
    old_start, old_open, old_by, old_id, _sup, old_to = rows["is-moving-to"]
    new_start, new_open, new_by, new_id, new_sup, _to = rows["moves-to"]
    assert (old_start, old_open, old_to, old_by) == ("2026-12-05", False, "2026-12-09", new_id)
    assert (new_start, new_open, new_by, new_sup) == ("2026-12-09", True, None, old_id)
    assert _line(memory) is None, "the line was released with its page"
    assert len(readers.main_calls) == 1
    assert [r["why"] for r in ledger.revised()] == [revision_pairs.WHY] and "held" not in ledger.revised()[0]
    page = (memory / "entities" / f"{ZED_PAGE}.md").read_text()
    _run(memory, monkeypatch, zed())
    assert (memory / "entities" / f"{ZED_PAGE}.md").read_text() == page and len(readers.small_calls) == 1


@pytest.mark.parametrize("small,main,main_calls", [
    (always("different"), always("same"), 0),
    (always("same"), always("different"), 1),
    (lambda p, ids: {"pairs": "same"}, always("same"), 0),
    (raising, always("same"), 0),
    (always("same"), raising, 1),
], ids=["first-different", "second-different", "unreadable", "first-raises", "second-raises"])
def test_a_released_claim_stays_open_on_anything_but_same_twice(tmp_path, monkeypatch, small, main, main_calls):
    memory, readers, ledger = zed_story(tmp_path, monkeypatch, [(Z1, zed()), (Z2, zed())], others={1: Z_MET},
                                        small=small, main=main)
    assert [(p, start, is_open) for p, start, is_open, *_ in _page_moves(memory)] == [
        ("is-moving-to", "2026-12-05", True), ("moves-to", "2026-12-09", True)]
    assert not ledger.revised() and len(readers.small_calls) == 1 and len(readers.main_calls) == main_calls


def test_a_conversation_read_the_same_night_that_says_the_old_held_claim_keeps_it(tmp_path, monkeypatch):
    # 6d (review 3, s6, on a held claim): another conversation read the night of the edit says the old day; it is
    # judged the same and refused when applied — the old claim stays open, with both conversations as its support.
    memory, readers, ledger = zed_story(tmp_path, monkeypatch, [(Z1, zed()), (Z2, zed())], others={1: Z_SAYS_OLD})
    rows = {p: rest for p, *rest in _page_moves(memory)}
    assert tuple(rows["is-moving-to"][:2]) == ("2026-12-05", True) and tuple(rows["moves-to"][:2]) == ("2026-12-09", True)
    old = next(c for c in _claims_of(memory, ZED_PAGE) if c.predicate == "is-moving-to")
    assert set(old.source_episodes) == {EP, "ep_2026-11-08_002"}
    assert len(readers.main_calls) == 1 and not ledger.revised()


@pytest.mark.parametrize("third", ["is moving to", "moves to", "relocates to"])
@pytest.mark.parametrize("promote", [False, True], ids=["held", "released-on-the-third-night"])
def test_an_edit_undone_while_held_ends_on_the_restored_day_alone(tmp_path, monkeypatch, third, promote):
    # The review story `undone` with no page: A, B, A. The old claim left the line whole, so the restore is a new claim
    # that meets the correction by the pair rule (or the same-slot rule when the wording is the same); no third rule.
    nights = [(Z1, zed()), (Z2, zed()), (Z1, zed(reread=third))]
    memory, readers, ledger = zed_story(tmp_path, monkeypatch, nights, others={2: Z_MET} if promote else None)
    if promote:
        assert [(p, start) for p, start, is_open, *_ in _page_moves(memory) if is_open] == [(
            third.replace(" ", "-"), "2026-12-05")]
    else:
        assert [(p, start) for p, start, *_ in _held_moves(memory)] == [(third.replace(" ", "-"), "2026-12-05")]


def test_a_held_claim_the_reread_says_nothing_of_keeps_its_own_day_when_released(tmp_path, monkeypatch):
    # review 3, s8 (6c): the day line is replaced and the re-read writes nothing for the move: nothing is dropped,
    # nothing asked; released later, the claim keeps the day it was heard with, never the run's day.
    memory, readers, ledger = zed_story(tmp_path, monkeypatch,
                                        [(Z1, zed()), (Z_EMPTY, zed(reread_empty=True)), (Z_EMPTY, zed())],
                                        others={2: Z_MET})
    assert readers.small_calls == [] and not ledger.revised()
    assert [(p, start, is_open) for p, start, is_open, *_ in _page_moves(memory)] == [
        ("is-moving-to", "2026-12-05", True)]


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


def _claim(cid, predicate, start, *, episodes=(EP,), subject="lia-prueba", **kw):
    from api.services.claims import Claim, Evidence

    return Claim(id=cid, text=f"Lia {predicate} Valencia", subject=subject, predicate=predicate,
                 object="valencia", valid_from=start, source_episodes=list(episodes),
                 evidence=[Evidence(episode=e, start=0, end=5, kind="user", hash="h") for e in episodes], **kw)


def _rev():
    from api.services import episode_revision

    return episode_revision.build({"id": EP, "content": MOVED, "source": "note"}, LIA)


def _verdict(**kw):
    base = dict(episode=EP, old_id="old", subject="lia-prueba", context="general", observer="agent",
                predicate="moves-to", object="valencia", valid_from="2026-12-08", expected_end="",
                old_subject="lia-prueba", old_object="valencia", old_from="2026-12-05", old_end="")
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
        ("about another subject", {"subject": "lia-otra"}, {}),
        ("a judged day the changed lines do not say", {"start": "2026-12-07"}, {"valid_from": "2026-12-07"}),
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


# --------------------------------------------------------------------------- #
# edited back (2026-11-25): a claim closed only by this conversation's own correction, said again, is current again
# --------------------------------------------------------------------------- #

TENTH = LIA.replace("5 December", "10 December")


def _walk(memory):
    """Every claim about Lia and Valencia, its ``superseded_by`` chain walked to its end: the chain never revisits a
    claim, each link's ``supersedes`` points back, and exactly one claim is current. Returns the chain from the first
    claim, as (start, open) per link."""
    claims = {c.id: c for c in _claims_of(memory, "lia-prueba") if c.object == "valencia" and not is_record(c)}
    assert len(claims) == len([c for c in _claims_of(memory, "lia-prueba") if c.object == "valencia"
                               and not is_record(c)]), "an id is doubled"
    for start in claims.values():
        seen, link = {start.id}, start
        while link.superseded_by:
            nxt = claims[link.superseded_by]
            assert nxt.id not in seen, "a loop in superseded_by"
            assert nxt.supersedes == link.id, "supersedes does not point back"
            seen.add(nxt.id)
            link = nxt
        seen, link = {start.id}, start
        while link.supersedes:
            prev = claims[link.supersedes]
            assert prev.id not in seen, "a loop in supersedes"
            seen.add(prev.id)
            link = prev
    first = next(c for c in claims.values() if not c.supersedes)
    chain, link = [], first
    while link is not None:
        chain.append((str(link.valid_from)[:10], link.valid_to is None))
        link = claims.get(link.superseded_by or "")
    return chain


def test_a_reworded_correction_undone_in_the_first_wording_ends_on_the_restored_day(tmp_path, monkeypatch):
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia()), (LIA, lia(reread="is moving to"))])
    assert _open_days(memory) == ["2026-12-05"]
    assert _walk(memory) == [("2026-12-05", False), ("2026-12-08", False), ("2026-12-05", True)]
    assert len(readers.main_calls) == 2          # the pair rule closed the correction, read twice, as on night 2
    # The history readers: each closed claim reads as superseded on its day, the restated one as current.
    from api.services import mcp_tools

    page = _claims_of(memory, "lia-prueba")
    lines = sorted(mcp_tools._history_line("lia-prueba", c, page) for c in page
                   if c.object == "valencia" and c.valid_to and not is_record(c))
    assert lines == ['- `lia-prueba` is-moving-to: "valencia" — superseded on 2026-12-08',
                     '- `lia-prueba` moves-to: "valencia" — superseded on 2026-12-08']
    assert [c.predicate for c in page if c.object == "valencia" and c.valid_to is None
            and not is_record(c)] == ["is-moving-to"]
    before = (memory / "entities" / "lia-prueba.md").read_text()
    _run(memory, monkeypatch, lia(reread="is moving to"))
    assert (memory / "entities" / "lia-prueba.md").read_text() == before


def test_the_same_wording_edited_back_ends_on_the_restored_day(tmp_path, monkeypatch):
    # origin/dev's own same-slot path (`redated`), the re-read keeping its wording: it ended on the edited day alone.
    same = lia(reread="is moving to")
    memory, readers = story(tmp_path, monkeypatch, [(LIA, same), (MOVED, same), (LIA, same)])
    assert _open_days(memory) == ["2026-12-05"]
    assert _walk(memory) == [("2026-12-05", False), ("2026-12-08", False), ("2026-12-05", True)]
    assert readers.small_calls == []              # the same slot: nothing is read


@pytest.mark.parametrize("reread", ["moves to", "is moving to"])
@pytest.mark.parametrize("bodies,last", [
    ((MOVED, LIA, MOVED), "2026-12-08"),           # A, B, A, B
    ((MOVED, LIA, MOVED, LIA), "2026-12-05"),      # A, B, A, B, A
    ((MOVED, TENTH), "2026-12-10"),                # A, B, C
    ((MOVED, LIA, TENTH), "2026-12-10"),           # A, B, A, C
])
def test_edits_back_and_forth_end_on_the_last_texts_day_alone(tmp_path, monkeypatch, bodies, last, reread):
    memory, _r = story(tmp_path, monkeypatch, [(LIA, lia())] + [(b, lia(reread=reread)) for b in bodies])
    assert _open_days(memory) == [last]
    chain = _walk(memory)
    assert chain[-1] == (last, True) and all(not is_open for _d, is_open in chain[:-1])
    before = (memory / "entities" / "lia-prueba.md").read_text()
    _run(memory, monkeypatch, lia(reread=reread))
    assert (memory / "entities" / "lia-prueba.md").read_text() == before


def test_an_edit_back_is_recorded_where_the_close_was_with_its_reason(tmp_path, monkeypatch):
    from api.services.claim_reconciler import EDITED_BACK

    seen: list[dict] = []
    monkeypatch.setattr(telemetry, "record", lambda event: seen.append(dict(event.refs or {})))
    for second in ("moves to", "is moving to"):       # the pair rule's correction, then the same slot's
        seen.clear()
        memory, _r = story(tmp_path / second.replace(" ", "_"), monkeypatch,
                           [(LIA, lia()), (MOVED, lia(reread=second)), (LIA, lia(reread="is moving to"))])
        reread = second
        rows = {cid: (start, is_open) for _p, start, is_open, _s, cid in _moves(memory)}
        revised = [r for r in seen if r.get("action") == "revised"]
        assert [r.get("why") for r in revised][-1] == EDITED_BACK, reread
        assert rows[revised[-1]["by"]] == ("2026-12-05", True) and rows[revised[-1]["closed"]] == ("2026-12-08", False)
        assert all(r.get("why") != EDITED_BACK for r in revised[:-1])


def test_a_re_read_that_is_not_a_revision_that_may_close_undoes_nothing(tmp_path, monkeypatch):
    # A revision that may close nothing (a transcript's cap, `Revision.closes`): the restatement folds into the
    # closed claim as before, and the corrected day stays current.
    from api.services import episode_revision

    memory = None
    real = episode_revision.attach
    nights = [(LIA, lia(reread="is moving to")), (MOVED, lia(reread="is moving to"))]
    memory, _r = story(tmp_path, monkeypatch, nights)

    def attach(memory_path, episodes):
        out = real(memory_path, episodes)
        for rev in out.values():
            rev.closes = False
        return out

    monkeypatch.setattr(episode_revision, "attach", attach)
    _revise(memory, EP, MOVED, LIA)
    _run(memory, monkeypatch, lia(reread="is moving to"))
    assert _open_days(memory) == ["2026-12-08"]


# ---- the closes that are never undone, engine-free (`claim_reconciler._edited_back`) ----


def _restore_rev():
    from api.services import episode_revision

    return episode_revision.build({"id": EP, "content": LIA, "source": "note"}, MOVED)


def _chain(**tail_kw):
    """A (12-05) closed by this conversation's correction B (12-08, the same slot), B open; ``tail_kw`` on B. A's close
    carries the mark the revision rules write (``closed_by_revision``)."""
    a = _claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b",
               closed_by_revision=EP)
    b = _claim("clm_b", tail_kw.pop("predicate", "is-moving-to"), "2026-12-08", supersedes="clm_a", **tail_kw)
    return a, b


def _ending():
    e = _claim("clm_e", "is-moving-to", "2026-12-08", valid_to="2026-12-08", supersedes="clm_a")
    e.text = "Lia previously moved to Valencia"
    return e


def _restated():
    return _claim("clm_a", "is-moving-to", "2026-12-05")


def _reconcile(slot, *, revising=True, redated=("clm_b",), revised=(), new=None, rev=None):
    from types import SimpleNamespace

    from api.services.claim_reconciler import reconcile_stage3

    new = new or _restated()
    settings = SimpleNamespace(memory_path=None, litellm_model="fake", archive_threshold=0.2, decay_nudge_threshold=0.4)
    out, nudges, audit = reconcile_stage3(
        [new], {"lia-prueba": list(slot)}, settings, now_date="2026-11-25", decay=False,
        cardinality_fn=lambda p: False,
        redated={i: EP for i in redated} or None, revised={i: EP for i in revised} or None,
        revising={EP: rev or _restore_rev()} if revising else None)
    return out["lia-prueba"], nudges, audit


def _undone(page) -> bool:
    return any(c.id != "clm_a" and c.predicate == "is-moving-to" and str(c.valid_from)[:10] == "2026-12-05"
               and c.valid_to is None for c in page)


def test_edited_back_on_the_same_slot_replaces_the_correction_and_keeps_the_history():
    from api.services.claim_reconciler import EDITED_BACK

    a, b = _chain()
    page, nudges, audit = _reconcile([a, b])
    (fresh,) = [c for c in page if c.id not in ("clm_a", "clm_b")]
    assert (fresh.valid_from, fresh.valid_to, fresh.supersedes) == ("2026-12-05", None, "clm_b")
    assert (b.valid_to, b.superseded_by) == ("2026-12-08", fresh.id)      # a day moved earlier: closed on its own
    assert (a.valid_to, a.superseded_by, a.supersedes) == ("2026-12-08", "clm_b", None)   # untouched
    assert {"action": "revised", "closed": "clm_b", "by": fresh.id, "why": EDITED_BACK} in audit
    assert not nudges


def test_edited_back_under_another_predicate_leaves_the_correction_to_the_pair_rule():
    a, b = _chain(predicate="moves-to")
    page, _n, _a = _reconcile([a, b], redated=())
    assert _undone(page) and b.valid_to is None          # only a reading of the pair may close it (after Stage 3)


@pytest.mark.parametrize("label,make", [
    ("not a revision read now", lambda: dict(slot=_chain(), revising=False)),
    ("the claim that took its place is also another conversation's",
     lambda: dict(slot=_chain(episodes=(EP, OTHER)))),
    ("the claim that took its place is the person's own",
     lambda: dict(slot=_chain(source_trust="user_stated", origin="manual_edit"))),
    ("the claim that took its place is an agent's", lambda: dict(slot=_chain(recorded_ts="2026-11-20T10:00:00Z"))),
    ("the closed claim also rests on another conversation",
     lambda: dict(slot=(_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b",
                               episodes=(EP, OTHER), closed_by_revision=EP), _chain()[1]))),
    ("closed by decay (no successor)",
     lambda: dict(slot=(_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08",
                               closed_by_revision=EP),), redated=())),
    # The rows below name the closed claim in ``redated`` too (the pipeline never does): each check is tested alone.
    ("the claim that took its place was closed by decay",
     lambda: dict(slot=_chain(valid_to="2026-11-20", closed_by_revision=EP))),
    ("closed by an ending this conversation said",
     lambda: dict(slot=(_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_e",
                               closed_by_revision=EP), _ending()), redated=("clm_e",))),
    ("the correction was then withdrawn by an agent",
     lambda: dict(slot=(*_chain(valid_to="2026-11-20", superseded_by="clm_retract_x", closed_by_revision=EP),
                        _claim("clm_retract_x", "retracts", "2026-11-20", valid_to="2026-11-20", supersedes="clm_b",
                               recorded_ts="2026-11-20T10:00:00Z")), redated=("clm_b", "clm_retract_x"))),
    ("the correction was then replaced by another conversation's claim",
     lambda: dict(slot=(*_chain(valid_to="2026-12-09", superseded_by="clm_c", closed_by_revision=EP),
                        _claim("clm_c", "is-moving-to", "2026-12-09", supersedes="clm_b", episodes=(OTHER,))),
                  redated=("clm_c",))),
    ("the correction gives way by no rule that exists (no third)", lambda: dict(slot=_chain(), redated=())),
    # review 4, M23: a record in the chain (planted: a writer's record is born closed and never superseded).
    ("a withdrawal record in the chain",
     lambda: dict(slot=(_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b",
                               closed_by_revision=EP),
                        _claim("clm_b", "is-moving-to", "2026-12-08", valid_to="2026-12-08", supersedes="clm_a",
                               superseded_by="clm_r", closed_by_revision=EP),
                        _claim("clm_r", "retracts", "2026-12-08", valid_to="2026-12-08", supersedes="clm_b",
                               superseded_by="clm_c"),
                        _claim("clm_c", "is-moving-to", "2026-12-09", supersedes="clm_r")),
                  redated=("clm_c",))),
    ("a pair the rule cannot meet (no day the changed lines say)",
     lambda: dict(slot=_chain(predicate="moves-to"), redated=(),
                  new=_claim("clm_a", "is-moving-to", "2026-12-05"))),
])
def test_a_close_this_conversation_did_not_make_alone_is_never_undone(label, make):
    kw = make()
    slot = [c for c in kw.pop("slot")]
    if label.startswith("a pair the rule cannot meet"):
        # The restated claim carries no day the restore says: the changed lines say "5 December", so give it another.
        kw["new"].valid_from = "2026-12-06"
        kw["new"].id = "clm_a"
        slot[0].valid_from = "2026-12-06"
    before = [(c.id, c.valid_to, c.superseded_by, c.supersedes) for c in slot]
    page, nudges, audit = _reconcile(slot, **kw)
    assert [(c.id, c.valid_to, c.superseded_by, c.supersedes) for c in slot] == before, label
    assert {c.id for c in page} == {c.id for c in slot}, label            # nothing born: the restatement folded in
    assert not any(a.get("action") == "revision_edited_back" for a in audit), label
    assert not nudges, label


def test_a_link_the_chain_does_not_hold_both_ways_is_not_this_conversations_history():
    # review 4, M16 (planted): the closed claim names an earlier one it superseded, but that one says another claim
    # superseded it. It is not this conversation's own correction, so it reads as what it is: here a belief that held
    # and ended (a departure on 20 December), and the restatement is history, born closed; the correction stays.
    a = _claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b", supersedes="clm_x",
               closed_by_revision=EP)
    x = _claim("clm_x", "is-moving-to", "2026-12-01", valid_to="2026-12-20", superseded_by="clm_z",
               closed_by_revision=EP)
    b = _claim("clm_b", "is-moving-to", "2026-12-08", supersedes="clm_a")
    page, _n, audit = _reconcile([a, x, b])
    assert b.valid_to is None and not _undone(page)
    assert any(e.get("action") == "after_departure" for e in audit)


# ---- review 4 (2026-11-26): what the text must say before anything is edited back ----

#: Night 3 keeps the corrected day and mentions the first one: nothing was edited back.
BOTH = MOVED.replace("She leaves on 8 December,", "She leaves on 8 December (she first planned 5 December),")


def _both_days(night2):
    """The re-read of :data:`BOTH` writes both days: the corrected one under night 2's wording, the first plan as it
    was first worded."""
    def answer(chunk):
        out = lia(reread=night2)(chunk)
        first = re.search(r"first planned (\d+) December", chunk)
        if "[Revision:" in chunk and first:
            out["relationships"].append({"source": "Lia Prueba", "target": "Valencia", "label": "is moving to",
                                         "starts": f"2026-12-{int(first[1]):02d}",
                                         "evidence_quote": "Lia Prueba moves to Valencia"})
        return out
    return answer


def _unchanged_by_night_three(tmp_path, monkeypatch, night2, third):
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia(reread=night2)), (MOVED, lia(reread=night2))])
    after_two, calls = _moves(memory), (len(readers.small_calls), len(readers.main_calls))
    _revise(memory, EP, MOVED, BOTH)
    _run(memory, monkeypatch, third)
    _commit(memory, "Sleep cycle")
    return memory, readers, after_two, calls


@pytest.mark.parametrize("night2", ["is moving to", "moves to"])
def test_the_old_day_only_mentioned_again_changes_nothing(tmp_path, monkeypatch, night2):
    # F2a/F2b: the restatement of the current claim never takes its place (it would close a claim with a copy of
    # itself), and the first day said again beside the corrected one is not the edit undone. Readers always "same".
    memory, readers, after_two, calls = _unchanged_by_night_three(tmp_path, monkeypatch, night2, _both_days(night2))
    assert _open_days(memory) == ["2026-12-08"]
    assert _moves(memory) == after_two                       # every claim as night 2 left it
    assert (len(readers.small_calls), len(readers.main_calls)) == calls   # no pair: the old day is still said


def test_only_the_old_day_re_read_while_the_text_keeps_the_new_one_changes_nothing(tmp_path, monkeypatch):
    # F2b, the same-slot path: the re-read (wrongly) writes only the first plan's day; no model is asked.
    def only_old(chunk):
        out = lia(reread="is moving to")(chunk)
        if "first planned" in chunk:
            for r in out["relationships"]:
                r["starts"] = "2026-12-05"
        return out

    memory, _r, after_two, _c = _unchanged_by_night_three(tmp_path, monkeypatch, "is moving to", only_old)
    assert _open_days(memory) == ["2026-12-08"] and _moves(memory) == after_two


def test_a_restatement_of_the_open_claim_folds_in_and_closes_nothing():
    # F2a engine-free: on a restore that does say 5 December, the restated CORRECTION (12-08, the open claim's own id
    # and content) is still no reason to close it; only the restated first claim can be.
    a, b = _chain()
    page, _n, audit = _reconcile([a, b], new=_claim("clm_b", "is-moving-to", "2026-12-08"))
    assert {c.id for c in page} == {"clm_a", "clm_b"} and b.valid_to is None
    assert not any(e.get("action") == "revision_edited_back" for e in audit)


@pytest.mark.parametrize("route", ["same slot", "pair"])
def test_no_edit_back_while_the_tails_day_is_still_said(route):
    # F2b engine-free: the restored day is said by the changed lines, but so is the day that took its place.
    from api.services import episode_revision

    rev = episode_revision.build({"id": EP, "content": BOTH, "source": "note"}, MOVED)
    a, b = _chain(**({} if route == "same slot" else {"predicate": "moves-to"}))
    page, _n, audit = _reconcile([a, b], rev=rev, redated=("clm_b",) if route == "same slot" else ())
    assert {c.id for c in page} == {"clm_a", "clm_b"} and b.valid_to is None
    assert not any(e.get("action") == "revision_edited_back" for e in audit)


def test_a_pair_is_only_where_the_old_day_is_no_longer_said():
    # `meets` carries the same condition: the old claim's day still in the text means the day did not move.
    from api.services import episode_revision

    old = _claim("clm_a", "is-moving-to", "2026-12-05")
    new = _claim("clm_b", "moves-to", "2026-12-08")
    moved_rev = episode_revision.build({"id": EP, "content": MOVED, "source": "note"}, LIA)
    both_rev = episode_revision.build({"id": EP, "content": BOTH, "source": "note"}, LIA)
    assert revision_pairs.meets(old, new, moved_rev)
    assert not revision_pairs.meets(old, new, both_rev)


@pytest.mark.parametrize("label,change", [
    ("another context", lambda o: setattr(o, "context", "work")),          # review 4, M18
    ("another speaker", lambda o: setattr(o, "observer", "external:bob-example")),   # review 4, M19
])
def test_a_pair_is_only_the_same_context_and_speaker(label, change):
    old = _claim("clm_a", "is-moving-to", "2026-12-05")
    new = _claim("clm_b", "moves-to", "2026-12-08")
    assert revision_pairs.meets(old, new, _rev()), label
    change(old)
    assert not revision_pairs.meets(old, new, _rev()), label


def test_a_day_only_the_unchanged_lines_say_is_no_pair():
    # review 4, M21: the new claim's day must be said by the CHANGED lines; here the edit touched another line.
    from api.services import episode_revision

    prior = MOVED
    body = MOVED.replace("plays the piano", "plays the harp")
    rev = episode_revision.build({"id": EP, "content": body, "source": "note"}, prior)
    assert "8 December" in body and not revision_pairs.Said(rev).changed("2026-12-08")
    assert not revision_pairs.meets(_claim("clm_a", "is-moving-to", "2026-12-05"),
                                    _claim("clm_b", "moves-to", "2026-12-08"), rev)


@pytest.mark.parametrize("third", ["different", "raise", "small same, main different"])
def test_an_edit_back_the_readers_do_not_call_the_same_leaves_both_open_as_before(tmp_path, monkeypatch, third):
    # F1 (the coordinator's decision): the restatement is born on the text alone (this conversation's correction, the
    # restored day said by the changed lines, the correction's day no longer said); whether the correction then gives
    # way is the pair rule's reading. A "different", a failed call or a split reading: both days open, exactly as
    # origin/dev ends (which folds nothing in and closes nothing).
    small, main = {"different": (always("different"), always("different")), "raise": (raising, raising),
                   "small same, main different": (always("same"), always("different"))}[third]
    memory, readers = story(tmp_path, monkeypatch, [(LIA, lia()), (MOVED, lia())])
    calls = len(readers.small_calls)
    readers._small, readers._main = small, main
    _revise(memory, EP, MOVED, LIA)
    _run(memory, monkeypatch, lia(reread="is moving to"))
    _commit(memory, "Sleep cycle")
    assert len(readers.small_calls) == calls + 1, "night 3's pair was read"
    assert _open_days(memory) == ["2026-12-05", "2026-12-08"]
    opened = {p: s for p, s, is_open, _x, _i in _moves(memory) if is_open}
    assert opened == {"is-moving-to": "2026-12-05", "moves-to": "2026-12-08"}


def test_an_edit_undone_while_another_conversation_says_the_restored_day_ends_on_it(tmp_path, monkeypatch):
    # Review 4 F5, kept: A, B, A on the same slot while another conversation read the same night says 5 December
    # (origin/dev ends on 8 December, the day neither conversation now says).
    same = lia(reread="is moving to")
    says = "user: Lia Prueba moves to Valencia.\nuser: She leaves on 5 December.\nuser: Fin."
    memory, _r = story(tmp_path, monkeypatch, [(LIA, same), (MOVED, same), (LIA, same)], others={1: says})
    assert _open_days(memory) == ["2026-12-05"]


def _large_page(tmp_path, n_claims=300, n_rels=20, lines=60):
    """A page of ``n_claims`` claims of this conversation and a revision whose re-read writes ``n_rels`` dated claims,
    each about one of the page's objects under another predicate (review 4's `cost.py`, smaller)."""
    from api.services import episode_revision
    from api.services.claims import Claim, write_claims

    memory = _bank(tmp_path)
    claims = [Claim(id=f"clm_2026-12-01_{i:08x}", text="x", subject="lia-prueba", predicate="visits",
                    object=f"place{i}", valid_from="2026-12-01", source_episodes=[EP]) for i in range(n_claims)]
    markdown_parser.write(memory / "entities" / "lia-prueba.md",
                          {"name": "Lia Prueba", "type": "person", "status": "active", "confidence": 0.9,
                           "source_episodes": [EP]}, write_claims("## Summary\nX.\n", claims))
    prior = "\n".join(f"user: line {i} about place{i % n_rels} on 3 December." for i in range(lines))
    body = "\n".join(f"user: line {i} about place{i % n_rels} on {4 + i % 20} December." for i in range(lines))
    rev = episode_revision.build({"id": EP, "content": body, "source": "note"}, prior)
    rels = [{"source": "Lia Prueba", "target": f"Place{i}", "label": "goes to", "starts": f"2026-12-{4 + i % 20:02d}",
             "evidence_quote": f"line {i}"} for i in range(n_rels)]
    extracted = [{"episode_id": EP, "episode_timestamp": "2026-11-07T10:00:00Z", "entities": [], "values": [],
                  "relationships": rels}]
    return memory, {EP: rev}, extracted


def _count(monkeypatch):
    """Counts every call of the date reader and of the old claim's test past the cheap ones."""
    from api.services import episode_revision

    seen = {"days": [], "old": []}
    real_says, real_old = episode_revision.says_day, revision_pairs._pairable_old
    monkeypatch.setattr(episode_revision, "says_day",
                        lambda text, day: seen["days"].append((hash(text), day)) or real_says(text, day))
    monkeypatch.setattr(revision_pairs, "_pairable_old", lambda c, ep: seen["old"].append(c.id) or real_old(c, ep))
    return seen


def test_each_day_is_read_once_per_revision_and_nothing_past_the_cap(tmp_path, monkeypatch):
    # Review 4, F4: `meets` read the whole changed text twice for every old and new claim compared (7.6 s at 500
    # claims on the page, 39.8 s at 3,000). Counted, never timed.
    memory, revs, extracted = _large_page(tmp_path, n_rels=40)       # 40 re-read claims, each day twice
    seen = _count(monkeypatch)
    pairs = revision_pairs.candidates(memory, revs, extracted)
    assert len(pairs) == revision_pairs.MAX_PAIRS
    reads = seen["days"]
    assert len(reads) == len(set(reads)), "a day read more than once in one text (the changed lines, the body)"
    assert len(reads) <= 21                         # 20 days the re-read writes and the page's one, never per pair
    assert len(seen["old"]) == revision_pairs.MAX_PAIRS, "only pairs pass the cheap tests; nothing past the cap"


def test_a_revision_past_the_cap_is_never_compared(tmp_path, monkeypatch):
    memory, revs, extracted = _large_page(tmp_path)
    monkeypatch.setattr(revision_pairs, "MAX_REVISIONS", 0)
    seen = _count(monkeypatch)
    reading = revision_pairs.read(memory, revs, extracted, lambda p: {}, lambda p: {})
    assert (reading.pairs, reading.capped, seen["old"]) == (0, 1, [])


def test_a_stop_asked_for_compares_nothing(tmp_path, monkeypatch):
    memory, revs, extracted = _large_page(tmp_path)
    seen = _count(monkeypatch)
    assert revision_pairs.candidates(memory, revs, extracted, cancelled=lambda: True) == []
    assert seen["old"] == []


@pytest.mark.parametrize("label,change", [
    ("a capped transcript's revision", {"closes": False}),
    ("a book's record", {"book": True}),
    ("nothing changed", {"changed": ()}),
])
def test_a_revision_that_may_close_nothing_is_never_read(tmp_path, monkeypatch, label, change):
    # Review 4, M14: no reading at all, not even the date reader, for a revision that may not close a claim.
    import dataclasses

    memory, revs, extracted = _large_page(tmp_path)
    assert revision_pairs.candidates(memory, revs, extracted), "the unchanged revision has pairs"
    seen = _count(monkeypatch)
    revs = {ep: dataclasses.replace(rev, **change) for ep, rev in revs.items()}
    calls = []
    reading = revision_pairs.read(memory, revs, extracted, lambda p: calls.append(p) or {}, lambda p: calls.append(p) or {})
    assert (reading.pairs, calls, seen["days"], seen["old"]) == (0, [], [], []), label


def test_a_value_edited_back_is_current_again_by_the_removed_texts_rule(tmp_path, monkeypatch):
    # review 4, M08: the `revised` route — piano, then guitar (the piano's words removed), then piano again. The guitar's
    # words are gone, so it gives way; without the route the restored value folds into the closed one and the guitar is
    # withdrawn as removed text: nothing would be current.
    guitar = LIA.replace("plays the piano", "plays the guitar")

    def instrument(chunk):
        out = lia(reread="is moving to")(chunk)
        played = re.search(r"plays the (\w+)", chunk)
        out["values"] = [{"entity": "Lia Prueba", "attribute": "instrument", "value": played[1],
                          "evidence_quote": f"Lia Prueba plays the {played[1]}"}] if played else []
        return out

    memory, _r = story(tmp_path, monkeypatch, [(LIA, instrument), (guitar, instrument), (LIA, instrument)])
    values = [c for c in _claims_of(memory, "lia-prueba") if "instrument" in c.predicate and not is_record(c)]
    assert sorted(str(c.object) for c in values if c.valid_to is None) == ["piano"]
    assert any(str(c.object) == "guitar" and c.valid_to and not is_record(c) for c in values)


# --------------------------------------------------------------------------- #
# held claims, engine-free: the drop from a line (6a, 6b, 6d) and the released claim (6e)
# --------------------------------------------------------------------------- #

def _zrev():
    from api.services import episode_revision

    return episode_revision.build({"id": EP, "content": Z2, "source": "note"}, Z1)


def _zclaim(cid, predicate, start, *, episodes=(EP,), subject=ZED_PAGE, obj="lisbon", **kw):
    from api.services.claims import Claim, Evidence

    return Claim(id=cid, text=f"Zed {predicate} Lisbon", subject=subject, predicate=predicate, object=obj,
                 valid_from=start, source_episodes=list(episodes),
                 evidence=[Evidence(episode=e, start=0, end=5, kind="user", hash="h") for e in episodes], **kw)


def _zverdict(**kw):
    base = dict(episode=EP, old_id="old", subject=ZED_PAGE, context="general", observer="agent",
                predicate="moves-to", object="lisbon", valid_from="2026-12-09", expected_end="", held="Zed Unknown",
                old_subject=ZED_PAGE, old_object="lisbon", old_from="2026-12-05", old_end="")
    return revision_pairs.Verdict(**{**base, **kw})


def _store(tmp_path, lines):
    """A scratch bank whose pending store holds ``{name: [claims]}``; returns (memory, the store's bytes)."""
    from api.services import pending_store
    from api.services.pending_store import PendingEntity

    memory = tmp_path / "bank"
    memory.mkdir(parents=True, exist_ok=True)
    pending_store.save(memory, [
        PendingEntity(name=name, type="person", description="A person.", source_episode=EP, confidence=0.6, tags=[],
                      history_entries=[], held_claims=[c.to_dict() for c in claims]) for name, claims in lines.items()])
    return memory, (memory / "pending_entities.jsonl").read_bytes()


def _held_ids(memory, name="Zed Unknown"):
    from api.services import pending_store

    return [d["id"] for e in pending_store.load(memory) if e.name == name for d in e.held_claims]


def test_apply_held_drops_the_old_claim_only_from_its_line_and_records_it(tmp_path):
    rev = _zrev()
    assert rev is not None and rev.changed
    other_line = _zclaim("old", "is-moving-to", "2026-12-05", subject="ana-x")     # the same id on another line
    memory, _ = _store(tmp_path, {"Zed Unknown": [_zclaim("old", "is-moving-to", "2026-12-05"),
                                                  _zclaim("keep", "works-at", "2026-10-01", obj="acme"),
                                                  _zclaim("new", "moves-to", "2026-12-09")],
                                  "Ana X": [other_line]})
    from api.services import pending_store

    before = {d["id"]: d for e in pending_store.load(memory) for d in e.held_claims if e.name == "Zed Unknown"}
    audit: list[dict] = []
    assert revision_pairs.apply_held(memory, [_zverdict()], {EP: rev}, audit) == {"old": EP}
    assert _held_ids(memory) == ["keep", "new"] and _held_ids(memory, "Ana X") == ["old"]
    after = {d["id"]: d for e in pending_store.load(memory) for d in e.held_claims if e.name == "Zed Unknown"}
    assert after == {k: v for k, v in before.items() if k != "old"}       # 6c: nothing else re-dated or rewritten
    assert audit == [{"action": "revised", "closed": "old", "by": "new", "why": revision_pairs.WHY, "held": True}]
    # A second run over the same state changes nothing.
    data = (memory / "pending_entities.jsonl").read_bytes()
    assert revision_pairs.apply_held(memory, [_zverdict()], {EP: rev}, []) == {}
    assert (memory / "pending_entities.jsonl").read_bytes() == data


def _old(**kw):
    return _zclaim("old", "is-moving-to", kw.pop("start", "2026-12-05"), **kw)


def _new(**kw):
    return _zclaim("new", "moves-to", kw.pop("start", "2026-12-09"), **kw)


@pytest.mark.parametrize("label,lines,verdict_kw,closes", [
    # 6a: the re-read's claim must stand in the same line, open, the same things, the judged day, this conversation.
    ("the new claim was not held (refused at the cap)", lambda: {"Zed Unknown": [_old()]}, {}, True),
    ("the new claim is held under another name", lambda: {"Zed Unknown": [_old()], "Zed Other": [_new()]}, {}, True),
    ("the new claim is closed", lambda: {"Zed Unknown": [_old(), _new(valid_to="2026-12-10")]}, {}, True),
    ("the new claim is superseded", lambda: {"Zed Unknown": [_old(), _new(superseded_by="x")]}, {}, True),
    ("the new claim carries another day", lambda: {"Zed Unknown": [_old(), _new(start="2026-12-10")]}, {}, True),
    ("the new claim is about another object", lambda: {"Zed Unknown": [_old(), _new(obj="porto")]}, {}, True),
    ("the new claim is another wording", lambda: {"Zed Unknown": [_old(), _zclaim("new", "visits", "2026-12-09")]},
     {}, True),
    ("the new claim is another conversation's", lambda: {"Zed Unknown": [_old(), _new(episodes=(OTHER,))]}, {}, True),
    ("the judged day is not said by the changed lines",
     lambda: {"Zed Unknown": [_old(), _new(start="2026-12-07")]}, {"valid_from": "2026-12-07"}, True),
    # 6d: independent support, checked on the line as it is now.
    ("another conversation also says the old claim",
     lambda: {"Zed Unknown": [_old(episodes=(EP, OTHER)), _new()]}, {}, True),
    ("the old claim is the person's own",
     lambda: {"Zed Unknown": [_old(source_trust="user_stated", origin="manual_edit"), _new()]}, {}, True),
    ("the old claim is an agent's", lambda: {"Zed Unknown": [_old(recorded_ts="2026-11-07T10:00:00Z"), _new()]},
     {}, True),
    ("the old claim is an event", lambda: {"Zed Unknown": [_zclaim("old", "happened", "2026-12-05"), _new()]},
     {"old_object": "lisbon"}, True),
    ("a capped transcript's revision", lambda: {"Zed Unknown": [_old(), _new()]}, {}, False),
    # 6e and the verdict's own fingerprint: the claim judged, not one like it.
    ("the old claim's day moved since it was judged", lambda: {"Zed Unknown": [_old(start="2026-12-06"), _new()]},
     {}, True),
    ("the old claim's end moved since it was judged",
     lambda: {"Zed Unknown": [_old(expected_end="2026-12-20"), _new()]}, {}, True),
    ("the old claim is now about another subject", lambda: {"Zed Unknown": [_old(subject="ana-x"), _new()]}, {}, True),
    ("the old claim is not about the object judged", lambda: {"Zed Unknown": [_old(), _new()]},
     {"old_object": "porto"}, True),
    ("the new claim is about another subject", lambda: {"Zed Unknown": [_old(), _new(subject="ana-x")]}, {}, True),
    ("the two are not about the same object", lambda: {"Zed Unknown": [_old(), _new(obj="porto")]},
     {"object": "porto"}, True),
    ("the verdict names another line", lambda: {"Zed Unknown": [_old(), _new()]}, {"held": "Zed Other"}, True),
    ("a verdict on a page claim", lambda: {"Zed Unknown": [_old(), _new()]}, {"held": ""}, True),
    ("already replaced on its page this pass", lambda: {"Zed Unknown": [_old(), _new()]}, {"done": True}, True),
])
def test_apply_held_leaves_the_line_byte_for_byte_unless_the_new_claim_stands_in_its_place(
        tmp_path, label, lines, verdict_kw, closes):
    rev = _zrev()
    rev.closes = closes
    verdict_kw = dict(verdict_kw)
    done = {"old": EP} if verdict_kw.pop("done", False) else None
    memory, data = _store(tmp_path, lines())
    audit: list[dict] = []
    assert revision_pairs.apply_held(memory, [_zverdict(**verdict_kw)], {EP: rev}, audit, done=done) == {}, label
    assert (memory / "pending_entities.jsonl").read_bytes() == data, label
    assert not [a for a in audit if a.get("action") == "revised"], label


def test_apply_held_one_new_claim_stands_for_one_old_claim(tmp_path):
    rev = _zrev()
    memory, _ = _store(tmp_path, {"Zed Unknown": [_old(), _zclaim("old2", "relocates-to", "2026-12-05"), _new()]})
    out = revision_pairs.apply_held(memory, [_zverdict(), _zverdict(old_id="old2")], {EP: rev}, [])
    assert out == {"old": EP} and _held_ids(memory) == ["old2", "new"]


def test_apply_held_records_every_drop_whatever_a_line_holds(tmp_path):
    # review 2, e1: a record per dropped claim, never capped below what a line can hold.
    from api.services import pending_store

    rev = _zrev()
    n = pending_store.MAX_HELD_CLAIMS
    olds = [_zclaim(f"old{i}", f"is-moving-to-{i}", "2026-12-05", obj=f"city{i}") for i in range(n)]
    news = [_zclaim(f"new{i}", "moves-to", "2026-12-09", obj=f"city{i}") for i in range(n)]
    memory, _ = _store(tmp_path, {"Zed Unknown": olds + news})
    verdicts = [_zverdict(old_id=f"old{i}", object=f"city{i}", old_object=f"city{i}") for i in range(n)]
    audit: list[dict] = []
    assert len(revision_pairs.apply_held(memory, verdicts, {EP: rev}, audit)) == n
    assert len([a for a in audit if a["action"] == "revised" and a.get("held")]) == n
    assert _held_ids(memory) == [f"new{i}" for i in range(n)]


def _moved(claim, line="Zed Unknown", slug=ZED_PAGE, target=ZED_PAGE):
    return {claim.id: revision_pairs.Moved(claim, line, slug, target)}


def test_apply_closes_the_claim_this_pass_released_from_its_line_and_no_other():
    # 6e: the verdict made on a held claim is applied to the very claim released from that line.
    rev = _zrev()
    old, new = _old(), _new()
    audit: list[dict] = []
    assert revision_pairs.apply({ZED_PAGE: [old, new]}, [_zverdict()], {EP: rev}, audit, released=_moved(old)) == {
        "old": EP}
    assert (old.valid_from, old.valid_to, old.superseded_by, new.supersedes) == ("2026-12-05", "2026-12-09", "new",
                                                                                 "old")   # 6c: its own day kept
    for label, slot, released in [
        ("a look-alike the page already held under the same id", lambda o, n: [_old(), n], lambda o: _moved(o)),
        ("nothing released this pass (the line still holds it)", lambda o, n: [o, n], lambda o: None),
        ("released from another line", lambda o, n: [o, n], lambda o: _moved(o, line="Zed Other")),
        ("released, then its day changed", lambda o, n: [o, n], lambda o: _moved(o)),
    ]:
        o, n = _old(), _new()
        if label.endswith("its day changed"):
            o.valid_from = "2026-12-06"
        page = slot(o, n)
        assert revision_pairs.apply({ZED_PAGE: page}, [_zverdict()], {EP: rev}, [], released=released(o)) == {}, label
        assert all(c.valid_to is None and c.superseded_by is None for c in page), label


def test_apply_follows_a_released_claim_onto_the_page_its_name_was_matched_to():
    # Stage 2 matched the held name to a page with another id: the line's claims went there (`pending_store.repointed`),
    # and so did the re-read's claim of that name; a claim about the name as an object went with its own subject.
    rev = _zrev()
    old, new = _old(subject="zed-u"), _new(subject="zed-u")
    assert revision_pairs.apply({"zed-u": [old, new]}, [_zverdict()], {EP: rev}, [],
                                released=_moved(old, target="zed-u")) == {"old": EP}
    old, new = _old(subject="zed-u"), _new(subject="zed-v")          # the re-read's claim went elsewhere
    assert revision_pairs.apply({"zed-u": [old], "zed-v": [new]}, [_zverdict()], {EP: rev}, [],
                                released=_moved(old, target="zed-u")) == {}
    assert old.valid_to is None


def test_apply_follows_a_released_claim_held_as_another_pages_object():
    # A claim held on the name's line as another page's OBJECT ("X helps Zed move to Lisbon" is X's claim): the release
    # keeps its subject and points its object at the page (`pending_store.repointed`); the verdict follows it there.
    rev = _zrev()
    old = _zclaim("old", "is-moving-to", "2026-12-05", subject="xavi-o", obj="zed-u")
    new = _zclaim("new", "moves-to", "2026-12-09", subject="xavi-o", obj="zed-u")
    verdict = _zverdict(subject="xavi-o", object=ZED_PAGE, old_subject="xavi-o", old_object=ZED_PAGE)
    assert revision_pairs.apply({"xavi-o": [old, new]}, [verdict], {EP: rev}, [],
                                released=_moved(old, target="zed-u")) == {"old": EP}
    assert (old.superseded_by, new.supersedes) == ("new", "old")


def test_a_held_claim_its_page_already_holds_is_offered_once_as_the_pages_own(tmp_path):
    memory, _ = _store(tmp_path, {"Zed Unknown": [_old(), _new()]})
    pool = revision_pairs._held_pool(memory, {ZED_PAGE: [_old()]})   # noqa: SLF001 - the one rule
    assert [(c.id, line) for c, line in pool[ZED_PAGE]] == [("new", "Zed Unknown")]


# ---- review 4, F3: a person's pick in the inbox (reported, not fixed: nothing in the bank records which closes the
# revision rules made, so the edited-back rule cannot tell this close from its own) ----

PICK = LIA.replace("She leaves on 5 December,", "She leaves on 5 December, or maybe 8 December,")


def _two_plans(chunk):
    """The first read writes both plans (two wordings, so two slots); a re-read of the edit writes what it says."""
    out = lia(reread="is moving to")(chunk)
    if "or maybe 8 December" in chunk:
        out["relationships"].append({"source": "Lia Prueba", "target": "Valencia", "label": "moves to",
                                     "starts": "2026-12-08", "evidence_quote": "Lia Prueba moves to Valencia"})
    return out


def test_a_pick_the_person_made_in_the_inbox_is_never_undone_by_an_edit_back(tmp_path, monkeypatch):
    # Driven through the resolver the route calls (`inbox_service.resolve`), on a scratch bank: the person picks
    # 8 December over 5 December, both read from one conversation; the conversation is then edited to say only
    # 5 December. `origin/dev` keeps the pick (the restatement folds into the claim the pick closed).
    import asyncio

    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    memory, readers = story(tmp_path, monkeypatch, [(PICK, _two_plans)])
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    first, other = sorted((c for c in _claims_of(memory, "lia-prueba") if c.object == "valencia"),
                          key=lambda c: str(c.valid_from))
    (memory / "inbox").mkdir(exist_ok=True)
    markdown_parser.write(memory / "inbox" / "inbox-901.md", {
        "kind": "conflict", "required_input": "choice", "status": "pending", "priority": 0.8,
        "entity_id": "lia-prueba", "entity_name": "Lia Prueba", "title": "When does Lia Prueba move?",
        "question": "When does Lia Prueba move?", "created_date": "2026-11-08", "predicate": first.predicate,
        "allow_other": True, "allow_defer": True,
        "options": [{"key": "a", "label": "valencia", "claim_id": first.id, "observed_at": "2026-11-07"},
                    {"key": "b", "label": "valencia", "claim_id": other.id, "observed_at": "2026-11-07"}]},
        "Two days for one move.")
    _commit(memory, "question")

    async def _no_synthesis(**kw):
        return kw["new_description"]

    monkeypatch.setattr("api.services.conflict_resolver._synthesize_entity_update", _no_synthesis)
    settings = type("S", (), {"memory_path": memory, "inbox_defer_days": 30, "litellm_model": "test-model",
                              "litellm_disambiguation_model": "", "consolidation_model": "", "llm_mode": "byok",
                              "effective_consolidation_model": "test-model"})()
    asyncio.run(inbox_service.resolve("inbox-901", InboxResolveRequest(action="resolve", optionKey="b"), settings))
    picked = {c.id: c for c in _claims_of(memory, "lia-prueba")}
    assert picked[first.id].superseded_by == other.id and picked[other.id].valid_to is None   # the person's pick

    _revise(memory, EP, PICK, LIA)
    _run(memory, monkeypatch, _two_plans)
    _commit(memory, "Sleep cycle")
    assert _open_days(memory) == ["2026-12-08"]


# ---- review 4, F3 closed (2026-11-26): the revision rules mark their own closes, and the edited-back rule requires the
# mark on every closed link (`Claim.closed_by_revision`, `claim_reconciler._corrected_by`) ----


def _restated_b():
    return _claim("clm_b", "is-moving-to", "2026-12-08")


@pytest.mark.parametrize("label,slot,new,redated", [
    # A bank written before the mark existed: the same chain, no mark anywhere.
    ("no mark at all (a close written before the mark existed)",
     lambda: (_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b"),
              _chain()[1]), _restated, ("clm_b",)),
    ("a mark naming another conversation",
     lambda: (_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b",
                     closed_by_revision=OTHER), _chain()[1]), _restated, ("clm_b",)),
    # A marked, B closed by a close with no mark (the person's pick of C), C open.
    ("the first close marked, the second not",
     lambda: (_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b",
                     closed_by_revision=EP),
              _claim("clm_b", "is-moving-to", "2026-12-08", valid_to="2026-12-10", supersedes="clm_a",
                     superseded_by="clm_c"),
              _claim("clm_c", "is-moving-to", "2026-12-10", supersedes="clm_b")), _restated, ("clm_c",)),
    # The reverse: A closed by a pick (no mark), B closed by this revision (marked), C open; A restated.
    ("the first close not marked, the second marked",
     lambda: (_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b"),
              _claim("clm_b", "is-moving-to", "2026-12-08", valid_to="2026-12-10", supersedes="clm_a",
                     superseded_by="clm_c", closed_by_revision=EP),
              _claim("clm_c", "is-moving-to", "2026-12-10", supersedes="clm_b")), _restated, ("clm_c",)),
])
def test_a_close_the_revision_did_not_mark_is_never_undone(label, slot, new, redated):
    slot = list(slot())
    before = [(c.id, c.valid_to, c.superseded_by, c.supersedes) for c in slot]
    page, nudges, audit = _reconcile(slot, new=new(), redated=redated)
    assert [(c.id, c.valid_to, c.superseded_by, c.supersedes) for c in slot] == before, label
    assert {c.id for c in page} == {c.id for c in slot}, label            # the restatement folded in
    assert not any(a.get("action") == "revision_edited_back" for a in audit), label
    assert not nudges, label


def test_a_close_with_no_mark_before_the_restated_claim_leaves_the_chain_as_it_is():
    # A closed by the person's pick of B (no mark), B closed by this revision's C (marked), C open; the restore says B's
    # day again. The walk back meets the pick: nothing is undone, the restatement folds into B (origin/dev's end).
    from api.services import episode_revision

    tenth = LIA.replace("5 December", "10 December")
    rev = episode_revision.build({"id": EP, "content": MOVED, "source": "note"}, tenth)
    a = _claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b")
    b = _claim("clm_b", "is-moving-to", "2026-12-08", valid_to="2026-12-10", supersedes="clm_a",
               superseded_by="clm_c", closed_by_revision=EP)
    c = _claim("clm_c", "is-moving-to", "2026-12-10", supersedes="clm_b")
    before = [(x.id, x.valid_to, x.superseded_by, x.supersedes) for x in (a, b, c)]
    page, _n, audit = _reconcile([a, b, c], new=_restated_b(), redated=("clm_c",), rev=rev)
    assert {x.id for x in page} == {"clm_a", "clm_b", "clm_c"}
    assert [(x.id, x.valid_to, x.superseded_by, x.supersedes) for x in (a, b, c)] == before
    assert not any(e.get("action") == "revision_edited_back" for e in audit)
    # The same page with the pick's close marked as this revision's (a chain this conversation made) is edited back:
    # the check above is the mark alone.
    a2 = _claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b",
                closed_by_revision=EP)
    b2 = _claim("clm_b", "is-moving-to", "2026-12-08", valid_to="2026-12-10", supersedes="clm_a",
                superseded_by="clm_c", closed_by_revision=EP)
    c2 = _claim("clm_c", "is-moving-to", "2026-12-10", supersedes="clm_b")
    page, _n, audit = _reconcile([a2, b2, c2], new=_restated_b(), redated=("clm_c",), rev=rev)
    (fresh,) = [x for x in page if x.id not in ("clm_a", "clm_b", "clm_c")]
    assert (fresh.valid_from, fresh.valid_to, fresh.supersedes) == ("2026-12-08", None, "clm_c")
    assert c2.superseded_by == fresh.id and c2.closed_by_revision == EP       # the edit back's own close, marked


def test_every_close_the_revision_rules_make_is_marked_with_the_conversation():
    from api.services.claim_reconciler import _close_by_revision

    a, b = _chain()
    page, _n, _a = _reconcile([a, b])
    (fresh,) = [c for c in page if c.id not in ("clm_a", "clm_b")]
    assert b.closed_by_revision == EP and fresh.closed_by_revision is None   # same slot (`redated`)
    old, new = _claim("clm_o", "is-moving-to", "2026-12-05"), _claim("clm_n", "moves-to", "2026-12-08")
    _close_by_revision(old, by=new, episode=EP)
    assert (old.superseded_by, old.closed_by_revision) == ("clm_n", EP)


def test_the_pair_rules_close_is_marked():
    rev = _rev()
    old, new = _claim("old", "is-moving-to", "2026-12-05"), _claim("new", "moves-to", "2026-12-08")
    revision_pairs.apply({"lia-prueba": [old, new]}, [_verdict()], {EP: rev}, [])
    assert (old.superseded_by, old.closed_by_revision) == ("new", EP)


def test_the_removed_texts_withdrawal_is_marked():
    from api.services import episode_revision

    old = _claim("clm_a", "is-moving-to", "2026-12-05")
    plan = episode_revision.Plan(revised_out={"clm_a": EP})
    rev = _rev()
    assert episode_revision.settle({"lia-prueba": [old]}, plan, {EP: rev}, "2026-11-26", []) == 1
    assert old.superseded_by and old.closed_by_revision == EP


@pytest.mark.parametrize("label,write", [
    ("the person's pick (inbox_service's close)",
     lambda c, other: __import__("api.services.inbox_service", fromlist=["x"])._close_on(c, by=other, day="2026-12-09")),
    ("an ordinary update (the reconciler's close)",
     lambda c, other: __import__("api.services.claim_reconciler", fromlist=["x"])._close(c, by=other)),
    ("a reopen", lambda c, other: (setattr(c, "valid_to", None), setattr(c, "superseded_by", None))),
    ("a merge re-linking the successor", lambda c, other: setattr(c, "superseded_by", "clm_b-from-other")),
    ("an agent's withdrawal record", lambda c, other: setattr(c, "superseded_by", "clm_retract_x")),
    ("the same day written again", lambda c, other: setattr(c, "valid_to", c.valid_to)),
])
def test_any_other_write_to_the_close_drops_the_mark(label, write):
    a, b = _chain()
    assert a.closed_by_revision == EP
    write(a, b)
    assert a.closed_by_revision is None, label


def test_an_open_claim_never_carries_the_mark_and_an_unmarked_page_serializes_as_before():
    from api.services.claims import Claim, parse_claims, write_claims

    a, b = _chain()
    data = a.to_dict()
    assert data["closed_by_revision"] == EP and Claim.from_dict(data).closed_by_revision == EP
    reopened = {**data, "valid_to": None, "superseded_by": None}
    assert Claim.from_dict(reopened).closed_by_revision is None            # a hand edit reopened it
    assert "closed_by_revision" not in b.to_dict()
    unmarked = _claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b")
    body = write_claims("# Lia\n", [unmarked, b])
    assert "closed_by_revision" not in body
    assert write_claims("# Lia\n", parse_claims(body, strict=True)) == body
    marked = write_claims("# Lia\n", [a, b])
    assert [c.closed_by_revision for c in parse_claims(marked, strict=True)] == [EP, None]
    # The fence is the unmarked one plus the one key on the marked claim's line, nothing else.
    assert marked.replace(f', "closed_by_revision": "{EP}"', "") == body


def test_the_mark_travels_with_its_claim_through_the_ledger_past_the_fence_cap(tmp_path):
    from api.services import claims_ledger
    from api.services.claims import parse_claims, write_claims

    a, b = _chain()
    filler = [_claim(f"clm_f{i:04d}", "likes", "2026-01-01") for i in range(600)]
    for i, c in enumerate(filler):
        c.object, c.text = f"thing-{i}", f"Lia likes thing number {i} " + "x" * 80
    page = tmp_path / "entities" / "lia-prueba.md"
    page.parent.mkdir(parents=True)
    markdown_parser.write(page, {"id": "lia-prueba", "name": "Lia Prueba"}, write_claims("# Lia\n", [a, b, *filler]))
    ledger = claims_ledger.path_for(page)
    assert ledger.exists()                                                  # past 64k characters: split
    lines = ledger.read_text().splitlines() + page.read_text().splitlines()
    assert sum('"closed_by_revision"' in ln for ln in lines) == 1
    back = {c.id: c for c in parse_claims(markdown_parser.parse(page).body, strict=True)}
    assert len(back) == 602 and back["clm_a"].closed_by_revision == EP
    assert all(c.closed_by_revision is None for cid, c in back.items() if cid != "clm_a")


def test_a_bank_written_before_the_mark_edited_back_ends_as_before(tmp_path, monkeypatch):
    # Nights 1 and 2 as before (the same-slot correction), then every mark stripped, as a bank written before the field
    # existed holds them: the edit back folds into the closed claim and the corrected day stays current alone, which is
    # how origin/dev ends the same three nights.
    from api.services.claims import parse_claims, write_claims

    same = lia(reread="is moving to")
    memory, _r = story(tmp_path, monkeypatch, [(LIA, same), (MOVED, same)])
    path = memory / "entities" / "lia-prueba.md"
    parsed = markdown_parser.parse(path)
    claims = parse_claims(parsed.body, strict=True)
    assert sum(c.closed_by_revision == EP for c in claims) == 1             # the real pipeline wrote the mark
    for c in claims:
        object.__setattr__(c, "closed_by_revision", None)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
    _commit(memory, "a bank from before the mark")
    ids = {c.id for c in _claims_of(memory, "lia-prueba")}
    _revise(memory, EP, MOVED, LIA)
    _run(memory, monkeypatch, same)
    _commit(memory, "Sleep cycle")
    assert _open_days(memory) == ["2026-12-08"]
    assert {c.id for c in _claims_of(memory, "lia-prueba")} == ids          # nothing born: folded into the closed claim


def test_the_mark_is_bookkeeping_and_never_reaches_a_page_writers_prompt():
    from api.services import entity_orientation, page_change
    from api.services.claims import write_claims

    a, b = _chain()
    before = {**a.to_dict(), "valid_to": None, "superseded_by": None}
    before.pop("closed_by_revision")
    meaningful, _fade = page_change.claim_diff(before, a.to_dict())
    assert set(meaningful) == {"valid_to", "superseded_by"}             # the close is shown; the mark is not a change
    data = entity_orientation.context(write_claims("# Lia\n", [a, b]), name="Lia Prueba", entity_type="person",
                                      fields={}, today="2026-12-20", source_dates=[])
    assert [c["id"] for c in data["current_claims"]] == ["clm_b"]
    assert "closed_by_revision" not in data["current_claims"][0]


def test_a_restatement_another_conversation_also_says_is_not_an_edit_back():
    # review 4, M15: condition 1 — the restatement is heard in the revised conversation alone. One the same night's other
    # conversation also says (one incoming claim citing both) finds no twin (`_reread_twin` wants every conversation it
    # was heard in cited by the closed claim, and a marked twin rests on this one alone, so the check in `_edited_back`
    # is implied there: M15 is equivalent at its one call site). It is placed as origin/dev places it (born closed
    # after the departure the chain reads as), no id of its own minted, the chain left as it is.
    a, b = _chain()
    new = _claim("clm_a", "is-moving-to", "2026-12-05", episodes=(EP, OTHER))
    before = [(c.id, c.valid_to, c.superseded_by, c.supersedes) for c in (a, b)]
    page, _n, audit = _reconcile([a, b], new=new)
    assert {c.id for c in page} == {"clm_a", "clm_b"}
    assert [(c.id, c.valid_to, c.superseded_by, c.supersedes) for c in (a, b)] == before
    assert not any(e.get("action") == "revision_edited_back" for e in audit)

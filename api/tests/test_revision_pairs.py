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
    """A (12-05) closed by this conversation's correction B (12-08, the same slot), B open; ``tail_kw`` on B."""
    a = _claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_b")
    b = _claim("clm_b", tail_kw.pop("predicate", "is-moving-to"), "2026-12-08", supersedes="clm_a", **tail_kw)
    return a, b


def _ending():
    e = _claim("clm_e", "is-moving-to", "2026-12-08", valid_to="2026-12-08", supersedes="clm_a")
    e.text = "Lia previously moved to Valencia"
    return e


def _restated():
    return _claim("clm_a", "is-moving-to", "2026-12-05")


def _reconcile(slot, *, revising=True, redated=("clm_b",), revised=(), new=None):
    from types import SimpleNamespace

    from api.services.claim_reconciler import reconcile_stage3

    new = new or _restated()
    settings = SimpleNamespace(memory_path=None, litellm_model="fake", archive_threshold=0.2, decay_nudge_threshold=0.4)
    out, nudges, audit = reconcile_stage3(
        [new], {"lia-prueba": list(slot)}, settings, now_date="2026-11-25", decay=False,
        cardinality_fn=lambda p: False,
        redated={i: EP for i in redated} or None, revised={i: EP for i in revised} or None,
        revising={EP: _restore_rev()} if revising else None)
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
                               episodes=(EP, OTHER)), _chain()[1]))),
    ("closed by decay (no successor)",
     lambda: dict(slot=(_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08"),), redated=())),
    # The rows below name the closed claim in ``redated`` too (the pipeline never does): each check is tested alone.
    ("the claim that took its place was closed by decay",
     lambda: dict(slot=_chain(valid_to="2026-11-20"))),
    ("closed by an ending this conversation said",
     lambda: dict(slot=(_claim("clm_a", "is-moving-to", "2026-12-05", valid_to="2026-12-08", superseded_by="clm_e"),
                        _ending()), redated=("clm_e",))),
    ("the correction was then withdrawn by an agent",
     lambda: dict(slot=(*_chain(valid_to="2026-11-20", superseded_by="clm_retract_x"),
                        _claim("clm_retract_x", "retracts", "2026-11-20", valid_to="2026-11-20", supersedes="clm_b",
                               recorded_ts="2026-11-20T10:00:00Z")), redated=("clm_b", "clm_retract_x"))),
    ("the correction was then replaced by another conversation's claim",
     lambda: dict(slot=(*_chain(valid_to="2026-12-09", superseded_by="clm_c"),
                        _claim("clm_c", "is-moving-to", "2026-12-09", supersedes="clm_b", episodes=(OTHER,))),
                  redated=("clm_c",))),
    ("the correction gives way by no rule that exists (no third)", lambda: dict(slot=_chain(), redated=())),
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

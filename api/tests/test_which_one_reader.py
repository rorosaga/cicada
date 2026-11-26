"""Ruling 83, first half: context decides which one was meant, and only then is anyone asked (`which_one_reader`).

A mention that could be two known pages is filed under the one its own conversation points to, through exactly what a tap on that
choice does, when (code) the held line is the question's, every conversation it holds was read, the main model named the same
candidate twice with a sentence located in the person's own turn, and the sentence (or its turn) carries something the record holds
for that candidate and for no other. Everything else stays the question, byte for byte.

Synthetic banks, invented names, a scripted reader: no engine and no network.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date

import pytest

from api.services import (bank_index, clarification_manager, evidence, inbox_tend, markdown_parser, pending_store, same_name,
                          which_one, which_one_reader as wr)
from api.services.claims import parse_claims
from api.tests.test_held_release import _Settings, _commit, _git, _held, _page

TODAY = date(2026, 11, 26)
EP1, EP2 = "ep_2026-11-20_001", "ep_2026-11-21_001"


def _episode(bank, ep: str, body: str, **extra) -> None:
    markdown_parser.write(bank / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": True, "source": "import", "origin": "chatgpt",
                           "timestamp": f"{ep[3:13]}T10:00:00+00:00", **extra}, body)


def _set(bank, pid: str, **fm) -> None:
    parsed = markdown_parser.parse(bank / "entities" / f"{pid}.md")
    markdown_parser.write(bank / "entities" / f"{pid}.md", {**parsed.frontmatter, **fm}, parsed.body)


def _world(tmp_path, monkeypatch, *, conversations: dict[str, str], line_episodes: list[str] | None = None,
           mention: str = "Nick", subject_page: bool = False):
    """Two people who answer to "Nick" (a brother, and a friend tied to a company), one conversation per entry, one held line,
    and the which-one question about it."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    from api.services import predicates

    bank = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True)
    predicates.install_predicate_map(bank)
    _page(bank, "nick-brother", "Nick Rowe", "person")
    _set(bank, "nick-brother", owner_roles=["brother"])
    _page(bank, "nick-friend", "Nick Vale", "person")
    page = bank / "entities" / "nick-friend.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body + "\nWorks at [[acme-labs]].\n")
    _page(bank, "acme-labs", "Acme Labs", "company")
    if subject_page:
        _page(bank, sanitize(mention), mention, "person")
    for ep, text in conversations.items():
        _episode(bank, ep, text)
    episodes = line_episodes or list(conversations)
    pending_store.upsert(bank, pending_store.PendingEntity(
        name=mention, type="person", description=f"{mention}, said once.", source_episode=episodes[0], confidence=0.7, tags=[],
        history_entries=[], held_claims=[_held(sanitize(mention), "visits", "a-weekend", 1, episodes[0])],
        heard_in=[{"episode": e} for e in episodes]))
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        _git(bank, *args)
    same_name.invalidate()
    path = which_one.raise_question(bank, mention, episodes[0], ["nick-brother", "nick-friend"], today=TODAY)
    assert path, "the which-one question exists"
    _commit(bank, "seed")
    return bank, bank / path


def sanitize(name: str) -> str:
    from api.services.id_utils import sanitize_id

    return sanitize_id(name)


_CAND = re.compile(r"^([A-F])\. (.+?)(?: \(|\s—)", re.M)


def scripted(*, name: str, sentence: str | None = None, answer: str | None = None, second: str | None = None, calls: list | None = None):
    """A reader that answers by the candidate's name (the letters move between the two reads) and copies ``sentence``."""
    async def ask(system: str, prompt: str) -> object:
        if calls is not None:
            calls.append(prompt)
        letters = {n: letter for letter, n in _CAND.findall(prompt)}
        mine = second if (second and "Be a skeptic" in prompt) else name
        got = answer or letters.get(mine, "none")
        return {"answer": got, "sentence": sentence or "", "reason": "scripted"}

    return ask


def _run(bank, path, ask, *, dry_run=False, trace=None):
    fm = dict(markdown_parser.parse(path).frontmatter)
    assert wr.is_eligible(fm, TODAY.isoformat())
    return asyncio.run(wr.tend(bank, _Settings(bank), ask, today=TODAY, dry_run=dry_run, trace=trace, model="haiku"))


def _claims(bank, pid):
    return [(c.subject, c.predicate, c.object) for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{pid}.md").body)]


def _untouched(bank, path, before: bytes) -> None:
    assert path.read_bytes() == before, "the question is exactly as it was"
    assert not (bank / "inbox" / "settled").exists() or not list((bank / "inbox" / "settled").glob("*.md"))


# --------------------------------------------------------------------------- filed by context


def test_a_relation_beside_the_name_files_the_mention_under_that_person_and_nobody_is_asked(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting this weekend.\nassistant: Nice."})
    calls: list = []
    report = _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting this weekend.", calls=calls))
    assert (report.read, report.settled, report.calls) == (1, 1, 2) and len(calls) == 2, "two reads, one conversation"
    assert not path.exists() and (bank / "inbox" / "settled" / f"{path.stem}.md").is_file()
    assert ("nick-brother", "visits", "a-weekend") in _claims(bank, "nick-brother"), "what a tap does: the held line lands there"
    assert _claims(bank, "nick-friend") == []
    assert "Nick" not in (markdown_parser.parse(bank / "entities" / "nick-brother.md").frontmatter.get("aliases") or []), \
        "a pick is the mention's answer, never an alias"
    rec = markdown_parser.parse(bank / "inbox" / "settled" / f"{path.stem}.md").frontmatter["settled"]
    assert rec["rule"] == wr.RULE and "visiting this weekend" in rec["reason"] and rec["evidence_spans"]
    assert "Settled" in _git(bank, "log", "-1", "--format=%B") or "Sleep" in _git(bank, "log", "-1", "--format=%B")


def test_a_full_name_two_turns_earlier_files_it_under_that_person(tmp_path, monkeypatch):
    talk = ("user: I had lunch with Nick Vale on Tuesday.\nassistant: How was it?\nuser: Good, we talked for ages.\n"
            "assistant: Great.\nuser: Nick wants to visit again soon.")
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: talk})
    report = _run(bank, path, scripted(name="Nick Vale", sentence="I had lunch with Nick Vale on Tuesday."))
    assert report.settled == 1 and ("nick-friend", "visits", "a-weekend") in _claims(bank, "nick-friend")


def test_a_thing_only_one_candidate_is_linked_to_files_it(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Nick from Acme Labs sent the contract over.\nassistant: Ok."})
    report = _run(bank, path, scripted(name="Nick Vale", sentence="Nick from Acme Labs sent the contract over."))
    assert report.settled == 1 and _claims(bank, "nick-friend")


def test_spanish_works_the_same_way(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Mi hermano Nick llega mañana.\nassistant: Perfecto."})
    _set(bank, "nick-brother", owner_roles=["hermano"])
    _commit(bank, "spanish role")
    report = _run(bank, path, scripted(name="Nick Rowe", sentence="Mi hermano Nick llega mañana."))
    assert report.settled == 1 and _claims(bank, "nick-brother")


# --------------------------------------------------------------------------- left as the question


@pytest.mark.parametrize("talk, sentence, why", [
    ("user: Nick called me yesterday.\nassistant: Ok.", "Nick called me yesterday.", "nothing_tells_them_apart"),
    ("user: My brother Nick and Nick Vale came.\nassistant: Ok.", "My brother Nick and Nick Vale came.", "nothing_tells_them_apart"),
    ("user: Nick said hi.\nassistant: Your brother Nick usually does.", "Your brother Nick usually does.", "first_read_sentence_not_located"),
], ids=["nothing decides", "a sentence that names both", "only the assistant said it"])
def test_a_pick_the_record_cannot_tie_stays_the_question(tmp_path, monkeypatch, talk, sentence, why):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: talk})
    before = path.read_bytes()
    report = _run(bank, path, scripted(name="Nick Rowe", sentence=sentence))
    assert report.settled == 0
    _untouched(bank, path, before)
    assert _claims(bank, "nick-brother") == [] and _claims(bank, "nick-friend") == []


@pytest.mark.parametrize("answer", ["none", "cannot_tell"])
def test_none_and_cannot_tell_leave_the_question_exactly_as_it_is_and_are_remembered(tmp_path, monkeypatch, answer):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    before = path.read_bytes()
    calls: list = []
    assert _run(bank, path, scripted(name="x", answer=answer, calls=calls)).settled == 0
    _untouched(bank, path, before)
    assert len(calls) == 1, "one read: nothing to confirm"
    again: list = []
    assert _run(bank, path, scripted(name="x", answer=answer, calls=again)).read == 0 and not again, "not read again unchanged"


def test_two_reads_that_name_different_candidates_leave_the_question(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    before = path.read_bytes()
    ask = scripted(name="Nick Rowe", second="Nick Vale", sentence="My brother Nick is visiting.")
    assert _run(bank, path, ask).settled == 0
    _untouched(bank, path, before)


def test_the_assistants_turn_is_never_where_the_mention_was_said(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Hello.\nassistant: Your brother Nick called."})
    assert _run(bank, path, scripted(name="Nick Rowe", sentence="Your brother Nick called.")).read == 1
    assert path.exists()


def test_every_conversation_the_line_holds_must_name_the_same_candidate(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={
        EP1: "user: My brother Nick is visiting.\nassistant: Nice.",
        EP2: "user: Nick Vale and I shipped it.\nassistant: Great."})
    before = path.read_bytes()

    async def ask(system, prompt):
        mine = "Nick Rowe" if "brother Nick is visiting" in prompt else "Nick Vale"
        sentence = "My brother Nick is visiting." if mine == "Nick Rowe" else "Nick Vale and I shipped it."
        return await scripted(name=mine, sentence=sentence)(system, prompt)

    report = _run(bank, path, ask)
    assert report.settled == 0 and report.calls == 4
    _untouched(bank, path, before)


def test_a_line_with_more_conversations_than_the_bound_is_left_unread(tmp_path, monkeypatch):
    eps = {f"ep_2026-11-{20 + i}_001": "user: My brother Nick is visiting.\nassistant: Nice." for i in range(wr.MAX_CONVERSATIONS + 1)}
    bank, path = _world(tmp_path, monkeypatch, conversations=eps)
    calls: list = []
    assert _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting.", calls=calls)).read == 0 and not calls


def test_a_mention_that_shares_its_id_with_a_page_is_the_persons_call(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."},
                        subject_page=True)
    calls: list = []
    assert _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting.", calls=calls)).read == 0 and not calls


def test_nothing_held_is_nothing_to_file(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    pending_store.drop_held(bank, ["clm_held_1"])
    pending_store.upsert(bank, pending_store.PendingEntity(name="Nick", type="person", description="", source_episode=EP1,
                                                           confidence=0.7, tags=[], history_entries=[]))
    assert asyncio.run(wr.run_tail(bank, _Settings(bank), user_triggered=True, ask=None)).read == 0


def test_a_candidate_the_person_said_the_mention_is_not_is_never_offered(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    pending_store.mark_apart(bank, "Nick", ["nick-brother"], [EP1])
    assert isinstance(wr.case_for(bank, path, dict(markdown_parser.parse(path).frontmatter)), str)


def test_the_owners_own_page_is_never_a_candidate(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    _set(bank, "nick-brother", owner=True)
    assert isinstance(wr.case_for(bank, path, dict(markdown_parser.parse(path).frontmatter)), str)


def test_a_rigged_reader_that_always_picks_the_first_files_only_where_the_record_ties_it(tmp_path, monkeypatch):
    """What the code conditions alone let through: the first candidate by name, copying the turn the mention is in."""
    stories = {
        "relation": ("user: My brother Nick is visiting.", "Nick Rowe", True),
        "friend's company": ("user: Nick from Acme Labs called.", "Nick Rowe", False),
        "nothing": ("user: Nick called.", "Nick Rowe", False),
        "both": ("user: My brother Nick and Nick Vale called.", "Nick Rowe", False),
    }
    filed = {}
    for key, (talk, first, _right) in stories.items():
        sub = tmp_path / key.replace(" ", "-").replace("'", "")
        sub.mkdir()
        bank, path = _world(sub, monkeypatch, conversations={EP1: f"{talk}\nassistant: Ok."})
        filed[key] = _run(bank, path, scripted(name=first, sentence=talk.removeprefix("user: "))).settled
    assert filed == {"relation": 1, "friend's company": 0, "nothing": 0, "both": 0}, \
        "wrong filings: the code leaves the one that rests on the other candidate's tie, and the ones with no tie"


# --------------------------------------------------------------------------- the dry run is silent, and a settle the person undoes is theirs


def test_a_dry_run_writes_nothing_and_remembers_nothing(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    rows: list = []
    report = _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting."), dry_run=True, trace=rows.append)
    assert report.settled == 1 and path.exists() and not _git(bank, "status", "--porcelain").strip()
    assert any(r["what"] == "would_file:nick-brother" for r in rows)
    assert any((r.get("eyes") or {}).get("sentence") for r in rows), "the eyes lines carry the words; the others never"
    plain = [r for r in rows if not r.get("eyes")]
    assert plain == [] and all("Nick" not in repr({k: v for k, v in r.items() if k != "eyes"}) for r in rows)


def test_a_settle_the_person_undoes_is_not_filed_again_until_something_it_read_changes(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    ask = scripted(name="Nick Rowe", sentence="My brother Nick is visiting.")
    assert _run(bank, path, ask).settled == 1
    seen = wr._seen(bank)
    assert seen[path.stem]["o"] == "filed"
    assert not wr.qr.due(seen[path.stem], seen[path.stem]["d"], "haiku")


def test_the_settle_is_refused_when_the_person_answers_while_the_model_reads(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})

    async def ask(system, prompt):
        pending_store.mark_apart(bank, "Nick", ["nick-brother"], [EP1])   # the person says "not him" while the model reads
        return await scripted(name="Nick Rowe", sentence="My brother Nick is visiting.")(system, prompt)

    assert _run(bank, path, ask).settled == 0 and path.exists()


# --------------------------------------------------------------------------- born in the right form


def _clarifier_world(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Nick Rowe and Nick Vale called, and Nick too.\nassistant: Ok."})
    path.unlink()
    _commit(bank, "no question yet")
    return bank


def test_stage_2s_question_for_a_name_two_people_answer_to_is_born_as_one_which_one(tmp_path, monkeypatch):
    bank = _clarifier_world(tmp_path, monkeypatch)
    clar = clarification_manager.ClarificationManager(bank)
    first = clar.create(entity_name="Nick", source_episode=EP1, uncertainty_type="Possible duplicate of Nick Rowe",
                        suggested_classification="person — could refer to the same person as Nick Rowe", suggested_confidence=0.5,
                        source_context="Could not decide.", target_id="nick-brother")
    assert first
    fm = markdown_parser.parse(bank / "inbox" / f"{first}.md").frontmatter
    assert fm["detected"] == which_one.DETECTED and fm["same_title"] == ["nick-brother", "nick-friend"]
    assert fm["title"] == "Were you talking about Nick Rowe or Nick Vale?"
    assert clar.create(entity_name="Nick", source_episode=EP1, uncertainty_type="Possible duplicate of Nick Vale",
                       suggested_classification="person", suggested_confidence=0.5, source_context="x",
                       target_id="nick-friend") is None, "the one open is the question: no pairwise one beside it"
    assert len(list((bank / "inbox").glob("inbox-*.md"))) == 1
    assert which_one.tend(bank, TODAY).written == [], "nothing is left for the nightly rewrite to convert"


def test_one_candidate_stays_the_pairwise_question(tmp_path, monkeypatch):
    bank, _path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Hi.\nassistant: Hi."}, mention="Nick")
    _page(bank, "mira-quell", "Mira Quell", "person")
    clar = clarification_manager.ClarificationManager(bank)
    item = clar.create(entity_name="Mira", source_episode=EP1, uncertainty_type="Possible duplicate of Mira Quell",
                       suggested_classification="person", suggested_confidence=0.6, source_context="x", target_id="mira-quell")
    fm = markdown_parser.parse(bank / "inbox" / f"{item}.md").frontmatter if item else {}
    assert not item or fm.get("detected") != which_one.DETECTED


def test_the_agent_never_works_a_which_one_question_as_a_pair(tmp_path, monkeypatch):
    from api.services import harness_agent as ha, harness_questions as hq

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Nick called.\nassistant: Ok."})
    assert hq.not_workable(bank, dict(markdown_parser.parse(path).frontmatter), ha.PRIVATE) == "not_a_pair"


def test_the_settled_rule_has_words_and_an_engine_free_recheck_is_not_claimed():
    assert inbox_tend.RULES[wr.RULE] and wr.RULE not in inbox_tend.ENGINE_FREE


# --------------------------------------------------------------------------- the owner's dry run


def _script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "which_one_dry_run.py"
    spec = importlib.util.spec_from_file_location("which_one_dry_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_dry_run_prints_ids_only_writes_nothing_and_refuses_eyes_inside_the_repo(tmp_path, monkeypatch, capsys):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    script = _script()
    assert script.main(["--memory", str(bank), "--eyes", str(script.REPO_ROOT / "eyes.txt")]) == 2
    eyes = tmp_path / "eyes.txt"
    assert script.main(["--memory", str(bank), "--eyes", str(eyes)]) == 0
    out = capsys.readouterr().out
    assert path.stem in out and "would_read" in out and "nick-brother,nick-friend" in out
    assert "Nick " not in out and "brother Nick" not in out, "no word of text on the stable lines"
    assert eyes.is_file() and not _git(bank, "status", "--porcelain").strip()

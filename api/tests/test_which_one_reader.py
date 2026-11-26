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


def test_conversations_that_name_different_candidates_are_each_filed_to_their_own(tmp_path, monkeypatch):
    """Ruling 83 (per conversation, `which_one_file`): the held line is no longer all-or-nothing. The line here holds one fact, said
    in the first conversation, so only that one goes, to the person that conversation meant; the second names the other person and
    has nothing held to file."""
    bank, path = _world(tmp_path, monkeypatch, conversations={
        EP1: "user: My brother Nick is visiting.\nassistant: Nice.",
        EP2: "user: Nick Vale and I shipped it.\nassistant: Great."})
    before = path.read_bytes()

    async def ask(system, prompt):
        mine = "Nick Rowe" if "brother Nick is visiting" in prompt else "Nick Vale"
        sentence = "My brother Nick is visiting." if mine == "Nick Rowe" else "Nick Vale and I shipped it."
        return await scripted(name=mine, sentence=sentence)(system, prompt)

    report = _run(bank, path, ask)
    assert report.settled == 1 and report.calls == 4
    assert ("nick-brother", "visits", "a-weekend") in _claims(bank, "nick-brother") and _claims(bank, "nick-friend") == []
    assert path.read_bytes() != before or not path.exists()


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


# --------------------------------------------------------------------------- the review's lines: a tell must be attached to the mention

#: ``(talk, the words the rigged reader copies, the candidate it always picks)``: each of these once filed the held line under the
#: wrong page because a tell of the pick stood somewhere in the sentence or its turn with nothing tying it to the mention.
MUST_NOT_FILE = {
    "a brother told me": ("My brother told me Nick quit his job.", "Nick Rowe"),
    "the brother's friend": ("My brother's friend Nick plays guitar.", "Nick Rowe"),
    "brother-in-law": ("My brother-in-law Nick is coming.", "Nick Rowe"),
    "not my brother, the other": ("Not my brother, the other Nick came by.", "Nick Rowe"),
    "a question": ("Which Nick, my brother, did you mean?", "Nick Rowe"),
    "a bare mention beside the full name": ("Nick and Nick Vale argued about it.", "Nick Vale"),
    "told him about the company": ("I told Nick about Acme Labs yesterday.", "Nick Vale"),
    "spanish: a brother told me": ("Mi hermano me dijo que Nick renunció.", "Nick Rowe"),
    "spanish: not him": ("No es mi hermano Nick, es el otro.", "Nick Rowe"),
    "spanish: a question": ("¿Es Nick mi hermano?", "Nick Rowe"),
    "contrast after the tie": ("My brother Nick is visiting, but not for long.", "Nick Rowe"),
    "a name too: my brother Dan": ("Nick is my brother Dan and I.", "Nick Rowe"),
}


@pytest.mark.parametrize("key", list(MUST_NOT_FILE))
def test_a_tell_that_is_not_attached_to_the_mention_never_files_it(tmp_path, monkeypatch, key):
    sentence, who = MUST_NOT_FILE[key]
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: f"user: {sentence}\nassistant: Ok."})
    _set(bank, "nick-brother", owner_roles=["brother", "hermano"])   # the record holds both words: the refusal is the sentence's
    _commit(bank, "both words")
    before = path.read_bytes()
    assert _run(bank, path, scripted(name=who, sentence=sentence)).settled == 0
    _untouched(bank, path, before)
    assert _claims(bank, "nick-brother") == [] and _claims(bank, "nick-friend") == []


@pytest.mark.parametrize("sentence, who", [
    ("My brother Nick is visiting this weekend.", "Nick Rowe"),
    ("Nick, my brother, is visiting this weekend.", "Nick Rowe"),
    ("Nick is my brother and he is visiting.", "Nick Rowe"),
    ("I think Nick (my brother) is visiting.", "Nick Rowe"),
    ("Nick Vale is visiting this weekend.", "Nick Vale"),
    ("Nick from Acme Labs is visiting this weekend.", "Nick Vale"),
    ("Nick, at Acme Labs, is visiting this weekend.", "Nick Vale"),
    ("Mi hermano Nick llega mañana.", "Nick Rowe"),
    ("Nick, mi hermano, llega mañana.", "Nick Rowe"),
    ("Nick es mi hermano y llega mañana.", "Nick Rowe"),
    ("Nick de Acme Labs llega mañana.", "Nick Vale"),
    ("Nick en Acme Labs llega mañana.", "Nick Vale"),
])
def test_the_forms_that_attach_a_tell_to_the_mention_file_it(tmp_path, monkeypatch, sentence, who):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: f"user: {sentence}\nassistant: Ok."})
    _set(bank, "nick-brother", owner_roles=["brother", "hermano"])
    _commit(bank, "both words")
    assert _run(bank, path, scripted(name=who, sentence=sentence)).settled == 1, sentence
    assert _claims(bank, "nick-brother" if who == "Nick Rowe" else "nick-friend")


def test_the_tell_in_another_turn_never_counts_only_the_copied_sentence_does(tmp_path, monkeypatch):
    talk = ("user: My brother is flying in on Friday.\nassistant: Nice.\nuser: Anyway, Nick from the gym called me.\n"
            "assistant: Ok.")
    for sentence in ("My brother is flying in on Friday.", "Anyway, Nick from the gym called me."):
        sub = tmp_path / str(abs(hash(sentence)))
        sub.mkdir()
        bank, path = _world(sub, monkeypatch, conversations={EP1: talk})
        before = path.read_bytes()
        assert _run(bank, path, scripted(name="Nick Rowe", sentence=sentence)).settled == 0
        _untouched(bank, path, before)


def test_a_tell_far_from_the_mention_in_one_long_turn_is_outside_what_the_reader_saw(tmp_path, monkeypatch):
    talk = ("user: " + "filler words here. " * 400 + "Nick quit his job on Monday. " + "more filler text. " * 300
            + "my brother is great.\nassistant: Ok.")
    for sentence in ("Nick quit his job on Monday.", "my brother is great."):
        sub = tmp_path / str(abs(hash(sentence)))
        sub.mkdir()
        bank, path = _world(sub, monkeypatch, conversations={EP1: talk})
        before = path.read_bytes()
        assert _run(bank, path, scripted(name="Nick Rowe", sentence=sentence)).settled == 0
        _untouched(bank, path, before)


def test_an_alias_of_a_linked_page_that_is_a_common_word_is_no_tell(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: Nick from home called me.\nassistant: Ok."})
    _page(bank, "harbor-house", "Harbor House", "place")
    _set(bank, "harbor-house", aliases=["home", "Harbor", "the old house"])
    page = bank / "entities" / "nick-friend.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body + "\nLives near [[harbor-house]].\n")
    _commit(bank, "a place")
    cands = wr.candidates_of(bank, ["nick-brother", "nick-friend"], "Nick")
    words = {t.words for c in cands for t in c.tells if t.kind == "linked"}
    assert "home" not in words and {"Harbor House", "Harbor", "the old house"} <= words
    before = path.read_bytes()
    assert _run(bank, path, scripted(name="Nick Vale", sentence="Nick from home called me.")).settled == 0
    _untouched(bank, path, before)


def test_a_relation_two_candidates_share_is_no_tell(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Ok."})
    _set(bank, "nick-friend", owner_roles=["brother"])
    _commit(bank, "two brothers")
    before = path.read_bytes()
    assert _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting.")).settled == 0
    _untouched(bank, path, before)


def test_a_sentence_names_the_mention_only_once_per_tell_every_occurrence_must_be_attached(tmp_path, monkeypatch):
    talk = "user: My brother Nick said Nick would come.\nassistant: Ok."
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: talk})
    before = path.read_bytes()
    assert _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick said Nick would come.")).settled == 0
    _untouched(bank, path, before)


def test_the_reader_is_told_the_name_and_the_clue_must_stand_in_one_sentence():
    assert "stand together" in wr.PROMPT and "in another sentence or another turn" in wr.PROMPT


_ROLE = [wr.Tell("role", "brother"), wr.Tell("role", "hermano")]
_FULL = [wr.Tell("full_name", "Nick Rowe")]
_LINKED = [wr.Tell("linked", "Acme Labs"), wr.Tell("linked", "Harbor")]


@pytest.mark.parametrize("text, tells, kinds", [
    ("My brother Nick came", _ROLE, ["role"]), ("Brother Nick came", _ROLE, ["role"]), ("MY  BROTHER  NICK", _ROLE, ["role"]),
    ("Nick (my brother) came", _ROLE, ["role"]), ("Nick's my brother", _ROLE, ["role"]), ("Mi hermano Nick", _ROLE, ["role"]),
    ("Nick Rowe called", _FULL, ["full_name"]), ("nick rowe called", _FULL, ["full_name"]),
    ("Nick from Acme Labs", _LINKED, ["linked"]), ("Nick from the Acme Labs team", _LINKED, ["linked"]),
    ("Acme Labs's Nick called", _LINKED, ["linked"]), ("Nick of Acme Labs", _LINKED, ["linked"]),
    ("Nick from Harbor", _LINKED, ["linked"]),
    # what breaks an attachment
    ("your brother Nick came", _ROLE, []), ("step-brother Nick came", _ROLE, []), ("my brother's friend Nick", _ROLE, []),
    ("Nick's brother came", _ROLE, []), ("Nick, my brother Dan, came", _ROLE, []), ("my older brother Nick", _ROLE, []),
    ("Nick called Nick Rowe", _FULL, []), ("Nick Smith from Acme Labs", _LINKED, []), ("Nick from harbor", _LINKED, []),
    ("Nick and Acme Labs", _LINKED, []), ("Nick works at Acme Labs", _LINKED, []),
])
def test_the_forms_that_attach_a_tell_to_the_mention(text, tells, kinds):
    assert wr.tie_of.attach(text, "Nick", tells) == kinds


@pytest.mark.parametrize("sentence, refused", [
    ("My brother Nick is visiting.", False), ("My brother Nick isn't visiting.", True), ("Is my brother Nick visiting?", True),
    ("Which one is my brother Nick", True), ("¿Mi hermano Nick llega hoy?", True), ("Mi hermano Nick no llega hoy.", True),
    ("My brother Nick is visiting but not the other one.", True), ("Mi hermano Nick llega, pero tarde.", True),
    ("My brother Nick is a different person.", True),
])
def test_a_question_a_negation_or_a_contrast_is_refused(sentence, refused):
    assert (wr.tie_of.tie("Nick", sentence, sentence, _ROLE, []) == []) is refused


def test_a_tell_of_another_candidate_in_the_sentence_is_refused():
    sentence = "My brother Nick works at Acme Labs."
    assert wr.tie_of.tie("Nick", sentence, sentence, _ROLE, [_LINKED]) == []
    assert wr.tie_of.tie("Nick", sentence, sentence, _ROLE, []) == ["role"]


def test_the_sentence_a_copy_is_cut_from_is_judged_whole_inside_what_was_shown():
    text = "Not him. That is not my brother Nick, honestly. Anyway."
    start = text.index("my brother Nick")
    quote = "my brother Nick"
    context = wr.tie_of.enclosing(text, start, start + len(quote), 0, len(text))
    assert context.strip() == "That is not my brother Nick, honestly."
    assert wr.tie_of.tie("Nick", quote, context, _ROLE, []) == [], "a reader cannot copy the 'not' away"
    assert wr.tie_of.enclosing(text, start, start + len(quote), start, start + len(quote)) == quote, "clamped to what was shown"


# --------------------------------------------------------------------------- a filing whose commit fails leaves nothing behind


def _tree(bank) -> dict[str, bytes]:
    return {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted(bank.rglob("*")) if p.is_file() and ".git" not in p.parts}


def test_a_filing_whose_commit_fails_puts_every_file_back_and_the_question_stays(tmp_path, monkeypatch):
    from api.services import git_service

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    stray = bank / "entities" / "acme-labs.md"
    stray.write_bytes(stray.read_bytes() + b"\nAn edit the person had not saved yet.\n")   # dirty before, and not the filing's
    before, head = _tree(bank), _git(bank, "rev-parse", "HEAD").strip()

    def boom(*args, **kwargs):
        raise git_service.GitError("the commit failed")

    monkeypatch.setattr(git_service, "commit_touched_sync", boom)
    report = _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting."))
    assert report.settled == 0 and path.exists()
    assert _tree(bank) == before, "every file the step touched is as it was: the pages, the held line, the question, no record"
    assert _git(bank, "rev-parse", "HEAD").strip() == head
    assert _git(bank, "status", "--porcelain").split() == ["M", "entities/acme-labs.md"], "only the earlier edit stays uncommitted"
    assert _claims(bank, "nick-brother") == [] and pending_store.held_line(bank, "Nick").held_claims
    assert wr._seen(bank)[path.stem]["o"] == "not_applied", "remembered as not filed, so it is read again, not forgotten"


def test_a_filing_that_commits_still_files_with_an_earlier_edit_left_alone(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    stray = bank / "entities" / "acme-labs.md"
    stray.write_bytes(stray.read_bytes() + b"\nAn edit the person had not saved yet.\n")
    assert _run(bank, path, scripted(name="Nick Rowe", sentence="My brother Nick is visiting.")).settled == 1
    assert b"had not saved yet" in stray.read_bytes()


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


def test_a_question_about_two_pages_is_written_exactly_as_before(tmp_path, monkeypatch):
    """`role_people.ask_same`: a nickname-titled PAGE against a full-name page. The subject has a page of its own, so it is no held
    mention: it stays the pairwise question the agent can work, never pulling in a third page that only shares the first name."""
    from api.services import harness_agent as ha, harness_questions as hq, role_people

    bank = _clarifier_world(tmp_path, monkeypatch)
    _page(bank, "nick", "Nick", "person")
    same_name.invalidate()
    item = role_people.ask_same(bank, "nick", "nick-friend", "You call this person Nick.")
    fm = dict(markdown_parser.parse(bank / item).frontmatter)
    assert fm.get("detected") != which_one.DETECTED and not fm.get("same_title")
    assert (fm["entity_id"], fm["merge_target_hint"], fm["fold_page"]) == ("nick", "nick-friend", True)
    assert fm["uncertainty_type"] == "Possible duplicate of Nick Vale" and "Rowe" not in fm["title"]
    assert hq.not_workable(bank, fm, ha.PRIVATE) != "not_a_pair", "the agent can still work a pair of pages"


@pytest.mark.parametrize("how", ["not on disk yet", "faded"])
def test_a_target_that_is_not_live_is_never_offered_and_such_a_question_is_not_even_asked(tmp_path, monkeypatch, how):
    """The question's own page missing from the choices cannot happen through Stage 2: `candidates_for` drops a page that is not
    live or not on disk, and `pair_evidence` has already refused to ask about one."""
    bank = _clarifier_world(tmp_path, monkeypatch)
    if how == "faded":
        _page(bank, "nick-gone", "Nick Gone", "person")
        _set(bank, "nick-gone", status="archived")
        same_name.invalidate()
    target = "nick-gone" if how == "faded" else "nick-newguy"
    assert target not in which_one.candidates_for(bank, "Nick", [target])
    item = clarification_manager.ClarificationManager(bank).create(
        entity_name="Nick", source_episode=EP1, uncertainty_type=f"Possible duplicate of {target.replace('-', ' ').title()}",
        suggested_classification="person", suggested_confidence=0.5, source_context="x", target_id=target)
    assert item is None


def test_a_question_whose_own_target_is_not_among_the_choices_keeps_the_form_it_had(tmp_path, monkeypatch):
    """Defence in depth: whatever drops the target, the question is the pairwise one it was, never one that no longer offers it."""
    bank = _clarifier_world(tmp_path, monkeypatch)
    monkeypatch.setattr(which_one, "candidates_for", lambda *a, **k: ["nick-friend", "nick-other"])
    item = clarification_manager.ClarificationManager(bank).create(
        entity_name="Nick", source_episode=EP1, uncertainty_type="Possible duplicate of Nick Rowe",
        suggested_classification="person", suggested_confidence=0.5, source_context="x", target_id="nick-brother")
    assert item
    fm = markdown_parser.parse(bank / "inbox" / f"{item}.md").frontmatter
    assert fm.get("detected") != which_one.DETECTED and not fm.get("same_title") and fm["merge_target_hint"] == "nick-brother"


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


def test_the_dry_run_refuses_a_demo_bank_before_anything_is_read(tmp_path, monkeypatch, capsys):
    bank, _path = _world(tmp_path, monkeypatch, conversations={EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    from api.services import demo_guard

    demo_guard.manifest_path(bank).write_text(f"kind: {demo_guard.DEMO_KIND}\n", encoding="utf-8")

    assert demo_guard.is_demo(bank), "the fixture is a demo bank"
    script = _script()

    def never(*args, **kwargs):
        raise AssertionError("a demo bank was read")

    monkeypatch.setattr(wr, "eligible", never)
    monkeypatch.setattr(wr, "tend", never)
    assert script.main(["--memory", str(bank), "--read"]) == 2
    assert "demo" in capsys.readouterr().err


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

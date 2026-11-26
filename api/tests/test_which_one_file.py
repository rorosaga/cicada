"""Ruling 83: a held mention is filed conversation by conversation (`which_one_file`, `which_one_reader`).

One nickname, two people, two conversations: in one it stands beside "my brother", in another beside a full name. Each conversation's
words go to the page its own reading named, through the landing a pick uses, one record per page, undoable per record; a
conversation nobody could tell keeps its words on the line and the question is about it alone; the person's pick on such a question
files that conversation only. Synthetic banks, invented names, a scripted reader: no engine and no network.
"""
from __future__ import annotations

import asyncio

from api.services import markdown_parser, pending_store, which_one_file as wf, which_one_reader as wr
from api.services import described_landing as dl
from api.services.claims import parse_claims
from api.tests.test_held_release import _git, _Settings, _held
from api.tests.test_which_one_reader import EP1, EP2, TODAY, _claims, _run, _world, scripted

EP3 = "ep_2026-11-22_001"
BROTHER = "user: My brother Nick is visiting this weekend.\nassistant: Nice."
MATE = "user: Nick Vale and I shipped the release together.\nassistant: Great."
BLANK = "user: Nick said hello again, that was all.\nassistant: Ok."


def _row(field: str, text: str, ep: str) -> dict:
    return {"field": field, "text": text, "evidence": [{"episode": ep, "hash": "h", "start": -1, "end": -1, "kind": "reasoning"}]}


def _hold(bank, *, claims: list[tuple[str, str, str]], facts: dict[str, str] | None = None, history: bool = False) -> None:
    """The held line the world made, with these claims (predicate, object, episode) and these key facts (text, episode)."""
    def change(line):
        line.held_claims = [_held("nick", p, o, i, ep) for i, (p, o, ep) in enumerate(claims, 1)]
        line.key_facts = list(facts or {})
        line.item_inputs = [_row("key_facts", t, ep) for t, ep in (facts or {}).items()]
        line.history_entries = [{"date": "2026-11-20", "event": "Nick came up"}] if history else []
        line.heard_in = [{"episode": e} for e in dict.fromkeys(ep for *_x, ep in claims)]
        return True
    wf.edit_line(bank, "Nick", change)


def _by_name(sentences: dict[str, tuple[str, str]]):
    """A reader that decides each conversation by a word in the prompt: ``{word: (candidate name, sentence)}``; no word, no verdict."""
    async def ask(system, prompt):
        for word, (name, sentence) in sentences.items():
            if word in prompt:
                return await scripted(name=name, sentence=sentence)(system, prompt)
        return {"answer": "cannot_tell", "sentence": "", "reason": "scripted"}
    return ask


BOTH = {"brother Nick is visiting": ("Nick Rowe", "My brother Nick is visiting this weekend."),
        "Nick Vale and I shipped": ("Nick Vale", "Nick Vale and I shipped the release together.")}


def _commit_all(bank) -> None:
    import subprocess

    _git(bank, "add", "-A")
    subprocess.run(["git", "-C", str(bank), "commit", "-qm", "step"], capture_output=True)


def _settled(bank) -> list[dict]:
    return [markdown_parser.parse(p).frontmatter["settled"] for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))] \
        if (bank / "inbox" / "settled").is_dir() else []


def test_two_conversations_two_people_each_conversations_words_go_to_its_own_person(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)],
          facts={"Visits on weekends.": EP1, "Ships releases.": EP2}, history=True)
    report = _run(bank, path, _by_name(BOTH))
    assert (report.read, report.settled, report.calls) == (1, 2, 4), "four reads, one landing per page"
    assert ("nick-brother", "visits", "a-weekend") in _claims(bank, "nick-brother")
    assert ("nick-friend", "ships", "the-release") in _claims(bank, "nick-friend")
    assert ("nick-friend", "visits", "a-weekend") not in _claims(bank, "nick-friend")
    assert ("nick-brother", "ships", "the-release") not in _claims(bank, "nick-brother"), "never under the wrong person"
    line = pending_store.held_line(bank, "Nick")
    assert line.held_claims == [] and line.key_facts == [] and line.history_entries, "what carries no conversation stays held"
    assert wf.filed(line) == {EP1: "nick-brother", EP2: "nick-friend"}
    assert "Visits on weekends." in (bank / "entities" / "nick-brother.md").read_text()
    assert "Ships releases." not in (bank / "entities" / "nick-brother.md").read_text()
    for pid in ("nick-brother", "nick-friend"):
        assert "Nick" not in (markdown_parser.parse(bank / "entities" / f"{pid}.md").frontmatter.get("aliases") or []), "no alias"
    recs = _settled(bank)
    assert sorted(r["entity_id"] for r in recs) == ["nick-brother", "nick-friend"] and all(r["rule"] == wf.RULE for r in recs)
    assert all(r["evidence_spans"] for r in recs)
    assert not path.exists() and (bank / "inbox" / "settled" / f"{path.stem}.md").is_file(), "every conversation filed: nothing asked"
    assert "Sleep" in _git(bank, "log", "-1", "--format=%B") or "Cicada-Author" in _git(bank, "log", "--format=%B", "-3")


def test_a_line_that_holds_nothing_else_leaves_and_its_question_goes_with_it(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)])
    wf.edit_line(bank, "Nick", lambda ln: bool(setattr(ln, "description", "") or setattr(ln, "summary", "")) or True)
    assert _run(bank, path, _by_name(BOTH)).settled == 2
    assert pending_store.held_line(bank, "Nick") is None, "nothing is left to keep: the line leaves, and a question about nothing is not live"


def test_three_conversations_two_filed_one_asked_about_that_conversation(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE, EP3: BLANK})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2), ("greets", "everyone", EP3)])
    report = _run(bank, path, _by_name(BOTH))
    assert report.settled == 2 and report.calls == 5
    line = pending_store.held_line(bank, "Nick")
    assert [d["predicate"] for d in line.held_claims] == ["greets"], "the conversation nobody could tell keeps its words held"
    assert _claims(bank, "nick-brother") and _claims(bank, "nick-friend")
    fm = markdown_parser.parse(path).frontmatter
    assert path.exists() and wr.which_one.episodes_of(fm) == [EP3], "the question is about the conversation still open"
    assert not wf.scope_of(fm), "one open conversation is the whole-line question as before"


def test_two_conversations_both_the_same_person_is_the_whole_line_as_before(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: "user: My brother Nick called me.\nassistant: Ok."})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("calls", "me", EP2)])
    ask = _by_name({"brother Nick is visiting": ("Nick Rowe", "My brother Nick is visiting this weekend."),
                    "brother Nick called": ("Nick Rowe", "My brother Nick called me.")})
    assert _run(bank, path, ask).settled == 1
    assert not path.exists() and (bank / "inbox" / "settled" / f"{path.stem}.md").is_file(), "one settle of the question, as today"
    assert not _settled(bank), "no per-conversation record"
    assert {c[1] for c in _claims(bank, "nick-brother")} == {"visits", "calls"}


def test_a_fact_two_conversations_share_goes_only_where_both_agree(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1)])
    both = _held("nick", "likes", "tea", 9, EP1)
    both["source_episodes"] = [EP1, EP2]
    wf.edit_line(bank, "Nick", lambda ln: bool(ln.held_claims.append(both)) or True)
    _run(bank, path, _by_name(BOTH))
    assert [d["predicate"] for d in pending_store.held_line(bank, "Nick").held_claims] == ["likes"], "two readings, one fact: held"


def test_undoing_one_filing_puts_its_claims_back_and_the_reader_never_files_it_again(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], facts={"Visits on weekends.": EP1}, history=True)
    _run(bank, path, _by_name(BOTH))
    rec = next(p for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))
               if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-brother")
    _commit_all(bank)
    assert wf.is_record(bank, rec.stem)
    page_before = (bank / "entities" / "nick-brother.md").read_bytes()
    paths, lines, _rec = wf.undo(bank, rec.stem)
    assert not rec.exists() and ("nick-brother", "visits", "a-weekend") not in _claims(bank, "nick-brother")
    assert ("nick-friend", "ships", "the-release") in _claims(bank, "nick-friend"), "the other filing stands"
    line = pending_store.held_line(bank, "Nick")
    assert [d["predicate"] for d in line.held_claims] == ["visits"] and line.key_facts == ["Visits on weekends."]
    assert wf.filed(line) == {EP2: "nick-friend"}, "that conversation is open again"
    assert (bank / "entities" / "nick-brother.md").read_bytes() != page_before and "Visits on weekends." not in (
        bank / "entities" / "nick-brother.md").read_text(), "the prose it landed is taken back exactly"
    assert "inbox/settled/" + rec.name in paths and any("undone" in line for line in lines)
    qfm = markdown_parser.parse(bank / "inbox" / f"{path.stem}.md").frontmatter
    assert wf.undone_of(qfm) == {EP1}
    _commit_all(bank)
    report = _run(bank, bank / "inbox" / f"{path.stem}.md",
                  scripted(name="Nick Rowe", sentence="My brother Nick is visiting this weekend."))
    assert ("nick-brother", "visits", "a-weekend") not in _claims(bank, "nick-brother"), "never filed again by the reader"
    assert report.settled == 0


def test_an_undo_is_refused_when_the_page_changed_under_what_it_landed(tmp_path, monkeypatch):
    import pytest

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], facts={"Visits on weekends.": EP1})
    _run(bank, path, _by_name(BOTH))
    rec = next(p for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))
               if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-brother")
    _commit_all(bank)
    page = bank / "entities" / "nick-brother.md"
    page.write_text(page.read_text() + "\nAn edit the person made afterwards.\n")
    with pytest.raises(dl.NotLandable):
        wf.undo(bank, rec.stem)
    assert rec.exists() and ("nick-brother", "visits", "a-weekend") in _claims(bank, "nick-brother"), "nothing was changed"


def test_two_conversations_nobody_could_tell_are_asked_one_at_a_time_and_a_pick_files_that_one_only(tmp_path, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BLANK, EP2: BLANK.replace("hello again", "hello twice")})
    _hold(bank, claims=[("greets", "everyone", EP1), ("greets", "nobody", EP2)], facts={"Says hello.": EP1, "Says hello twice.": EP2})
    assert _run(bank, path, _by_name({})).settled == 0
    fm = markdown_parser.parse(path).frontmatter
    assert wf.scope_of(fm) == [EP1] and wr.which_one.episodes_of(fm) == [EP1, EP2], "about one conversation at a time"
    assert fm["kind"] == "merge_suggestion" and fm["same_title"] and fm["detected"] == "which_one", "the keys resolvers read are unchanged"
    _commit_all(bank)
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="merge", merge_target="nick-brother"), _Settings(bank)))
    assert [c[1:] for c in _claims(bank, "nick-brother")] == [("greets", "everyone")], "that conversation's words only"
    assert _claims(bank, "nick-friend") == []
    line = pending_store.held_line(bank, "Nick")
    assert [d["object"] for d in line.held_claims] == ["nobody"] and line.key_facts == ["Says hello twice."]
    assert path.exists(), "the next conversation is asked next"
    nfm = markdown_parser.parse(path).frontmatter
    assert wr.which_one.episodes_of(nfm) == [EP2] and not wf.scope_of(nfm)
    assert "Nick" not in (markdown_parser.parse(bank / "entities" / "nick-brother.md").frontmatter.get("aliases") or [])
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="merge", merge_target="nick-friend"), _Settings(bank)))
    assert not path.exists() and [c[1:] for c in _claims(bank, "nick-friend")] == [("greets", "nobody")]


def test_one_conversation_is_the_whole_line_question_nothing_is_scoped(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BLANK})
    _run(bank, path, _by_name({}))
    assert not wf.scope_of(markdown_parser.parse(path).frontmatter)


def test_what_carries_no_conversation_is_never_filed_by_guess(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)])
    wf.edit_line(bank, "Nick", lambda ln: bool(setattr(ln, "links", [{"url": "https://example.com/a", "title": "A"}]) or
                                                setattr(ln, "open_questions", ["Is Nick local?"])) or True)
    _run(bank, path, _by_name(BOTH))
    line = pending_store.held_line(bank, "Nick")
    assert line.links and line.open_questions, "history, links and questions carry no conversation: they stay held"
    assert "Is Nick local?" not in (bank / "entities" / "nick-brother.md").read_text()


def test_a_failed_commit_puts_every_filing_back(tmp_path, monkeypatch):
    from api.services import git_service

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], facts={"Visits on weekends.": EP1})
    _commit_all(bank)
    before = {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted(bank.rglob("*")) if p.is_file() and ".git" not in p.parts}

    def boom(*a, **k):
        raise git_service.GitError("no")

    monkeypatch.setattr(git_service, "commit_touched_sync", boom)
    assert _run(bank, path, _by_name(BOTH)).settled == 0
    after = {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted(bank.rglob("*")) if p.is_file() and ".git" not in p.parts}
    assert after == before, "pages, the line, the question and the record are as they were"


def test_a_dry_run_names_each_conversation_and_each_page_and_writes_nothing(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE, EP3: BLANK})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2), ("greets", "everyone", EP3)])
    rows: list = []
    before = {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted(bank.rglob("*")) if p.is_file() and ".git" not in p.parts}
    _run(bank, path, _by_name(BOTH), dry_run=True, trace=rows.append)
    what = [(r["episode"], r["what"]) for r in rows]
    assert (EP1, "named:nick-brother") in what and (EP2, "named:nick-friend") in what
    assert (EP3, "would_ask") in what and any(w == "would_file:nick-brother" for _e, w in what)
    assert all("brother Nick" not in str({k: v for k, v in r.items() if k != "eyes"}) for r in rows), "ids and enums only, outside the eyes"
    assert {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted(bank.rglob("*")) if p.is_file() and ".git" not in p.parts} == before


# --------------------------------------------------------------------------- review round: the invariant, on a scratch bank, after every operation


def _page_of(bank, pid: str):
    return markdown_parser.parse(bank / "entities" / f"{pid}.md")


def _snapshot(bank) -> dict:
    """What the line holds, per (claim, conversation) and per (fact text, conversation): the whole of what must be accounted for."""
    line = pending_store.held_line(bank, "Nick")
    claims = {d["id"]: wf.claim_episodes(d) for d in line.held_claims if d.get("subject") == "nick"}
    texts = {}
    for row in wf.prose_rows(line):
        texts[row["text"]] = wf.row_episodes(row)
    return {"claims": claims, "facts": texts}


def _check(bank, before: dict, expected: dict[str, str], *, path=None, preexisting: dict[str, list[str]] | None = None) -> None:
    """The invariant: what landed plus what is still held is what was held, nothing twice and nothing wrong; every piece still held
    that can be asked about has an open question that covers it; a page is credited only with conversations whose words landed on it.
    ``expected``: the page each conversation means."""
    line = pending_store.held_line(bank, "Nick")
    held_claims = {d["id"]: wf.claim_episodes(d) for d in line.held_claims} if line else {}
    pages = ("nick-brother", "nick-friend")
    on_pages = {pid: {c.id: c for c in parse_claims(_page_of(bank, pid).body)} for pid in pages}
    for cid, eps in before["claims"].items():
        where = [pid for pid in pages if cid in on_pages[pid]]
        assert not (cid in held_claims and where), f"{cid} is held and on a page: twice"
        assert len(where) <= 1, f"{cid} is on two pages"
        assert cid in held_claims or where, f"{cid} is nowhere: lost"
        for pid in where:
            assert {expected[e] for e in eps} == {pid}, f"{cid} landed under the wrong person"
            assert wf.claim_episodes(on_pages[pid][cid].to_dict()) == eps, "a claim carries only its own conversations"
    held_rows = {r["text"]: wf.row_episodes(r) for r in wf.prose_rows(line)} if line else {}
    for text, eps in before["facts"].items():
        for e in eps:
            wanted = expected.get(e)
            landed = [pid for pid in pages if text in _page_of(bank, pid).body]
            if e in held_rows.get(text, set()):
                continue
            assert wanted in landed, f"{text!r} said in {e} is neither held nor on {wanted}"
        for pid in pages:
            if text in _page_of(bank, pid).body:
                assert pid in {expected[e] for e in eps}, f"{text!r} is on a page no conversation of it meant"
    for pid in pages:
        credited = set(_page_of(bank, pid).frontmatter.get("source_episodes") or [])
        meant = {e for e, p in expected.items() if p == pid}
        assert credited <= meant, f"{pid} credited with {credited - meant}, which is not its own"
    if line is not None:
        asked = set(wf.unfiled(line)) | set(wf.stranded(line))
        if asked:
            assert path is not None and path.exists(), "something can still be asked: a question is open"
            assert asked <= set(wr.which_one.episodes_of(markdown_parser.parse(path).frontmatter)), "and it covers exactly that"
        else:
            assert path is None or not path.exists(), "nothing can be asked: the question is closed"


def _sets(bank, *, history=True, facts=None):
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)],
          facts=facts if facts is not None else {"Visits on weekends.": EP1, "Ships releases.": EP2}, history=history)


def _pick(bank, path, page: str) -> None:
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="merge", merge_target=page), _Settings(bank)))


def _undecided_world(tmp_path, monkeypatch, *, facts=None, history=True):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BLANK, EP2: BLANK.replace("hello again", "hello twice")})
    _hold(bank, claims=[("greets", "everyone", EP1), ("greets", "nobody", EP2)],
          facts=facts if facts is not None else {"Says hello.": EP1, "Says hello twice.": EP2}, history=history)
    assert _run(bank, path, _by_name({})).settled == 0
    _commit_all(bank)
    return bank, path


MEANT = {EP1: "nick-brother", EP2: "nick-friend"}


def test_someone_else_on_a_question_about_one_conversation_is_that_conversations_answer_alone(tmp_path, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    bank, path = _undecided_world(tmp_path, monkeypatch)
    before = _snapshot(bank)
    assert wf.scope_of(markdown_parser.parse(path).frontmatter) == [EP1]
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="reject", option_key="another"), _Settings(bank)))
    line = pending_store.held_line(bank, "Nick")
    assert wf.said_not(line) == {EP1: {"nick-brother", "nick-friend"}}, "kept apart from the candidates for that conversation"
    assert pending_store.apart_of(bank, "Nick") == frozenset(), "never for the whole name: the other conversation still has its candidates"
    assert path.exists() and wr.which_one.episodes_of(markdown_parser.parse(path).frontmatter) == [EP2], "the question moves on"
    assert not wf.scope_of(markdown_parser.parse(path).frontmatter)
    assert [d["id"] for d in line.held_claims] == ["clm_held_1", "clm_held_2"], "nothing is lost"
    # The reader reads the second conversation only: the first was answered.
    _commit_all(bank)
    case = wr.case_for(bank, path, dict(markdown_parser.parse(path).frontmatter), today=TODAY.isoformat())
    assert isinstance(case, wr.Case) and case.episodes == [EP2]
    _pick(bank, path, "nick-friend")
    _check(bank, before, {EP2: "nick-friend", EP1: "nick-brother"}, path=path)
    assert [c[1:] for c in _claims(bank, "nick-friend")] == [("greets", "nobody")] and _claims(bank, "nick-brother") == []
    assert not path.exists(), "the person answered every conversation: nothing is open"


def test_a_dismissal_of_a_scoped_question_is_that_conversations_alone_too(tmp_path, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    bank, path = _undecided_world(tmp_path, monkeypatch)
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="dismiss"), _Settings(bank)))
    line = pending_store.held_line(bank, "Nick")
    assert list(wf.said_not(line)) == [EP1] and pending_store.apart_of(bank, "Nick") == frozenset()
    assert path.exists() and wr.which_one.episodes_of(markdown_parser.parse(path).frontmatter) == [EP2]


def test_a_scoped_pick_credits_only_the_conversation_it_filed_and_the_last_tap_lifts_no_leftover(tmp_path, monkeypatch):
    bank, path = _undecided_world(tmp_path, monkeypatch)
    before = _snapshot(bank)
    _pick(bank, path, "nick-brother")
    assert _page_of(bank, "nick-brother").frontmatter["source_episodes"] == [EP1], "exactly the conversation whose words landed"
    _check(bank, before, MEANT, path=path)
    _commit_all(bank)
    _pick(bank, path, "nick-friend")
    assert _page_of(bank, "nick-friend").frontmatter["source_episodes"] == [EP2]
    friend = (bank / "entities" / "nick-friend.md").read_text()
    assert "Nick, said once." not in friend and "Nick came up" not in friend, "a line-level description and a history line carry no conversation"
    assert "Says hello twice." in friend and "Says hello." not in friend.replace("Says hello twice.", "")
    line = pending_store.held_line(bank, "Nick")
    assert line.description == "Nick, said once." and line.history_entries, "they stay held: nobody can say whose they are"
    _check(bank, before, MEANT, path=path)
    assert not path.exists()


def test_a_whole_line_answer_still_lifts_everything_when_nothing_was_filed_elsewhere(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: "user: My brother Nick called.\nassistant: Ok."})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("calls", "me", EP2)], history=True)
    _pick(bank, path, "nick-brother")
    page = (bank / "entities" / "nick-brother.md").read_text()
    assert "Nick came up" in page and "Nick, said once." in page, "as before: one person, the whole line"
    assert pending_store.held_line(bank, "Nick") is None


def test_a_claim_two_conversations_cite_that_named_different_people_is_asked_not_stranded(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], history=False)
    both = _held("nick", "likes", "tea", 9, EP1)
    both["source_episodes"] = [EP1, EP2]
    wf.edit_line(bank, "Nick", lambda ln: bool(ln.held_claims.append(both)) or True)
    before = _snapshot(bank)
    _run(bank, path, _by_name(BOTH))
    line = pending_store.held_line(bank, "Nick")
    assert [d["predicate"] for d in line.held_claims] == ["likes"] and wf.stranded(line) == [EP1, EP2]
    assert path.exists(), "the question stays open: somebody must be asked about that claim"
    fm = markdown_parser.parse(path).frontmatter
    assert wr.which_one.episodes_of(fm) == [EP1, EP2] and wf.scope_of(fm) == [EP1, EP2], "and it covers exactly that"
    _check(bank, before, MEANT, path=path)
    _commit_all(bank)
    _pick(bank, path, "nick-friend")
    assert ("nick-friend", "likes", "tea") in _claims(bank, "nick-friend") and not path.exists()
    assert wf.filed(pending_store.held_line(bank, "Nick") or line) == {EP1: "nick-brother", EP2: "nick-friend"}, "no filing is moved"
    assert pending_store.held_line(bank, "Nick") is None or not pending_store.held_line(bank, "Nick").held_claims


def test_a_stranded_claim_answered_someone_else_is_no_longer_asked(tmp_path, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], history=False)
    both = _held("nick", "likes", "tea", 9, EP1)
    both["source_episodes"] = [EP1, EP2]
    wf.edit_line(bank, "Nick", lambda ln: bool(ln.held_claims.append(both)) or True)
    _run(bank, path, _by_name(BOTH))
    _commit_all(bank)
    asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="reject", option_key="another"), _Settings(bank)))
    line = pending_store.held_line(bank, "Nick")
    assert [d["predicate"] for d in line.held_claims] == ["likes"] and not path.exists(), "answered: held, nothing more to ask"
    assert wf.filed(line) == MEANT, "the filings stand"


def test_a_fact_both_conversations_state_lands_on_both_pages_each_with_its_own_span(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], facts={"Likes tea.": EP1}, history=False)
    wf.edit_line(bank, "Nick", lambda ln: bool(ln.item_inputs.append(_row("key_facts", "Likes tea.", EP2))) or True)
    before = _snapshot(bank)
    assert before["facts"] == {"Likes tea.": {EP1, EP2}}, "the rows of one text are united"
    _run(bank, path, _by_name(BOTH))
    for ep, pid in MEANT.items():
        page = _page_of(bank, pid)
        assert "Likes tea." in page.body
        spans = page.frontmatter["section_provenance"]
        assert f"{ep} " in str(spans["sources"].values()) and all(
            other not in str(spans["sources"].values()) for other in MEANT if other != ep), "each page cites only its own conversation"
    line = pending_store.held_line(bank, "Nick")
    assert line is None or line.key_facts == []
    _check(bank, before, MEANT, path=path)


def test_a_fact_waits_whole_while_one_of_its_conversations_is_undecided_and_lands_when_it_is_filed(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: BLANK})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("greets", "everyone", EP2)], facts={"Likes tea.": EP1}, history=False)
    wf.edit_line(bank, "Nick", lambda ln: bool(ln.item_inputs.append(_row("key_facts", "Likes tea.", EP2))) or True)
    before = _snapshot(bank)
    _run(bank, path, _by_name(BOTH))
    assert pending_store.held_line(bank, "Nick").key_facts == ["Likes tea."], "undecided conversation: the fact stays whole"
    assert "Likes tea." not in (bank / "entities" / "nick-brother.md").read_text()
    _commit_all(bank)
    _pick(bank, path, "nick-friend")
    exp = {EP1: "nick-brother", EP2: "nick-friend"}
    assert "Likes tea." in (bank / "entities" / "nick-brother.md").read_text() and "Likes tea." in (bank / "entities" / "nick-friend.md").read_text(), \
        "the person's tap lands the fact on the page each of its conversations meant"
    _check(bank, before, exp, path=path)


def test_when_a_filing_empties_the_line_the_question_closes_in_the_same_commit(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], history=False)
    wf.edit_line(bank, "Nick", lambda ln: bool(setattr(ln, "description", "") or setattr(ln, "summary", "")) or True)
    assert _run(bank, path, _by_name(BOTH)).settled == 2
    assert pending_store.held_line(bank, "Nick") is None
    assert not path.exists(), "a question about nothing is not left open"
    shelf = bank / "inbox" / "settled" / f"{path.stem}.md"
    assert markdown_parser.parse(shelf).frontmatter["settled"]["rule"] == wf.ANSWERED
    last = _git(bank, "show", "--no-renames", "--name-status", "--format=%s", "HEAD")
    assert f"D\tinbox/{path.name}" in last and f"A\tinbox/settled/{path.name}" in last and "A\tinbox/settled/land-" in last, \
        "one commit: the filing and the close"
    # Taking the last filing back asks it again.
    rec = max((p for p in (bank / "inbox" / "settled").glob("land-*.md")), key=lambda p: p.name)
    _commit_all(bank)
    wf.undo(bank, rec.stem)
    assert path.exists() and not shelf.exists() and pending_store.held_line(bank, "Nick") is not None


def test_an_undo_of_the_first_filing_after_the_line_left_gives_its_claims_a_line_again(tmp_path, monkeypatch):
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], history=False)
    wf.edit_line(bank, "Nick", lambda ln: bool(setattr(ln, "description", "")) or True)
    before = _snapshot(bank)
    _run(bank, path, _by_name(BOTH))
    _commit_all(bank)
    first = next(p for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))
                 if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-brother")
    wf.undo(bank, first.stem)
    line = pending_store.held_line(bank, "Nick")
    assert [d["predicate"] for d in line.held_claims] == ["visits"] and wf.filed(line) == {EP2: "nick-friend"}
    assert path.exists() and wf.unfiled(line) == [EP1]
    _check(bank, before, MEANT, path=path)


def test_an_undo_survives_the_nightly_bookkeeping_of_a_page_that_landed_prose(tmp_path, monkeypatch):
    from api.services.claims import write_claims

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], facts={"Visits on weekends.": EP1})
    _run(bank, path, _by_name(BOTH))
    rec = next(p for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))
               if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-brother")
    _commit_all(bank)
    page = bank / "entities" / "nick-brother.md"
    parsed = markdown_parser.parse(page)
    cs = parse_claims(parsed.body)
    for c in cs:   # what Sleep does every night: the decay watermark and a confidence
        c.confidence, c.decayed_through = 0.31, "2026-12-30"
    markdown_parser.write(page, {**parsed.frontmatter, "last_referenced": "2026-12-30", "version": 9}, write_claims(parsed.body, cs))
    _commit_all(bank)
    wf.undo(bank, rec.stem)
    assert "Visits on weekends." not in page.read_text() and _claims(bank, "nick-brother") == []
    assert wf.filed(pending_store.held_line(bank, "Nick")) == {EP2: "nick-friend"}
    assert _page_of(bank, "nick-brother").frontmatter["last_referenced"] == "2026-12-30", "what changed since is kept"
    assert _page_of(bank, "nick-brother").frontmatter.get("source_episodes") == [], "the credit the filing gave is taken back"


def test_sleeps_settle_of_a_question_about_one_conversation_files_only_what_its_evidence_covers(tmp_path, monkeypatch):
    from api.services import inbox_tend

    bank, path = _undecided_world(tmp_path, monkeypatch)
    before = _snapshot(bank)

    def decision(eps):
        return inbox_tend.Decision(path.stem, "merge_suggestion", "some_other_rule", {"action": "merge", "merge_target": "nick-brother"},
                                   answer="Nick Rowe", model="haiku", fingerprint=path.read_bytes(),
                                   spans=[{"episode": e, "start": 0, "end": 1, "kind": "user"} for e in eps])

    raw = {p.relative_to(bank).as_posix(): p.read_bytes() for p in bank.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert asyncio.run(inbox_tend.apply(bank, _Settings(bank), decision([EP1]))) is False, "evidence of one of two: left for the person"
    assert {p.relative_to(bank).as_posix(): p.read_bytes() for p in bank.rglob("*") if p.is_file() and ".git" not in p.parts} == raw
    assert asyncio.run(inbox_tend.apply(bank, _Settings(bank), decision([EP2]))) is False, "and the one that is not the scope too"
    assert asyncio.run(inbox_tend.apply(bank, _Settings(bank), decision([EP1, EP2]))) is True, "evidence of every open conversation: the whole of it"
    _check(bank, before, {EP1: "nick-brother", EP2: "nick-brother"}, path=path)


def test_a_leftover_line_counts_no_conversation_that_was_filed_to_a_page(tmp_path, monkeypatch):
    from api.services import entity_resolver

    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2)], history=True)
    _run(bank, path, _by_name(BOTH))
    line = pending_store.held_line(bank, "Nick")
    assert line is not None and line.episodes() == [EP1, EP2] and wf.filed(line) == MEANT
    assert wf.counted(line) == set(), "both conversations are filed: a later mention adds one conversation, not three"
    unit = entity_resolver._Unborn("Nick", "nick", {}, [], line, set(), False, stored=True)
    assert unit.episodes() == set(), "the project-birth count reads the same filter"
    wf.mark_filed(bank, "Nick", [EP2], None, taking_back="nick-friend")
    line = pending_store.held_line(bank, "Nick")
    assert wf.counted(line) == {EP2}
    change = {"entity": {}}
    entity_resolver._fold_pending(change, line)
    credited = {s.get("source_episode") for s in change.get("sources", change.get("source_episodes", []))
                if isinstance(s, dict)}
    assert EP2 in str(change) and EP1 not in str(change), "a promotion credits the conversation nobody filed, never the one another page has"
    assert credited <= {EP2}


def test_the_scope_is_on_the_wire_and_an_agent_is_told_which_conversation_it_is_about(tmp_path, monkeypatch):
    from api.services import inbox_service, mcp_tools

    bank, path = _undecided_world(tmp_path, monkeypatch)
    items = {i.id: i for i in inbox_service.load_inbox(bank)}
    item = items[path.stem]
    assert item.scope_episodes == [EP1] and item.model_dump(by_alias=True)["scopeEpisodes"] == [EP1]
    assert all(i.scope_episodes is None for i in items.values() if i.id != path.stem)
    clause = mcp_tools._scope_clause(dict(markdown_parser.parse(path).frontmatter))
    assert EP1 in clause and "2026-11-20" in clause and len(clause) < 140
    assert mcp_tools._scope_clause({"kind": "clarification"}) == ""


def test_the_invariant_holds_after_every_operation_of_a_long_story(tmp_path, monkeypatch):
    """Three conversations (a brother, a teammate, one nobody can tell), a claim two of them cite, a fact two of them state: read,
    tapped, undone, tapped again, each step checked against what was held at the start."""
    bank, path = _world(tmp_path, monkeypatch, conversations={EP1: BROTHER, EP2: MATE, EP3: BLANK})
    _hold(bank, claims=[("visits", "a-weekend", EP1), ("ships", "the-release", EP2), ("greets", "everyone", EP3)],
          facts={"Likes tea.": EP1, "Greets all.": EP3}, history=True)
    shared = _held("nick", "likes", "tea", 9, EP1)
    shared["source_episodes"] = [EP1, EP2]
    wf.edit_line(bank, "Nick", lambda ln: bool(ln.held_claims.append(shared)) or bool(ln.item_inputs.append(_row("key_facts", "Likes tea.", EP2))))
    before = _snapshot(bank)
    meant = {EP1: "nick-brother", EP2: "nick-friend", EP3: "nick-friend"}
    _run(bank, path, _by_name(BOTH))
    _check(bank, before, meant, path=path)                       # read: two filed, the shared claim and the third asked
    _commit_all(bank)
    _pick(bank, path, "nick-friend")                              # the person: the third conversation is the teammate's
    _check(bank, before, meant, path=path)
    _commit_all(bank)
    rec = next(p for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))
               if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-brother")
    wf.undo(bank, rec.stem)                                       # the brother's filing is taken back
    _check(bank, before, meant, path=path)
    _commit_all(bank)
    assert path.exists() and EP1 in wf.unfiled(pending_store.held_line(bank, "Nick"))
    _pick(bank, path, "nick-brother")                             # and answered by the person, the other way round
    _check(bank, before, meant, path=path)

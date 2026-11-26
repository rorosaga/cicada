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
from api.tests.test_held_release import _git, _Settings, _held
from api.tests.test_which_one_reader import EP1, EP2, _claims, _run, _world, scripted

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

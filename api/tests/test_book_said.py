"""Ruling 61: a chat changes a book's status — the model judges, the record decides whose words and which book."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from api.services import book_said, books, evidence, markdown_parser
from api.services.claims import HAPPENED, parse_claims

DAY = "2026-10-20"
CHAT = "user: I finally finished Example Title last night.\n\nassistant: Example Title is a long one. Nice.\n"


def _episode(bank: Path, ep_id: str, body: str, **fm) -> str:
    (bank / "episodes").mkdir(parents=True, exist_ok=True)
    meta = {"id": ep_id, "timestamp": f"{DAY}T10:00:00Z", "source": "claude-code", "origin": "claude-code",
            "processed": False, "content_hash": "x", **fm}
    markdown_parser.write(bank / "episodes" / f"{ep_id}.md", meta, body)
    return ep_id


def _book(bank: Path, title: str, *, isbn: str = "9780306406157", apple: str | None = None, ep: str = "ep_door",
          today: str = "2026-10-01") -> str:
    index = books.BookIndex(bank)
    facts = books.BookFacts(title=title, authors=["An Author"], isbns=[isbn] if isbn else [], apple_id=apple,
                            title_from="apple-books" if apple else "openlibrary")
    entity_id, _, _ = books.ensure_page(bank, index, facts, ep, today)
    from api.services import bank_index

    bank_index.invalidate(bank)
    return entity_id


def _status(bank: Path, entity_id: str) -> tuple[str | None, list]:
    claims = parse_claims(markdown_parser.parse(bank / "entities" / f"{entity_id}.md").body)
    live = books.live_status_claims(claims)
    return next((c.object for c in live if not c.valid_to), None), claims


def _mark(entity: dict, text: str = CHAT, *, fm: dict | None = None, day: str | None = DAY, ep: str = "ep_chat"):
    from api.services import authorship

    fm = fm if fm is not None else {"origin": "claude-code"}
    return book_said.at_extraction(entity, episode_id=ep, frontmatter=fm, text=text, day=day,
                                   override=authorship.of_episode(fm), gaps=())


def _said(status="finished", quote="I finally finished Example Title last night.", **extra):
    return {"name": "Example Title", "reading_status": {"status": status, "quote": quote, **extra}}


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    (root / "entities").mkdir(parents=True)
    from api.services import owner_identity

    monkeypatch.setattr(books, "_owner", lambda _m: "user")
    assert owner_identity is not None
    return root


# ------------------------------------------------------------------ whose words ---------------------------------


def test_the_persons_own_words_make_a_mark_and_the_field_never_stays_on_the_entity():
    entity = _said()
    mark = _mark(entity)
    assert mark["status"] == "finished" and mark["day"] == DAY and mark["stated"] is False
    assert book_said.MODEL_KEY not in entity


@pytest.mark.parametrize("quote", ["Example Title is a long one.", "words nobody said"])
def test_an_agents_line_or_an_unlocated_quote_changes_nothing(quote):
    assert _mark(_said(quote=quote)) is None


def test_someone_elses_line_in_a_meeting_is_not_the_persons():
    text = "speaker:Sam: I finished Example Title.\n\nYou: Oh nice.\n"
    assert _mark(_said(quote="I finished Example Title."), text) is None


def test_an_agents_saved_note_is_never_the_persons():
    fm = {"origin": "claude-code", "evidence_kind": "assistant"}
    assert _mark(_said(), "I finally finished Example Title last night.", fm=fm) is None


def test_the_same_words_said_first_by_the_agent_still_find_the_persons_turn():
    text = "assistant: I finished Example Title.\n\nuser: I finished Example Title.\n"
    span = book_said.own_span(text, "I finished Example Title.", episode_id="ep_x", override=None)
    assert span is not None and text[:span.start].endswith("user: ")


def test_a_title_the_conversation_never_says_is_the_models_memory():
    entity = {"name": "Another Title", "reading_status": {"status": "finished", "quote": "I finally finished"}}
    assert _mark(entity) is None


def test_an_undated_conversation_and_a_door_set_no_status():
    assert _mark(_said(), day=None) is None
    for door in books.DOORS:
        assert _mark(_said(), fm={"origin": door}) is None


def test_an_invented_status_is_refused():
    assert _mark(_said(status="abandoned")) is None


@pytest.mark.parametrize("raw,want", [("2026-10-19", ("2026-10-19", True)), ("2026-12-01", (DAY, False)),
                                      ("last night", (DAY, False))])
def test_a_stated_day_counts_only_up_to_the_conversation(raw, want):
    mark = _mark(_said(on=raw))
    assert (mark["day"], mark["stated"]) == want


# ------------------------------------------------------------------ the right work ------------------------------


def test_a_clear_title_lands_on_the_page_with_a_located_span_and_a_happening(bank):
    page = _book(bank, "Example Title")
    _episode(bank, "ep_chat", CHAT)
    mark = _mark(_said())
    paths = book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [mark]}], today=date(2026, 11, 4))
    status, claims = _status(bank, page)
    assert status == "finished"
    made = next(c for c in claims if c.predicate == books.STATUS_PREDICATE)
    assert made.valid_from == DAY and made.source_episodes == ["ep_chat"]
    span = made.evidence[0]
    assert span.kind == "user" and CHAT[span.start:span.end] == mark["quote"]
    happened = [c for c in claims if c.predicate == HAPPENED]
    assert [(c.object, c.status, c.valid_from) for c in happened] == [("finished reading", "done", DAY)]
    assert f"entities/{page}.md" in paths and "episodes/ep_chat.md" in paths
    fm = markdown_parser.parse(bank / "entities" / f"{page}.md").frontmatter
    assert "ep_chat" in fm["source_episodes"]


def test_a_reading_said_with_no_day_is_a_status_and_no_happening(bank):
    page = _book(bank, "Example Title")
    text = "user: I'm reading Example Title.\n"
    _episode(bank, "ep_chat", text)
    mark = _mark(_said(status="reading", quote="I'm reading Example Title."), text)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [mark]}])
    status, claims = _status(bank, page)
    assert status == "reading" and not [c for c in claims if c.predicate == HAPPENED]


def test_a_title_with_a_subtitle_is_clear_and_two_pages_are_not(bank):
    page = _book(bank, "Example Title: A Novel")
    index = book_said.TitleIndex(bank)
    assert index.clear_page(["Example Title"]) == page
    other = _book(bank, "Example Title: The Sequel", isbn="9780131103627")
    index = book_said.TitleIndex(bank)
    assert index.clear_page(["Example Title"]) is None
    exact = _book(bank, "Example Title", isbn="9780201633610")
    index = book_said.TitleIndex(bank)
    assert index.clear_page(["Example Title"]) == exact and {page, other, exact} <= index.ids


def test_stage_twos_join_counts_only_for_a_book_page(bank):
    page = _book(bank, "Example Title")
    index = book_said.TitleIndex(bank)
    assert index.clear_page(["Exmaple Titel"], joined=page) == page
    assert index.clear_page(["Exmaple Titel"], joined="some-concept") is None


def test_two_copies_of_one_title_stay_a_mention_held_on_the_episode(bank):
    first, second = _book(bank, "Example Title", isbn="", apple="asset-a"), _book(bank, "Example Title", isbn="9780131103627")
    assert first != second
    _episode(bank, "ep_chat", CHAT)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}])
    assert _status(bank, first)[0] is None and _status(bank, second)[0] is None
    assert book_said.waiting(bank)


def test_a_first_mention_is_held_and_a_door_making_the_page_applies_it_dated_as_said(bank, monkeypatch):
    _episode(bank, "ep_chat", CHAT)
    assert book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}]) == []
    assert list((bank / "entities").glob("*.md")) == []
    assert book_said.waiting(bank)
    page = _book(bank, "Example Title")
    book_said.apply_waiting(bank, today=date(2026, 11, 4))
    status, claims = _status(bank, page)
    assert status == "finished"
    assert next(c for c in claims if c.predicate == books.STATUS_PREDICATE).valid_from == DAY
    assert not book_said.waiting(bank)


def test_held_words_a_revision_removed_go_away_with_them(bank):
    _episode(bank, "ep_chat", CHAT)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}])
    path = bank / "episodes" / "ep_chat.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, "user: Example Title is on my desk.\n")
    from api.services import bank_index

    bank_index.invalidate(bank)
    page = _book(bank, "Example Title")
    book_said.apply_waiting(bank)
    assert _status(bank, page)[0] is None and not book_said.waiting(bank)


# ------------------------------------------------------------------ newest evidence -----------------------------


def _record(bank, page, status, day, ep, **kw):
    _episode(bank, ep, f"**Status:** {books.STATUS_WORDS[status]}\n", origin="apple-books")
    assert books.set_status(bank, page, status=status, day=day, episode_id=ep, quote=books.STATUS_WORDS[status],
                            observer="user", today="2026-11-04", **kw)


def test_a_late_read_never_overrides_a_newer_status(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "reading", "2026-10-25", "ep_door")
    _episode(bank, "ep_chat", CHAT)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}])
    status, claims = _status(bank, page)
    assert status == "reading"
    said = next(c for c in claims if c.object == "finished")
    assert said.valid_to == "2026-10-25"
    assert not list((bank / "inbox").rglob("*.md")) if (bank / "inbox").exists() else True


def test_a_newer_chat_beats_an_older_record(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "reading", "2026-10-01", "ep_door")
    _episode(bank, "ep_chat", CHAT)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}])
    assert _status(bank, page)[0] == "finished"


def test_the_same_day_further_along_wins_whichever_is_read_first(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "reading", DAY, "ep_door")
    _episode(bank, "ep_chat", CHAT)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}])
    assert _status(bank, page)[0] == "finished"


def test_a_real_conflict_keeps_the_record_and_asks_once_and_the_answer_stands(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "finished", DAY, "ep_door")
    text = "user: I'm still reading Example Title.\n"
    _episode(bank, "ep_chat", text)
    mark = _mark(_said(status="reading", quote="I'm still reading Example Title."), text)
    paths = book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [mark]}])
    status, claims = _status(bank, page)
    assert status == "finished"
    asked = [p for p in paths if p.startswith("inbox/")]
    assert len(asked) == 1
    item = markdown_parser.parse(bank / asked[0]).frontmatter
    assert item["kind"] == "conflict" and item["predicate"] == books.STATUS_PREDICATE
    assert {o["label"] for o in item["options"] if o.get("claim_id")} == {"finished", "reading"}
    # The person's answer closes the record in favour of their words: a later write keeps that order.
    live = {c.object: c for c in books.live_status_claims(claims)}
    chosen, loser = live["reading"], live["finished"]
    chosen.valid_to, chosen.superseded_by = None, None
    loser.valid_to, loser.superseded_by = DAY, chosen.id
    assert books._rechain([loser, chosen], "2026-11-04") is False
    assert books._rechain([chosen, loser], "2026-11-04") is False and chosen.valid_to is None


# ------------------------------------------------------------------ undo ----------------------------------------


def test_not_right_takes_it_back_and_the_status_before_returns_and_it_is_never_written_again(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "reading", "2026-10-01", "ep_door")
    _episode(bank, "ep_chat", CHAT)
    mark = _mark(_said())
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [mark]}])
    current = books.current_status(bank, page)
    assert current["status"] == "finished" and current["fromChat"] is True and current["episode"] == "ep_chat"
    out = books.undo_status(bank, page, current["claimId"], today="2026-11-04")
    assert out["action"] == "retracted" and out["status"] == "reading"
    status, claims = _status(bank, page)
    assert status == "reading"
    done = next(c for c in claims if c.predicate == HAPPENED)
    assert done.superseded_by, "the happening goes with it"
    # A re-read of the same conversation, a revision included, says nothing new.
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [mark]}])
    book_said.apply_waiting(bank)
    assert _status(bank, page)[0] == "reading"
    assert not books.set_status(bank, page, status="finished", day=DAY, episode_id="ep_chat", quote="x",
                                observer="user", today="2026-11-04")


def test_a_status_an_edited_conversation_withdrew_leaves_the_one_before_in_force(bank):
    from api.services.agentic_write import _withdrawal_record
    from api.services.claims import write_claims

    page = _book(bank, "Example Title")
    _record(bank, page, "reading", "2026-10-01", "ep_door")
    _episode(bank, "ep_chat", CHAT)
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [_mark(_said())]}])
    path = bank / "entities" / f"{page}.md"
    parsed = markdown_parser.parse(path)
    claims = parse_claims(parsed.body)
    target = next(c for c in claims if c.object == "finished" and c.predicate == books.STATUS_PREDICATE)
    record = _withdrawal_record(target, claims, reason="edited", author="cicada", origin="sleep", session_id=None,
                                spans=[evidence.reasoning("")], day="2026-11-04", fallback_subject=page)
    target.valid_to, target.superseded_by = "2026-11-04", record.id
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [*claims, record]))
    from api.services import bank_index

    bank_index.invalidate(bank)
    assert books.current_status(bank, page)["status"] == "reading"
    assert books.counts(bank)["reading"] == 1 and books.counts(bank)["finished"] == 0


def test_a_door_record_reports_no_chat_and_undo_of_nothing_is_not_found(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "reading", "2026-10-01", "ep_door")
    assert books.current_status(bank, page)["fromChat"] is False
    assert books.undo_status(bank, page, "clm_book_nope")["action"] == "not_found"


def test_evidence_kind_of_the_span_agrees_with_the_episode(bank):
    _episode(bank, "ep_chat", CHAT)
    span = evidence.verify(bank, "ep_chat", "I finally finished Example Title last night.")
    assert span.kind == book_said.OWN_KIND


# ---------------------------------------------------- said again, taken back, whose words (review of #612) --------


def _chat(bank: Path, ep: str, text: str, quote: str, *, day: str = DAY, **said) -> None:
    _episode(bank, ep, text, timestamp=f"{day}T10:00:00Z")
    mark = _mark(_said(quote=quote, **said), text, day=day, ep=ep)
    book_said.settle(bank, [{"episode_id": ep, book_said.KEY: [mark]}], today=date(2026, 11, 4))


def _happened(claims, what: str) -> list:
    return [c for c in claims if c.predicate == HAPPENED and c.object == what]


def test_not_right_stays_when_a_re_read_dates_the_same_words_differently(bank):
    page = _book(bank, "Example Title")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    books.undo_status(bank, page, books.current_status(bank, page)["claimId"], today="2026-11-04")
    again = _mark(_said(on="2026-10-18"))
    assert again["day"] == "2026-10-18"
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [again]}], today=date(2026, 11, 4))
    assert _status(bank, page)[0] is None
    rows = markdown_parser.parse(bank / "episodes" / "ep_chat.md").frontmatter[book_said.KEY]
    assert len(rows) == 1


def test_not_right_stays_when_a_re_read_quotes_the_same_conversation_differently(bank):
    page = _book(bank, "Example Title")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    books.undo_status(bank, page, books.current_status(bank, page)["claimId"], today="2026-11-04")
    other = _mark(_said(quote="finished Example Title", on="2026-10-18"))
    book_said.settle(bank, [{"episode_id": "ep_chat", book_said.KEY: [other]}], today=date(2026, 11, 4))
    assert _status(bank, page)[0] is None


def test_not_right_on_a_finish_reopens_the_reading_it_settled(bank):
    page = _book(bank, "Example Title")
    text = "user: I started Example Title.\n"
    _chat(bank, "ep_began", text, "I started Example Title.", day="2026-10-01", status="reading", on="2026-10-01")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    thread = _happened(_status(bank, page)[1], "started reading")[0]
    assert thread.valid_to and thread.superseded_by, "the finish settled it"
    out = books.undo_status(bank, page, books.current_status(bank, page)["claimId"], today="2026-11-04")
    assert out["status"] == "reading"
    claims = _status(bank, page)[1]
    thread = _happened(claims, "started reading")[0]
    assert thread.valid_to is None and thread.superseded_by is None and thread.status == "ongoing"
    assert _happened(claims, "finished reading")[0].superseded_by


def test_saying_it_again_days_later_only_adds_the_episode(bank):
    page = _book(bank, "Example Title")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    text = "user: As I said, I finished Example Title.\n"
    _chat(bank, "ep_again", text, "I finished Example Title.", day="2026-10-27")
    status, claims = _status(bank, page)
    records = books.live_status_claims(claims)
    assert status == "finished" and len(records) == 1 and records[0].valid_from == DAY
    assert records[0].source_episodes == ["ep_chat", "ep_again"]
    assert [e.episode for e in records[0].evidence] == ["ep_chat", "ep_again"]
    assert len(_happened(claims, "finished reading")) == 1
    assert "ep_again" in markdown_parser.parse(bank / "entities" / f"{page}.md").frontmatter["source_episodes"]


def test_a_finish_after_a_new_reading_is_a_second_reading_not_a_repeat(bank):
    page = _book(bank, "Example Title")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    text = "user: I am reading Example Title again.\n"
    _chat(bank, "ep_re", text, "I am reading Example Title again.", day="2026-10-25", status="reading")
    text = "user: I finished Example Title again.\n"
    _chat(bank, "ep_end", text, "I finished Example Title again.", day="2026-10-30")
    status, claims = _status(bank, page)
    assert status == "finished" and len(books.live_status_claims(claims)) == 3
    assert [c.valid_from for c in _happened(claims, "finished reading")] == [DAY, "2026-10-30"]


def test_a_repeat_of_a_record_with_no_happening_still_files_the_happening(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "finished", "2026-10-01", "ep_door")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    status, claims = _status(bank, page)
    assert status == "finished" and len(books.live_status_claims(claims)) == 1
    assert len(_happened(claims, "finished reading")) == 1


def test_a_door_still_records_each_day_it_states(bank):
    page = _book(bank, "Example Title")
    _record(bank, page, "reading", "2026-10-01", "ep_door")
    _record(bank, page, "reading", "2026-10-05", "ep_door2")
    assert len(books.live_status_claims(_status(bank, page)[1])) == 2


def test_the_happening_cites_the_persons_turn_when_an_agent_said_it_first(bank):
    page = _book(bank, "Example Title")
    text = "assistant: I finished Example Title.\n\nuser: I finished Example Title.\n"
    _chat(bank, "ep_chat", text, "I finished Example Title.")
    claims = _status(bank, page)[1]
    span = _happened(claims, "finished reading")[0].evidence[0]
    assert span.kind == "user" and span.start == text.index("user:") + len("user: ")


def test_an_applied_row_keeps_no_copy_of_the_words(bank):
    _book(bank, "Example Title")
    _chat(bank, "ep_chat", CHAT, "I finally finished Example Title last night.")
    row = markdown_parser.parse(bank / "episodes" / "ep_chat.md").frontmatter[book_said.KEY][0]
    assert "quote" not in row and row["said"] and row["page"]

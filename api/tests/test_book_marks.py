"""Ruling 64 (ROR-95, G39): what the person marked in a book is kept word for word with no model, it lights the page, and
Sleep reads a book's record for what its marks share, in one bounded chunk. Invented books and passages only."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from api.services import apple_books, bank_index, book_marks, books, entity_extractor, evidence, goodreads_export, \
    markdown_parser, page_blocks, quiet_pages, sensitive_text
from api.services.claims import HIGHLIGHTED, NOTED, is_mark, is_persons_words, parse_claims, write_claims

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 1)
PASSAGE_A = "The lanterns were lit long before anyone agreed on the way home."
PASSAGE_B = "An orchard keeps its own calendar,\nand no one reads it twice."
NOTE_A = "This is what I meant about the slow walk back."


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    (root / "entities").mkdir(parents=True)
    (root / "episodes").mkdir()
    monkeypatch.setattr(books, "_owner", lambda _m: "user")
    bank_index.invalidate()
    return root


def _note(text, day="2026-05-01", uuid="n", note=""):
    return {"uuid": uuid, "selectedText": text, "note": note, "createdAt": f"{day}T10:00:00Z"}


def _book(annotations=(), *, asset="ASSET-A", title="The Lantern Orchard", author="Ada Example", finished=False,
          progress=0.5):
    return {"assetId": asset, "title": title, "author": author, "isFinished": finished, "progress": progress,
            "contentType": 1, "addedAt": "2026-03-01T10:00:00Z", "lastOpenedAt": "2026-09-10T20:00:00Z",
            "finishedAt": "2026-09-12T21:00:00Z" if finished else None, "annotations": list(annotations)}


def _sync(bank, *items):
    apple_books.sync(bank, {"books": list(items)}, now=NOW, bank="test")
    bank_index.invalidate(bank)
    out = books.apply_pending(bank, today=TODAY)
    bank_index.invalidate(bank)
    return out


def _page(bank, entity="the-lantern-orchard"):
    parsed = markdown_parser.parse(bank / "entities" / f"{entity}.md")
    return parsed, parse_claims(parsed.body)


def _marks(bank, entity="the-lantern-orchard"):
    return [c for c in _page(bank, entity)[1] if is_mark(c)]


def test_every_highlight_and_note_is_a_claim_word_for_word_with_a_span(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=NOTE_A), _note(PASSAGE_B, "2026-05-02", uuid="2")]))
    marks = _marks(bank)
    assert [c.predicate for c in marks] == [HIGHLIGHTED, NOTED, HIGHLIGHTED]
    assert marks[0].text == f"Highlighted: {PASSAGE_A}"
    assert marks[1].text == f"Noted: {NOTE_A}"
    assert marks[2].text == f"Highlighted: {PASSAGE_B}", "a passage of two lines keeps both, in its own lines"
    assert [c.valid_from for c in marks] == ["2026-05-01", "2026-05-01", "2026-05-02"]
    body = evidence.source_text(bank, marks[0].evidence[0].episode)
    assert [c.evidence[0].kind for c in marks] == ["page", "user", "page"], "the book's words, then the person's"
    span = marks[0].evidence[0]
    assert body[span.start:span.end] == PASSAGE_A and span.hash == evidence.body_hash(body)
    assert body[marks[1].evidence[0].start:marks[1].evidence[0].end] == NOTE_A
    two_lines = marks[2].evidence[0]
    assert body[two_lines.start:two_lines.end] == PASSAGE_B.replace("\n", "\n> ")
    assert all(c.authored_by == "user" and c.source_episodes == [span.episode] for c in marks)


def test_a_library_entry_with_nothing_marked_gets_no_mark_and_no_stamp(bank):
    _sync(bank, _book())
    assert _marks(bank) == []
    episode = next((bank / "episodes").glob("*.md"))
    assert books.MARKS_KEY not in markdown_parser.parse(episode).frontmatter


def test_a_status_change_moves_the_spans_and_writes_nothing_twice(bank):
    item = [_note(PASSAGE_A, uuid="1", note=NOTE_A)]
    _sync(bank, _book(item))
    first = {c.id: c.evidence[0].start for c in _marks(bank)}
    _sync(bank, _book(item))   # nothing changed: nothing pending
    assert {c.id: c.evidence[0].start for c in _marks(bank)} == first
    _sync(bank, _book(item, finished=True))   # the status line grows, every passage moves
    marks = _marks(bank)
    assert {c.id for c in marks} == set(first) and all(c.evidence[0].start != first[c.id] for c in marks)
    body = evidence.source_text(bank, marks[0].evidence[0].episode)
    assert body[marks[0].evidence[0].start:marks[0].evidence[0].end] == PASSAGE_A
    assert marks[0].evidence[0].hash == evidence.body_hash(body), "on the body as it stands"


def test_a_removed_highlight_closes_and_comes_back_when_marked_again(bank):
    one, two = _note(PASSAGE_A, uuid="1"), _note(PASSAGE_B, "2026-05-02", uuid="2")
    _sync(bank, _book([one, two]))
    _sync(bank, _book([one]))
    by = {c.text: c for c in _marks(bank)}
    assert by[f"Highlighted: {PASSAGE_B}"].valid_to == TODAY.isoformat(), "history, never deleted"
    assert by[f"Highlighted: {PASSAGE_A}"].valid_to is None
    assert [i["text"] for i in book_marks.block(_page(bank)[1])["items"]] == [PASSAGE_A]
    _sync(bank, _book([one, two]))
    assert all(c.valid_to is None for c in _marks(bank))


def test_a_mark_the_person_took_back_is_never_written_again(bank):
    from api.services.claims import RETRACT_PREDICATE, Claim, write_claims

    one, two = _note(PASSAGE_A, uuid="1"), _note(PASSAGE_B, "2026-05-02", uuid="2")
    _sync(bank, _book([one]))
    parsed, claims = _page(bank)
    victim = next(c for c in claims if is_mark(c))
    claims.append(Claim(id="clm_r", text="Not right.", subject=victim.subject, predicate=RETRACT_PREDICATE,
                        object=victim.id, object_kind="literal"))
    victim.valid_to = TODAY.isoformat()
    markdown_parser.write(bank / "entities" / "the-lantern-orchard.md", parsed.frontmatter,
                          write_claims(parsed.body, claims))
    _sync(bank, _book([one, two]))
    assert next(c for c in _marks(bank) if c.id == victim.id).valid_to == TODAY.isoformat()
    assert [i["text"] for i in book_marks.block(_page(bank)[1])["items"]] == [PASSAGE_B]


@pytest.mark.parametrize("close", [{"recovered_by": "claim_recovery"}, {"superseded_by": "clm_successor"}],
                         ids=["recovered_history", "closed_by_a_successor"])
def test_a_resync_never_reopens_a_mark_something_else_closed(bank, close):
    one, two = _note(PASSAGE_A, uuid="1"), _note(PASSAGE_B, "2026-05-02", uuid="2")
    _sync(bank, _book([one]))
    parsed, claims = _page(bank)
    victim = next(c for c in claims if is_mark(c))
    victim.valid_to = "2026-06-01"
    for field, value in close.items():
        setattr(victim, field, value)
    markdown_parser.write(bank / "entities" / "the-lantern-orchard.md", parsed.frontmatter,
                          write_claims(parsed.body, claims))
    for book in ([one], [one, two]):   # the same highlights again, then a real change, so the writer runs over it
        _sync(bank, _book(book))
        kept = next(c for c in _marks(bank) if c.id == victim.id)
        assert kept.valid_to == "2026-06-01", "still closed"
        assert all(getattr(kept, field) == value for field, value in close.items())
    assert [i["text"] for i in book_marks.block(_page(bank)[1])["items"]] == [PASSAGE_B], "the new passage still lands"


def test_a_record_applied_before_this_ruling_gets_its_marks_without_a_second_status(bank):
    item = _book([_note(PASSAGE_A, uuid="1")], finished=True)
    _sync(bank, item)
    # An older bank: the record is applied, and its page holds its status but no marks.
    parsed, claims = _page(bank)
    from api.services.claims import write_claims

    kept = [c for c in claims if not is_mark(c)]
    markdown_parser.write(bank / "entities" / "the-lantern-orchard.md", parsed.frontmatter,
                          write_claims(parsed.body, kept))
    episode = next((bank / "episodes").glob("*.md"))
    ep = markdown_parser.parse(episode)
    fm = {k: v for k, v in ep.frontmatter.items() if k != books.MARKS_KEY}
    markdown_parser.write(episode, fm, ep.body)
    bank_index.invalidate(bank)
    assert len(books.pending(bank)) == 1
    before = [c for c in _page(bank)[1] if not is_mark(c)]
    assert books.apply_pending(bank, today=TODAY)["applied"] == 0
    bank_index.invalidate(bank)
    assert [c.text for c in _marks(bank)] == [f"Highlighted: {PASSAGE_A}"]
    assert [c.id for c in _page(bank)[1] if not is_mark(c)] == [c.id for c in before], "status untouched"
    assert books.pending(bank) == []


def test_a_goodreads_review_is_a_note_on_the_page(bank):
    csv = ("Book Id,Title,Author,ISBN13,My Rating,Exclusive Shelf,Date Read,Date Added,My Review,Private Notes,"
           "Bookshelves,Number of Pages\n"
           f'77,The Quiet Engine,Bea Sample,,0,read,2026/02/01,2026/01/01,"{NOTE_A}",,,\n').encode()
    goodreads_export.stage(bank, csv, bank="test", now=NOW)
    bank_index.invalidate(bank)
    books.apply_pending(bank, today=TODAY)
    bank_index.invalidate(bank)
    marks = _marks(bank, "the-quiet-engine")
    assert [(c.predicate, c.text, c.evidence[0].kind) for c in marks] == [(NOTED, f"Noted: {NOTE_A}", "user")]


# ---- quiet --------------------------------------------------------------------------------------------------------


def test_a_highlighted_book_is_not_quiet_and_a_library_entry_stays_quiet(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1")]),
          _book(asset="ASSET-B", title="The Unopened Atlas"))
    assert quiet_pages.page_is_quiet(bank, "the-lantern-orchard") is False
    assert quiet_pages.page_is_quiet(bank, "the-unopened-atlas") is True


def test_a_book_whose_only_highlight_was_removed_goes_quiet_again(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1")]))
    assert quiet_pages.page_is_quiet(bank, "the-lantern-orchard") is False
    _sync(bank, _book())
    assert quiet_pages.page_is_quiet(bank, "the-lantern-orchard") is True


def test_a_theme_page_drawn_from_marked_books_is_not_quiet(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1")]))
    episode = next((bank / "episodes").glob("*.md")).stem
    markdown_parser.write(bank / "entities" / "focus.md", {"name": "Focus", "type": "concept",
                                                           "source_episodes": [episode]}, "## Summary\nFocus.")
    bank_index.invalidate(bank)
    assert quiet_pages.page_is_quiet(bank, "focus") is False


def test_a_model_writing_the_same_predicate_is_no_mark():
    claim = SimpleNamespace(predicate=HIGHLIGHTED, origin="claude-code")
    assert is_mark(claim) is False and is_persons_words(claim) is False


# ---- what a caller sees --------------------------------------------------------------------------------------------


def test_the_card_draws_notes_under_their_passage_and_a_remote_caller_sees_no_words(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=NOTE_A), _note(PASSAGE_B, "2026-05-02", uuid="2")]))
    blocks = page_blocks.for_page(bank, "the-lantern-orchard", page_blocks.wanted(["marks"], remote=False))
    assert "marks" in blocks["order"]
    assert blocks["marks"]["total"] == 2
    assert [(i["text"], i["note"]) for i in blocks["marks"]["items"]] == [(PASSAGE_A, NOTE_A), (PASSAGE_B, None)]
    kinds = page_blocks.wanted(["marks"], remote=True)
    assert kinds == ("marks",)
    masked = page_blocks.for_caller(blocks, kinds, verbatim=False)
    said = page_blocks.words(masked, kinds, verbatim=False) + str(masked)
    assert "lanterns" not in said and "slow walk" not in said and masked["marks"]["total"] == 2
    full = page_blocks.words(page_blocks.for_caller(blocks, kinds, verbatim=True), kinds, verbatim=True)
    assert PASSAGE_A in full and NOTE_A in full
    assert all(is_persons_words(c) for c in _marks(bank)), "the words are gated like the person's own"


def test_a_caller_without_sources_reads_no_passage_or_note_through_any_tool(bank, monkeypatch):
    from api.services import ask_service, mcp_tools

    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=NOTE_A)]))
    secret = ("lanterns were lit", "slow walk back")
    remote = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="unknown", raw_excerpts=False,
                                   read_surface="remote")
    local = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="unknown")
    page = "the-lantern-orchard"

    def calls(ctx):
        return {"recall": mcp_tools.recall(ctx, "lanterns"),
                "detail": mcp_tools.recall_detail(ctx, page, include=["blocks"]),
                "perspective": mcp_tools.get_perspective(ctx, page),
                "timeline": mcp_tools.timeline(ctx, since="2020-01-01")}

    for name, reply in calls(remote).items():
        assert not any(word in str(reply) for word in secret), name
    assert secret[0] in str(calls(local)["detail"]) and secret[1] in str(calls(local)["perspective"])
    seen: list[str] = []

    def llm(prompt, *a, **k):
        seen.append(str(prompt))
        return "{}"

    retrieve = lambda _q, _k: [{"id": page, "text": "x", "score": 1.0, "metadata": {"entity_id": page}}]   # noqa: E731
    ask_service.answer_query(bank, "what did I mark?", retrieve_fn=retrieve, llm_fn=llm, source_words=False)
    assert seen and not any(word in " ".join(seen) for word in secret)
    seen.clear()
    ask_service.answer_query(bank, "what did I mark?", retrieve_fn=retrieve, llm_fn=llm, source_words=True)
    assert seen and secret[0] in " ".join(seen)


def test_a_mark_is_never_a_belief_sentence_on_the_page(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1")]))
    from api.services import page_citations

    parsed, claims = _page(bank)
    block = page_citations.block(bank, "the-lantern-orchard", fm=parsed.frontmatter, body=parsed.body, claims=claims)
    assert PASSAGE_A not in str(block.get("beliefs"))


def test_the_beliefs_list_leaves_marks_to_the_pages_own_block(bank):
    from api.routers import claims as claims_route

    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=NOTE_A)], finished=True))
    listed = claims_route._load_subject_claims(bank, "the-lantern-orchard")
    assert listed and not any(is_mark(c) for c in listed), "the status stays a belief; the marks do not"


def test_a_flagged_value_is_never_repeated_on_the_page_and_the_body_keeps_it(bank):
    card = "4539 1488 0343 6467"
    assert sensitive_text.find(f"my card is {card}"), "the fixture is one the detector flags"
    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=f"my card is {card}")]))
    note = next(c for c in _marks(bank) if c.predicate == NOTED)
    assert card not in note.text and "held back" in note.text and card not in note.object
    body = evidence.source_text(bank, note.evidence[0].episode)
    assert card in body, "the stored record is untouched"


def test_a_big_book_spills_into_its_ledger_and_every_reader_still_holds_every_mark(bank):
    many = [_note(f"Passage number {i} of the invented orchard, {'with room ' * 30}.", uuid=f"{i:05d}")
            for i in range(400)]
    _sync(bank, _book(many))
    assert (bank / "entities" / "the-lantern-orchard.claims.jsonl").exists()
    assert len(_marks(bank)) == 400
    bank_index.invalidate(bank)
    assert quiet_pages.page_is_quiet(bank, "the-lantern-orchard") is False
    blocks = page_blocks.for_page(bank, "the-lantern-orchard", ("marks",))
    assert blocks["marks"]["total"] == 400


# ---- the private-use character --------------------------------------------------------------------------------------


def test_private_use_characters_are_stripped_from_every_text_apple_books_posts(bank):
    _sync(bank, _book([_note("Long walk\U000f0001 home.", uuid="1", note="Mine.")],
                      title="The Lantern Orchard", author="Ada Example"))
    episode = next((bank / "episodes").glob("*.md"))
    parsed = markdown_parser.parse(episode)
    assert apple_books._PRIVATE_USE.search(parsed.body) is None
    fm = _page(bank)[0].frontmatter
    assert fm["book"]["authors"] == ["Ada Example"] and fm["name"] == "The Lantern Orchard"
    assert [c.text for c in _marks(bank)] == ["Highlighted: Long walk home.", "Noted: Mine."]


# ---- what Sleep reads ------------------------------------------------------------------------------------------------


def _episode(body, **extra):
    return {"id": "ep_1", "origin": "apple-books", "book": {"status": "reading"}, "content": body, **extra}


def _big_body(n=2000, width=300):
    head = "**Status:** Reading now\n**Book:** The Lantern Orchard\n**Author:** Ada Example\n"
    return head + "".join(f"\n## Highlight, 2026-05-01\n> {i:05d} {'orchard ' * (width // 8)}\n" for i in range(n))


def test_a_book_that_fits_is_read_whole_and_a_big_one_is_a_spread_within_one_chunk():
    small = "**Book:** X\n\n## Highlight, 2026-05-01\n> One.\n"
    assert book_marks.plan_read(small) is None
    body = _big_body() + "\n## User note\nThis one is mine.\n"
    spans, shown, there = book_marks.plan_read(body)
    assert there == 2001 and 20 < shown < 200
    assert sum(hi - lo for lo, hi in spans) + 2 * len(spans) <= book_marks.READ_CHARS + 2
    text = "\n\n".join(body[lo:hi] for lo, hi in spans)
    assert "This one is mine." in text, "every note first"
    numbers = sorted(int(m) for m in re.findall(r"(\d{5}) orchard", text))
    assert numbers[0] < 100 and numbers[-1] > 1800, "spread from one end to the other"


def test_a_revision_that_fits_reads_its_window_and_one_that_does_not_reads_a_spread_of_it():
    body = _big_body(200)
    assert book_marks.plan_read(body, [(len(body) - 400, len(body))]) is None
    spans, shown, there = book_marks.plan_read(body, [(0, 100), (len(body) - 30_000, len(body))])
    assert there < 200 and shown <= there
    assert sum(hi - lo for lo, hi in spans) <= book_marks.READ_CHARS


def test_the_status_lines_are_blanked_with_every_offset_kept():
    body = "**Status:** Finished\n**Finished on:** 2026-01-02\n**My rating:** 5 of 5\n**Book:** X\n"
    masked = book_marks.mask_status(body)
    assert len(masked) == len(body) and "Finished" not in masked and "rating" not in masked and "**Book:** X" in masked


def test_the_note_is_only_for_a_book_with_marks_and_names_what_is_held():
    assert book_marks.note({"id": "e", "origin": "apple-books", "book": {}, "content": "**Status:** Finished\n"}) is None
    assert book_marks.note({"id": "e", "origin": "chat", "content": "## User note\nhi"}) is None
    said = book_marks.note(_episode("## User note\nhi"), themes=["Attention"], shown=(5, 50))
    assert said.startswith(book_marks.NOTE_PREFIX) and "Attention" in said and "5 spread" in said
    assert book_marks.THEME_PREDICATE in said


def _extract(episodes, monkeypatch, memory=None):
    seen: list[dict] = []

    async def fake(ep_id, chunk, ci, total, settings, **kw):
        seen.append({"chunk": chunk, "ci": ci, "total": total, **kw})
        return {"entities": [], "relationships": []}

    monkeypatch.setattr(entity_extractor, "_extract_chunk", fake)
    asyncio.run(entity_extractor.extract(episodes, SimpleNamespace(memory_path=memory, litellm_model="m")))
    return seen


def test_stage_one_makes_one_call_per_book_without_the_status_line(monkeypatch):
    big = _episode(_big_body(), id="ep_big", timestamp="2026-05-01T10:00:00Z")
    seen = _extract([big], monkeypatch)
    assert len(seen) == 1 and seen[0]["total"] == 1, "one call, however many highlights"
    assert len(seen[0]["chunk"]) <= book_marks.READ_CHARS + 4 * 200
    assert "Reading now" not in seen[0]["chunk"] and "The Lantern Orchard" in seen[0]["chunk"]
    assert seen[0]["source_note"].startswith(book_marks.NOTE_PREFIX)
    assert "spread across it are shown" in seen[0]["source_note"]


def test_stage_one_leaves_every_other_episode_alone(monkeypatch):
    other = {"id": "ep_chat", "origin": "claude-code", "content": "user: **Status:** Reading now\n",
             "timestamp": "2026-05-01T10:00:00Z"}
    seen = _extract([other], monkeypatch)
    assert "Reading now" in seen[0]["chunk"] and "source_note" not in seen[0]


def test_books_are_read_one_at_a_time_and_each_hears_the_themes_of_the_last(monkeypatch):
    calls: list[dict] = []
    running = {"now": 0, "most": 0}

    async def fake(ep_id, chunk, ci, total, settings, **kw):
        running["now"] += 1
        running["most"] = max(running["most"], running["now"])
        await asyncio.sleep(0)
        calls.append({"id": ep_id, "note": kw.get("source_note") or ""})
        running["now"] -= 1
        return {"entities": [{"name": f"Theme of {ep_id}", "type": "concept"}], "relationships": []}

    monkeypatch.setattr(entity_extractor, "_extract_chunk", fake)
    body = "**Book:** X\n\n## Highlight, 2026-05-01\n> One.\n"
    episodes = [_episode(body, id=f"ep_{i}", timestamp="2026-05-01T10:00:00Z") for i in range(3)]
    asyncio.run(entity_extractor.extract(episodes, SimpleNamespace(memory_path=None, litellm_model="m")))
    assert running["most"] == 1 and len(calls) == 3
    assert "Theme of" not in calls[0]["note"]
    assert f"Theme of {calls[0]['id']}" in calls[1]["note"]
    assert f"Theme of {calls[1]['id']}" in calls[2]["note"]


def test_a_read_of_a_record_never_writes_about_the_marks_on_the_books_own_page():
    episode = _episode("x", book={"title": "The Lantern Orchard: A Novel"})
    book = {"name": "The Lantern Orchard", "type": "media", "summary": "s", "key_facts": ["k"]}
    theme = {"name": "Focus", "type": "concept", "summary": "kept", "key_facts": ["kept"]}
    assert book_marks.of_a_read([book, theme], [], [], episode, owner_fm=None)[0] == [theme]
    assert book_marks.of_a_read([theme], [], [], _episode("x", book={}), owner_fm=None)[0] == [theme]


def test_the_page_says_why_it_matters_in_a_count_and_never_in_the_words(bank):
    from api.services import page_relevance

    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=NOTE_A), _note(PASSAGE_B, "2026-05-02", uuid="2")]))
    line = page_relevance.for_page(bank, "the-lantern-orchard").to_dict()["line"]
    assert "you marked 2 passages in it" in line and "lanterns" not in line and "slow walk" not in line


def test_theme_hints_name_pages_books_link_to_and_names_held_from_a_book(bank):
    from api.services import pending_store

    _sync(bank, _book([_note(PASSAGE_A, uuid="1")]))
    parsed, _ = _page(bank)
    markdown_parser.write(bank / "entities" / "the-lantern-orchard.md",
                          {**parsed.frontmatter, "related": ["[[slow-attention]]"]}, parsed.body)
    markdown_parser.write(bank / "entities" / "slow-attention.md", {"name": "Slow attention", "type": "concept"}, "x")
    episode = next((bank / "episodes").glob("*.md")).stem
    pending_store.upsert(bank, pending_store.PendingEntity(
        name="Walking home", type="concept", description="", source_episode=episode, confidence=0.7, tags=[],
        history_entries=[]))
    pending_store.upsert(bank, pending_store.PendingEntity(
        name="A chat name", type="concept", description="", source_episode="ep_none", confidence=0.7, tags=[],
        history_entries=[]))
    bank_index.invalidate(bank)
    hints = book_marks.theme_hints(bank)
    assert "Slow attention" in hints and "Walking home" in hints and "A chat name" not in hints


# ---- a record applied before ruling 64, its page merged away since --------------------------------------------------


def _applied_before_marks(bank):
    """A record whose page exists and whose marks were never written: as a record applied before ruling 64 reads."""
    _sync(bank, _book([_note(PASSAGE_A, uuid="1", note=NOTE_A)]))
    parsed = markdown_parser.parse(bank / "entities" / "the-lantern-orchard.md")
    plain = [c for c in parse_claims(parsed.body) if not is_mark(c)]
    markdown_parser.write(bank / "entities" / "the-lantern-orchard.md", parsed.frontmatter,
                          write_claims(parsed.body, plain))
    ep = next((bank / "episodes").glob("*.md"))
    parsed = markdown_parser.parse(ep)
    markdown_parser.write(ep, {k: v for k, v in parsed.frontmatter.items() if k != books.MARKS_KEY}, parsed.body)
    bank_index.invalidate(bank)
    return ep


def test_a_record_applied_before_marks_follows_its_page_through_a_merge(bank):
    from api.services import entity_merge

    ep = _applied_before_marks(bank)
    (bank / "entities" / "the-orchard-book.md").write_text(
        "---\nname: The Orchard Book\ntype: media\nsource_episodes: []\n---\n\n## Summary\nA book.\n")
    entity_merge.merge_entities(bank, "the-lantern-orchard", "the-orchard-book")
    assert not (bank / "entities" / "the-lantern-orchard.md").exists()
    bank_index.invalidate(bank)

    books.apply_pending(bank, today=TODAY)
    bank_index.invalidate(bank)

    words = [c.text for c in _marks(bank, "the-orchard-book")]
    assert any(PASSAGE_A in w for w in words) and any(NOTE_A in w for w in words)
    assert markdown_parser.parse(ep).frontmatter.get(books.MARKS_KEY), "stamped, so it is not tried again"
    assert not (bank / "entities" / "the-lantern-orchard.md").exists(), "the old page is not brought back"


def _merged(bank, *notes, into="the-orchard-book"):
    """A's page with ``notes``, B's page, A merged into B by the real merge."""
    from api.services import entity_merge

    _sync(bank, _book(list(notes)), _book([_note(PASSAGE_B, uuid="b1")], asset="ASSET-B", title="The Orchard Book"))
    entity_merge.merge_entities(bank, "the-lantern-orchard", into)
    bank_index.invalidate(bank)


def _open_marks(bank, entity="the-orchard-book"):
    return [c for c in _marks(bank, entity) if not c.valid_to]


def _no_page_comes_back(bank, entity="the-orchard-book"):
    assert not (bank / "entities" / "the-lantern-orchard.md").exists()
    assert [p.stem for p in (bank / "entities").glob("the-*.md")] == [entity]


def test_a_new_highlight_on_a_merged_book_lands_on_the_page_it_became_with_no_second_copy(bank):
    one = _note(PASSAGE_A, uuid="1", note=NOTE_A)
    _merged(bank, one)
    before = {c.id for c in _open_marks(bank)}
    _sync(bank, _book([one, _note("A third passage the person marked.", "2026-05-03", uuid="3")]))

    _no_page_comes_back(bank)
    live = _open_marks(bank)
    assert len(live) == 4 and before < {c.id for c in live}, "what the merge carried is what stays open"
    assert len({c.text for c in live}) == 4
    page = _page(bank, "the-orchard-book")[0].frontmatter
    assert "ASSET-A" in page["book"]["apple_books"], "the identity is on the winner now, so the index finds it"
    assert books.BookIndex(bank).by_key["apple:ASSET-A"] == "the-orchard-book"


def test_a_mark_taken_back_before_a_merge_stays_taken_back_after_one(bank):
    from api.services.claims import RETRACT_PREDICATE, Claim

    one, two = _note(PASSAGE_A, uuid="1"), _note("A second passage the person marked.", "2026-05-02", uuid="2")
    _sync(bank, _book([one, two]))
    parsed, claims = _page(bank)
    victim = next(c for c in claims if is_mark(c) and PASSAGE_A in c.text)
    claims.append(Claim(id="clm_r", text="Not right.", subject=victim.subject, predicate=RETRACT_PREDICATE,
                        object=victim.id, object_kind="literal"))
    markdown_parser.write(bank / "entities" / "the-lantern-orchard.md", parsed.frontmatter,
                          write_claims(parsed.body, claims))
    _merged(bank, one, two)
    _sync(bank, _book([one, two, _note("A third passage the person marked.", "2026-05-03", uuid="3")]))

    drawn = [i["text"] for i in book_marks.block(_page(bank, "the-orchard-book")[1])["items"]]
    assert PASSAGE_A not in drawn and "A third passage the person marked." in drawn
    _no_page_comes_back(bank)


def test_a_passage_both_merged_pages_held_is_one_open_mark_resting_on_both_records(bank):
    from api.services import entity_merge

    same = _note(PASSAGE_A, uuid="1")
    _sync(bank, _book([same]), _book([_note(PASSAGE_A, uuid="b1")], asset="ASSET-B", title="The Orchard Book"))
    entity_merge.merge_entities(bank, "the-lantern-orchard", "the-orchard-book")
    bank_index.invalidate(bank)
    assert len(_open_marks(bank)) == 2, "a merge reconciles nothing"

    _sync(bank, _book([same], finished=True))

    live = _open_marks(bank)
    assert len(live) == 1 and len(live[0].source_episodes) == 2
    assert {e.episode for e in live[0].evidence} == set(live[0].source_episodes)


def test_a_status_change_after_a_merge_goes_on_the_winner_with_no_repeat_of_what_it_carried(bank):
    one = _note(PASSAGE_A, uuid="1")
    _merged(bank, one)
    claims = _page(bank, "the-orchard-book")[1]
    held = [c.id for c in books.live_status_claims(claims)]
    happened = [c.id for c in claims if c.predicate == "happened"]

    _sync(bank, _book([one]))   # nothing new said: nothing written twice, only the record's own apply
    claims = _page(bank, "the-orchard-book")[1]
    assert [c.id for c in books.live_status_claims(claims)] == held

    _sync(bank, _book([one], finished=True))
    _no_page_comes_back(bank)
    claims = _page(bank, "the-orchard-book")[1]
    finished = [c for c in books.live_status_claims(claims) if c.object == books.FINISHED]
    assert len(finished) == 1 and finished[0].subject == "the-orchard-book"
    assert len([c for c in books.live_status_claims(claims) if not c.valid_to]) == 1, "one record in force"
    assert len(_open_marks(bank)) == 2
    new = [c for c in claims if c.predicate == "happened" and c.id not in happened]
    assert [c.object for c in new] == [books.HAPPENING_TEXT[books.FINISHED].lower()]


def test_a_status_taken_back_before_a_merge_stays_taken_back_after_one(bank):
    one = _note(PASSAGE_A, uuid="1")
    _sync(bank, _book([one]))
    taken = next(c for c in books.live_status_claims(_page(bank)[1]) if not c.valid_to)
    books.undo_status(bank, "the-lantern-orchard", taken.id, today=TODAY.isoformat())
    bank_index.invalidate(bank)
    _merged(bank, one)

    _sync(bank, _book([one, _note("A third passage the person marked.", "2026-05-03", uuid="3")]))
    live = books.live_status_claims(_page(bank, "the-orchard-book")[1])
    assert not [c for c in live if set(c.source_episodes) & set(taken.source_episodes)]


def test_a_rating_after_a_merge_is_said_once(bank):
    _sync(bank, _book([_note(PASSAGE_A, uuid="1")]), _book(asset="ASSET-B", title="The Orchard Book"))
    ep = next(p for p in (bank / "episodes").glob("*.md")
              if markdown_parser.parse(p).frontmatter.get("book_entity_id") == "the-lantern-orchard")
    assert books.set_rating(bank, "the-lantern-orchard", rating=4, day="2026-05-01", episode_id=ep.stem, quote="4 of 5",
                            observer="ada-lovelace", today=TODAY.isoformat())
    from api.services import entity_merge

    entity_merge.merge_entities(bank, "the-lantern-orchard", "the-orchard-book")
    bank_index.invalidate(bank)
    again = dict(rating=4, day="2026-05-01", episode_id=ep.stem, quote="4 of 5", observer="ada-lovelace",
                 today=TODAY.isoformat())
    assert not books.set_rating(bank, "the-orchard-book", **again), "the winner already holds it, under the old id"
    assert books.set_rating(bank, "the-orchard-book", **{**again, "rating": 5})
    live = [c for c in _page(bank, "the-orchard-book")[1] if c.predicate == books.RATING_PREDICATE and not c.valid_to]
    assert [c.object for c in live] == ["5/5"]


def test_a_chain_of_merges_is_followed_to_its_end(bank):
    from api.services import entity_merge

    one = _note(PASSAGE_A, uuid="1")
    _merged(bank, one)
    _sync(bank, _book(asset="ASSET-C", title="The Third Copy"))
    entity_merge.merge_entities(bank, "the-orchard-book", "the-third-copy")
    bank_index.invalidate(bank)

    _sync(bank, _book([one, _note("A third passage the person marked.", "2026-05-03", uuid="3")]))
    _no_page_comes_back(bank, "the-third-copy")
    live = _open_marks(bank, "the-third-copy")
    assert len(live) == 3 and len({c.text for c in live}) == 3


def test_a_record_merged_into_a_page_that_is_no_book_stays_there_and_never_makes_it_one(bank):
    from api.services import entity_merge

    one = _note(PASSAGE_A, uuid="1")
    _sync(bank, _book([one]))
    (bank / "entities" / "the-orchard-idea.md").write_text(
        "---\nname: The Orchard Idea\ntype: concept\nsource_episodes: []\n---\n\n## Summary\nAn idea.\n")
    entity_merge.merge_entities(bank, "the-lantern-orchard", "the-orchard-idea")
    bank_index.invalidate(bank)

    for _round in range(2):   # the second: the record's stamp now names the page itself, with no redirect to follow
        _sync(bank, _book([one, _note("A third passage the person marked.", "2026-05-03", uuid="3")], progress=0.6 + _round / 10))

    _no_page_comes_back(bank, "the-orchard-idea")
    parsed, _claims = _page(bank, "the-orchard-idea")
    assert not books.is_book(parsed.frontmatter) and parsed.frontmatter["type"] == "concept"
    assert len(_open_marks(bank, "the-orchard-idea")) == 2


def test_a_record_whose_page_is_gone_with_no_redirect_stops_being_tried(bank):
    ep = _applied_before_marks(bank)
    (bank / "entities" / "the-lantern-orchard.md").unlink()
    bank_index.invalidate(bank)
    books.apply_pending(bank, today=TODAY)
    bank_index.invalidate(bank)
    assert not (bank / "entities" / "the-lantern-orchard.md").exists()
    assert markdown_parser.parse(ep).frontmatter.get(books.MARKS_KEY)
    assert not books.pending(bank)


# ---- no model that writes a page reads a mark -----------------------------------------------------------------------


def test_a_page_writer_reads_no_mark_and_a_mark_is_no_reason_to_write(bank):
    from api.services import catchup_chat, conflict_resolver, entity_article, entity_orientation

    many = [_note(f"Passage {i}: the lanterns of the orchard number {i}.", uuid=f"{i}", note=NOTE_A if i == 0 else "")
            for i in range(8)]
    _sync(bank, _book(many))
    parsed, claims = _page(bank)
    assert len([c for c in claims if is_mark(c)]) == 9
    fm, body = parsed.frontmatter, parsed.body

    context = {"today": "2026-10-02", "owner": None, "names": {}, "known": set(), "max_chars": 40_000}
    change = {"id": "the-lantern-orchard", "source_episode": "ep_2026-10-02_001"}
    new = {"name": "The Lantern Orchard", "type": "media", "summary": "I finished it and loved it."}
    job = conflict_resolver._article_job(change, {"frontmatter": fm, "body": body}, new, context)
    assert job is not None and "lanterns" not in job["prompt"] and NOTE_A not in job["prompt"]
    assert entity_article.material(job["inputs"]) < entity_article.MIN_MATERIAL, "the marks are no material"
    assert not entity_article.worth_writing({}, ["ep_2026-10-02_001"], job["inputs"]), "nine marks write no article"

    data = entity_orientation.context(body, name="The Lantern Orchard", entity_type="media", fields={},
                                      today="2026-10-02", source_dates=[])
    assert "lanterns" not in str(data["current_claims"]) and NOTE_A not in str(data)

    assert "lanterns" not in str(catchup_chat.context_lines(bank, "the-lantern-orchard", limit=40))


def test_a_passage_taken_out_of_a_record_never_reaches_a_page_writer_and_a_note_does(bank):
    from api.services import episode_revision, revision_prose

    prior = ("**Status:** Reading\n\n## Highlight, 2026-05-01\n\n> The lanterns were lit long before dusk.\n\n"
             "## User note\n\nI keep walking back the slow way.\n")
    both_out = "**Status:** Reading\n"
    episode = {"id": "ep_2026-05-01_001", "origin": books.APPLE_ORIGIN, "book": {"title": "x"}, "content": both_out}
    rev = episode_revision.build(episode, prior)
    said = " ".join(c.before for c in revision_prose.changes_of(rev))
    assert rev.book and "lanterns" not in said
    plain = {"id": "ep_2026-05-01_002", "origin": "claude-code", "content": both_out}
    assert "lanterns" in " ".join(c.before for c in revision_prose.changes_of(episode_revision.build(plain, prior)))

    only_note = prior.split("## User note")[0]
    rev = episode_revision.build({**episode, "content": only_note}, prior)
    said = " ".join(c.before for c in revision_prose.changes_of(rev))
    assert "walking back" in said and "lanterns" not in said, "a note is the person's: what it said can still be undone"


# ---- what a read may put on the owner's page -----------------------------------------------------------------------


OWNER_FM = {"name": "Ada Lovelace", "owner": True, "aliases": ["Countess"]}


def _record(note=NOTE_A):
    content = f"**Status:** Reading\n\n## Highlight, 2026-05-01\n\n> {PASSAGE_A}\n\n## User note\n\n{note}\n"
    return {"id": "ep_2026-05-01_001", "origin": books.APPLE_ORIGIN, "book": {"title": "The Lantern Orchard"},
            "content": content}


def _span(episode, quote, kind):
    start = episode["content"].index(quote)
    return [{"episode": episode["id"], "start": start, "end": start + len(quote), "kind": kind}]


@pytest.mark.parametrize("name", ["Ada Lovelace", "Ada", "ada", "Countess", "Ada Lovelase", "the user", "Lovelace"])
def test_no_entry_for_the_owner_under_any_name_they_go_by_note_or_no_note(name):
    theme = {"name": "Slow walks", "type": "concept"}
    book = {"name": "The Lantern Orchard", "type": "media", "summary": "x"}
    owner = {"name": name, "type": "person", "summary": "practices sourdough baking", "key_facts": ["bakes"],
             "history_entries": ["bakes"]}
    entities, _rels, _vals = book_marks.of_a_read([book, owner, theme], [], [], _record(), owner_fm=OWNER_FM)
    assert entities == [theme]


def test_a_concept_that_shares_the_owners_first_name_keeps_its_own_entry():
    ada = {"name": "Ada", "type": "concept"}
    assert book_marks.of_a_read([ada], [], [], _record(), owner_fm=OWNER_FM)[0] == [ada]


def test_only_what_is_located_in_a_note_reaches_the_owner():
    episode = _record()
    note = _span(episode, "the slow walk back", "user")
    passage = _span(episode, "lanterns were lit", "page")
    held_in_passage_but_user = _span(episode, "lanterns were lit", "user")
    rels = [
        {"source": "Ada", "target": "Baking", "label": "practices", "evidence": passage},
        {"source": "The Lantern Orchard", "target": "Ada Lovelace", "label": "taught", "evidence": passage},
        {"source": "Ada Lovelace", "target": "Baking", "label": "does", "evidence": held_in_passage_but_user},
        {"source": "Ada Lovelace", "target": "Baking", "label": "does", "evidence": []},
        {"source": "Ada Lovelace", "target": "Baking", "label": "someone else", "evidence": note,
         "observer": "external:bob"},
        {"source": "Ada Lovelace", "target": "Walking", "label": "cares about", "evidence": note},
        {"source": "The Lantern Orchard", "target": "Focus", "label": "explores-theme", "evidence": passage},
    ]
    values = [{"entity": "Ada", "attribute": "hobby", "value": "baking", "evidence": passage},
              {"entity": "Countess", "attribute": "walks", "value": "slowly", "evidence": note}]
    _ents, kept_rels, kept_vals = book_marks.of_a_read([], rels, values, episode, owner_fm=OWNER_FM)
    assert [r["label"] for r in kept_rels] == ["cares about", "explores-theme"]
    assert kept_rels[0]["source"] == "Ada Lovelace"
    assert [(v["entity"], v["attribute"]) for v in kept_vals] == [("Ada Lovelace", "walks")], "an alias lands on their page"


@pytest.mark.parametrize("name", ["Ada", "Lovelace", "ada"])
def test_a_friend_sharing_the_owners_first_name_or_surname_stays_themselves(name):
    from api.services import entity_resolver

    episode = _record()
    note, passage = _span(episode, "the slow walk back", "user"), _span(episode, "lanterns were lit", "page")
    friend = {"name": name, "type": "person", "summary": "a friend"}
    rels = [{"source": name, "target": "The Lantern Orchard", "label": "recommended", "evidence": note}]
    vals = [{"entity": name, "attribute": "changed", "value": "her mind", "evidence": note}]
    entities, kept_rels, kept_vals = book_marks.of_a_read([friend], rels, vals, episode, owner_fm=OWNER_FM)
    assert entities == [friend] and kept_rels == rels and kept_vals == vals
    assert entity_resolver.endpoint_id(name, {"ada lovelace": "ada-lovelace"}) is None, "and Stage 2 would not join it"

    # Outside a note the same name says nothing: a model's reading of a passage.
    rels = [{"source": name, "target": "Baking", "label": "practices", "evidence": passage}]
    assert book_marks.of_a_read([friend], rels, [], episode, owner_fm=OWNER_FM)[:2] == ([], [])


def test_a_close_spelling_stays_as_written_for_stage_two_to_join_and_gets_no_entry_of_its_own():
    from api.services import entity_resolver

    episode = _record()
    note = _span(episode, "the slow walk back", "user")
    close = "Ada Lovelase"
    rels = [{"source": close, "target": "Walking", "label": "cares about", "evidence": note}]
    entities, kept_rels, _ = book_marks.of_a_read([{"name": close, "type": "person"}], rels, [], episode, owner_fm=OWNER_FM)
    assert entities == [] and kept_rels == rels
    assert entity_resolver.endpoint_id(close, {"ada lovelace": "ada-lovelace"}) == "ada-lovelace"


def test_a_self_reference_is_left_for_the_resolver_and_a_bank_with_no_owner_page_still_holds_the_line():
    episode = _record()
    note, passage = _span(episode, "the slow walk back", "user"), _span(episode, "lanterns were lit", "page")
    rels = [{"source": "the user", "target": "Walking", "label": "a", "evidence": note},
            {"source": "the user", "target": "Baking", "label": "b", "evidence": passage}]
    kept = book_marks.of_a_read([], rels, [], episode, owner_fm=None)[1]
    assert [(r["source"], r["label"]) for r in kept] == [("the user", "a")]

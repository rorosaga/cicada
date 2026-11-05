"""One standard for "this part of this source" (ROR-16, G118): the shape, the judge, the route. Synthetic fixtures."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, demo_bank, evidence, markdown_parser, provenance, source_spans
from api.services.claims import Claim, Evidence, write_claims
from api.services.source_spans import CURRENT, DERIVED, GROWN, HELD, STALE, UNLOCATED, Source

SECRET = "Tr4y-example-42!"
NOTE = ("Rover arm: the gripper camera needs recalibrating.\n\n"
        f"Lab room: the wifi password is {SECRET} and the door code is on the board.\n\n"
        "Lab cluster: the login node asks for a key now.")
NOTE_ID = "ep_2026-09-01_001"
CHAT_ID = "ep_2026-09-02_001"
CHAT = "user: first thing\nassistant: noted"


def _claim(cid: str, subject: str, ev: Evidence | None, doc: str = NOTE_ID, **extra) -> Claim:
    return Claim(id=cid, text=f"sentence of {cid}", subject=subject, predicate="said", object="x", object_kind="literal",
                 observer="agent", context="general", epistemic="explicit", source_trust="agent", confidence=0.8,
                 valid_from="2026-09-01", recorded_at="2026-09-01", source_episodes=[doc],
                 evidence=[ev] if ev else [], **extra)


def _span(text: str, quote: str, kind: str = "user", doc: str = NOTE_ID, hash: str | None = None) -> Evidence:  # noqa: A002
    at = text.index(quote)
    return Evidence(episode=doc, start=at, end=at + len(quote), hash=hash or evidence.body_hash(text), kind=kind)


def _page(memory: Path, stem: str, name: str, claims: list[Claim], etype: str = "project") -> None:
    fm = {"name": name, "type": etype, "status": "active", "confidence": 0.9, "source_episodes": [NOTE_ID]}
    markdown_parser.write(memory / "entities" / f"{stem}.md", fm, write_claims(f"## Summary\n{name}.\n", claims))


@pytest.fixture
def memory(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    (mem / "episodes").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(mem))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    source_spans.forget()
    markdown_parser.write(mem / "episodes" / f"{NOTE_ID}.md",
                          {"id": NOTE_ID, "origin": "apple-notes", "source": "apple-notes", "title": "Bench notes",
                           "timestamp": "2026-09-01T08:00:00+00:00", "processed": True}, NOTE)
    markdown_parser.write(mem / "episodes" / f"{CHAT_ID}.md",
                          {"id": CHAT_ID, "origin": "telegram", "title": "A chat",
                           "timestamp": "2026-09-02T08:00:00+00:00", "processed": True}, CHAT)
    _page(mem, "rover", "Rover", [_claim("c-rover", "rover", _span(NOTE, "the gripper camera needs recalibrating"))])
    _page(mem, "cluster", "Cluster", [
        _claim("c-key", "cluster", _span(NOTE, "the login node asks for a key now")),
        _claim("c-wifi", "cluster", _span(NOTE, f"the wifi password is {SECRET}")),
        _claim("c-old", "cluster", _span(NOTE, "Lab cluster", hash="deadbeefcafe")),
        _claim("c-inferred", "cluster", Evidence(episode=NOTE_ID, kind="reasoning")),
    ], "tool")
    yield mem
    config.get_settings.cache_clear()
    source_spans.forget()


def _source(memory: Path, doc: str = NOTE_ID) -> Source:
    return Source.open(memory, doc)


def test_the_one_judge_answers_every_status(memory):
    source = _source(memory)
    s = NOTE.index("the gripper")
    digest = evidence.body_hash(NOTE)
    assert source.status(s, s + 5, digest) == CURRENT
    assert source.status(s, s + 5, "deadbeefcafe") == STALE
    assert source.status(s, len(NOTE) + 10, digest) == STALE
    assert source.status(-1, -1, digest) == UNLOCATED
    at = NOTE.index(SECRET)
    assert source.status(at, at + 4, digest) == HELD
    assert source.status(at - 8, at + 1, digest) == HELD, "touching the value holds the span"
    chat = _source(memory, CHAT_ID)
    grown = "user: first thing"
    assert chat.status(0, len(grown), evidence.body_hash(grown)) == GROWN
    assert source.derived(s, s + 5).status == DERIVED


def test_only_what_may_be_drawn_carries_a_place(memory):
    source = _source(memory)
    s = NOTE.index("the gripper")
    at = NOTE.index(SECRET)
    digest = evidence.body_hash(NOTE)
    assert source.span(s, s + 5, digest, "user").at.model_dump() == {"type": "text", "start": s, "end": s + 5}
    assert source.span(s, s + 5, "deadbeefcafe", "user").at is None
    assert source.span(at, at + 4, digest, "user").at is None
    assert source.nothing().at is None and source.nothing().status == UNLOCATED


def test_every_span_into_a_source_is_grouped_by_page_in_document_order(memory):
    with TestClient(main.app) as client:
        res = client.get(f"/episodes/{NOTE_ID}/spans")
        assert res.status_code == 200
        body = res.json()
        assert client.get(f"/episodes/{NOTE_ID}/spans", headers={"If-None-Match": res.headers["etag"]}).status_code == 304
    assert body["sourceKind"] == "note" and body["hash"] == evidence.body_hash(NOTE) and body["length"] == len(NOTE)
    assert [g["page"] for g in body["groups"]] == ["rover", "cluster"], "pages by where they first point"
    assert body["groups"][1]["name"] == "Cluster" and body["groups"][1]["type"] == "tool"
    cluster = {s["claimId"]: s for s in body["groups"][1]["spans"]}
    assert cluster["c-key"]["status"] == CURRENT and cluster["c-key"]["at"]["start"] == NOTE.index("the login node")
    assert cluster["c-wifi"]["status"] == HELD and cluster["c-wifi"]["at"] is None
    assert cluster["c-old"]["status"] == STALE and cluster["c-old"]["at"] is None
    assert "c-inferred" not in cluster, "an inference points at the source, at no part of it"
    assert SECRET not in json.dumps(body), "offsets and ids: the route carries no words"


def test_the_etag_moves_when_a_page_does(memory):
    with TestClient(main.app) as client:
        first = client.get(f"/episodes/{NOTE_ID}/spans").headers["etag"]
        _page(memory, "lab", "Lab", [_claim("c-lab", "lab", _span(NOTE, "Rover arm"))])
        bank_index.invalidate()
        res = client.get(f"/episodes/{NOTE_ID}/spans", headers={"If-None-Match": first})
    assert res.status_code == 200 and "lab" in [g["page"] for g in res.json()["groups"]]


def test_a_changed_page_alone_is_read_again(memory, monkeypatch):
    source_spans.for_source(memory, NOTE_ID)
    calls: list[str] = []
    real = markdown_parser.parse
    monkeypatch.setattr(markdown_parser, "parse", lambda p, **k: (calls.append(Path(p).name), real(p, **k))[1])
    source_spans.for_source(memory, NOTE_ID)
    assert f"{NOTE_ID}.md" in calls and "rover.md" not in calls and "cluster.md" not in calls, "a warm read parses no page"


def test_a_claim_in_a_ledger_is_found(memory):
    """A page past 64k characters keeps its claims beside it. The old scan read only the page's own text."""
    ep = "ep_2026-09-03_001"
    words = "said only on a big page"
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "origin": "telegram", "timestamp": "2026-09-03T08:00:00+00:00"}, f"user: {words}")
    big = [_claim(f"c-{n:05d}", "big", _span(NOTE, "Rover arm")) for n in range(400)]
    text = f"user: {words}"
    big.append(_claim("c-only", "big", _span(text, words, doc=ep), doc=ep))
    fm = {"name": "Big", "type": "person", "status": "active", "confidence": 0.9, "source_episodes": []}
    markdown_parser.write(memory / "entities" / "big.md", fm, write_claims("## Summary\nBig.\n", big))
    assert (memory / "entities" / "big.claims.jsonl").exists(), "the fixture must overflow into a ledger"
    bank_index.invalidate()
    assert source_spans.pages_citing(memory, ep) == ["big.md"]
    assert [r.claim_id for r in provenance.episode_citations(memory, ep).citations] == ["c-only"]


def test_a_held_span_never_travels_as_words(memory):
    at = NOTE.index(SECRET)
    start, end = NOTE.index("the wifi"), at + len(SECRET)
    digest = evidence.body_hash(NOTE)
    with TestClient(main.app) as client:
        focus = client.get(f"/episodes/{NOTE_ID}/text", params={"start": start, "end": end, "hash": digest}).json()["focus"]
        span = client.get(f"/episodes/{NOTE_ID}/span", params={"start": start, "end": end}).json()
        near = client.get(f"/episodes/{NOTE_ID}/span", params={"start": at - 30, "end": at - 20, "context": 200}).json()
        rows = client.get(f"/episodes/{NOTE_ID}/citations").json()["citations"]
    assert focus["start"] is None and focus["span"]["status"] == HELD and focus["span"]["at"] is None
    assert focus["stale"] is False, "no banner: nothing says why"
    assert span["held"] is True and span["text"] == span["before"] == span["after"] == ""
    assert SECRET not in json.dumps(near), "a value in the neighbourhood stays out of a preview"
    row = next(r for r in rows if r["claimId"] == "c-wifi")
    assert row["start"] is None and row["span"]["status"] == HELD


def test_a_left_alarm_draws_again(memory):
    path = memory / "episodes" / f"{NOTE_ID}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "sensitive": {"kept": {"password": 1}}}, parsed.body)
    bank_index.invalidate()
    at = NOTE.index(SECRET)
    assert _source(memory).status(at, at + 4, evidence.body_hash(NOTE)) == CURRENT


def test_a_popover_quote_near_a_secret_keeps_its_place_and_no_words(memory):
    docs = provenance._Episodes(memory)
    text = docs.body(NOTE_ID)
    held = docs.held(NOTE_ID)
    assert held, "the fixture holds a value"
    held_span = provenance._span_model(text, NOTE_ID, NOTE.index(SECRET), NOTE.index(SECRET) + 4, hash="", kind="user",
                                       held=held)
    assert held_span.held is True and held_span.start is None and held_span.excerpt == ""
    near = provenance._span_model(text, NOTE_ID, NOTE.index("Lab room"), NOTE.index("Lab room") + 8, hash="", kind="user",
                                  held=held)
    assert near.held is False and near.start is not None and near.excerpt == "", "its neighbourhood holds the value"


def test_a_locked_note_is_no_source(memory):
    path = memory / "episodes" / f"{NOTE_ID}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, evidence.LOCKED_NOTE_KEY: True}, "")
    bank_index.invalidate()
    with TestClient(main.app) as client:
        assert client.get(f"/episodes/{NOTE_ID}/spans").status_code == 404
        assert client.get(f"/episodes/{NOTE_ID}/text").status_code == 404
    assert source_spans.for_source(memory, NOTE_ID) is None


def test_a_marks_place_rides_the_card_and_never_a_caller_without_sources(memory):
    from api.services import book_marks
    from api.services.claims import HIGHLIGHTED, MARK_ORIGIN

    span = _span(NOTE, "Rover arm")
    mark = Claim(id="c-mark", text="Highlighted: Rover arm", subject="b", predicate=HIGHLIGHTED, object="Rover arm",
                 object_kind="literal", observer="user", context="general", epistemic="explicit",
                 source_trust="user_stated", confidence=0.9, valid_from="2026-09-01", recorded_at="2026-09-01",
                 source_episodes=[NOTE_ID], origin=MARK_ORIGIN, authored_by="user", evidence=[span])
    block = book_marks.block([mark])
    assert block["items"][0]["evidence"] == {"episode": NOTE_ID, "start": span.start, "end": span.end,
                                             "hash": span.hash, "kind": "user"}
    assert "evidence" not in book_marks.for_caller(block)["items"][0]


def test_a_media_id_named_only_in_source_episodes_is_found(memory):
    fm = {"name": "Mentions", "type": "concept", "status": "active", "confidence": 0.9, "source_episodes": ["media-a.b-c"]}
    markdown_parser.write(memory / "entities" / "mentions.md", fm, "## Summary\nMentions.\n")
    bank_index.invalidate()
    assert source_spans.pages_citing(memory, "media-a.b-c") == ["mentions.md"]


def test_a_bad_id_never_reaches_the_disk(memory):
    with TestClient(main.app) as client:
        assert client.get("/episodes/..%2Fsecrets/spans").status_code == 404


@pytest.mark.parametrize("doc,fm,kind", [
    ("rover-page", {}, "page"),
    (NOTE_ID, {"origin": "apple-notes"}, "note"),
    (NOTE_ID, {"origin": "folder", "folder_id": "a"}, "note"),
    (NOTE_ID, {"origin": "folder", "meeting": {"speakers": ["You"]}}, "meeting"),
    (NOTE_ID, {"origin": "apple-books", "book": {"title": "A book"}}, "book"),
    (NOTE_ID, {"origin": "telegram"}, "conversation"),
    (NOTE_ID, {"origin": "claude-code", "harness": "claude-code"}, "conversation"),
    (NOTE_ID, {"origin": "safari-bookmark"}, "save"),
    (NOTE_ID, {"origin": "rss"}, "item"),
    (NOTE_ID, {"source": "web-check"}, "web"),
    (NOTE_ID, {"source": "video-watch"}, "video"),
    (NOTE_ID, {"source": "page-read"}, "page"),
])
def test_what_a_source_is_comes_from_its_record(doc, fm, kind):
    assert source_spans.kind_of(doc, fm) == kind


def test_the_demo_cites_every_kind_to_its_words(tmp_path):
    """The proof bank: a note, a meeting, a book, a save, a chat and a fetched page, plus one stale and one held."""
    source_spans.forget()
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    demo_bank.populate(bank, today=date(2026, 11, 5))
    bank_index.invalidate()
    seen: dict[str, set[str]] = {}
    docs = [p.stem for p in (bank / "episodes").glob("*.md")] + ["media-arxiv-2303-04137"]
    for doc in docs:
        spans = source_spans.for_source(bank, doc)
        for group in spans.groups if spans else []:
            seen.setdefault(spans.source_kind, set()).update(s.status for s in group.spans)
    assert {"note", "meeting", "book", "save", "conversation", "page"} <= set(seen), seen
    assert {CURRENT, STALE, HELD} <= seen["note"], seen

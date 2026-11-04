"""G235: Remove on a real-shaped bank: it never damages a page, never loses the only copy, and a failure leaves the value
findable and the state honest. Made-up values only."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from api.models.schemas import InboxResolveRequest
from api.services.episode_staging import Turn
from api.services import (bank_index, claims_ledger, episode_staging, inbox_service, markdown_parser, search_index,
                          sensitive_flags as sf, sensitive_hold, sensitive_purge as purge, sensitive_text as st, turn_signals,
                          vector_index)

VALUE = "Zebra7-lantern"
EP = "ep_2026-11-01_001"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=bank, check=True,
                          capture_output=True, text=True).stdout


def _ep(bank: Path, ep: str = EP, body: str = f"user: my password is {VALUE}\nassistant: Logged in with {VALUE}.", **fm) -> Path:
    path = bank / "episodes" / f"{ep}.md"
    markdown_parser.write(path, {"id": ep, "processed": True, "processed_by": "sleep", "source": "chatgpt", "title": "Plans",
                                 "timestamp": "2026-11-01T10:00:00Z", "content_hash": episode_staging.content_hash(body),
                                 **fm}, body)
    bank_index.invalidate()
    return path


def _commit(bank: Path) -> None:
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "capture")


@pytest.fixture
def bank(tmp_path) -> Path:
    b = tmp_path / "bank"
    for d in ("episodes", "entities", "inbox", "hubs"):
        (b / d).mkdir(parents=True)
    _git(b, "init", "-q")
    (b / ".gitkeep").write_text("")
    _git(b, "add", "-A")
    _git(b, "commit", "-qm", "start")
    bank_index.invalidate()
    sensitive_hold.forget()
    yield b
    bank_index.invalidate()


def _remove(bank: Path, *eps: str) -> dict:
    bank_index.invalidate()
    rows = [r for r in sf.plan(bank) if not eps or r["episode"] in eps]
    return sf.remove_planned(bank, [r["row"] for r in rows], stamp=sf.plan_stamp(rows))


def _page(bank: Path, name: str, fm: dict, body: str, raw_fm: str | None = None) -> Path:
    path = bank / "entities" / f"{name}.md"
    if raw_fm is None:
        markdown_parser.write(path, {"name": name, "type": "concept", **fm}, body)
    else:
        path.write_text(f"---\n{raw_fm}\n---\n\n{body}\n", encoding="utf-8")
    return path


# ---- item 1: by value across the conversation


def test_the_same_value_elsewhere_in_the_conversation_goes_and_the_row_goes_with_it(bank):
    path = _ep(bank)
    _commit(bank)
    out = _remove(bank)
    body = markdown_parser.parse(path).body
    assert VALUE not in body and body.count("[removed: password]") == 2 and "Logged in with" in body
    assert out["removed"] == 1 and out["left"] == 0 and out["still_found"] == 0
    assert VALUE not in path.read_text()


def test_another_conversation_holding_the_same_value_goes_too_with_its_words_around_it(bank):
    _ep(bank)
    other = _ep(bank, "ep_2026-11-02_001", f"user: alpha\nassistant: tried {VALUE} and it worked\nuser: beta")
    _commit(bank)
    _remove(bank, EP)
    text = other.read_text()
    assert VALUE not in text and "tried [removed: password] and it worked" in text and "user: beta" in text
    fm = markdown_parser.parse(other).frontmatter
    assert fm["processed"] is False and fm["sensitive"]["removed"]["pending"] is True
    assert VALUE in _git(bank, "show", "HEAD~1:episodes/ep_2026-11-02_001.md")


def test_a_source_sending_it_again_brings_neither_line_back(bank):
    path = _ep(bank)
    _commit(bank)
    _remove(bank)
    fm = dict(markdown_parser.parse(path).frontmatter)
    turns = [Turn(speaker="user", text=f"my password is {VALUE}"), Turn(speaker="assistant", text=f"Logged in with {VALUE}.")]

    @dataclasses.dataclass
    class Draft:
        turns: list
        body: str | None = None
        title: str | None = None

    out = sf.reapply_draft(Draft(turns=turns), fm)
    assert all(VALUE not in t.text for t in out.turns)
    assert out.turns[1].text == "Logged in with [removed: password]."


# ---- item 6: the vector index


def test_the_vector_index_loses_the_passage_and_keeps_the_rest(bank, tmp_path):
    _ep(bank)
    _ep(bank, "ep_2026-11-02_001", "user: an ordinary line about the trip")

    def embed(texts, *, is_query=False):
        return np.ones((len(texts), 4), dtype=np.float32)

    index = vector_index.SqliteVecIndexer(bank, embed_fn=embed, model_name="fake")
    index.index_episodes()
    assert VALUE.encode() in index.db_path.read_bytes()
    removed = vector_index.forget_passages(bank, (VALUE,))
    assert removed >= 1
    assert VALUE.encode() not in index.db_path.read_bytes()
    conn = index._connect()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'meta\\_%' ESCAPE '\\'")]
    kept = sum(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables)
    conn.close()
    assert kept >= 1


def test_a_conversations_own_passages_go_by_id_without_a_word_that_is_not_distinctive(bank):
    _ep(bank, EP, "user: my password is guatemala.")
    _ep(bank, "ep_2026-11-02_001", "user: a trip to guatemala was lovely")

    def embed(texts, *, is_query=False):
        return np.ones((len(texts), 4), dtype=np.float32)

    index = vector_index.SqliteVecIndexer(bank, embed_fn=embed, model_name="fake")
    index.index_episodes()
    sf.forget_in_indexes(bank, {"guatemala": "[removed: password]"}, (EP,))
    conn = index._connect()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'meta\\_%' ESCAPE '\\'")]
    texts = [r[0] for t in tables for r in conn.execute(f"SELECT text FROM {t}")]
    conn.close()
    assert any("a trip to guatemala" in t for t in texts) and not any("my password is" in t for t in texts)


# ---- item 7: never damage a file


@pytest.mark.parametrize("raw_fm", [
    f"name: Alpha\ntype: concept\ndescription: Said its password is {VALUE} on a call",       # a mark would make ": " a mapping
    f"name: {VALUE}\ntype: concept",                                                          # a mark would make a list
    f"name: Alpha\ntype: concept\nlabel: {VALUE}",
    f"name: Alpha\ntype: concept\ndescription: {VALUE} or something like it",                 # `[removed] or x`: a parse error
])
def test_frontmatter_stays_yaml_and_stays_the_same_shape(bank, raw_fm):
    _ep(bank)
    path = _page(bank, "alpha", {}, f"Cited in {EP}.", raw_fm=raw_fm)
    _commit(bank)
    _remove(bank)
    parsed = markdown_parser.parse(path)
    assert VALUE not in path.read_text()
    assert isinstance(parsed.frontmatter, dict) and parsed.frontmatter["type"] == "concept"
    for key, value in parsed.frontmatter.items():
        assert isinstance(value, str), key
    bank_index.invalidate()
    assert any(f.path == path for f in bank_index.files(bank, "entities"))     # the page did not disappear


def test_a_non_ascii_value_written_escaped_by_yaml_goes(bank):
    _ep(bank, EP, "user: my password is Añoranza7")
    path = _page(bank, "alpha", {"aliases": ["Añoranza7", "Alpha"], "summary": "x Añoranza7 y"}, f"Cited in {EP}.")
    assert "Añoranza7" not in path.read_text()      # yaml.dump escaped it: a raw replace never saw it
    _commit(bank)
    assert _remove(bank)["still_found"] == 0
    fm = markdown_parser.parse(path).frontmatter
    assert fm["aliases"] == ["Alpha"] and "Añoranza7" not in fm["summary"]      # an alias of a mark names nothing


def test_a_wikilink_and_a_claim_fence_stay_whole(bank):
    _ep(bank)
    fence = "```claims\n" + json.dumps({"id": "c1", "subject": "alpha", "predicate": "login", "object": VALUE,
                                        "evidence": [{"episode": EP}]}) + "\n```"
    path = _page(bank, "alpha", {}, f"See [[{VALUE}]] and [[beta]].\n\n{fence}")
    _commit(bank)
    _remove(bank)
    text = markdown_parser.parse(path).body
    assert "[[[" not in text and "[[beta]]" in text and "See [removed: password] and" in text
    from api.services.claims import parse_claims

    (claim,) = parse_claims(text, strict=True)
    assert claim.object == "[removed: password]"


def test_an_old_yaml_fence_is_rewritten_by_its_one_encoder_and_still_parses(bank):
    _ep(bank)
    fence = f"```claims\n- id: c1\n  subject: alpha\n  predicate: login\n  object: {VALUE}\n```"
    path = _page(bank, "alpha", {}, f"Prose.\n\n{fence}")
    _commit(bank)
    _remove(bank)
    from api.services.claims import parse_claims

    (claim,) = parse_claims(markdown_parser.parse(path).body, strict=True)
    assert claim.object == "[removed: password]"


def test_a_ledger_line_is_json_after(bank):
    _ep(bank)
    page = _page(bank, "alpha", {}, "Prose.")
    ledger = claims_ledger.path_for(page)
    ledger.write_text(json.dumps({"id": "c1", "object": VALUE}) + "\n" + json.dumps({"id": "c2", "object": "fine"}) + "\n")
    _commit(bank)
    _remove(bank)
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert rows == [{"id": "c1", "object": "[removed: password]"}, {"id": "c2", "object": "fine"}]


def test_a_file_that_does_not_parse_is_left_as_it_was_and_counted(bank):
    _ep(bank)
    (bank / "inbox" / "broken.yaml").write_text(f"a: [unclosed {VALUE}\n")
    _commit(bank)
    out = _remove(bank)
    assert (bank / "inbox" / "broken.yaml").read_text() == f"a: [unclosed {VALUE}\n" and out["still_found"] == 1


def test_a_key_field_is_never_rewritten_and_is_counted(bank):
    _ep(bank)
    path = _page(bank, "alpha", {"id": VALUE}, "Prose.")
    _commit(bank)
    out = _remove(bank)
    assert markdown_parser.parse(path).frontmatter["id"] == VALUE and out["still_found"] == 1


def test_sweep_written_leaves_the_file_parseable(bank):
    ep = {"id": EP, "content": f"user: my password is {VALUE}"}
    path = _page(bank, "alpha", {"summary": f"It is {VALUE}"}, f"Prose {VALUE}")
    assert sf.sweep_written(bank, [ep], ["entities/alpha.md"]) == 1
    fm = markdown_parser.parse(path).frontmatter
    assert fm["summary"] == "It is [removed]" and VALUE not in path.read_text()


# ---- item 8: a wrong alarm never rewrites the bank


def test_a_common_word_stays_on_a_page_with_no_tie_and_on_a_tied_line_that_does_not_speak_of_a_secret(bank):
    _ep(bank, EP, "user: mi contraseña es guatemala.\nuser: el viaje a guatemala fue lindo")
    other = _page(bank, "viaje", {}, "The trip to guatemala. See [[guatemala]].")
    tied = _page(bank, "alpha", {}, f"Cited in {EP}. The trip to guatemala.\nThe password was guatemala.")
    _commit(bank)
    before = other.read_bytes()
    out = _remove(bank)
    assert out["removed"] == 1
    assert other.read_bytes() == before
    text = markdown_parser.parse(tied).body
    assert "The trip to guatemala." in text and "The password was [removed: password]." in text
    body = markdown_parser.parse(bank / "episodes" / f"{EP}.md").body
    assert "el viaje a guatemala fue lindo" in body and "contraseña es [removed: password]" in body


def test_a_distinctive_value_is_its_own_tie(bank):
    _ep(bank)
    page = _page(bank, "untied", {}, f"Nothing cites it, but {VALUE} is here.")
    _commit(bank)
    _remove(bank)
    assert VALUE not in page.read_text()


def test_no_file_without_a_value_is_rewritten(bank):
    _ep(bank)
    path = bank / "entities" / "alpha.md"
    path.write_text("---\nname: Alpha\ntype:   concept\n---\nProse, oddly formatted   \n")
    _commit(bank)
    before = path.read_bytes()
    _remove(bank)
    assert path.read_bytes() == before


# ---- item 9: never the only copy


def test_a_conversation_never_committed_is_committed_before_a_word_changes(bank):
    _ep(bank, processed=False, processed_by=None)
    out = _remove(bank)
    assert out["removed"] == 1
    assert VALUE in _git(bank, "log", "-p", "--format=", "--", f"episodes/{EP}.md")
    subjects = _git(bank, "log", "--format=%s").splitlines()
    assert any(s.startswith("Older version kept before a removal") for s in subjects)
    assert subjects[0].startswith("Sensitive removal")


def test_a_bank_with_no_history_refuses_and_changes_nothing(tmp_path):
    bank = tmp_path / "bank"
    (bank / "episodes").mkdir(parents=True)
    path = _ep(bank)
    before = path.read_bytes()
    with pytest.raises(sf.RemovalRefused):
        _remove(bank)
    assert path.read_bytes() == before


def test_a_commit_that_will_not_take_refuses_and_changes_nothing(bank, monkeypatch):
    path = _ep(bank, processed=False, processed_by=None)
    before = path.read_bytes()
    from api.services import git_service

    def no(*_a, **_k):
        raise git_service.GitError("no")

    monkeypatch.setattr(git_service, "commit_touched_sync", no)
    with pytest.raises(sf.RemovalRefused):
        _remove(bank)
    assert path.read_bytes() == before


# ---- item 10: exactly what the dry run listed


def test_a_swapped_row_is_refused(bank):
    _ep(bank)
    _ep(bank, "ep_2026-11-02_001", "user: my password is Second9value")
    _commit(bank)
    rows = sf.plan(bank)
    seen = [rows[0]["row"]]
    stamp = sf.plan_stamp(rows[:1])
    _ep(bank, rows[0]["episode"], "user: nothing here any more")
    with pytest.raises(ValueError):
        sf.remove_planned(bank, seen, stamp=stamp)         # same count of rows, not the same row


def test_a_row_that_grew_since_is_refused(bank):
    _ep(bank)
    _commit(bank)
    rows = sf.plan(bank)
    stamp = sf.plan_stamp(rows)
    _ep(bank, EP, f"user: my password is {VALUE}\nuser: my card is 4539 1488 0343 6467")
    with pytest.raises(ValueError):
        sf.remove_planned(bank, [rows[0]["row"]], stamp=stamp)
    assert VALUE in (bank / "episodes" / f"{EP}.md").read_text()


# ---- item 11: every store


def test_every_store_a_value_can_reach(bank):
    _ep(bank)
    (bank / "pending_entities.jsonl").write_text(json.dumps({"name": "alpha", "summary": VALUE, "source_episode": EP}) + "\n")
    (bank / "_index.md").write_text(f"# Index\n- alpha: {VALUE}\n")
    for d, name in (("nudges", "n1.md"), ("clarifications", "c1.md"), ("backlog/alpha", "b1.md")):
        (bank / d).mkdir(parents=True)
        (bank / d / name).write_text(f"---\ntitle: about it\nnote: said {VALUE}\n---\nsaid {VALUE}\n")
    _commit(bank)
    out = _remove(bank)
    for rel in ("pending_entities.jsonl", "_index.md", "nudges/n1.md", "clarifications/c1.md", "backlog/alpha/b1.md"):
        assert VALUE not in (bank / rel).read_text(), rel
    assert out["still_found"] == 0
    assert _git(bank, "status", "--porcelain").strip() == ""             # all of it committed


def test_the_route_rebuilds_the_cursor(bank, monkeypatch):
    from api.routers import inbox as inbox_router
    from api.services import state_dictionary

    _ep(bank)
    _commit(bank)
    called = []

    async def refresh(memory, settings):
        called.append(memory)

    monkeypatch.setattr(state_dictionary, "refresh_admitted", refresh)
    rows = sf.plan(bank)
    settings = SimpleNamespace(memory_path=bank)
    asyncio.run(inbox_router.remove_sensitive({"rows": [r["row"] for r in rows], "plan": sf.plan_stamp(rows)}, settings))
    assert called == [bank]


def test_the_word_index_loses_it_on_the_row_too(bank):
    _ep(bank)
    _commit(bank)
    search_index.rebuild_fresh(bank)
    _remove(bank)
    db = search_index.db_path(bank)
    if db.exists():
        assert VALUE.encode() not in db.read_bytes()


# ---- item 12: a reply still points at its turn


def test_a_reply_keeps_its_turn_after_the_offsets_move(bank):
    first = f"user: my password is {VALUE}\n"
    second = "speaker:Ana: so how was the trip\n"
    third = "speaker:Bob: and something else\n"
    fourth = "speaker:Cid: and more\n"
    fifth = "user: it was fine"
    body = first + second + third + fourth + fifth
    extras = [{"offset": len(first + second + third + fourth), "reply_to": len(first)}]
    path = _ep(bank, EP, body, turn_extras=extras)
    _commit(bank)
    assert len(turn_signals.signals({"turn_extras": extras}, body)) == 1
    _remove(bank)
    parsed = markdown_parser.parse(path)
    (entry,) = parsed.frontmatter["turn_extras"]
    assert parsed.body[entry["reply_to"]:].startswith("speaker:Ana:")
    assert parsed.body[entry["offset"]:].startswith("user: it was fine")
    (signal,) = turn_signals.signals(parsed.frontmatter, parsed.body)
    assert "how was the trip" in signal.line


# ---- a failure in the middle


def test_a_page_that_cannot_be_written_leaves_the_value_findable_and_the_row_standing(bank, monkeypatch):
    path = _ep(bank)
    _ep(bank, "ep_2026-11-02_001", "user: my password is Second9value")
    good_page = _page(bank, "alpha", {}, f"Cited, and {VALUE}.")
    _page(bank, "beta", {}, f"Cited, and {VALUE}.")
    _commit(bank)
    real = markdown_parser.write_document
    def fails_on_beta(target, text):
        if Path(target).name == "beta.md":
            raise OSError("disk full")
        real(target, text)

    monkeypatch.setattr(markdown_parser, "write_document", fails_on_beta)
    out = _remove(bank)
    assert out["failed"] == 1 and out["removed"] == 1 and out["committed"] is True
    assert VALUE in markdown_parser.parse(path).body          # its body is the last thing to go, and has not
    assert "Second9value" not in (bank / "episodes" / "ep_2026-11-02_001.md").read_text()
    assert VALUE not in good_page.read_text()
    assert out["left"] == 1
    assert [r["episode"] for r in sf.plan(bank)] == [EP]      # it still asks
    monkeypatch.setattr(markdown_parser, "write_document", real)
    bank_index.invalidate()
    again = _remove(bank)                                     # and doing it again finishes the job
    assert again["removed"] == 1 and again["left"] == 0 and again["still_found"] == 0
    assert VALUE not in path.read_text()


def test_the_card_keeps_a_row_that_failed_and_says_so(bank, monkeypatch):
    _ep(bank)
    _commit(bank)
    sf.note_read({"filepath": str(bank / "episodes" / f"{EP}.md")}, {"password": 1}, "agent", held={"password": 1})
    bank_index.invalidate()
    report = sf.sync_review(bank)
    assert report.rows == 1
    _commit(bank)
    item = bank / report.paths[0]

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(sf, "remove_episode", boom)
    settings = SimpleNamespace(memory_path=bank, inbox_defer_days=30, litellm_model="m", inbox_stale_after_days=90)
    with pytest.raises(HTTPException) as err:
        asyncio.run(inbox_service.resolve(item.stem, InboxResolveRequest(action="resolve", option_key="remove"), settings))
    assert err.value.status_code == 409 and VALUE not in str(err.value.detail)
    assert item.exists()
    assert VALUE in (bank / "episodes" / f"{EP}.md").read_text()


def test_nothing_in_a_reply_or_a_commit_message_holds_a_value(bank):
    _ep(bank)
    _commit(bank)
    out = _remove(bank)
    assert VALUE not in json.dumps(out)
    assert VALUE not in _git(bank, "log", "--format=%B")
    assert VALUE not in st.REMOVED_MARK


def test_in_scope_matches_the_walk(bank):
    _ep(bank)
    _page(bank, "alpha", {}, "x")
    (bank / "_state.md").write_text("---\nx: 1\n---\n")
    walked = {p.relative_to(bank).as_posix() for p in purge.bank_files(bank)}
    assert "entities/alpha.md" in walked and "_state.md" not in walked and not any(w.startswith("episodes/") for w in walked)
    assert all(purge.in_scope(w) for w in walked)
    assert not purge.in_scope("_state.md") and not purge.in_scope("episodes/x.md") and not purge.in_scope(".awake/x.json")

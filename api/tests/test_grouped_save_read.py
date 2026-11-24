"""Short saves of one origin read together in Stage 1 (G246, ruling 80, Track 3; ``grouped_save_read``).

The switch is off until the saves battery's grouped leg is measured. With it on, up to 25 short background saves of one
origin ride one call; the answer is used only when it lines up exactly, else each save is read alone with the same facts.
Everything #858 established for one save holds per save inside a group. Synthetic text only (`alpha-co`, `example.com`).
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (authorship, engine_errors, entity_extractor, evidence, grouped_save_read, history_index,
                          owner_identity, providers, saved_reading)

TODAY = date(2026, 11, 24)
OWNER = "Alpha Owner"


def _body(k: int, text: str | None = None, *, channel: str = "alex-example", extra: str = "") -> str:
    text = text if text is not None else f"alpha-co-{k} ships alpha-tool-{k} every Friday."
    return (f"# Post {k}\n\n**Source:** url\n**URL:** https://x.com/i/web/status/{k}\n**Site:** x.com\n"
            f"**Channel:** {channel}\n**Saved:** 2026-11-20\n\n## Description\n{text}{extra}")


def _save(k: int, *, origin: str = "x-bookmarks", text: str | None = None, **extra) -> dict:
    return {"id": f"ep_2026-11-20_{k:03d}", "content": _body(k, text), "timestamp": "2026-11-20T10:00:00+00:00",
            "origin": origin, "source": "url", "url": f"https://x.com/i/web/status/{k}",
            authorship.KEY: evidence.SAVE_KIND, **extra}


def _resp(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=payload if isinstance(payload, str) else json.dumps(payload)))])


def _entity(name, type_="tool", **extra):
    return {"name": name, "type": type_, "summary": f"{name} is a thing.", "key_facts": [], "confidence": 0.7, **extra}


def _answer(text: str) -> dict:
    """The ordinary Stage 1 answer for one save written by `_body`: two entities and one relationship quoted from it."""
    found = re.search(r"alpha-co-(\d+)", text)
    if found is None:
        return {"entities": [], "relationships": []}
    k = found.group(1)
    return {"entities": [_entity(f"alpha-co-{k}", "company"), _entity(f"alpha-tool-{k}")],
            "relationships": [{"source": f"alpha-co-{k}", "target": f"alpha-tool-{k}", "label": "ships",
                               "evidence_quote": f"alpha-co-{k} ships alpha-tool-{k} every Friday"}]}


def _blocks(user: str) -> list[str]:
    return re.findall(r"<<<SAVE \d+>>>\n(.*?)\n<<<END SAVE \d+>>>", user, re.S)


class Fake:
    """The model: answers a grouped message with ``group(blocks)`` and a single one with ``single(user)``."""

    def __init__(self, group=None, single=None, error=None):
        self.calls: list[tuple[str, str]] = []
        self.group = group or (lambda blocks: {"results": [{"save": n, **_answer(b)} for n, b in enumerate(blocks, 1)]})
        self.single = single or (lambda user: _answer(user))
        self.error = error

    @property
    def grouped(self) -> list[str]:
        return [u for _s, u in self.calls if self.is_group(u)]

    @property
    def singles(self) -> list[str]:
        return [u for _s, u in self.calls if not self.is_group(u)]

    @staticmethod
    def is_group(user: str) -> bool:
        return bool(re.match(r"\d+ saved items follow\.", user))

    async def __call__(self, **kw):
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        self.calls.append((system, user))
        if self.error is not None and self.is_group(user):
            raise self.error
        if self.is_group(user):
            return _resp(self.group(_blocks(user)))
        return _resp(self.single(user))


def _run(episodes, fake: Fake, *, owner: str | None = OWNER, **kw):
    async def no_sleep(*_a, **_k):
        return None

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), \
            patch.object(entity_extractor.asyncio, "sleep", no_sleep), \
            patch.object(owner_identity, "owner_name", lambda *a, **k: owner):
        return asyncio.run(entity_extractor.extract([dict(e) for e in episodes], Settings(_env_file=None), today=TODAY, **kw))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(grouped_save_read, "ON", True)


def _facts(results) -> dict[str, list]:
    return {r["episode_id"]: [(rel["source"], rel["label"], rel["target"], rel.get("observer"),
                               [e["kind"] for e in rel.get("evidence", [])]) for rel in r["relationships"]]
            for r in results}


# --------------------------------------------------------------------------- #
# the switch and who is grouped
# --------------------------------------------------------------------------- #


def test_the_switch_is_off_so_every_save_is_read_alone():
    assert grouped_save_read.ON is False
    fake = Fake()
    out = _run([_save(k) for k in range(1, 6)], fake)
    assert len(out) == 5 and len(fake.singles) == 5 and not fake.grouped


def test_short_saves_of_one_origin_ride_one_call_and_each_keeps_its_own_facts(on):
    saves = [_save(k) for k in range(1, 9)]
    grouped, alone = Fake(), Fake()
    out = _run(saves, grouped)
    assert len(grouped.calls) == 1 and len(grouped.grouped) == 1 and not grouped.singles
    assert _blocks(grouped.grouped[0]).__len__() == 8
    # The same facts as eight single reads (the grouped answer is the single answers, sent together).
    grouped_save_read.ON = False
    try:
        out_alone = _run(saves, alone)
    finally:
        grouped_save_read.ON = True
    assert len(alone.singles) == 8
    assert _facts(out) == _facts(out_alone)
    for r in out:
        (rel,) = r["relationships"]
        assert rel["observer"] == "external:alex-example" and rel["evidence"][0]["kind"] == "page"
        assert rel["source"] == "alpha-co-" + str(int(r["episode_id"][-3:]))


def test_each_block_carries_its_own_text_and_its_own_date_note(on):
    old = _save(2, text="alpha-co-2 ships alpha-tool-2 every Friday.", posted="2021-03-04")
    fake = Fake()
    _run([_save(1), old, _save(3)], fake)
    blocks = _blocks(fake.grouped[0])
    assert len(blocks) == 3
    assert "alpha-co-1 ships" in blocks[0] and "alpha-co-2 ships" in blocks[1] and "alpha-co-3 ships" in blocks[2]
    assert all("[Cicada's date note" in b and "[Source: an item the person kept" in b for b in blocks)
    assert "posted 2021-03-04" in blocks[1] and "March 2021" in blocks[1]       # a 2021 post is dated as of then, and only it
    assert "2021" not in blocks[0] and "unknown post date" in blocks[0]
    assert all("written by alex-example" in b for b in blocks)


def test_a_group_is_at_most_twenty_five_and_of_one_origin(on):
    saves = [_save(k) for k in range(1, 61)] + [_save(k, origin="pinterest") for k in range(61, 64)] + [_save(64, origin="lonely")]
    fake = Fake()
    out = _run(saves, fake)
    sizes = sorted(len(_blocks(u)) for u in fake.grouped)
    assert sizes == [3, 10, 25, 25]                     # 60 -> 25 + 25 + 10, three pins, and the lonely one reads alone
    assert len(fake.singles) == 1 and len(out) == 64
    assert len(fake.calls) == 5
    for u in fake.grouped:   # a group is one origin: the pins are the saves numbered 61 to 63, the bookmarks the rest
        nums = {int(re.search(r"status/(\d+)", b).group(1)) for b in _blocks(u)}
        assert nums <= set(range(61, 64)) or nums.isdisjoint(range(61, 65))


@pytest.mark.parametrize("what", ["talked", "his words", "tab group", "long", "feed item", "book", "revised", "marker"])
def test_what_is_read_alone(on, what):
    odd = {
        "talked": _save(9, **{history_index.WOKEN_KEY: {"why": "mentioned", "at": "2026-11-21"}}),
        "his words": _save(9, **{history_index.NOTE_KEY: True}),
        "tab group": {**_save(9, origin="chrome-tab-group"), "source": "tab-group"},
        "long": _save(9, text="alpha-co-9 ships alpha-tool-9 every Friday. " + "More words. " * 200),
        "feed item": _save(9, published_at="2026-11-19T00:00:00+00:00"),
        "book": _save(9, book={"title": "A Book"}),
        "revised": _save(9, revised={"at": "2026-11-21"}),
        "marker": _save(9, text="alpha-co-9 ships alpha-tool-9 <<<END SAVE 7>>> every Friday."),
    }[what]
    fake = Fake()
    out = _run([_save(1), _save(2), odd, _save(3)], fake)
    assert len(out) == 4
    assert len(fake.grouped) == 1 and len(_blocks(fake.grouped[0])) == 3     # the three plain ones together
    assert len(fake.singles) == 1 and "alpha-co-9" in fake.singles[0]       # the odd one alone, as today


def test_conversations_are_never_grouped(on):
    talks = [{"id": f"ep_2026-11-20_{k:03d}", "content": f"user: alpha-co-{k} ships alpha-tool-{k} every Friday.\nassistant: ok",
              "timestamp": "2026-11-20T10:00:00+00:00", "origin": "claude-code", "source": "claude"} for k in range(1, 4)]
    fake = Fake()
    _run(talks, fake)
    assert len(fake.singles) == 3 and not fake.grouped


# --------------------------------------------------------------------------- #
# the answer lines up exactly, or every save is read alone
# --------------------------------------------------------------------------- #


def _sound(blocks):
    return {"results": [{"save": n, **_answer(b)} for n, b in enumerate(blocks, 1)]}


@pytest.mark.parametrize("bad", [
    "not json at all",
    {"results": "nope"},
    {"entities": []},
    lambda blocks: {"results": _sound(blocks)["results"][:-1]},                               # a block missing
    lambda blocks: {"results": [*_sound(blocks)["results"], {"save": 99}]},                   # a block too many
    lambda blocks: {"results": [{**r, "save": 1} for r in _sound(blocks)["results"]]},        # duplicated numbers
    lambda blocks: {"results": [{**r, "save": r["save"] - 1} for r in _sound(blocks)["results"]]},   # 0-based
    lambda blocks: {"results": [{**r, "entities": "x"} for r in _sound(blocks)["results"]]},  # a list that is no list
    lambda blocks: {"results": ["x", "y", "z"]},
])
def test_a_malformed_or_misaligned_answer_reads_each_save_alone_with_the_same_facts(on, bad):
    saves = [_save(k) for k in range(1, 4)]
    fake = Fake(group=(lambda blocks: bad(blocks) if callable(bad) else bad))
    out = _run(saves, fake)
    assert len(fake.grouped) == 1 and len(fake.singles) == 3          # one wasted call, then one per save: money, never facts
    reference = Fake()
    grouped_save_read.ON = False
    try:
        expected = _run(saves, reference)
    finally:
        grouped_save_read.ON = True
    assert _facts(out) == _facts(expected) and all(r["relationships"] for r in out)


def test_numbers_as_strings_or_out_of_order_are_matched_to_their_own_save(on):
    def reply(blocks):
        rows = [{**_answer(b), "save": str(n)} for n, b in enumerate(blocks, 1)]
        return {"results": list(reversed(rows))}
    out = _run([_save(1), _save(2), _save(3)], Fake(group=reply))
    for r in out:
        k = r["episode_id"][-1]
        (rel,) = r["relationships"]
        assert rel["source"] == f"alpha-co-{k}"       # each save got its own block back, never a neighbour's


def test_a_save_with_nothing_in_it_has_an_empty_block_and_is_still_filed(on):
    def reply(blocks):
        return {"results": [{"save": 1, **_answer(blocks[0])}, {"save": 2}, {"save": 3, **_answer(blocks[2])}]}
    fake = Fake(group=reply)
    out = _run([_save(1), _save(2), _save(3)], fake)
    assert len(fake.calls) == 1 and len(out) == 3
    by = {r["episode_id"][-1]: r for r in out}
    assert by["2"]["entities"] == [] and by["1"]["relationships"] and by["3"]["relationships"]


# --------------------------------------------------------------------------- #
# evidence is located only in the save it came from
# --------------------------------------------------------------------------- #


def test_a_quote_lifted_from_a_neighbour_is_never_located_in_this_save(on):
    def reply(blocks):
        rows = [{"save": n, **_answer(b)} for n, b in enumerate(blocks, 1)]
        # block 1 states its fact with a quote that only save 2 holds
        rows[0]["relationships"][0]["evidence_quote"] = "alpha-co-2 ships alpha-tool-2 every Friday"
        return {"results": rows}
    out = _run([_save(1), _save(2)], Fake(group=reply))
    one, two = (next(r for r in out if r["episode_id"].endswith(s)) for s in ("001", "002"))
    (lifted,) = one["relationships"]
    assert [e["kind"] for e in lifted["evidence"]] == ["reasoning"]                   # not located: filed as inference
    assert lifted["source"] == "alpha-co-1"                                            # the claim is still written
    assert lifted["observer"] == "external:alex-example"                              # and it is still its author's
    assert two["relationships"][0]["evidence"][0]["kind"] == "page"                  # its true owner located it


def test_the_same_words_in_two_saves_are_located_in_each_own_text(on):
    text = "alpha-co-7 ships alpha-tool-7 every Friday."
    saves = [_save(7, text=text), {**_save(7, text=text), "id": "ep_2026-11-20_008"}]
    out = _run(saves, Fake())
    starts = {r["episode_id"]: r["relationships"][0]["evidence"][0] for r in out}
    for ep_id, ev in starts.items():
        body = next(s["content"] for s in saves if s["id"] == ep_id)
        assert ev["kind"] == "page" and body[ev["start"]:ev["end"]] == "alpha-co-7 ships alpha-tool-7 every Friday"


# --------------------------------------------------------------------------- #
# what #858 established for one save holds per save inside a group
# --------------------------------------------------------------------------- #


def test_nothing_lands_on_the_owners_page_no_question_and_the_entity_cap_hold_per_save(on):
    def reply(blocks):
        rows = []
        for n, b in enumerate(blocks, 1):
            row = _answer(b)
            row["entities"] += [_entity(OWNER, "person", key_facts=["I love alpha-tool"]), *[_entity(f"extra-{n}-{j}") for j in range(12)]]
            row["entities"][0]["ask_person"] = "is this still true?"
            row["relationships"].append({"source": OWNER, "target": row["entities"][1]["name"], "label": "uses",
                                         "evidence_quote": "alpha-tool"})
            rows.append({"save": n, **row})
        return {"results": rows}
    out = _run([_save(1), _save(2)], Fake(group=reply))
    for r in out:
        names = {e["name"] for e in r["entities"]}
        assert OWNER not in names                                                       # nothing on the owner's page
        assert len(names) <= saved_reading.MAX_ENTITIES                                 # the entity cap, per save
        assert all("ask_person" not in e for e in r["entities"])                        # a save raises no question
        assert not any(OWNER in (rel["source"], rel["target"]) for rel in r["relationships"])


def test_a_saves_own_date_decides_its_claims_inside_a_group(on):
    saves = [_save(1, posted="2021-03-04"), _save(2)]
    out = _run(saves, Fake())
    by = {r["episode_id"][-1]: r for r in out}
    assert by["1"]["relationships"][0]["source_episode_timestamp"].startswith("2021-03-04")     # its post day, not the save day
    assert by["2"]["relationships"][0]["source_episode_timestamp"].startswith("2026-11-20")
    assert all(r.get(entity_extractor.SAVED_KEY) for r in out)


def test_a_save_with_a_sensitive_value_is_held_back_per_save_and_reported_before_the_call(on):
    card = "4539 1488 0343 6467"
    # A save's page text is never scanned (it is the page's); a section of the person's own words is.
    saves = [_save(1), {**_save(2), "content": _body(2, extra=f"\n\n## Saved because\nmy card is {card}")}, _save(3)]
    order: list[str] = []
    fake = Fake()
    real_call = fake.__call__

    async def tracing(**kw):
        order.append("call")
        return await real_call(**kw)

    flagged: list[str] = []

    def on_sensitive(ep, kinds, engine, held):
        order.append("flag")
        flagged.append(ep["id"])

    async def no_sleep(*_a, **_k):
        return None

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: tracing), \
            patch.object(entity_extractor.asyncio, "sleep", no_sleep), \
            patch.object(owner_identity, "owner_name", lambda *a, **k: OWNER):
        out = asyncio.run(entity_extractor.extract([dict(s) for s in saves], Settings(_env_file=None), today=TODAY,
                                                   on_sensitive=on_sensitive))
    assert flagged == ["ep_2026-11-20_002"] and order == ["flag", "call"]            # only that save, before the send
    assert len(out) == 3 and len(fake.grouped) == 1
    assert "0343" not in fake.grouped[0] and "6467" not in fake.grouped[0]            # the value never reached the model
    assert "alpha-co-1" in fake.grouped[0] and "alpha-co-3" in fake.grouped[0]


def test_per_save_callbacks_still_fire_for_every_save(on):
    started, read, done, ticks = [], [], [], []
    fake = Fake()
    out = _run([_save(k) for k in range(1, 5)], fake, on_episode_started=lambda e: started.append(e["id"]),
               on_episode_read=lambda e: read.append(e["id"]), on_episode_done=lambda e: done.append(e["id"]),
               progress_callback=lambda: ticks.append(1))
    ids = [f"ep_2026-11-20_{k:03d}" for k in range(1, 5)]
    assert sorted(started) == sorted(read) == sorted(done) == ids and len(ticks) == 4 and len(out) == 4


# --------------------------------------------------------------------------- #
# stops, errors, the limit: still counted per save, nothing deadlocks
# --------------------------------------------------------------------------- #


def test_a_stop_before_the_call_sends_nothing_and_skips_every_save(on):
    fake, skipped = Fake(), []
    out = _run([_save(k) for k in range(1, 4)], fake, stop_check=lambda: True, on_episode_skipped=lambda e: skipped.append(e["id"]))
    assert out == [] and not fake.calls and len(skipped) == 3


def test_the_spending_line_skips_each_save_and_fails_none(on):
    fake, skipped, failed = Fake(error=engine_errors.SpendLimitReached("limit")), [], []
    out = _run([_save(k) for k in range(1, 4)], fake, on_episode_skipped=lambda e: skipped.append(e["id"]),
               on_episode_failed=lambda e, x: failed.append(e["id"]))
    assert out == [] and len(skipped) == 3 and not failed and len(fake.calls) == 1


def test_an_engines_own_trouble_is_each_saves_failure_as_with_a_single_read(on):
    fake, failed = Fake(error=engine_errors.EngineThrottled("slow down")), []
    out = _run([_save(k) for k in range(1, 4)], fake, on_episode_failed=lambda e, x: failed.append((e["id"], type(x).__name__)))
    assert out == [] and len(failed) == 3 and {n for _i, n in failed} == {"EngineThrottled"}
    assert len(fake.calls) == 1                         # one call, not three: the throttle is the engine's, not a save's


def test_a_refused_group_is_read_alone_so_one_save_cannot_cost_the_rest(on):
    fake = Fake(error=engine_errors.EngineRefused("declined"))
    out = _run([_save(k) for k in range(1, 4)], fake)
    assert len(out) == 3 and len(fake.grouped) == 1 and len(fake.singles) == 3


def test_a_timeout_twice_is_read_alone_and_a_transient_one_is_retried_once(on):
    fake = Fake(error=engine_errors.EngineTimeout("slow"))
    out = _run([_save(k) for k in range(1, 4)], fake)
    assert len(out) == 3 and len(fake.grouped) == 2 and len(fake.singles) == 3        # tried twice, then alone

    state = {"n": 0}

    class Flaky(Fake):
        async def __call__(self, **kw):
            if self.is_group(kw["messages"][1]["content"]):
                state["n"] += 1
                if state["n"] == 1:
                    raise engine_errors.EngineTimeout("slow")
            return await super().__call__(**kw)
    flaky = Flaky()
    out = _run([_save(k) for k in range(1, 4)], flaky)
    assert len(out) == 3 and not flaky.singles and state["n"] == 2


def test_a_cancel_stops_a_save_that_has_not_started_and_the_rest_still_read_together(on):
    seen = {"n": 0}

    def cancel():
        seen["n"] += 1
        return seen["n"] == 2                      # the second save's pre-check
    fake = Fake()
    out = _run([_save(k) for k in range(1, 5)], fake, cancel_check=cancel)
    assert len(out) == 3 and len(fake.grouped) == 1 and len(_blocks(fake.grouped[0])) == 3


def test_more_groups_than_slots_do_not_deadlock(on):
    saves = [_save(k, origin=f"origin-{k % 14}") for k in range(1, 15)] + [_save(k, origin=f"origin-{k % 14}") for k in range(15, 29)]
    fake = Fake()
    out = _run(saves, fake)
    assert len(out) == 28 and len(fake.grouped) == 14 and not fake.singles


def test_a_save_that_turns_out_to_need_its_own_read_leaves_the_group_without_holding_it_up(on):
    # more than one chunk is impossible for an eligible save, so it is a book's marks after the plan: simulate by a revision
    fake = Fake()
    saves = [_save(1), _save(2), _save(3)]
    with patch.object(grouped_save_read, "eligible", lambda ep: True):
        saves[1] = {**saves[1], "content": _body(2) + "\n\n" + "x" * 13_000}        # two chunks: it reads alone
        out = _run(saves, fake)
    assert len(out) == 3 and len(fake.grouped) == 1 and len(_blocks(fake.grouped[0])) == 2


# --------------------------------------------------------------------------- #
# the stages around it
# --------------------------------------------------------------------------- #


def test_a_batch_of_background_saves_alone_skips_the_skills_call_and_only_when_on(monkeypatch):
    ds = SimpleNamespace(background_ids=frozenset({"a", "b"}))
    only = SimpleNamespace(ds=ds, only_ids=["a", "b"])
    mixed = SimpleNamespace(ds=ds, only_ids=["a", "c"])
    assert grouped_save_read.saves_only_batch(only) is False                    # off
    monkeypatch.setattr(grouped_save_read, "ON", True)
    assert grouped_save_read.saves_only_batch(only) is True
    assert grouped_save_read.saves_only_batch(mixed) is False
    assert grouped_save_read.saves_only_batch(None) is False
    assert grouped_save_read.saves_only_batch(SimpleNamespace(ds=ds, only_ids=[])) is False


def test_the_episode_loader_carries_the_mark_of_a_save_he_talked_about(tmp_path):
    from api.services import markdown_parser, sleep_cycle

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    fm = {"id": "ep_2026-11-20_001", "source": "url", "origin": "x-bookmarks", "url": "https://x.com/i/web/status/1",
          "media_entity_id": "media-a", "timestamp": "2026-11-20T10:00:00+00:00", "processed": False,
          history_index.WOKEN_KEY: {"why": "mentioned", "at": "2026-11-21"}}
    markdown_parser.write(memory / "episodes" / "ep_2026-11-20_001.md", fm, _body(1))
    (ep,) = sleep_cycle._get_unprocessed_episodes(memory)
    assert ep[history_index.WOKEN_KEY] and not grouped_save_read.eligible(ep)


def test_no_new_stage_name_is_needed():
    """Grouped calls are Stage 1's own (`extraction`), so the line, the ledger and the model tier are the ones already there."""
    from api.services import sleep_spend

    assert "extraction" in sleep_spend.LINE_STAGES
    assert "stage=stage" in __import__("inspect").getsource(entity_extractor._extract_group)


def test_align_reads_numbers_by_the_one_shared_rule():
    rows = [{"save": 2, "entities": [{"name": "b"}]}, {"save": 1}]
    out = grouped_save_read.align({"results": rows}, 2)
    assert out == [{"entities": [], "relationships": [], "values": []}, {"entities": [{"name": "b"}], "relationships": [], "values": []}]
    assert grouped_save_read.align({"results": rows}, 3) is None
    assert grouped_save_read.align([], 1) is None


# --------------------------------------------------------------------------- #
# the drain: a batch of background saves alone may hold fifty and skips the skills call
# --------------------------------------------------------------------------- #


def _drained(tmp_path, monkeypatch, *, on: bool):
    from drain_harness import install, seed_bank, settings
    from api.services import bank_index, markdown_parser, sleep_cycle

    monkeypatch.setattr(grouped_save_read, "ON", on)
    bank_index.invalidate()
    rig = install(monkeypatch, engine_label="claude-cli")   # a plan: no spending line to size the batch
    skill_calls: list[int] = []

    async def spy(changes, *_a, **_k):
        skill_calls.append(len(changes))
        return []

    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", spy)

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "mcp", "session_id": "ses_one"}, "user: a conversation")
        for k in range(60):
            eid = f"ep_2026-11-20_{k:03d}"
            markdown_parser.write(
                memory / "episodes" / f"{eid}.md",
                {"id": eid, "timestamp": "2026-11-20T10:00:00+00:00", "processed": False, "source": "bookmark",
                 "origin": "chrome-bookmark", "url": f"https://example.com/{eid}", "media_entity_id": f"media-{eid}",
                 "title": f"Title {eid}", "saved_at": "2026-11-20"}, "# A title\n\n## Description\nwords")

    memory = seed_bank(tmp_path, [], extra=extra)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=25), "sleep_grouped", user_triggered=True,
                                drain=True))
    return rig, skill_calls


def test_a_batch_of_background_saves_alone_holds_fifty_and_skips_skills_when_on(tmp_path, monkeypatch):
    rig, skills = _drained(tmp_path, monkeypatch, on=True)
    assert [len(b) for b in rig.extract_batches] == [25, 36]        # the first holds the conversation; the second is saves alone
    assert len(skills) == 1                                            # only the batch with a conversation looked for skills


def test_the_same_night_with_the_switch_off_is_what_it_was(tmp_path, monkeypatch):
    rig, skills = _drained(tmp_path, monkeypatch, on=False)
    assert [len(b) for b in rig.extract_batches] == [25, 25, 11]
    assert len(skills) == 3

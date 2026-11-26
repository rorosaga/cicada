"""More worlds a Sleep settle (or an undo of one) runs in, for the gate and the restore tests (`settle_guard`, G98).

Each builder takes a scratch bank (the ``memory`` fixture of ``test_settle_guard``: a git repo with an owner page) and returns
``(settle, pages the settle writes)``: ``settle()`` runs it with nothing stubbed and answers whether it landed. Synthetic
banks, invented names, a scripted engine: no network.

The families are the branches of ``inbox_tend.apply`` (a retirement, a normalization, the page-locked resolver's merge, reject,
archive, keep, resolve, dismiss and answer actions, a nickname) and of ``inbox_tend.undo`` (the plain reopen, an alias, a join,
a label map). ``test_settle_guard_gate`` runs every one of them with its commit stopped and checks that every file the settle
changed was reported by its writer.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from api.services import design_refs, inbox_tend, markdown_parser, same_name_doubts
from api.services.claims import Claim, Evidence, write_claims
from api.tests import test_alias_collisions as ac
from api.tests import test_inbox_tend as ti
from api.tests import test_looks_polish as lp

#: A real PNG (the Looks fixtures' own): the bytes a person's uploaded picture and a look's screenshot hold.
PNG = lp._png(32, 32)


def _settle_one(memory: Path, d, **kw):
    def settle() -> bool:
        d.fingerprint = (memory / "inbox" / f"{d.item_id}.md").read_bytes()
        return asyncio.run(ti.inbox_tend.apply(memory, ti._Settings(memory), d, **kw))

    return settle


def _tend(memory: Path, fn):
    def settle() -> bool:
        return asyncio.run(inbox_tend.tend(memory, ti._Settings(memory), episodes=[], run_policy=True, llm_fn=fn)).settled == 1

    return settle


def decay_archive(memory):
    """A one-off page archived: the page and the question's record."""
    ti._entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    ti._item(memory, "inbox-001", kind="decay", entity_id="example-gadget", entity_name="Example Gadget")
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "one_off"
    return _settle_one(memory, d), ["entities/example-gadget.md"]


def decay_keep(memory):
    """The decay judge keeps a live page (``keep_active``): the page and the record."""
    ti._entity(memory, "example-gadget", type="tool", status="decaying", source_episodes=["ep_2026-05-01_001", "ep_2026-06-01_001"])
    ti._item(memory, "inbox-001", kind="decay", entity_id="example-gadget", entity_name="Example Gadget")
    ti._commit(memory)
    fn = ti._judge_fn({"verdict": "keep", "confidence": 0.95, "reason": "still live"})
    return _tend(memory, fn), ["entities/example-gadget.md"]


def conflict_newest(memory):
    """The newest dated statement settles a conflict: the page's claims are closed through the person's own writer."""
    ti._conflict_page(memory)
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "newest_evidence"
    return _settle_one(memory, d), ["entities/tool-a.md"]


def conflict_dismissed(memory):
    """A multi-valued conflict keeps every value: the ``dismiss`` action."""
    claims = [Claim(id=f"clm_{k}", text="x", subject="tool-a", predicate="uses", object=k, valid_from="2026-05-01",
                    recorded_at="2026-05-01") for k in ("alpha-lib", "beta-lib")]
    ti._entity(memory, "tool-a", type="tool", status="active", body=write_claims("## Summary\nA.\n", claims))
    ti._item(memory, "inbox-001", kind="conflict", entity_id="tool-a", predicate="uses",
             options=[{"key": "a", "label": "alpha-lib", "claim_id": "clm_alpha-lib"},
                      {"key": "b", "label": "beta-lib", "claim_id": "clm_beta-lib"}])
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "multi_valued"
    return _settle_one(memory, d), ["entities/tool-a.md"]


def conflict_ledger(memory):
    """A conflict on a page whose claims live in its ledger: closing one moves lines between the page and the ledger."""
    older = Claim(id="clm_old", text="Tool A runs on alpha-os", subject="tool-a", predicate="takes-place-in", object="alpha-os",
                  valid_from="2026-05-01", recorded_at="2026-05-01", evidence=[Evidence(episode="ep_2026-05-01_001", kind="user")])
    newer = Claim(id="clm_new", text="Tool A runs on beta-os", subject="tool-a", predicate="takes-place-in", object="beta-os",
                  valid_from="2026-05-01", recorded_at="2026-05-01", evidence=[Evidence(episode="ep_2026-08-03_001", kind="user")])
    from api.services.claims import parse_claims

    many = parse_claims(ti._big_claims("tool-a"))
    ti._entity(memory, "tool-a", type="tool", status="active", body=write_claims("## Summary\nA tool.\n", [older, newer, *many]))
    assert (memory / "entities" / "tool-a.claims.jsonl").exists()
    ti._item(memory, "inbox-001", kind="conflict", entity_id="tool-a", entity_name="Tool A", predicate="takes-place-in",
             question="What does Tool A run on?",
             options=[{"key": "a", "label": "alpha-os", "claim_id": "clm_old"}, {"key": "b", "label": "beta-os", "claim_id": "clm_new"},
                      {"key": "both", "label": "Both"}])
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "newest_evidence"
    return _settle_one(memory, d), ["entities/tool-a.md"]


def normalization_fold(memory):
    """A spelling fold: the claims of every page that used the label, and the label map."""
    ti._entity(memory, "tool-a", type="tool")
    ti._entity(memory, "tool-c", type="tool", body=write_claims("## Summary\nA.\n", [
        Claim(id="clm_x", text="Tool C Built With widgets", subject="tool-c", predicate="Built With", object="widgets",
              valid_from="2026-05-01", recorded_at="2026-05-01")]))
    ti._item(memory, "inbox-001", kind="normalization", entity_id="tool-a", raw_predicate="Built With",
             canonical_predicate="built-with", claim_id="clm_x")
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "spelling_fold"
    return _settle_one(memory, d), ["entities/tool-a.md"]


def normalization_seed_fold(memory):
    """A fold Cicada's own list ships is confirmed in the label map (``_predicates.yaml``) and its claims relabelled."""
    ti._entity(memory, "tool-c", type="tool", body=write_claims("## Summary\nA.\n", [
        Claim(id="clm_x", text="Tool C used widgets", subject="tool-c", predicate="used", object="widgets",
              valid_from="2026-05-01", recorded_at="2026-05-01")]))
    ti._item(memory, "inbox-001", kind="normalization", entity_id="tool-c", raw_predicate="used",
             canonical_predicate="uses", claim_id="clm_x")
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "seed_fold"
    return _settle_one(memory, d), ["entities/tool-c.md"]


def answered_in_conversation(memory):
    """The person's own words answer a conflict: a claim closed the day they said it, the span as evidence."""
    ti._tool_conflict(memory)
    ep = ti._episode(memory, "ep_2026-10-01_001", "user: For the record, Tool A is an agent harness, not an agent itself.\n\n"
                                                  "assistant: Noted.")
    ti._commit(memory)
    fn = ti._fake({"answered": True, "option": "a", "quote": "Tool A is an agent harness, not an agent itself"})

    def settle() -> bool:
        return asyncio.run(inbox_tend.tend(memory, ti._Settings(memory), episodes=[ep], run_policy=False, llm_fn=fn)).settled == 1

    return settle, ["entities/tool-a.md"]


def mention_in_passing(memory):
    """A name said once in passing is dismissed: nothing written about who it is."""
    ti._passing(memory, "inbox-001", "Example Striker", "ep_2026-06-01_001",
                "user: Who scores the most from distance this season?\n\nassistant: Example Striker leads that table.")
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "in_passing"
    return _settle_one(memory, d), []


def nickname(memory):
    """A role-only person is titled by the nickname the person's own words use: its own commit, no settle record."""
    ti._episode(memory, "ep_2026-06-01_001", "user: Nick is coming to dinner, my brother.\n\nassistant: Lovely.")
    ti._entity(memory, "my-brother", type="person", name="My brother", status="active", unnamed=True,
               source_episodes=["ep_2026-06-01_001"])
    ti._item(memory, "inbox-001", kind="clarification", entity_id="my-brother", entity_name="My brother", asks="name",
             title="What is your brother's name?", suggested_classification="person")
    ti._commit(memory)
    d = inbox_tend.Decision("inbox-001", "clarification", inbox_tend.NICKNAME_RULE,
                            {"action": inbox_tend.NICKNAME_ACTION, "answer": "Nick"}, answer="Nick",
                            quote={"episode": "ep_2026-06-01_001", "quote": "Nick"}, model="fake-model")
    return _settle_one(memory, d), ["entities/my-brother.md"]


def _rich_pair(memory, *, people: bool = False):
    """A loser with a ledger, an uploaded picture, a look and an edge, a winner with a ledger, a page that links to the loser."""
    typ = "person" if people else "tool"
    ti._entity(memory, "tool-b", type=typ, name="Tool B", status="active", body=ti._big_claims("tool-b"))
    ti._entity(memory, "tool-bee", type=typ, name="Tool Bee", status="active", body=ti._big_claims("tool-bee"),
               picture={"kind": "upload", "ext": "png"})
    (memory / "assets" / "pictures").mkdir(parents=True)
    (memory / "assets" / "pictures" / "tool-bee.png").write_bytes(PNG)
    ti._entity(memory, "linker", type="concept", status="active", body="## Summary\nUses [[Tool Bee]] a lot.\n")
    (memory / "graph_edges.yaml").write_text("edges:\n- source: linker\n  target: tool-bee\n  label: uses\n")
    design_refs.add_ref(memory, image=PNG, entity="tool-bee", look=([], []))
    ti._item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
             merge_target_hint="tool-b", suggested_classification=typ)
    ti._item(memory, "inbox-002", kind="merge_suggestion", entity_id="tool-b", entity_name="Tool B",
             merge_target_hint="tool-bee", suggested_classification=typ)   # the same question, asked the other way round
    ti._commit(memory)


def rich_merge(memory):
    """The widest merge: two ledgers, the loser's picture and look, a repointed page and edge, a redirect."""
    _rich_pair(memory)
    fn = ti._judge_fn({"verdict": "same", "confidence": 0.97, "reason": "one tool"})
    return _tend(memory, fn), ["entities/tool-b.md", "entities/linker.md"]


def two_signals_join(memory):
    """Two people joined on two independent signals; the loser's other doubt becomes the winner's (``_same_name_doubts.yaml``)."""
    ti._two_signal_pair(memory)
    same_name_doubts.add_pairs(memory, [("tom", "tom-elsewhere")])
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "two_signals"
    return _settle_one(memory, d), ["entities/tomas.md"]


def _which_one_world(memory, conversations: dict[str, str], claims: list[tuple[str, str, str]]):
    """Ruling 83: two people who answer to "Nick" (a brother, a teammate), one held line and its which-one question, on the gate's bank."""
    from api.services import pending_store, same_name, which_one
    from api.tests import test_held_release as hr
    from api.tests import test_which_one_reader as wo

    wo._page(memory, "nick-brother", "Nick Rowe", "person")
    wo._set(memory, "nick-brother", owner_roles=["brother"])
    wo._page(memory, "nick-friend", "Nick Vale", "person")
    friend = memory / "entities" / "nick-friend.md"
    parsed = markdown_parser.parse(friend)
    markdown_parser.write(friend, parsed.frontmatter, parsed.body + "\nWorks at [[acme-labs]].\n")
    wo._page(memory, "acme-labs", "Acme Labs", "company")
    for ep, text in conversations.items():
        wo._episode(memory, ep, text)
    eps = list(conversations)
    pending_store.upsert(memory, pending_store.PendingEntity(
        name="Nick", type="person", description="Nick, said once.", source_episode=eps[0], confidence=0.7, tags=[],
        history_entries=[{"date": "2026-11-20", "event": "Nick came up"}],
        held_claims=[hr._held("nick", p, o, i, ep) for i, (p, o, ep) in enumerate(claims, 1)], heard_in=[{"episode": e} for e in eps]))
    same_name.invalidate()
    path = which_one.raise_question(memory, "Nick", eps[0], ["nick-brother", "nick-friend"], today=wo.TODAY)
    assert path
    ti._commit(memory)
    return memory / path


def which_one_filing(memory):
    """Ruling 83: each conversation of a held nickname filed to the page its own reading named: two pages, their ledgers, the line
    (`pending_entities.jsonl`), one record per page and the question, in one guarded settle per page."""
    from api.tests import test_which_one_file as tw
    from api.tests import test_which_one_reader as wo

    path = _which_one_world(memory, {wo.EP1: tw.BROTHER, wo.EP2: tw.MATE, tw.EP3: tw.BLANK},
                            [("visits", "a-weekend", wo.EP1), ("ships", "the-release", wo.EP2), ("greets", "x", tw.EP3)])
    fn = tw._by_name(tw.BOTH)

    def settle() -> bool:
        return asyncio.run(wo.wr.tend(memory, ti._Settings(memory), fn, today=wo.TODAY, model="haiku")).settled == 2

    return settle, ["entities/nick-brother.md", "entities/nick-friend.md"]


def which_one_closing(memory):
    """The last filing empties the line and closes the question in the same settle: the question is moved to its shelf."""
    from api.services import pending_store
    from api.tests import test_which_one_file as tw
    from api.tests import test_which_one_reader as wo

    path = _which_one_world(memory, {wo.EP1: tw.BROTHER, wo.EP2: tw.MATE}, [("visits", "a-weekend", wo.EP1), ("ships", "the-release", wo.EP2)])
    pending_store.release(memory, ["Nick"])
    pending_store.upsert(memory, pending_store.PendingEntity(
        name="Nick", type="person", description="", source_episode=wo.EP1, confidence=0.7, tags=[], history_entries=[],
        held_claims=[wo._held("nick", "visits", "a-weekend", 1, wo.EP1), wo._held("nick", "ships", "the-release", 2, wo.EP2)],
        heard_in=[{"episode": wo.EP1}, {"episode": wo.EP2}]))
    ti._commit(memory)
    fn = tw._by_name(tw.BOTH)

    def settle() -> bool:
        return asyncio.run(wo.wr.tend(memory, ti._Settings(memory), fn, today=wo.TODAY, model="haiku")).settled == 2

    return settle, ["entities/nick-brother.md", "entities/nick-friend.md"]


def which_one_narrowing(memory):
    """Two conversations nobody could tell: the reader only narrows the question to one conversation (its own file, one settle)."""
    from api.tests import test_which_one_file as tw
    from api.tests import test_which_one_reader as wo

    _which_one_world(memory, {wo.EP1: tw.BLANK, wo.EP2: tw.BLANK.replace("hello again", "hello twice")},
                     [("greets", "everyone", wo.EP1), ("greets", "nobody", wo.EP2)])
    fn = tw._by_name({})

    def settle() -> bool:
        asyncio.run(wo.wr.tend(memory, ti._Settings(memory), fn, today=wo.TODAY, model="haiku"))
        return bool(markdown_parser.parse(next((memory / "inbox").glob("inbox-*.md"))).frontmatter.get("scope_episodes"))

    return settle, []


def which_one_refile(memory):
    """A claim of a conversation filed before, held since: it lands on that verdict with no read (`which_one_file.refile`)."""
    from api.services import pending_store, which_one_file
    from api.services.claims import Claim
    from api.tests import test_which_one_file as tw
    from api.tests import test_which_one_reader as wo

    _which_one_world(memory, {wo.EP1: tw.BROTHER, wo.EP2: tw.MATE}, [("visits", "a-weekend", wo.EP1), ("ships", "the-release", wo.EP2)])
    asyncio.run(wo.wr.tend(memory, ti._Settings(memory), tw._by_name(tw.BOTH), today=wo.TODAY, model="haiku"))
    pending_store.hold(memory, {"nick": [Claim.from_dict(wo._held("nick", "likes", "tea", 7, wo.EP1))]})
    ti._commit(memory)

    def settle() -> bool:
        return which_one_file.refile(memory, today=wo.TODAY.isoformat()).settled == 1

    return settle, ["entities/nick-brother.md"]


FAMILIES = {
    "which_one_filing": which_one_filing,
    "which_one_closing": which_one_closing,
    "which_one_narrowing": which_one_narrowing,
    "which_one_refile": which_one_refile,
    "decay_archive": decay_archive,
    "decay_keep": decay_keep,
    "conflict_newest": conflict_newest,
    "conflict_dismissed": conflict_dismissed,
    "conflict_ledger": conflict_ledger,
    "normalization_fold": normalization_fold,
    "normalization_seed_fold": normalization_seed_fold,
    "answered_in_conversation": answered_in_conversation,
    "mention_in_passing": mention_in_passing,
    "nickname": nickname,
    "rich_merge": rich_merge,
    "two_signals_join": two_signals_join,
}


# --------------------------------------------------------------------------- the undo of each kind of settle


def _undoing(memory, item: str = "inbox-001"):
    def undo() -> bool:
        try:
            inbox_tend.undo_committed(memory, item)
        except Exception:  # noqa: BLE001 — a refused undo: the gate asserts it did not happen
            return False
        return True

    return undo


def undo_retirement(memory):
    from api.tests import test_settle_guard as tg

    settle, _written, _paths = tg._retirement(memory)
    assert settle()
    return _undoing(memory), []


def undo_merge(memory):
    _rich_pair(memory)
    assert _tend(memory, ti._judge_fn({"verdict": "same", "confidence": 0.97, "reason": "one tool"}))()
    return _undoing(memory), ["entities/tool-b.md", "entities/tool-bee.md"]


def undo_normalization(memory):
    settle, _written = normalization_fold(memory)
    assert settle()
    return _undoing(memory), []


def undo_conflict(memory):
    settle, _written = conflict_newest(memory)
    assert settle()
    return _undoing(memory), []


def undo_join(memory):
    """Taking back a join is the person saying they are two people: the pair is kept apart, inside the undo."""
    settle, _written = two_signals_join(memory)
    assert settle()
    return _undoing(memory), []


def undo_alias(memory):
    """Taking back the removal of a name keeps it for good (`wrong_aliases`)."""
    table = ac._labelled(memory)
    asyncio.run(ac.alias_collisions.tend(memory, ac.SimpleNamespace(memory_path=memory), ac.Judge(table)))
    rec = next(p for p in (memory / "inbox" / "settled").glob("*.md")
               if markdown_parser.parse(p).frontmatter["settled"]["rule"] == ac.alias_collisions.APART)
    ac._commit(memory)
    return _undoing(memory, rec.stem), ["entities/lumen-search.md"]


def undo_which_one(memory):
    """Taking one filing of a held nickname back (`which_one_file.undo_committed`): the claims go back to the line, the page loses them,
    the question is told, the record goes."""
    from api.services import which_one_file
    from api.tests import test_which_one_file as tw
    from api.tests import test_which_one_reader as wo

    _which_one_world(memory, {wo.EP1: tw.BROTHER, wo.EP2: tw.MATE, tw.EP3: tw.BLANK},
                     [("visits", "a-weekend", wo.EP1), ("ships", "the-release", wo.EP2), ("greets", "x", tw.EP3)])
    assert asyncio.run(wo.wr.tend(memory, ti._Settings(memory), tw._by_name(tw.BOTH), today=wo.TODAY, model="haiku")).settled == 2
    rec = next(p for p in sorted((memory / "inbox" / "settled").glob("land-*.md"))
               if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-brother")

    def undo() -> bool:
        try:
            which_one_file.undo_committed(memory, rec.stem)
        except Exception:  # noqa: BLE001 - a refused undo: the gate asserts it did not happen
            return False
        return True

    return undo, ["entities/nick-brother.md"]


UNDO_FAMILIES = {
    "undo_which_one": undo_which_one,
    "undo_retirement": undo_retirement,
    "undo_merge": undo_merge,
    "undo_normalization": undo_normalization,
    "undo_conflict": undo_conflict,
    "undo_join": undo_join,
    "undo_alias": undo_alias,
}

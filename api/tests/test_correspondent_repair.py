"""G179 repair — a page that absorbed a texted agent is split back (``correspondent_repair``,
``scripts/repair_correspondent_pages``).

The bad state is made the way it happened, synthetically: an archived ``concept`` page named like the agent, lifted
by a later mention from another conversation (a scheduled run), then a Sleep run from before Stage 2 knew the
correspondent (the marking switched off) puts the agent's conversation on it — its claims, its source, a fact in its
prose, and a claim on another page pointing at it. Then: the dry run counts and writes nothing; ``--apply`` gives the
old page back exactly as its own history had it before the conversation, moves the agent's part to a ``tool`` page
of its own, born active, repoints the other page's claim, in one ``cicada`` commit; a second run is a no-op."""
from __future__ import annotations

import json
import subprocess

import pytest

from api.scripts import repair_correspondent_pages
from api.services import correspondent_repair, correspondents, entity_resolver, markdown_parser
from api.services.claims import Claim, parse_claims, write_claims
from api.tests.test_correspondent_identity import _run_sleep
from api.tests.test_messages_sleep_attribution import MODEL_ANSWER, _conversation, _page
from api.tests.test_sleep_cycle_hold import _bank

BASE_CLAIM = Claim(id="c-concept-1", text="instinct contrasts with learning", subject="instinct",
                   predicate="contrasts-with", object="Learning", object_kind="literal", valid_from="2025-10-19",
                   source_episodes=["ep_2025-10-19_001"])
FACT = "Answers within a minute of a text."


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _concept(memory, **fm):
    markdown_parser.write(
        memory / "entities" / "instinct.md",
        {"name": "Instinct", "type": "concept", "status": "archived", "confidence": 0.0, "created": "2025-10-19",
         "last_referenced": "2025-10-19", "decayed_through": "2025-12-01", "source_episodes": ["ep_2025-10-19_001"],
         "version": 3, **fm},
        write_claims("## Summary\nInstinct is an innate, unlearned pattern of behaviour.", [BASE_CLAIM]))


def _bad_bank(tmp_path, monkeypatch, *, git=True):
    memory = _bank(tmp_path)
    if git:
        _git(memory, "init", "-q")
        _git(memory, "config", "user.email", "test@cicada.local")
        _git(memory, "config", "user.name", "Cicada Test")
    _concept(memory)
    for slug, name, kind in (("alpha-project", "alpha-project", "project"), ("beta-tool", "beta-tool", "tool"),
                             ("gamma-lib", "gamma-lib", "tool")):
        _page(memory, slug, name, kind)
    if git:
        _commit(memory, "seed")
    # A scheduled run lifted it with a mention from another conversation, and charged its decay through the night.
    _concept(memory, status="decaying", confidence=0.374, last_referenced="2026-10-06", decayed_through="2026-10-16",
             source_episodes=["ep_2025-10-19_001", "ep_2026-10-06_001"], version=4)
    if git:
        _commit(memory, "scheduled run")
    before = (memory / "entities" / "instinct.md").read_bytes()
    _conversation(tmp_path, memory)

    answer = json.loads(json.dumps(MODEL_ANSWER))
    answer["entities"][0]["key_facts"] = [FACT]
    answer["relationships"].append({"source": "alpha-project", "target": "Instinct", "label": "is tracked by",
                                    "evidence_quote": "alpha-project launches next week"})
    with monkeypatch.context() as m:
        m.setattr(correspondents, "identity", lambda record: None)   # Stage 2 before the fix: by name alone
        # …and before G227 (#539): an exact title joined its one page whatever its kind, so the `tool` mention
        # landed on the `concept` page. Today that pair goes to the same-title judge and is held, never joined.
        m.setattr(entity_resolver, "_same_title_pick", lambda entity, group: group[0] if len(group) == 1 else None)
        _run_sleep(memory, monkeypatch, answer)
    if git:
        _commit(memory, "Sleep cycle (the bad one)")
    return memory, before


def _claims(memory, page_id):
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{page_id}.md").body)


def test_the_bad_state_is_what_was_measured(tmp_path, monkeypatch):
    memory, _ = _bad_bank(tmp_path, monkeypatch)
    fm = markdown_parser.parse(memory / "entities" / "instinct.md").frontmatter
    assert fm["type"] == "concept" and fm["status"] == "decaying"   # the agent's conversation on the concept
    triples = {(c.subject, c.predicate, c.object) for c in _claims(memory, "instinct")}
    assert ("instinct", "runs-on", "beta-tool") in triples
    assert not (memory / "entities" / "instinct-agent.md").exists()


def test_dry_run_then_apply_then_a_no_op(tmp_path, monkeypatch, capsys):
    memory, _ = _bad_bank(tmp_path, monkeypatch)
    (episode,) = sorted((memory / "episodes").glob("*.md"))
    ep_id = markdown_parser.parse(episode).frontmatter["id"]
    head = _git(memory, "rev-parse", "HEAD")

    # Dry run: counts only, nothing written.
    assert repair_correspondent_pages.main(["--bank", str(memory)]) == 0
    counts = json.loads(capsys.readouterr().out)
    assert (counts["splits"], counts["new_pages"], counts["claims_repointed"]) == (1, 1, 1)
    assert counts["claims_moved"] >= 1 and counts["sources_moved"] == 1 and counts["applied"] is False
    assert "nstinct" not in json.dumps(counts)
    assert _git(memory, "status", "--porcelain") == "" and _git(memory, "rev-parse", "HEAD") == head

    # Refused while Sleep runs: nothing written.
    with pytest.raises(correspondent_repair.SleepRunning):
        correspondent_repair.apply(memory, sleep_running=lambda: True)
    assert _git(memory, "status", "--porcelain") == ""

    plan = correspondent_repair.apply(memory, sleep_running=lambda: False, today="2026-10-16")
    assert plan.committed and len(plan.splits) == 1

    # The old page is what its own history held before the conversation: the scheduled run's state, its own claim.
    old = markdown_parser.parse(memory / "entities" / "instinct.md")
    assert old.frontmatter["type"] == "concept" and old.frontmatter["status"] == "decaying"
    assert float(old.frontmatter["confidence"]) == 0.374
    assert str(old.frontmatter["last_referenced"]) == "2026-10-06"
    assert str(old.frontmatter["decayed_through"]) == "2026-10-16"
    assert old.frontmatter["source_episodes"] == ["ep_2025-10-19_001", "ep_2026-10-06_001"]
    assert [c.id for c in parse_claims(old.body)] == ["c-concept-1"]
    assert FACT not in old.body and "innate, unlearned" in old.body

    # The agent's page: a tool, born active, with the conversation's source, claims (observers as they were) and fact.
    agent = markdown_parser.parse(memory / "entities" / "instinct-agent.md")
    fm = agent.frontmatter
    assert (fm["name"], fm["type"], fm["status"]) == ("Instinct", "tool", "active")
    assert float(fm["confidence"]) >= 0.4 and fm["source_episodes"] == [ep_id]
    assert str(fm["last_referenced"]) == "2026-09-03" and str(fm["created"]) == "2026-09-03"
    assert FACT in agent.body
    moved = {(c.subject, c.predicate, c.object): c for c in parse_claims(agent.body)}
    runs_on = moved[("instinct-agent", "runs-on", "beta-tool")]
    assert runs_on.observer == "external:instinct" and [e.kind for e in runs_on.evidence] == ["assistant"]

    # The other page's claim from the conversation points at the agent now.
    tracked = [c for c in _claims(memory, "alpha-project") if c.predicate == "is-tracked-by"]
    assert tracked and all(c.object == "instinct-agent" for c in tracked)

    # One `cicada` commit, a clean tree.
    message = _git(memory, "log", "-1", "--format=%B")
    assert "trigger: maintenance/correspondent-split" in message and "Cicada-Author: cicada" in message
    assert _git(memory, "rev-list", "--count", f"{head.strip()}..HEAD").strip() == "1"
    assert _git(memory, "status", "--porcelain") == ""

    # A second run finds nothing.
    again = correspondent_repair.apply(memory, sleep_running=lambda: False, today="2026-10-16")
    assert (len(again.splits), again.written, again.committed) == (0, 0, False)
    assert correspondent_repair.survey(memory).counts()["pages_to_split"] == 0


def test_a_page_with_no_history_before_the_conversation_is_counted_not_touched(tmp_path, monkeypatch):
    memory, _ = _bad_bank(tmp_path, monkeypatch, git=False)
    before = (memory / "entities" / "instinct.md").read_bytes()
    plan = correspondent_repair.apply(memory, sleep_running=lambda: False)
    assert plan.counts()["no_history"] == 1 and not plan.splits and plan.written == 0
    assert (memory / "entities" / "instinct.md").read_bytes() == before


def test_a_page_whose_claims_spilled_into_its_ledger_is_split_whole(tmp_path):
    """The real page held the conversation's claims past the fence budget: the ledger goes with the split."""
    from api.services import claims_ledger

    memory = _bank(tmp_path)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _concept(memory)
    _commit(memory, "seed")
    ep = "ep_2026-09-03_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": True, "timestamp": "2026-09-03T10:00:00Z", "conversation": "c" * 16,
                           "correspondent": {"name": "Instinct", "kind": "agent", "decided_by": "person"}},
                          "user: hi\nassistant: hello")
    many = [Claim(id=f"clm-{i:04d}", text=f"Instinct said fact number {i} " + "x" * 300, subject="instinct",
                  predicate="said", object=f"Fact {i}", object_kind="literal", valid_from="2026-09-03",
                  observer="external:instinct", source_episodes=[ep]) for i in range(250)]
    page = memory / "entities" / "instinct.md"
    parsed = markdown_parser.parse(page)
    fm = {**parsed.frontmatter, "source_episodes": [*parsed.frontmatter["source_episodes"], ep], "version": 4}
    markdown_parser.write(page, fm, write_claims(parsed.body, [*parse_claims(parsed.body), *many]))
    assert claims_ledger.path_for(page).exists()
    _commit(memory, "absorbed")

    plan = correspondent_repair.apply(memory, sleep_running=lambda: False, today="2026-10-16")
    assert plan.committed and plan.counts()["claims_moved"] == 250
    assert [c.id for c in parse_claims(markdown_parser.parse(page).body)] == ["c-concept-1"]
    # What stays in the ledger is the page's own (a line the body carries back stays where it was), never the agent's.
    assert not any("clm-" in line for line in claims_ledger.ledger_lines(page))
    agent = memory / "entities" / "instinct-agent.md"
    assert len(parse_claims(markdown_parser.parse(agent).body)) == 250
    assert {c.subject for c in parse_claims(markdown_parser.parse(agent).body)} == {"instinct-agent"}
    assert _git(memory, "status", "--porcelain") == ""
    assert correspondent_repair.apply(memory, sleep_running=lambda: False).written == 0


OTHER_FACT = "Often contrasted with habit."


def test_nothing_outside_the_conversation_moves_or_reverts(tmp_path, monkeypatch):
    """The reviewer's case: after the bad Sleep, a Sleep batch reads an unrelated conversation about the word (a source,
    a fact, a claim, a lift), and the person edits the page (closes a claim, removes a source and an alias, picks a
    picture). Only the agent's conversation leaves; everything else stays exactly as it is."""
    from api.services.claims import strip_claims_block

    memory, _ = _bad_bank(tmp_path, monkeypatch)
    page = memory / "entities" / "instinct.md"
    other = "ep_2026-10-12_001"
    markdown_parser.write(memory / "episodes" / f"{other}.md",
                          {"id": other, "processed": True, "source": "mcp", "timestamp": "2026-10-12T09:00:00Z"},
                          "user: is instinct the same as habit?")
    parsed = markdown_parser.parse(page)
    fm = {**parsed.frontmatter, "source_episodes": [*parsed.frontmatter["source_episodes"], other],
          "status": "active", "confidence": 0.6, "last_referenced": "2026-10-12", "decayed_through": "2026-10-12"}
    later = Claim(id="c-later-1", text="instinct differs from habit", subject="instinct", predicate="differs-from",
                  object="Habit", object_kind="literal", valid_from="2026-10-12", source_episodes=[other])
    prose = strip_claims_block(parsed.body).replace("## Key Facts\n", f"## Key Facts\n- {OTHER_FACT}\n")
    claims = parse_claims(parsed.body)
    for claim in claims:
        if claim.predicate == "runs-on":   # the other conversation backs one of the agent's claims too
            claim.source_episodes = [*claim.source_episodes, other]
    markdown_parser.write(page, fm, write_claims(prose, [*claims, later]))
    _commit(memory, "Sleep cycle 2026-10-16 (batch 1 of 1)")

    parsed = markdown_parser.parse(page)
    fm = {**parsed.frontmatter,
          "sources_removed": [{"ref": "https://example.com/x", "predicate": "", "by": "user", "on": "2026-10-16"}],
          "aliases_removed": [{"alias": "Gut feeling", "by": "user", "on": "2026-10-16"}],
          "picture": {"source": "user", "file": "pictures/x.png"}}
    claims = parse_claims(parsed.body)
    for claim in claims:
        if claim.id == "c-concept-1":
            claim.valid_to = "2026-10-16"
    markdown_parser.write(page, fm, write_claims(strip_claims_block(parsed.body), claims))
    _commit(memory, "Inbox resolution: the person's edits")
    before = markdown_parser.parse(page)
    (episode,) = [p for p in (memory / "episodes").glob("*.md") if p.stem != other]
    conv_ep = markdown_parser.parse(episode).frontmatter["id"]

    plan = correspondent_repair.apply(memory, sleep_running=lambda: False, today="2026-10-16")
    counts = plan.counts()
    assert (counts["splits"], counts["prose_left"], counts["prose_moved"], counts["claims_copied"]) == (1, 1, 0, 1)

    after = markdown_parser.parse(page)
    fm_before, fm_after = before.frontmatter, after.frontmatter
    # The person's fields and every key the conversation did not set are exactly as they were.
    for key in ("sources_removed", "aliases_removed", "picture", "type", "name", "aliases", "tags", "related"):
        assert fm_after.get(key) == fm_before.get(key), key
    # Its life is its own remaining history's: the later conversation's lift stands, its day is the last mention.
    assert (fm_after["status"], float(fm_after["confidence"]), str(fm_after["last_referenced"])) == \
        ("active", 0.6, "2026-10-12")
    assert fm_after["source_episodes"] == [e for e in fm_before["source_episodes"] if e != conv_ep]
    # Claims keep their current state; only the agent's conversation's leave.
    kept = {c.id: c for c in parse_claims(after.body)}
    assert kept["c-concept-1"].valid_to == "2026-10-16" and "c-later-1" in kept
    shared = [c for c in kept.values() if c.predicate == "runs-on"]
    assert len(shared) == 1 and set(shared[0].source_episodes) == {conv_ep, other}   # also backed elsewhere: stays
    assert all(conv_ep not in c.source_episodes for c in kept.values() if c.predicate != "runs-on")
    # The prose was touched by more than the conversation: left as it is, the other conversation's fact included.
    assert OTHER_FACT in after.body and strip_claims_block(after.body) == strip_claims_block(before.body)

    agent = markdown_parser.parse(memory / "entities" / "instinct-agent.md")
    assert agent.frontmatter["type"] == "tool" and agent.frontmatter["source_episodes"] == [conv_ep]
    assert OTHER_FACT not in agent.body and "Instinct runs on beta-tool" in agent.body   # its facts from its claims
    assert {c.subject for c in parse_claims(agent.body)} == {"instinct-agent"}
    assert all(set(c.source_episodes) == {conv_ep} for c in parse_claims(agent.body))
    assert "runs-on" in {c.predicate for c in parse_claims(agent.body)}                  # its copy, the agent's part

    assert correspondent_repair.apply(memory, sleep_running=lambda: False).written == 0


def test_a_page_that_only_lists_the_name_as_an_alias_is_not_split(tmp_path, monkeypatch):
    memory, _ = _bad_bank(tmp_path, monkeypatch)
    page = memory / "entities" / "instinct.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "name": "Gut sense", "aliases": ["Instinct"]}, parsed.body)
    _commit(memory, "rename")
    counts = correspondent_repair.survey(memory).counts()
    assert (counts["splits"], counts["skipped_alias"]) == (0, 1)

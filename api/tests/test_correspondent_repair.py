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
from api.services import correspondent_repair, correspondents, markdown_parser
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

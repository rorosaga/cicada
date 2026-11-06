"""A conflict's second value lives only in the question until it is answered (`claim_reconciler._conflict_nudge`):
an answer that keeps it has to write it, or the click loses what the person just said was true."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import date
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import claim_reconciler, inbox_generator, inbox_service, markdown_parser
from api.services.claims import Claim, parse_claims, write_claims


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.litellm_disambiguation_model = ""
        self.consolidation_model = ""
        self.llm_mode = "byok"

    @property
    def effective_consolidation_model(self) -> str:
        return self.litellm_model


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _claim(cid: str, obj: str, day: str, episode: str) -> Claim:
    return Claim(id=cid, text=f"Alpha lives in {obj}", subject="alpha", predicate="lives-in", object=obj,
                 observer="owner", context="general", source_trust="user_stated", confidence=0.7,
                 valid_from=day, recorded_at=day, source_episodes=[episode])


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    async def _fake(**kwargs):
        return f"{kwargs['new_description']}"

    monkeypatch.setattr("api.services.conflict_resolver._synthesize_entity_update", _fake)


@pytest.fixture
def repo(tmp_path) -> Path:
    """The page holds the first value; the second reached only the question, the way the reconciler leaves it."""
    root = tmp_path / "memory"
    (root / "entities").mkdir(parents=True)
    (root / "inbox").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@cicada.local")
    _git(root, "config", "user.name", "Cicada Test")
    on_page = _claim("clm_page", "lisbon", "2026-02-01", "ep_2026-02-01_001")
    off_page = _claim("clm_off", "porto", "2026-02-01", "ep_2026-02-01_002")
    markdown_parser.write(
        root / "entities" / "alpha.md",
        {"name": "Alpha", "type": "person", "status": "active", "confidence": 0.8, "created": "2026-01-01",
         "last_referenced": "2026-02-01", "decay_rate": 0.05, "source_episodes": [], "tags": [], "related": [],
         "version": 1},
        write_claims("Alpha is a person.\n", [on_page]),
    )
    inbox_generator.write_claim_nudges([claim_reconciler._conflict_nudge(on_page, off_page, "2026-03-01")], root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _item(repo: Path) -> str:
    return next((repo / "inbox").glob("*.md")).stem


def _claims(repo: Path) -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(repo / "entities" / "alpha.md").body)}


def _by_object(repo: Path) -> dict[str, Claim]:
    return {c.object: c for c in _claims(repo).values()}


def _answer(repo: Path, key: str) -> None:
    asyncio.run(inbox_service.resolve(_item(repo), InboxResolveRequest(action="resolve", optionKey=key), _Settings(repo)))


def test_both_keeps_the_value_that_was_only_in_the_question(repo):
    assert set(_by_object(repo)) == {"lisbon"}  # the setup: the second value is not on the page
    _answer(repo, "both")
    held = _by_object(repo)
    assert set(held) == {"lisbon", "porto"}
    assert held["lisbon"].valid_to is None and held["porto"].valid_to is None


def test_picking_the_value_off_the_page_keeps_it(repo):
    _answer(repo, "b")
    held = _by_object(repo)
    assert held["porto"].valid_to is None
    assert held["lisbon"].valid_to == date.today().isoformat()


def test_both_on_a_question_with_no_claims_keeps_both_answers(repo):
    item = next((repo / "inbox").glob("*.md"))
    parsed = markdown_parser.parse(item)
    parsed.frontmatter.update(predicate="description", options=[
        {"key": "a", "label": "Still in the beta"},
        {"key": "b", "label": "Already in production"},
        {"key": "both", "label": "Both are true (different contexts)"},
    ])
    markdown_parser.write(item, parsed.frontmatter, parsed.body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "description question")
    _answer(repo, "both")
    page = (repo / "entities" / "alpha.md").read_text()
    assert "Still in the beta" in page and "Already in production" in page


def _make_multi(repo: Path) -> None:
    item = next((repo / "inbox").glob("*.md"))
    parsed = markdown_parser.parse(item)
    parsed.frontmatter["predicate"] = "works-at"
    markdown_parser.write(item, parsed.frontmatter, parsed.body)
    page = repo / "entities" / "alpha.md"
    entity = markdown_parser.parse(page)
    claims = parse_claims(entity.body)
    for claim in claims:
        claim.predicate = "works-at"
    markdown_parser.write(page, entity.frontmatter, write_claims(entity.body, claims))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "multi-valued")


def _dismiss(repo: Path) -> None:
    asyncio.run(inbox_service.resolve(_item(repo), InboxResolveRequest(action="dismiss"), _Settings(repo)))


def test_dismissing_a_multi_valued_question_keeps_the_value_only_in_it(repo):
    _make_multi(repo)
    _dismiss(repo)
    held = _by_object(repo)
    assert set(held) == {"lisbon", "porto"} and held["porto"].valid_to is None
    # A dismissal says nothing about the value: it stays what it was, an extraction.
    assert held["porto"].source_trust == "agent_extracted"
    assert not list((repo / "inbox").glob("*.md"))
    assert "porto" in _git(repo, "show", "HEAD:entities/alpha.md")


def test_dismissing_a_multi_valued_question_touches_no_page_when_every_value_is_held(repo):
    _make_multi(repo)
    page = repo / "entities" / "alpha.md"
    entity = markdown_parser.parse(page)
    claims = parse_claims(entity.body) + [_claim("clm_off", "porto", "2026-02-01", "ep_2026-02-01_002")]
    claims[-1].predicate = "works-at"
    markdown_parser.write(page, entity.frontmatter, write_claims(entity.body, claims))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "held")
    before = page.read_text()
    _dismiss(repo)
    assert page.read_text() == before


def test_a_kept_value_carries_its_day_and_conversation_and_the_persons_confirmation(repo):
    _answer(repo, "both")
    kept = _by_object(repo)["porto"]
    assert kept.id == "clm_off"
    assert kept.valid_from == "2026-02-01"  # when it was said, never the day of the click
    assert kept.recorded_at == date.today().isoformat()
    assert kept.source_episodes == ["ep_2026-02-01_002"]
    assert kept.source_trust == "user_stated" and kept.authored_by == "user"
    # The same belief slot, marked as both standing, the way a value on the page is.
    assert kept.observer == "owner" and kept.context == "as of 2026-02-01"
    assert "porto" in _git(repo, "show", "HEAD:entities/alpha.md")


def test_the_sentence_names_every_value(repo):
    _answer(repo, "both")
    page = (repo / "entities" / "alpha.md").read_text()
    assert "Both are true: lisbon and porto" in page


def test_the_picked_value_closes_the_page_value_and_points_at_it(repo):
    _answer(repo, "b")
    claims = _claims(repo)
    assert claims["clm_page"].superseded_by == "clm_off"
    assert claims["clm_off"].supersedes == "clm_page"
    assert claims["clm_off"].confidence >= 0.9


def test_picking_the_page_value_writes_nothing_for_the_other(repo):
    """The person said it is not the one: the rival is not written as ever having been true."""
    _answer(repo, "a")
    held = _by_object(repo)
    assert set(held) == {"lisbon"} and held["lisbon"].valid_to is None


def test_an_open_claim_saying_the_same_value_is_that_value(repo):
    """The value reached the page under another id since the question opened: no second claim."""
    page = repo / "entities" / "alpha.md"
    entity = markdown_parser.parse(page)
    claims = parse_claims(entity.body) + [_claim("clm_later", "Porto", "2026-02-20", "ep_2026-02-20_001")]
    markdown_parser.write(page, entity.frontmatter, write_claims(entity.body, claims))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "same value later")
    _answer(repo, "b")
    claims = _claims(repo)
    assert "clm_off" not in claims
    assert claims["clm_later"].valid_to is None and claims["clm_page"].superseded_by == "clm_later"


def test_three_values_all_stand(repo):
    item = next((repo / "inbox").glob("*.md"))
    parsed = markdown_parser.parse(item)
    options = parsed.frontmatter["options"]
    third = dict(options[1], key="bx", label="braga", claim_id="clm_third", observed_at="2026-02-02",
                 description="Last mentioned 2026-02-02 · extracted from ep_2026-02-02_001")
    third.pop("source_episode", None)
    parsed.frontmatter["options"] = [*options[:2], third, *options[2:]]
    markdown_parser.write(item, parsed.frontmatter, parsed.body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "third")
    _answer(repo, "both")
    held = _by_object(repo)
    assert set(held) == {"lisbon", "porto", "braga"}
    assert all(c.valid_to is None for c in held.values())
    assert held["braga"].source_episodes == ["ep_2026-02-02_001"]  # an item written before options named their own
    assert "All are true: lisbon, porto and braga" in (repo / "entities" / "alpha.md").read_text()


def test_a_value_sleep_settles_is_never_written_as_the_persons_act(repo):
    from api.services import inbox_actor

    token = inbox_actor.set_actor(inbox_actor.Actor(rule="judged_conflict", authors=("cicada",)))
    try:
        _answer(repo, "b")
    finally:
        inbox_actor.reset(token)
    kept = _by_object(repo)["porto"]
    assert kept.source_trust == "agent_extracted" and kept.authored_by == "cicada"
    assert kept.origin == "inbox-tend"


def test_a_row_that_is_not_a_value_is_never_named_as_one(repo):
    item = next((repo / "inbox").glob("*.md"))
    parsed = markdown_parser.parse(item)
    parsed.frontmatter["options"] = [*parsed.frontmatter["options"], {"key": "other", "label": "Something else"}]
    markdown_parser.write(item, parsed.frontmatter, parsed.body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "other row")
    _answer(repo, "both")
    page = (repo / "entities" / "alpha.md").read_text()
    assert "Both are true: lisbon and porto" in page and "Something else" not in page


def test_dismissing_never_reopens_a_value_already_closed(repo):
    _make_multi(repo)
    page = repo / "entities" / "alpha.md"
    entity = markdown_parser.parse(page)
    closed = _claim("clm_closed", "porto", "2026-01-01", "ep_2026-01-01_001")
    closed.predicate = "works-at"
    closed.valid_to = "2026-01-15"
    markdown_parser.write(page, entity.frontmatter, write_claims(entity.body, [*parse_claims(entity.body), closed]))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "closed")
    before = page.read_text()
    _dismiss(repo)
    assert page.read_text() == before

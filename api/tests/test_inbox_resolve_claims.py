"""G60 §2.4 — resolving a conflict actually moves the claim layer."""

from __future__ import annotations

from datetime import date


import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser
from api.services.claims import parse_claims


def run(coro):
    return asyncio.run(coro)


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
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


ENTITY_BODY = """Rodrigo is a student.

```claims
- id: clm_a
  text: Rodrigo works at mongodb
  subject: rodrigo
  predicate: works-at
  object: mongodb
  observer: agent
  context: general
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-02-18'
  recorded_at: '2026-02-18'
- id: clm_b
  text: Rodrigo works at supahost
  subject: rodrigo
  predicate: works-at
  object: supahost
  observer: agent
  context: general
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-02-18'
  recorded_at: '2026-02-18'
```
"""


def _workspace(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    (repo / "inbox").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")

    markdown_parser.write(
        repo / "entities" / "rodrigo.md",
        {"name": "Rodrigo", "type": "person", "status": "active", "confidence": 0.8,
         "created": "2026-01-01", "last_referenced": "2026-02-18", "decay_rate": 0.05,
         "source_episodes": [], "tags": [], "related": [], "version": 3},
        ENTITY_BODY,
    )
    markdown_parser.write(
        repo / "inbox" / "inbox-001.md",
        {"kind": "conflict", "required_input": "choice", "status": "pending",
         "priority": 0.8, "entity_id": "rodrigo", "entity_name": "Rodrigo",
         "title": "Where does Rodrigo work now?",
         "question": "Where does Rodrigo work now?",
         "created_date": "2026-06-18", "predicate": "works-at",
         "allow_other": True, "allow_defer": True,
         "options": [
             {"key": "a", "label": "mongodb", "claim_id": "clm_a",
              "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
             {"key": "b", "label": "supahost", "claim_id": "clm_b",
              "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
             {"key": "both", "label": "Both are true (different contexts)"},
         ]},
        "Conflicting beliefs about Rodrigo.",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _claims(repo: Path) -> dict:
    body = markdown_parser.parse(repo / "entities" / "rodrigo.md").body
    return {c.id: c for c in parse_claims(body)}


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """The body rewrite goes through the LLM; make it deterministic + offline."""
    async def _fake(**kwargs):
        return f"{kwargs['new_description']}"

    monkeypatch.setattr(
        "api.services.conflict_resolver._synthesize_entity_update", _fake
    )


def test_picking_an_option_supersedes_every_other_option_claim(tmp_path):
    repo = _workspace(tmp_path)
    settings = _Settings(repo)

    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b"), settings
    ))

    assert out["status"] == "resolved"
    claims = _claims(repo)
    assert claims["clm_b"].valid_to is None
    assert claims["clm_b"].confidence >= 0.9
    assert claims["clm_a"].valid_to == date.today().isoformat()
    assert claims["clm_a"].superseded_by == "clm_b"
    assert claims["clm_b"].supersedes == "clm_a"

    fm = markdown_parser.parse(repo / "entities" / "rodrigo.md").frontmatter
    assert fm["version"] == 4
    assert not (repo / "inbox" / "inbox-001.md").exists()

    log = _git(repo, "log", "--format=%s%n%b")
    assert "Cicada-Author: user" in log
    assert "inbox/conflict/resolved" in log


def test_both_keeps_claims_open_and_qualifies_their_context(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="both"), _Settings(repo)
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None
    assert claims["clm_b"].valid_to is None
    assert claims["clm_a"].context == "as of 2026-02-18"
    assert claims["clm_b"].context == "as of 2026-02-18"


def test_neither_with_free_text_writes_a_user_claim_and_closes_both(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="resolve", optionKey="neither", answer="Acme Robotics"),
        _Settings(repo),
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to == date.today().isoformat()
    assert claims["clm_b"].valid_to == date.today().isoformat()

    new = [c for c in claims.values() if c.object == "Acme Robotics"]
    assert len(new) == 1
    user_claim = new[0]
    assert user_claim.source_trust == "user_stated"
    assert user_claim.origin == "clarification"
    assert user_claim.authored_by == "user"
    assert user_claim.confidence == 0.95
    assert user_claim.predicate == "works-at"
    assert user_claim.valid_to is None
    # It closed them, so both point at it.
    assert claims["clm_a"].superseded_by == user_claim.id


def test_neither_without_text_only_closes(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="resolve", optionKey="neither"),
        _Settings(repo),
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to == date.today().isoformat()
    assert claims["clm_b"].valid_to == date.today().isoformat()
    assert len(claims) == 2, "no new claim is written when there is nothing to say"


def test_free_text_without_an_option_key_behaves_like_neither(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="resolve", answer="Acme Robotics"),
        _Settings(repo),
    ))
    claims = _claims(repo)
    assert any(c.object == "Acme Robotics" and c.source_trust == "user_stated"
               for c in claims.values())


def test_defer_writes_remind_after_and_keeps_the_item(tmp_path):
    repo = _workspace(tmp_path)
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="defer", remindDays=14), _Settings(repo)
    ))

    assert out["status"] == "deferred"
    path = repo / "inbox" / "inbox-001.md"
    assert path.exists()
    fm = markdown_parser.parse(path).frontmatter
    assert fm["remind_after"] == out["remindAfter"]
    # Claims untouched.
    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None and claims["clm_b"].valid_to is None


def test_defer_defaults_to_the_settings_window(tmp_path):
    repo = _workspace(tmp_path)
    settings = _Settings(repo)
    settings.inbox_defer_days = 30
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="defer"), settings
    ))
    from datetime import date, timedelta

    assert out["remindAfter"] == str(date.today() + timedelta(days=30))


def test_skip_leaves_everything_untouched(tmp_path):
    repo = _workspace(tmp_path)
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="skip"), _Settings(repo)
    ))
    assert out["status"] == "skipped"
    assert (repo / "inbox" / "inbox-001.md").exists()


CLAIMLESS_OPTIONS = [
    {"key": "a", "label": "mongodb"},
    {"key": "b", "label": "supahost"},
    {"key": "both", "label": "Both are true (different contexts)"},
]


def _make_claimless(repo: Path) -> None:
    """Rewrite the seeded item to the legacy / entity-path shape: no claim ids."""
    path = repo / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    parsed.frontmatter["options"] = CLAIMLESS_OPTIONS
    markdown_parser.write(path, parsed.frontmatter, parsed.body)


def test_picking_a_claimless_option_records_the_choice_not_its_opposite(tmp_path):
    """C1 — legacy and entity-path options carry `claim_id: None`. Picking one
    is still an affirmative answer: the page must say "works at supahost", never
    "none of the previously recorded values … are current".
    """
    repo = _workspace(tmp_path)
    _make_claimless(repo)

    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b"), _Settings(repo)
    ))

    assert out["status"] == "resolved"
    body = markdown_parser.parse(repo / "entities" / "rodrigo.md").body
    assert "supahost" in body
    assert "None of the previously recorded values" not in body
    assert not (repo / "inbox" / "inbox-001.md").exists()


def test_a_claimless_pick_still_closes_the_other_claim_backed_options(tmp_path):
    repo = _workspace(tmp_path)
    path = repo / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    # Mixed shape: the chosen option has no claim, the loser does.
    parsed.frontmatter["options"] = [
        {"key": "a", "label": "mongodb", "claim_id": "clm_a"},
        {"key": "b", "label": "supahost"},
    ]
    markdown_parser.write(path, parsed.frontmatter, parsed.body)

    run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b"), _Settings(repo)
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to == date.today().isoformat()
    # No winner claim exists, so nothing claims to have superseded it.
    assert claims["clm_a"].superseded_by is None
    body = markdown_parser.parse(repo / "entities" / "rodrigo.md").body
    assert "supahost" in body


def test_the_commit_manifest_does_not_repeat_one_page_per_closed_claim(tmp_path):
    """M3 — one file line per file, not one per closed claim."""
    repo = _workspace(tmp_path)
    path = repo / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    body = markdown_parser.parse(repo / "entities" / "rodrigo.md").body
    # Add a third competing claim so two losers close on one pick.
    third = body.replace(
        "```claims\n",
        "```claims\n"
        "- id: clm_c\n"
        "  text: Rodrigo works at acme\n"
        "  subject: rodrigo\n"
        "  predicate: works-at\n"
        "  object: acme\n"
        "  observer: agent\n"
        "  context: general\n"
        "  source_trust: agent_extracted\n"
        "  confidence: 0.6\n"
        "  valid_from: '2026-02-18'\n"
        "  recorded_at: '2026-02-18'\n",
    )
    entity = markdown_parser.parse(repo / "entities" / "rodrigo.md")
    markdown_parser.write(repo / "entities" / "rodrigo.md", entity.frontmatter, third)
    parsed.frontmatter["options"] = [
        {"key": "a", "label": "mongodb", "claim_id": "clm_a"},
        {"key": "b", "label": "supahost", "claim_id": "clm_b"},
        {"key": "c", "label": "acme", "claim_id": "clm_c"},
    ]
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "third value")

    run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b"), _Settings(repo)
    ))

    # the person's commit, not HEAD — G53's `resolve()` commits `_state.md` as `cicada` on top
    message = _git(repo, "log", "-1", "--grep=^Inbox resolution", "--format=%B")
    lines = [ln for ln in message.splitlines() if ln.startswith("entities/")]
    assert len(lines) == len(set(lines)) == 2, message


def test_defer_commits_the_item_with_an_inbox_deferred_trigger(tmp_path):
    """M4 — deferring must not leave the store dirty for the next Sleep sweep."""
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="defer", remindDays=14), _Settings(repo)
    ))

    assert _git(repo, "status", "--porcelain").strip() == ""
    message = _git(repo, "log", "-1", "--format=%B")
    assert "Inbox deferral" in message
    assert "trigger: inbox/deferred" in message
    assert "Cicada-Author: user" in message


def test_defer_commits_only_the_inbox_file(tmp_path):
    repo = _workspace(tmp_path)
    # An unrelated dirty file must not be swept into the deferral commit.
    (repo / "entities" / "stray.md").write_text("---\nname: Stray\n---\n\nnope\n")

    run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="defer", remindDays=14), _Settings(repo)
    ))

    files = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["inbox/inbox-001.md"]
    assert (repo / "entities" / "stray.md").exists()


# --- Malformed resolve requests (PR13 review) -------------------------------


def _untouched(repo: Path) -> None:
    """Nothing was written: both claims still open, the question still there."""
    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None and claims["clm_b"].valid_to is None
    assert (repo / "inbox" / "inbox-001.md").exists()
    body = markdown_parser.parse(repo / "entities" / "rodrigo.md").body
    assert "None of the previously recorded values" not in body


def test_an_unknown_option_key_is_rejected_not_treated_as_neither(tmp_path):
    """An `optionKey` matching no option used to fall through to the "neither"
    branch, permanently closing EVERY competing claim from one malformed
    request. It must 400 with nothing written."""
    repo = _workspace(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve", optionKey="z"), _Settings(repo)
        ))
    assert exc.value.status_code == 400 and "z" in exc.value.detail
    _untouched(repo)


def test_a_missing_option_key_with_no_answer_is_rejected(tmp_path):
    """"Resolve" with neither a pick nor free text says nothing about the
    facts, so it must not be read as "none of these are current"."""
    repo = _workspace(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve"), _Settings(repo)
        ))
    assert exc.value.status_code == 400
    _untouched(repo)


# --- M3: legacy pre-G60 conflict items must remain dismissable -------------


def _make_legacy_unquestioned(repo: Path) -> None:
    """Rewrite the seeded item to the legacy pre-G60 shape: no `options`, no
    `question` — exactly what a pre-G60 conflict item looks like on disk."""
    path = repo / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    parsed.frontmatter.pop("options", None)
    parsed.frontmatter.pop("question", None)
    markdown_parser.write(path, parsed.frontmatter, parsed.body)


def test_dismiss_with_no_key_removes_a_legacy_item_without_touching_claims(tmp_path):
    """M3: a conflict item with no `options` and no `question` (legacy
    pre-G60) must stay dismissable via action="dismiss" with no key/answer —
    exactly the shape `InboxCardView`'s bare Dismiss button and the deprecated
    `/nudges` shim send. Nothing claim-wise is closed."""
    repo = _workspace(tmp_path)
    _make_legacy_unquestioned(repo)

    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="dismiss"), _Settings(repo)
    ))

    assert out["status"] == "resolved"
    assert not (repo / "inbox" / "inbox-001.md").exists()
    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None and claims["clm_b"].valid_to is None


def test_dismiss_with_no_key_still_400s_for_a_modern_question_item(tmp_path):
    """A modern item (has `options` and/or a `question`) must keep the strict
    400 even for action="dismiss" — only the legacy no-options/no-question
    shape gets the bypass."""
    repo = _workspace(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="dismiss"), _Settings(repo)
        ))
    assert exc.value.status_code == 400
    _untouched(repo)


def test_the_deprecated_nudges_shim_can_dismiss_a_legacy_conflict_item(tmp_path, monkeypatch):
    """`NudgeResolveRequest` carries no `optionKey` field at all, so before
    this fix no conflict item was resolvable through the deprecated shim. A
    legacy item must still be dismissable through `/nudges/{id}/resolve`."""
    from fastapi.testclient import TestClient

    from api import config, main

    repo = _workspace(tmp_path)
    _make_legacy_unquestioned(repo)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(repo))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    try:
        resp = client.post("/nudges/inbox-001/resolve", json={"action": "dismiss"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "resolved"
    finally:
        config.get_settings.cache_clear()

    assert not (repo / "inbox" / "inbox-001.md").exists()
    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None and claims["clm_b"].valid_to is None


def test_a_corrupt_claims_block_aborts_the_resolve_entirely(tmp_path):
    """A ```claims block that will not parse must abort BEFORE the entity is
    rewritten and before the question is deleted — the old code skipped only
    the claim edits and then rewrote the page (through the LLM) and unlinked
    the item, losing the trapped claims for good."""
    repo = _workspace(tmp_path)
    entity_path = repo / "entities" / "rodrigo.md"
    entity = markdown_parser.parse(entity_path)
    corrupt = "Rodrigo is a student.\n\n```claims\n- id: clm_a\n  text: \"unterminated\n```\n"
    markdown_parser.write(entity_path, entity.frontmatter, corrupt)
    before = entity_path.read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve", optionKey="a"), _Settings(repo)
        ))

    assert exc.value.status_code == 409
    assert entity_path.read_text(encoding="utf-8") == before, "the page must be byte-identical"
    assert (repo / "inbox" / "inbox-001.md").exists(), "the question must be kept"


def test_a_malformed_claims_entry_also_aborts_the_resolve_with_a_409(tmp_path):
    """D3: a claims block that parses as valid YAML but contains a malformed
    ENTRY (a bare scalar list item, or a field that fails conversion) must
    abort the resolve exactly like unparseable YAML does — before this fix
    `parse_claims(strict=True)` silently dropped such entries, and the
    subsequent `write_claims` call would then re-render the (now truncated)
    list, permanently deleting the trapped claim."""
    repo = _workspace(tmp_path)
    entity_path = repo / "entities" / "rodrigo.md"
    entity = markdown_parser.parse(entity_path)
    malformed = (
        "Rodrigo is a student.\n\n```claims\n"
        "- id: clm_a\n  text: fine\n  subject: rodrigo\n  predicate: works-at\n"
        "  object: mongodb\n"
        "- just a bare string, not a mapping\n"
        "```\n"
    )
    markdown_parser.write(entity_path, entity.frontmatter, malformed)
    before = entity_path.read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve", optionKey="a"), _Settings(repo)
        ))

    assert exc.value.status_code == 409
    assert entity_path.read_text(encoding="utf-8") == before, "the page must be byte-identical"
    assert (repo / "inbox" / "inbox-001.md").exists(), "the question must be kept"

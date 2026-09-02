"""What the Sleep cycle still does on an IDLE run (zero unprocessed episodes).

Two tail steps are time-driven, not episode-driven, so both must run on the
early return and not only after a full 5-stage cycle: the G59 logo warm-up
(otherwise a quiet night never warms missing logos) and the G60 §2.3 open-
question refresh (otherwise a stale question never gains its "Neither anymore"
escalation during exactly the quiet weeks it was written for).

Hermetic: no network, no real git, no real model — mirrors
``test_sleep_resumable.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from api.services import predicates, sleep_cycle


def _empty_memory(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _settings(memory):
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
        inbox_stale_after_days=90,
    )


def test_warm_logos_runs_on_the_zero_unprocessed_episodes_early_return(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    calls = []

    async def fake_warm_logos(memory_path, *, limit=50, fetcher=None):
        calls.append((memory_path, limit))
        return 0

    monkeypatch.setattr("api.services.logo_service.warm_logos", fake_warm_logos)

    import asyncio
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-empty"))

    assert calls == [(memory, 50)]
    assert sleep_cycle.get_sleep_state().status == "idle"


def _git(repo, *args):
    import subprocess

    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                          capture_output=True, text=True).stdout


def test_stale_question_refresh_also_runs_on_the_idle_early_return(tmp_path):
    """G60 §2.3 is time-driven, not episode-driven: a quiet week (zero
    unprocessed episodes) must still escalate a question every option of which
    has gone silent, or the escalation never fires during exactly the quiet
    period it exists for."""
    import asyncio

    from api.services import markdown_parser

    memory = _empty_memory(tmp_path)
    (memory / "inbox").mkdir()
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    markdown_parser.write(
        memory / "inbox" / "inbox-001.md",
        {"kind": "conflict", "required_input": "choice", "status": "pending",
         "priority": 0.8, "entity_id": "rodrigo", "entity_name": "Rodrigo",
         "title": "Where does Rodrigo work now?",
         "question": "Where does Rodrigo work now?",
         # Older than the 90-day staleness window, with dateless options — the
         # exact shape the "Neither anymore" escalation was written for.
         "created_date": "2020-01-01", "predicate": "works-at",
         "allow_other": True, "allow_defer": True,
         "options": [{"key": "a", "label": "mongodb"}, {"key": "b", "label": "supahost"}]},
        "Conflicting beliefs about Rodrigo.",
    )
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-idle"))

    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    keys = [str(o.get("key")) for o in fm["options"]]
    assert "neither" in keys, "an idle cycle must still escalate a stale question"
    assert sleep_cycle.get_sleep_state().questions_refreshed == 1

    # ...and it must not leave the inbox dirty for the next real cycle to sweep
    # in under a model's name: this is system maintenance, author `cicada`.
    assert _git(memory, "status", "--porcelain").strip() == ""
    message = _git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in message

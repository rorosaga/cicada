"""Old bulk material is read on the engine's lightest model (ruling 80, owner 2026-11-24, G246).

The owner ordered every save read, and his Sleep runs on a metered key with a mid-size model. The measured cost of a read is
about two calls, 13k tokens in and 1.8k out, a save; the pile is thousands of old bookmarks. His answer to the three options
he was shown: "current model for new saves and the 453 list saves; the smallest model for old bookmarks." This module is
that answer, in three parts that each have one home here.

**What is old bulk material** (:func:`why`, the one table). A save *released from the pile* (``turn_released_on``, stamped by
``history_index.take_turns``) that is one of:

* ``browser``: a browser's bookmark taken in by a sync or an import — origin ``<browser>-bookmark``
  (``bookmark_sync.CHANNEL_BY_ORIGIN``, so a new browser joins by being synced), or a bookmarks file imported before the door
  was stamped (``source: bookmark`` with no origin);
* ``file``: a save that arrived out of a file the person gave — an export or an archive, any platform
  (``arrived_by: file``, stamped by ``media_ingestor.parse_upload`` on every item of the file).

Everything else reads on the model the person chose, as always: conversations, a save made singly (never in the pile), a save
he talked about or gave a reason, and a pile save that came from a saved list he turned on and his agent read in his browser,
or from a connector he connected (an X, Reddit or GitHub poll, a Pinterest pin, a Substack list) — those carry no
``arrived_by``, whatever their origin. **A list save kept before the stamp existed carries none either, so it reads on the
chosen model**: when in doubt the person's own model is used, never the lighter one.

**What the lightest model is** (:func:`lighter`). The same engine, the same sign-in, the same key, the same billing: never
another. A plan engine's small model: the Claude plan's ``haiku``. A key's provider's own lightest model Cicada knows a price
for: a Claude key's newest priced Haiku, an OpenAI key's ``gpt-5.4-nano``, a Gemini key's flash-lite; another provider's key,
a router, a local model, the ChatGPT plan and the Cursor, OpenCode and Grok plans have no lighter model Cicada knows (no
list gives one), so the chosen model is used and nothing fails. On a metered path the lighter model must have a price and
cost less than the chosen one on a read of the measured size: otherwise there is no lighter model. A chosen model with no
price still stops a metered run (``sleep_spend``), as before.

**What a lighter batch is.** A batch is read by one model (``sleep_drain.next_batch_retrying`` cuts at the boundary), so the
engine copy it runs on carries the lighter model in the main fields; the same-name second look keeps reading with the person's
own (``kept_main_models``). The option (``sleep_run_prefs.light_old_saves``) is on unless the person turned it off; then
nothing here changes anything.

Rails: frontmatter only (the cached ``bank_index``); no model, no fetch, no write.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from api.services import history_index

#: ``arrived_by`` of a save that came out of a file the person gave (``media_ingestor.FILE_DOOR``).
FILE_DOOR = "file"
#: The two kinds of old bulk material, as the run's record names them.
BROWSER, FILE = "browser", "file"
#: A read of the measured size (ruling 80's cost note: 13k in, 1.8k out a save with text): what two models are compared on.
REFERENCE_IN, REFERENCE_OUT = 13_000, 1_800
#: A key's provider -> its own lightest model Cicada knows a price for, where one is known. The Claude key's is read from the
#: key's own list (:func:`_claude_key`). A provider not named has no lighter model Cicada knows.
LIGHTEST_KEY: dict[str, str] = {"openai": "gpt-5.4-nano", "gemini": "gemini/gemini-flash-lite-latest"}
#: The Claude plan's small model: the alias that always means the newest of its line.
PLAN_CLAUDE_SMALL = "haiku"


def browser_origins() -> frozenset[str]:
    """The origins a browser's bookmarks are stamped with (``bookmark_sync``): Chrome and the other Chromium browsers, Safari."""
    from api.services import bookmark_sync

    return frozenset(bookmark_sync.CHANNEL_BY_ORIGIN)


def why(fm: dict | None) -> str | None:
    """``browser`` or ``file`` for a save released from the pile that is old bulk material, else ``None`` (the table)."""
    if not isinstance(fm, dict) or not fm.get(history_index.TURN_KEY):
        return None
    origin = str(fm.get("origin") or "")
    if origin in browser_origins() or (not origin and fm.get("source") == "bookmark"):
        return BROWSER
    if fm.get("arrived_by") == FILE_DOOR:
        return FILE
    return None


def is_old_bulk(fm: dict | None) -> bool:
    return why(fm) is not None


def old_bulk_ids(memory_path: Path, ids) -> frozenset[str]:
    """Which of ``ids`` are old bulk material now (cached frontmatter; a save he has since talked about is not a
    background save, so the caller asks only of those)."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    out = set()
    for ep_id in ids:
        entry = bank_index.file(memory_path, "episodes", f"{ep_id}.md")
        if entry is not None and is_old_bulk(entry.frontmatter):
            out.add(ep_id)
    return frozenset(out)


@dataclass(frozen=True)
class Lighter:
    """The engine copy a lighter batch runs on, the model it names, and the person's own for the record."""
    settings: object
    model: str
    chosen: str


def _reference_cost(model: str) -> float | None:
    """What a read of the measured size costs on ``model`` at list price, or ``None`` when no price is known."""
    from api.services import sleep_spend

    try:
        return sleep_spend._cost(model, REFERENCE_IN, REFERENCE_OUT)
    except Exception:  # noqa: BLE001 — a table that cannot be read is no price
        return None


def _is_small_line(model: str) -> bool:
    """Is a Claude model already of the small (Haiku) line, by its own name? Only ever used to leave a choice alone."""
    return "haiku" in {w for w in re.split(r"[^a-z]+", (model or "").lower()) if w}


def _plan_claude(resolved) -> Lighter | None:
    from api.services import agent_engine

    chosen = agent_engine.model_for_stage(resolved, None)
    if _is_small_line(chosen):
        return None
    return Lighter(resolved.model_copy(update={"agent_model": PLAN_CLAUDE_SMALL,
                                               "kept_main_models": {"agent_model": chosen}}),
                   PLAN_CLAUDE_SMALL, chosen)


def _claude_key(chosen: str) -> str | None:
    """A Claude key's lightest priced model: the newest active Haiku with a price row, as the key stores it."""
    from api.services import anthropic_models, price_supplement

    for model in anthropic_models.active(anthropic_models.TIER_LINE["small"]):
        if price_supplement.claude_cost(model, input_tokens=1, output_tokens=1) is not None:
            return anthropic_models.stored_id(model)
    return None


def _other_key(chosen: str) -> str | None:
    """Another key's own lightest model Cicada knows, when ``chosen`` is that provider's own model id."""
    from api.services.connections import byok

    provider = byok.provider_for_model(chosen)
    candidate = LIGHTEST_KEY.get(provider)
    own = (provider == "openai" and ("/" not in chosen or chosen.startswith("openai/"))) \
        or (provider == "gemini" and chosen.startswith("gemini/"))
    return candidate if candidate and own else None


def _key(resolved) -> Lighter | None:
    from api.services import anthropic_models

    chosen = str(getattr(resolved, "litellm_model", "") or "").strip()
    if not chosen:
        return None
    candidate = _claude_key(chosen) if anthropic_models.is_claude(chosen) else _other_key(chosen)
    if not candidate or candidate == chosen:
        return None
    dear, cheap = _reference_cost(chosen), _reference_cost(candidate)
    if dear is None or cheap is None or cheap >= dear:
        return None     # no price to compare, or no saving: the person's own model reads
    updates: dict = {"litellm_model": candidate, "kept_main_models": {"litellm_model": chosen}}
    if str(getattr(resolved, "consolidation_model", "") or "").strip():
        updates["consolidation_model"] = ""     # the later stages follow the batch's one model
    return Lighter(resolved.model_copy(update=updates), candidate, chosen)


def lighter(resolved) -> Lighter | None:
    """The lightest model of the engine ``resolved`` is, as an engine copy, or ``None`` when there is none to use: a stand-in
    with no copy, no engine, an engine whose lighter model Cicada does not know, a chosen model that is already the lightest
    or that has no price to compare on a key. Never another provider, sign-in, key or billing path."""
    from api.services import engine_select

    if not hasattr(resolved, "model_copy") or engine_select.no_engine(resolved):
        return None
    label = engine_select.engine_label(resolved)
    if label == "claude-cli":
        return _plan_claude(resolved)
    if label == "litellm":
        return _key(resolved)
    return None


__all__ = ["BROWSER", "FILE", "FILE_DOOR", "LIGHTEST_KEY", "Lighter", "browser_origins", "is_old_bulk", "lighter",
           "old_bulk_ids", "why"]

"""Stage 3: Conflict Resolution & Temporal Decay."""

import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from loguru import logger
from tqdm import tqdm

from api.config import Settings
from api.models.schemas import DecayClass
from api.services import (
    alias_policy, decay_policy, decay_tuning, engine_errors, entity_article, entity_body, entity_types, episode_time,
    fact_sources, json_parse, markdown_parser, page_edits, role_people, section_provenance, source_dates,
)
from api.services.providers import resolve_llm_fn


def _litellm():
    """litellm, imported when a model is first called, never at import time.

    The import costs ~0.8-1.5 s, and this module sits under every reader that touches the inbox
    (``inbox_generator`` -> ``inbox_service`` -> ``search_service`` -> ``mcp_tools``): a fresh process's
    first recall paid for a library no read uses. ``conflict_resolver.litellm`` still names the module
    (:func:`__getattr__`), so patching ``conflict_resolver.litellm.acompletion`` patches what every call
    here reads."""
    import litellm

    return litellm


def __getattr__(name: str):
    if name == "litellm":
        return _litellm()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Confidence floor a settled entity is restored to when it is mentioned again
# (G66 §1.6; since the read-on-time ruling, 2026-10-16, whatever its status —
# a decaying or archived page also becomes active) — high enough to clear
# `decay_nudge_threshold` (0.4) and `archive_threshold` (0.2) with room to
# spare, low enough that a single passing mention doesn't outrank a
# well-established belief.
RECOVERY_CONFIDENCE = 0.6

# G85 §2 / Wave-1 1.8: a single decay pass never charges more than one
# week's worth of decay, regardless of how many days have actually elapsed
# since the baseline. `decay_rate` is defined per-week, so a week is the
# natural unit. This is a safety rail INDEPENDENT of the one-shot
# `decayed_through` backfill migration (`decay_migration.py`) — a future gap
# (a paused schedule, a laptop off for a month, an engine outage) must
# degrade gracefully over several cycles instead of charging the whole gap
# as if it were user disinterest in one cliff. The watermark advances by
# only the CAPPED amount, so the remaining "debt" persists and gets worked
# off on subsequent cycles rather than being silently dropped.
MAX_DECAY_DAYS_PER_CYCLE = 7


async def resolve_and_prune(
    resolved: list[dict],
    existing: list[dict],
    settings: Settings,
    *,
    now: datetime | None = None,
    tuning: dict[str, float] | None = None,
    decay: bool = True,
    cancel_check=None,
    progress_callback=None,
) -> list[dict]:
    """Apply conflict resolution and temporal decay to all entities.

    The synthesis and contradiction calls — the long, paid part of this stage — overlap
    across pages, at most ``agent_max_concurrency`` pages at once (1 is one page after
    another; a plan engine is further held to the same number process-wide by the
    provider permit). A page's own two calls stay in order, and every result is applied
    in the pages' order once all are in, so ``changes`` is the serial loop's
    (``_overlap_pages``). An engine error stops new pages, waits out the ones in flight
    and is raised as it was.

    ``cancel_check`` (Sleep page v5, a pause must be able to land here): polled before
    each page's calls start. Once it says stop, no further page is asked about, the
    pages in flight finish, and the partial ``changes`` come back for the caller to
    discard, as Stage 2 does; nothing is on disk before Stage 5.
    ``progress_callback(done, total)`` counts the pages to update, fixed when the stage
    starts; ``done`` grows as pages finish.

    ``decay``: ``False`` skips the unreferenced-entity decay loop only — a drain
    (``sleep_drain``) charges decay once, in the batch that empties its queue,
    where a plain cycle charges it every time (TODO ruling 1). The
    ``learned_on`` stamp on created and referenced pages stays either way; with
    ``decay`` they also carry the ``settle`` directive ``apply_changes`` charges.

    ``now``: decay reference time; defaults to ``datetime.now()``. Mirrors
    ``claim_reconciler.reconcile_stage3``'s ``now_date`` — injectable so a test
    can simulate elapsed time without monkeypatching the stdlib clock.

    ``tuning``: the per-type pace (G147, ``{type: multiplier}``); ``None``
    reads the bank's ``_decay_tuning.yaml`` (``decay_tuning.load``), so a test
    can inject a pace without writing the file.
    """
    changes: list[dict] = list(resolved)
    # G194 A1: the day the synthesis and contradiction prompts call today — the decay pass's reference day below.
    cycle_day = (now or datetime.now()).date().isoformat()

    # IDs of entities referenced in this cycle
    referenced_ids = {r["id"] for r in resolved}

    # Synthesize updates and detect contradictions on update branches
    existing_by_id = {e["id"]: e for e in existing}
    update_changes = [c for c in resolved if c.get("action") == "update"]
    progress = tqdm(
        total=len(update_changes),
        desc="Stage 3: synth",
        unit="ent",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        leave=True,
        disable=len(update_changes) == 0,
    )
    conflicts_found = 0
    rereads = 0
    total_pages = len(update_changes)
    if progress_callback is not None:
        progress_callback(0, total_pages)
    # The per-page decisions that need no model call run first, in order: whether the page is asked about at
    # all and with what. Only the calls overlap (`_overlap_pages`); every result is applied below in this order.
    jobs: list[dict] = []
    context = _article_context(existing, settings, cycle_day) if getattr(settings, "page_articles_enabled", False) else None
    for change in update_changes:
        job = _page_job(change, existing_by_id, settings, context)
        if job == "reread":
            rereads += 1
        elif job is not None:
            jobs.append(job)
    finished = total_pages - len(jobs)
    progress.update(finished)
    if progress_callback is not None and finished:
        progress_callback(finished, total_pages)

    def _page_done() -> None:
        nonlocal finished
        finished += 1
        progress.update(1)
        if progress_callback is not None:
            progress_callback(finished, total_pages)

    concurrency = max(1, int(getattr(settings, "agent_max_concurrency", 1) or 1))
    decided = await _overlap_pages(
        jobs, lambda job: _decide_page(job, settings, cycle_day),
        concurrency=concurrency, cancel_check=cancel_check, on_done=_page_done,
    )
    for index, job in enumerate(jobs):
        if index not in decided:
            continue  # a cancel stopped before this page; the caller discards the partial result
        change, synthesized, contradiction = job["change"], *decided[index]
        if isinstance(synthesized, dict):
            change["article"] = synthesized   # the article writer's lead and sections (`entity_article.payload`)
        elif synthesized:
            change["synthesized_body"] = synthesized
            if job["section_aware"]:
                change['section_aware_synthesis'] = True
        if contradiction and contradiction.get("has_unresolvable_contradiction"):
            conflicts_found += 1
            progress.set_postfix_str(f"conflicts={conflicts_found}", refresh=False)
            today_str = str(date.today())
            built = build_entity_question(job["entity_name"], contradiction, today_str)
            changes.append({
                "id": change["id"],
                "action": "conflict_nudge",
                "entity": job["new_entity"],
                "conflict_context": contradiction.get("contradiction", ""),
                "predicate": "description",
                "question": built["question"],
                "options": built["options"],
                "allow_other": True,
                "allow_defer": True,
                "source_episode": change.get("source_episode", ""),
                "trigger": "sleep/conflict_resolution",
            })

    progress.close()
    if rereads:
        logger.info(f"Stage 3: {rereads} page(s) re-read from conversations they already credit, saying nothing new "
                    "about what they are — merged without a call")
    if progress_callback is not None and not (cancel_check is not None and cancel_check()):
        progress_callback(len(update_changes), len(update_changes))

    # Temporal decay for unreferenced entities (G147). The weekly rate is
    # `decay_policy.effective`: the class's (or explicit) rate x the spacing
    # factor over distinct mention weeks x the per-type pace the person chose —
    # the SAME function `GET /entities/{id}` serves, so the card's pace is the
    # pace charged. Evergreen entities are skipped.
    now = now or datetime.now()
    alpha, floor = decay_policy.spacing_params(settings)
    if tuning is None:
        # G147: the per-type pace the person approved in Settings → Memory. One
        # small file read per cycle; a demo or test settings object without a
        # bank path has none.
        memory_path = getattr(settings, "memory_path", None)
        tuning = decay_tuning.load(memory_path) if memory_path else {}
    # Age counts from when it was said (owner ruling 2026-10-09, amending G170's "an import is not
    # silence"): a page this cycle creates or references keeps its content date (`last_referenced`), and
    # `learned_on` records the day Cicada read it. The gap between the two is silence the conversations
    # themselves prove — the run read everything waiting — so the decay pass charges it in full, once
    # (`decay_policy.silence`); only the time after `learned_on` is ruling 1's capped, live silence.
    # Nothing is charged mid-drain: the batches before the last pass `decay=False`, so the order the
    # conversations are read in, and where the batches break, cannot change what a page ends the drain at.
    learned_on = now.date().isoformat()
    # The pass that charges decay also settles the pages it itself creates or references: they are not in
    # `existing`, so the loop below never sees them. The arithmetic runs in `apply_changes`, on the page
    # as merged, and rides in the commit that writes the page (never the `(decay)` commit, G85).
    # Every create/update carries the pace's inputs (`decay_params`): an old conversation that makes a faded
    # one-off a repeat lifts it to the repeat floor in any batch; only the decay pass's carry `settle`.
    params = {
        "today": learned_on, "alpha": alpha, "floor": floor, "tuning": dict(tuning or {}),
        "archive": float(getattr(settings, "archive_threshold", 0.2)),
        "nudge": float(getattr(settings, "decay_nudge_threshold", 0.4)),
    }
    for change in resolved:
        if change.get("action") not in ("create", "update"):
            continue
        change["learned_on"] = learned_on
        change["decay_params"] = params
        # A memory export entry is no mention (`episode_time`): it settles nothing.
        if decay and not change.get("untimed"):
            change["settle"] = params
    # A memory export entry is no week a page came up in (`episode_time`), here as on the card.
    untimed = episode_time.untimed_ids(getattr(settings, "memory_path", None)) if decay else frozenset()
    decay_candidates = [e for e in existing if e["id"] not in referenced_ids] if decay else []
    decay_progress = tqdm(
        total=len(decay_candidates),
        desc="Stage 3: decay",
        unit="ent",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}",
        leave=True,
        disable=len(decay_candidates) == 0,
    )
    faded_by_age = 0
    for entity_data in (existing if decay else ()):
        entity_id = entity_data["id"]
        if entity_id in referenced_ids:
            continue
        decay_progress.update(1)

        fm = entity_data["frontmatter"]
        status = fm.get("status", "active")
        if status in ("archived", "dropped") and not fm.get(decay_policy.READ_LATE_KEY):
            continue

        clear_late = []
        if fm.get(decay_policy.READ_LATE_KEY):
            placed = _placed_on_time(fm, params, untimed)
            if placed is not None:
                # A conversation read late earlier in this drain, placed on the day it was said; this pass's live
                # silence is in it (at most a week, ruling 1), so nothing more is charged here.
                changes.append({"id": entity_id, "source_episode": "", "trigger": "sleep/decay", **placed})
                continue
            clear_late = [decay_policy.READ_LATE_KEY]   # it lifts nothing: old stays old, decay as usual
            if status in ("archived", "dropped"):
                changes.append({
                    "id": entity_id, "action": "decay", "new_confidence": fm.get("confidence", 0.0),
                    "new_status": status, "source_episode": "", "trigger": "sleep/decay",
                    "decayed_through": _extract_date_string(fm.get("decayed_through")) or now.date().isoformat(),
                    "clear": clear_late,
                })
                continue
        confidence = fm.get("confidence", 0.5)
        effective = decay_policy.effective(fm, alpha=alpha, floor=floor, tuning=tuning, untimed=untimed)
        decay_class, decay_rate = effective.decay_class, effective.rate
        if decay_class is DecayClass.evergreen:
            # An artifact, not a belief: it does not become less true by going
            # unmentioned. No decay math, no decay nudge, never auto-archived.
            continue
        # G85 §2 / Wave-1 1.1: decay is charged exactly once per elapsed interval —
        # from the later of `last_referenced` and the `decayed_through` watermark this
        # pass stamps. Proven silence (last said -> `learned_on`) is charged in full;
        # live silence is capped at MAX_DECAY_DAYS_PER_CYCLE and the watermark advances
        # only by what was charged, so an outage or a paused schedule works off over
        # several cycles instead of one cliff (TODO ruling 1).
        said = _extract_date_string(fm.get("last_referenced"))
        learned = _extract_date_string(fm.get("learned_on"))
        owed = decay_policy.silence(
            said, _extract_date_string(fm.get("decayed_through")), learned, now.date(), MAX_DECAY_DAYS_PER_CYCLE)
        if owed is None:
            # Fallback: single step if we cannot determine last reference
            decay_amount = decay_rate
            decay_today = now.date().isoformat()
        else:
            decay_amount = None
            decay_today = owed.watermark.isoformat()
        if decay_amount is not None:
            new_confidence = max(0.0, confidence - decay_amount)
        else:
            # Proven silence floors just under the question line for a page heard in 2+ conversations
            # (owner 2026-10-09: one-offs archive, repeats fade); live silence carries it on to the archive.
            new_confidence = decay_policy.charge(
                confidence, decay_rate, owed, nudge_threshold=settings.decay_nudge_threshold,
                conversations=decay_policy.conversations(fm.get("source_episodes"), untimed=untimed),
                at_least=fm.get(MENTION_FLOOR_KEY))
        # Faded by its age: heard late, and this pass's proven silence took it below the question line. Marked,
        # it fades and archives quietly from here — a question fires only when live silence carries a page across
        # 0.4 (`decay_policy.asks`), so a page still above the line after its age keeps its question.
        marked = fm.get(decay_policy.FADED_BY_AGE_KEY)
        newly = (not marked and owed is not None and owed.proven_days > 0 and decay_policy.heard_late(said, learned)
                 and new_confidence < settings.decay_nudge_threshold)
        faded = marked or newly
        mark = {decay_policy.FADED_BY_AGE_KEY: decay_today} if newly else {}
        if MENTION_FLOOR_KEY in fm:
            mark["clear"] = [MENTION_FLOOR_KEY]   # the mention's gap is settled: the floor has done its job
        asks = not newly and decay_policy.asks(
            confidence, new_confidence, settings.decay_nudge_threshold, faded_by_age=marked)

        if new_confidence < settings.archive_threshold:
            faded_by_age += 0 if asks or not faded else 1
            changes.append({
                "id": entity_id,
                "action": "archive",
                "new_confidence": new_confidence,
                "new_status": "archived",
                "source_episode": "",
                "trigger": "sleep/decay",
                "decayed_through": decay_today,
                **mark,
            })
        elif new_confidence < settings.decay_nudge_threshold:
            faded_by_age += 0 if asks else 1
            changes.append({
                "id": entity_id,
                "action": "decay_nudge" if asks else "decay",
                "new_confidence": new_confidence,
                "new_status": "decaying",
                "source_episode": "",
                "trigger": "sleep/decay",
                "decayed_through": decay_today,
                **mark,
            })
        else:
            changes.append({
                "id": entity_id,
                "action": "decay",
                "new_confidence": new_confidence,
                "new_status": status,
                "source_episode": "",
                "trigger": "sleep/decay",
                "decayed_through": decay_today,
                **({"clear": mark["clear"]} if "clear" in mark else {}),
            })
        if clear_late:
            changes[-1]["clear"] = [*changes[-1].get("clear", []), *clear_late]

    decay_progress.close()
    if faded_by_age:
        logger.info(f"Stage 3: {faded_by_age} page(s) faded by the age of what they came from, below "
                    f"{settings.decay_nudge_threshold} or archived — no question asked")
    return changes


def _article_context(existing: list[dict], settings: Settings, today: str, memory_path=None) -> dict:
    """What every page's article writer shares, read once per stage: the bank's page names (a ``[[link]]`` must name
    one), each id's display name, and the owner's name (G169) — from ``memory_path`` when the caller names the bank
    (the rebuild script), else the settings' bank (Sleep)."""
    known: set[str] = set()
    names: dict[str, str] = {}
    people: set[str] = set()
    for page in existing:
        fm = page.get("frontmatter") or {}
        names[page["id"]] = str(fm.get("name") or page["id"])
        if fm.get("type") == "person":
            people.add(page["id"])
        known |= {page["id"], names[page["id"]], *(str(a) for a in fm.get("aliases") or [] if a)}
    owner = None
    try:
        from api.services import owner_identity
        owner = owner_identity.owner_name(memory_path or getattr(settings, "memory_path", None), settings)
    except Exception:  # noqa: BLE001 - a missing owner costs the name, never the article
        owner = None
    return {"known": known, "names": names, "people": people, "owner": owner, "today": today,
            "max_chars": int(getattr(settings, "page_article_max_input_chars", 60000) or 60000)}


_LINK = __import__("re").compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _linkable(original_body: str, record: dict, names: dict[str, str], known: set[str]) -> list[str]:
    """The pages this one already links to — in its prose, its Related block, its claims — by display name."""
    from api.services.claims import parse_claims

    found = set(_LINK.findall(original_body or ""))
    found |= set(_LINK.findall("\n".join(str(v) for v in record.values())))
    try:
        found |= {names.get(c.object, "") for c in parse_claims(original_body or "") if c.object_kind == "node"}
    except Exception:  # noqa: BLE001
        pass
    lowered = {k.lower() for k in known}
    return sorted(n for n in found if n and n.strip().lower() in lowered)


def _article_job(change: dict, existing_entity: dict, new_entity: dict, context: dict) -> dict | None:
    """The article writer's inputs for one page, or ``None`` (over budget: the page keeps the deterministic merge)."""
    fm = existing_entity.get("frontmatter", {}) or {}
    from api.services.claims import strip_claims_block

    original = existing_entity.get("body", "")
    entity_type = new_entity.get("type") or fm.get("type", "concept")
    name = str(fm.get("name") or new_entity.get("name") or change["id"])
    fields = {k: new_entity.get(k) or [] for k in ("key_facts", "history_entries", "links", "open_questions")}
    record = entity_article.record_sections(strip_claims_block(original), str(entity_type), fields)
    inputs = entity_article.build(
        name=name, entity_type=str(entity_type), frontmatter=fm, original_body=original, record=record,
        incoming=new_entity, today=context["today"], update_days=_change_dates(change), owner=context["owner"],
        linkable=_linkable(original, record, context["names"], context["known"]))
    # A hub page's record (the owner's: thousands of activity claims) is more than one prompt holds: the writer gets
    # its strongest inputs (`entity_article.fit`); the record below the article keeps every one.
    inputs = entity_article.fit(inputs, max_chars=context["max_chars"], people=context.get("people") or ())
    prompt = entity_article.prompt(inputs, max_chars=context["max_chars"])
    if prompt is None:
        return None
    return {"inputs": inputs, "prompt": prompt, "name": name,
            "aliases": [str(a) for a in fm.get("aliases") or [] if a], "known": context["known"]}


def _page_job(change: dict, existing_by_id: dict[str, dict], settings: Settings,
              article_context: dict | None = None) -> dict | str | None:
    """What Stage 3 asks the engine about one update, decided without a call: ``None`` when the page gets no call,
    ``"reread"`` for a re-read that says nothing new, else the call's inputs. A function of the change and the
    pages as they were read before the stage — never of another page's answer — which is what lets the calls
    overlap (`_overlap_pages`).

    ``article_context`` (``page_articles_enabled``): a machine page resting on 2+ conversations gets the article
    writer's one call in place of the synthesis call (`entity_article`); a one-conversation page and one whose inputs
    are over the budget get no write call (the deterministic merge). A page that already has its stamped Article is
    never handed to the summary or legacy rewrite, setting on or off: those replace the lead the writer owns."""
    entity_id = change["id"]
    existing_entity = existing_by_id.get(entity_id)
    if not existing_entity:
        return None
    new_entity = change.get("entity", {}) or {}
    new_desc = (new_entity.get("description") or "").strip()
    new_history = new_entity.get("history_entries", []) or []
    fm0 = existing_entity.get("frontmatter", {}) or {}
    page_sections = entity_body.parse_sections(_strip_claims(existing_entity.get("body", "")))
    has_article = entity_article.stamped(fm0, page_sections)
    if article_context is not None or has_article:
        # The contradiction check reads what the update says about the thing: Stage 1 fills `summary` (an older
        # payload, `description`), so an article page's check does not depend on which one it filled.
        new_desc = _entity_summary(new_entity)
    if article_context is not None:
        if _is_human_edited(fm0, page_sections):
            return None
        if not (_entity_summary(new_entity) or new_history or any(
                new_entity.get(k) for k in ("key_facts", "links", "open_questions"))):
            return None
        sources = set(_change_source_episodes(change))
        if (sources and not sources - set(fm0.get("source_episodes") or [])
                and not entity_body.adds_anything(existing_entity.get("body", ""), _entity_summary(new_entity),
                                                  new_entity.get("key_facts") or [])):
            return "reread"
        writer = None
        if entity_article.eligible(fm0, sources):
            writer = _article_job(change, existing_entity, new_entity, article_context)
        if writer is None and not has_article and not entity_article.eligible(fm0, sources):
            has_article = True   # a stub: the deterministic merge, no write call
        if writer is None and not has_article:
            article_context = None   # over budget, never written: today's path below
        else:
            change_days = _change_dates(change)
            if writer is None and not new_desc:
                return None
            return {
                "change": change, "new_entity": new_entity, "new_desc": new_desc, "new_history": new_history,
                "section_aware": False, "existing_body": existing_entity.get("body", ""),
                "entity_type": new_entity.get("type") or fm0.get("type", "concept"),
                "entity_name": new_entity.get("name") or fm0.get("name", entity_id),
                "page_said": _extract_date_string(fm0.get("last_referenced")), "change_days": change_days,
                "source_reference_date": _latest_change_date(change) or (change_days[-1] if change_days else None),
                "article": writer, "no_rewrite": writer is None,
            }
    section_aware = getattr(settings, 'summary_synthesis_enabled', False)
    if section_aware:
        new_desc = _entity_summary(new_entity)
        if _is_human_edited(existing_entity.get('frontmatter', {}),
                            entity_body.parse_sections(existing_entity.get('body', ''))):
            return None
    if not new_desc and not new_history and not (section_aware and any(
            new_entity.get(k) for k in ('key_facts', 'links', 'open_questions'))):
        return None

    existing_body = existing_entity.get("body", "")
    fm = existing_entity.get("frontmatter", {}) or {}
    sources = set(_change_source_episodes(change))
    if (sources and not sources - set(fm.get("source_episodes") or [])
            and not entity_body.adds_anything(existing_body, _entity_summary(new_entity),
                                              new_entity.get("key_facts") or [])):
        # A re-read of conversations the page already credits (a resumed conversation, G104) in which
        # every summary sentence and fact is one the page already holds: nothing to rewrite or re-check.
        # A re-read that brings anything else still gets both calls.
        return "reread"
    change_days = _change_dates(change)
    return {
        "change": change,
        "new_entity": new_entity,
        "new_desc": new_desc,
        "new_history": new_history,
        "section_aware": section_aware,
        "existing_body": existing_body,
        "entity_type": new_entity.get("type") or fm.get("type", "concept"),
        "entity_name": new_entity.get("name") or fm.get("name", entity_id),
        "page_said": _extract_date_string(fm.get("last_referenced")),
        "change_days": change_days,
        # The prompt's fallback line may use a day recovered from an id; the stored fields never do.
        "source_reference_date": _latest_change_date(change) or (change_days[-1] if change_days else None),
        "no_rewrite": has_article,
    }


def _strip_claims(body: str) -> str:
    from api.services.claims import strip_claims_block

    return strip_claims_block(body or "")


async def _write_article(job: dict, settings: Settings) -> dict | None:
    """The article writer's one call (`entity_article`): ``entity_article.payload`` for Stage 5, or ``None`` when
    the answer is not a valid article (the page keeps the deterministic merge, no retry)."""
    writer = job["article"]
    completion = _litellm().acompletion
    llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model, completion=completion,
                            stage="merge")
    response = await llm_fn(messages=[{"role": "user", "content": writer["prompt"]}],
                            response_format={"type": "json_object"})
    raw = json_parse.parse_json_object(response.choices[0].message.content)
    written = entity_article.parse(raw, writer["inputs"], name=writer["name"], aliases=writer["aliases"],
                                   known=writer["known"])
    if written is None:
        logger.debug(f"Article for {job['change']['id']}: not a valid article; the page keeps the merge")
        return None
    if written.dropped:
        logger.debug(f"Article for {job['change']['id']}: left out {written.dropped}")
    return entity_article.payload(writer["inputs"], written, name=writer["name"], aliases=writer["aliases"])


async def _decide_page(job: dict, settings: Settings, cycle_day: str) -> tuple[str | None, dict | None]:
    """One page's calls, in their serial order: the synthesis, then (with a description) the contradiction check.
    Returns ``(synthesized body, contradiction payload)``; writes nothing and touches no other page."""
    entity_id = job["change"]["id"]
    synthesized = None
    try:
        if job.get("article"):
            synthesized = await _write_article(job, settings)
        elif job.get("no_rewrite"):
            synthesized = None   # an article page or a stub: the deterministic merge
        else:
            synthesized = await _synthesize_entity_update(
                entity_name=job["entity_name"],
                entity_type=job["entity_type"],
                existing_body=job["existing_body"],
                new_description=job["new_desc"],
                new_history_entries=job["new_history"],
                source_reference_date=job["source_reference_date"],
                settings=settings,
                page_last_referenced=job["page_said"],
                source_dates_seen=job["change_days"],
                today=cycle_day,
                new_fields=job["new_entity"] if job["section_aware"] else None,
            )
    except engine_errors.EngineError:
        # G74(a), M2: an ENGINE failure is not "nothing to synthesize" —
        # flattening it here let a partial throttle silently skip
        # synthesis for every entity while the cycle still committed and
        # reported "Completed". Propagate so the cycle stops with the
        # episode queue intact, same contract as the resolver's judge.
        raise
    except Exception as e:
        logger.debug(f"Synthesis failed for {entity_id}: {e}")

    if not job["new_desc"]:
        return synthesized, None

    try:
        contradiction = await _detect_contradiction(
            entity_name=job["entity_name"],
            existing_body=job["existing_body"],
            new_description=job["new_desc"],
            settings=settings,
            existing_as_of=job["page_said"],
            new_as_of=job["change_days"],
            today=cycle_day,
        )
    except engine_errors.EngineError:
        # Same reasoning as the synthesis branch above: an engine failure
        # must not be read as "no contradiction found".
        raise
    except Exception as e:
        logger.debug(f"Contradiction check failed for {entity_id}: {e}")
        contradiction = None
    return synthesized, contradiction


async def _overlap_pages(jobs: list, run, *, concurrency: int, cancel_check=None, on_done=None) -> dict[int, object]:
    """Run ``run(job)`` for each job with at most ``concurrency`` in flight; ``{index: result}`` for each finished.

    Jobs start in list order — ``concurrency`` workers take the next one — so 1 is the serial loop. Before each
    start ``cancel_check`` is polled; once it says stop, or any job raises, nothing new starts and the jobs in
    flight are waited out (a plan call runs in a worker thread and is never interrupted; none outlives the stage).
    Then the error of the EARLIEST job that raised is re-raised, the same object: every job before it started and
    finished, so it is the error the serial loop would have met first (a plan limit is still the drain's pause)."""
    results: dict[int, object] = {}
    errors: dict[int, BaseException] = {}
    state = {"next": 0, "stopped": False}

    async def worker() -> None:
        while not state["stopped"] and state["next"] < len(jobs):
            if cancel_check is not None and cancel_check():
                state["stopped"] = True
                return
            index = state["next"]
            state["next"] += 1
            try:
                results[index] = await run(jobs[index])
            except Exception as exc:  # noqa: BLE001 - re-raised below, after the jobs in flight finish
                errors[index] = exc
                state["stopped"] = True
                return
            if on_done is not None:
                on_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(max(1, concurrency), len(jobs)))]
    try:
        await asyncio.gather(*workers)
    finally:
        state["stopped"] = True
        for task in workers:
            if not task.done():
                task.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
    if errors:
        raise errors[min(errors)]
    return results


def apply_changes(changes: list[dict], memory_path) -> None:
    """Write entity changes to disk."""
    entities_dir = memory_path / "entities"

    write_progress = tqdm(
        total=len(changes),
        desc="Stage 5: write",
        unit="ent",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}",
        leave=True,
        disable=len(changes) == 0,
    )
    # `graph_edges.yaml`, read once on the first update that needs it: nothing in this loop writes it
    # (`inbox_generator.generate` merges new edges after), and it grows with the bank — one read per merged entity
    # was most of a Sleep batch on a 2,000-page bank.
    edges_by_entity: dict[str, list[dict]] | None = None
    untimed_ids: frozenset[str] | None = None   # the bank's memory-export ids, read on the first settle
    for change in changes:
        write_progress.update(1)
        entity_id = change["id"]
        action = change["action"]
        filepath = entities_dir / f"{entity_id}.md"

        learned = change.get("learned_on") or str(date.today())
        if action == "create":
            entity = change.get("entity", {})
            created_date = _earliest_change_date(change) or str(date.today())
            last_referenced = _latest_change_date(change) or created_date
            # The closed type set, held again where the page is born (`entity_types`): a pending line or a payload
            # read before the extraction rail existed may still carry `organization`.
            entity_type = entity_types.in_set(entity.get("type"))
            # Stage-1 may PROPOSE a class; `agent_class` re-applies the rail here
            # so an `evergreen` that slipped past extraction can never be written.
            decay_class = (
                decay_policy.agent_class(entity.get("decay_class"))
                or decay_policy.default_class_for(entity_type)
            )
            frontmatter = {
                "name": entity.get("name", entity_id.replace("-", " ").title()),
                "type": entity_type,
                "status": "active",
                "confidence": entity.get("confidence", 0.5),
                "created": created_date,
                # Heard only in a memory export entry: never mentioned in a conversation, so no last mention,
                # and its silence clock starts the day Cicada learned it.
                **({"decayed_through": learned} if change.get("untimed") else {
                    "last_referenced": last_referenced,
                    # Age counts from when it was said: nothing is charged before the mention, and the decay
                    # pass of the run that read it charges the silence since (`decay_policy.silence`).
                    "decayed_through": last_referenced,
                    "learned_on": learned,
                }),
                **decay_policy.frontmatter_fields(decay_class),
                "source_episodes": _change_source_episodes(change),
                "tags": entity.get("tags", []) or [],
                # A reference ("the lock", "my app") is not a name: kept, it would draw this page to every judge
                # call those common words recur in (`alias_policy`).
                "aliases": alias_policy.keep(entity.get("aliases", []) or []),
                "related": [],
                "version": 1,
                "layout_version": 2,
                # A person known only by their relation to the owner: the relation, and no name yet (`role_people`).
                **role_people.create_fields(entity),
            }
            # G61 S3-b: Stage 1's optional official site is stored UNVERIFIED (`fact_sources.propose_site`: pure, no
            # network, never over a tombstone or an existing `website`); Cicada's own read confirms it later and only
            # a trusted site ever draws a picture. `added_by: agent` — this seam is not handed the engine's model id
            # (the commit's `Cicada-Author` still names it).
            if entity.get("website") and str(entity_type).lower() in ("company", "tool", "project"):
                fact_sources.propose_site(frontmatter, str(entity["website"]), added_by="agent")
            body = entity_body.compose_body_v2(
                summary=_entity_summary(entity),
                key_facts=entity.get("key_facts", []) or [],
                history_entries=entity.get("history_entries", []) or [],
                related=[],
                links=entity.get("links", []) or [],
                open_questions=entity.get("open_questions", []) or [],
                name=frontmatter['name'], entity_type=entity_type,
            )
            section_provenance.refresh(frontmatter, "", body,
                _selected_page_inputs(entity, entity_body.parse_sections(body)))
            if change.get("settle"):
                untimed_ids = _untimed_once(untimed_ids, memory_path)
                _settle(frontmatter, change["settle"], untimed_ids)
            markdown_parser.write(filepath, frontmatter, body)

        elif action == "update" and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            # A memory export entry alone is no re-mention ("facts yes, activity no", `episode_time`): its facts
            # and source land below, but the last mention, the silence clock and the status stay.
            mentioned = not change.get("untimed")
            lift = False
            if mentioned:
                fm = parsed.frontmatter
                known = {str(ep) for ep in decay_policy._as_list(fm.get("source_episodes"))}
                said_before = _extract_date_string(fm.get("last_referenced"))
                charged = _extract_date_string(fm.get("decayed_through"))
                heard = _latest_change_date(change) or str(date.today())
                said = _max_date(said_before, heard)
                fm["last_referenced"] = said
                if decay_policy.owed(said_before, charged, _extract_date_string(fm.get("learned_on"))):
                    # Not yet settled (read earlier in this run, or in one that stopped): age counts from the
                    # latest mention, and the decay pass that settles it charges from there.
                    if said_before is None or said > said_before:
                        fm["learned_on"] = _max_date(_extract_date_string(fm.get("learned_on")), learned)
                elif charged is None or heard >= charged:
                    # A settled page mentioned in a conversation no charge has covered yet: the counter-signal
                    # to decay. Recovery (G66 §1.6) — `dropped` is deliberately excluded: the person dismissed
                    # that entity and it is never resurfaced. Its clock restarts when it was said; the gap until
                    # Cicada read it is proven silence, charged once by the pass that settles it — never below
                    # where the page stood before the mention (`MENTION_FLOOR_KEY`). The revival is
                    # `max(current, 0.6)` whatever the status (read on time, owner 2026-10-16): a mention read late
                    # lifts an active page as far, so when a conversation is read never changes where a page ends.
                    evergreen = decay_policy.resolve(fm)[0] is DecayClass.evergreen
                    if not evergreen:
                        fm.setdefault(MENTION_FLOOR_KEY, float(fm.get("confidence", 0.0) or 0.0))
                    status = str(fm.get("status", "active"))
                    if status in ("decaying", "archived"):
                        fm["status"] = "active"
                    # An evergreen page never decays, so an active one stays where it is; a decaying or archived
                    # one (hand-archived, or settled before it became evergreen) is revived as before (G66 §1.6).
                    if status in ("decaying", "archived") or (status == "active" and not evergreen):
                        fm["confidence"] = max(float(fm.get("confidence", 0.0) or 0.0), RECOVERY_CONFIDENCE)
                    fm.pop(decay_policy.FADED_BY_AGE_KEY, None)   # back in the person's words: asked like any page
                    fm["decayed_through"] = _max_date(charged, heard)
                    fm["learned_on"] = learned
                else:
                    # A conversation from before the watermark, read late (a newly connected source's history, an
                    # export imported later): it counts as if Cicada had read it the day it was said (owner
                    # 2026-10-16) — revived that day and charged the silence since, never lower than the page
                    # stands. Placed by the decay pass (`_revive_on_time`, from `READ_LATE_KEY`), so nothing is
                    # charged mid-drain; the clock and `learned_on` stay, the watermark already covers the days
                    # since. If it makes a one-off faded by its age a repeat, the repeat floor applies below too.
                    untimed_ids = _untimed_once(untimed_ids, memory_path)
                    late = _new_mention_day(change, known, untimed_ids)
                    if late and decay_policy.resolve(fm)[0] is not DecayClass.evergreen \
                            and str(fm.get("status", "active")) in _STATUS_RANK:
                        fm[decay_policy.READ_LATE_KEY] = _max_date(
                            _extract_date_string(fm.get(decay_policy.READ_LATE_KEY)), late)
                    lift = bool(fm.get(decay_policy.FADED_BY_AGE_KEY))
            parsed.frontmatter["version"] = parsed.frontmatter.get("version", 1) + 1

            episodes = parsed.frontmatter.get("source_episodes", [])
            for source_ep in _change_source_episodes(change):
                if source_ep and source_ep not in episodes:
                    episodes.append(source_ep)
            parsed.frontmatter["source_episodes"] = episodes

            # Merge new tags
            new_entity = change.get("entity", {})
            new_tags = new_entity.get("tags", []) or []
            if new_tags:
                existing_tags = set(parsed.frontmatter.get("tags", []) or [])
                parsed.frontmatter["tags"] = sorted(existing_tags | set(new_tags))

            # Merge new aliases
            # Only Sleep's NEW aliases are filtered: what the page already lists (a hand-added one too) stays.
            new_aliases = alias_policy.keep(new_entity.get("aliases", []) or [])
            # G198: an alias an edit removed stays removed (`aliases_removed`, like `sources_removed`).
            new_aliases = page_edits.keep_aliases(parsed.frontmatter, new_aliases)
            if new_aliases or parsed.frontmatter.get("aliases"):
                existing_aliases = parsed.frontmatter.get("aliases", []) or []
                merged_aliases = list(existing_aliases)
                seen = {a.lower() for a in merged_aliases}
                for alias in new_aliases:
                    if alias and alias.lower() not in seen:
                        merged_aliases.append(alias)
                        seen.add(alias.lower())
                parsed.frontmatter["aliases"] = merged_aliases

            # M5e rule 3c (§8): on a HUMAN-EDITED page the agent may never
            # regenerate-away human prose. Detect human-editedness from the RAW
            # body (the lossy v2 lift folds non-canonical hand-added headings
            # into Key Facts, so the detector + preservation must run BEFORE the
            # lift). A page is human-edited if frontmatter says so, or the raw
            # body carries a non-canonical H2 the agent pipeline never emits.
            from api.services.claims import preserve_claims_blocks, strip_claims_block

            original_body = parsed.body
            prose_body = strip_claims_block(original_body)
            raw_sections = entity_body.parse_sections(prose_body)
            human_edited = _is_human_edited(parsed.frontmatter, raw_sections)

            synthesized_body = change.get("synthesized_body")
            new_fields = {
                'name': parsed.frontmatter.get('name', entity_id),
                'type': parsed.frontmatter.get('type', 'concept'),
                "summary": _entity_summary(new_entity),
                "key_facts": new_entity.get("key_facts", []) or [],
                "history_entries": new_entity.get("history_entries", []) or [],
                "links": new_entity.get("links", []) or [],
                "open_questions": new_entity.get("open_questions", []) or [],
            }
            # G198: the writer's article with the page's pinned corrections in, records and all.
            article = page_edits.correct_article(parsed.frontmatter, change.get("article"))
            if article and not human_edited:
                # The article writer (`entity_article`): the record merged deterministically, then the lead and
                # the Article it wrote, then what this update's orientation said that the article does not carry.
                sections = entity_article.compose(prose_body, str(parsed.frontmatter.get("type", "concept")),
                                                  new_fields, article)
            elif synthesized_body and not human_edited and change.get('section_aware_synthesis'):
                # Opt-in orientation synthesis: `entity_orientation.compose` already unioned every section.
                sections = entity_body.parse_sections(strip_claims_block(synthesized_body))
            elif synthesized_body and not human_edited:
                # Legacy whole-body synthesis: its Summary and the History it adds; every other item as the
                # page had it, then the extraction's own items. The prompt is given only the description and
                # history, and a rewrite can leave an item out or rephrase it — which used to drop the new
                # facts silently and could drop old ones (G194, page quality 2026-10-09).
                sections = entity_body.adopt_rewrite(
                    entity_body.upgrade_legacy_to_v2(prose_body, str(parsed.frontmatter.get("type", "concept"))),
                    entity_body.parse_sections(strip_claims_block(synthesized_body)))
                sections = entity_body.merge_sections_fallback(sections, {**new_fields, 'summary': ''})
            elif human_edited:
                # Additive-only merge over the RAW sections (preserving every
                # human-authored line, canonical or not, verbatim). The LLM
                # synthesis rewrite is suppressed entirely — the prose-level
                # mirror of "an agent claim may not close a human claim".
                sections = entity_body.merge_sections_human_safe(
                    raw_sections, new_fields, human_edited=True
                )
            else:
                # Agent-only page with no synthesis: deterministic section merge
                # over the lifted v2 sections (unchanged behavior).
                sections = entity_body.upgrade_legacy_to_v2(
                    prose_body, str(parsed.frontmatter.get("type", "concept"))
                )
                sections = entity_body.merge_sections_fallback(sections, new_fields)
            if not human_edited and not article and not entity_article.stamped(parsed.frontmatter, raw_sections):
                sections = entity_body.bound_summary(
                    sections, previous=raw_sections.get('Summary', ''),
                    name=str(parsed.frontmatter.get('name', entity_id)),
                    entity_type=str(parsed.frontmatter.get('type', 'concept')),
                    names=[str(a) for a in parsed.frontmatter.get('aliases') or []])
            # G198: the page's pinned corrections — an edit's fixed words — are written over whatever this update
            # wrote, so Sleep never puts the old words back (Related is rebuilt below and left alone).
            sections = page_edits.apply_corrections_to_sections(parsed.frontmatter, sections)
            parsed.frontmatter["layout_version"] = 2

            # Related reconciler — rebuild the ## Related block from the
            # related slug list + graph_edges.yaml so wikilinks stay in sync.
            if edges_by_entity is None:
                edges_by_entity = _edges_by_entity(memory_path)
            related_block = _reconcile_related(entity_id, parsed.frontmatter, memory_path, edges_by_entity)
            if related_block:
                sections["Related"] = related_block
            else:
                sections.pop("Related", None)

            final_body = preserve_claims_blocks(original_body, entity_body.render_sections(sections))
            # Every path now writes the extraction's exact items (the legacy rewrite's are unioned back in),
            # so each one that survives exactly keeps its source row; a rephrased one stays unrecorded.
            selected = _selected_page_inputs(new_entity, sections, parsed.frontmatter, original_body)
            if article and not human_edited:
                # Each written paragraph carries the evidence of the inputs it cites, under its exact text (G118).
                selected[section_provenance.INPUTS] = list(selected.get(section_provenance.INPUTS) or []) + list(
                    article.get("records") or [])
                # Written the day Cicada read it (the cycle's day — `learned_on` since the age rule).
                entity_article.stamp(parsed.frontmatter, entity_body.parse_sections(strip_claims_block(final_body)),
                                     written=change.get("learned_on") or str(date.today()))
            section_provenance.refresh(parsed.frontmatter, original_body, final_body, selected)
            if lift and change.get("decay_params") and parsed.frontmatter.get(decay_policy.FADED_BY_AGE_KEY):
                untimed_ids = _untimed_once(untimed_ids, memory_path)
                _lift_to_repeat_floor(parsed.frontmatter, change["decay_params"], untimed_ids)
            if change.get("settle") and mentioned:
                untimed_ids = _untimed_once(untimed_ids, memory_path)
                _settle(parsed.frontmatter, change["settle"], untimed_ids)
            markdown_parser.write(filepath, parsed.frontmatter, final_body)

        elif action in ("decay", "decay_nudge", "archive") and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            parsed.frontmatter["confidence"] = change.get("new_confidence", 0.0)
            if "new_status" in change:
                parsed.frontmatter["status"] = change["new_status"]
            # G85 §2 / Wave-1 1.1: stamp the watermark so the NEXT decay pass
            # charges only the interval elapsed since today, not the whole
            # span back to `last_referenced` again. Uses the SAME reference
            # date the decay pass computed against (falls back to the real
            # today for a change dict built outside `resolve_and_prune`).
            parsed.frontmatter["decayed_through"] = change.get("decayed_through") or str(date.today())
            if change.get(decay_policy.FADED_BY_AGE_KEY):
                parsed.frontmatter[decay_policy.FADED_BY_AGE_KEY] = change[decay_policy.FADED_BY_AGE_KEY]
            for key in change.get("clear") or ():
                parsed.frontmatter.pop(key, None)
            markdown_parser.write(filepath, parsed.frontmatter, parsed.body)

    write_progress.close()


# ---------- Helpers ----------


def _untimed_once(untimed_ids: frozenset[str] | None, memory_path) -> frozenset[str]:
    return untimed_ids if untimed_ids is not None else episode_time.untimed_ids(memory_path)


#: What a revived page stood at before the mention, kept only until the pass that settles the mention's gap: the
#: proven silence it charges never takes the page below it (a mention never lowers).
MENTION_FLOOR_KEY = "confidence_before_mention"


def _lift_to_repeat_floor(fm: dict, params: dict, untimed: frozenset[str]) -> None:
    """A one-off its age faded (``faded_by_age``) that an older conversation, read in a later run, makes a repeat:
    where the two conversations read in one run would have left it — the repeat floor less the live silence charged
    since its age was settled — when that is higher. Only raises, so how the imports split across runs never
    changes where a page ends."""
    if decay_policy.conversations(fm.get("source_episodes"), untimed=untimed) < 2:
        return
    if str(fm.get("status", "active")) == "dropped":
        return
    effective = decay_policy.effective(fm, alpha=params["alpha"], floor=params["floor"],
                                       tuning=params.get("tuning") or {}, untimed=untimed)
    if effective.decay_class is DecayClass.evergreen:
        return
    # Live silence from the day its age was settled to today: an archived page is never charged, so its watermark
    # stopped the day it archived and says nothing about the weeks since.
    since = date.fromisoformat(str(fm[decay_policy.FADED_BY_AGE_KEY])[:10])
    today = date.fromisoformat(params["today"])
    lifted = decay_policy.proven_floor(params["nudge"]) - effective.rate * max(0, (today - since).days) / 7.0
    if lifted <= float(fm.get("confidence", 0.0) or 0.0):
        return
    fm["confidence"] = lifted
    fm["decayed_through"] = today.isoformat()   # charged through today: the next pass charges only what follows
    fm["status"] = "archived" if lifted < params["archive"] else "decaying"


def _new_mention_day(change: dict, known: set[str], untimed: frozenset[str]) -> str | None:
    """The day the latest conversation in ``change`` that the page does not already credit was said — a re-read of
    a conversation the page holds, or a memory export entry, is no new mention. ``None`` when there is none."""
    fresh = [ep for ep in _change_source_episodes(change) if ep not in known and ep not in untimed]
    if not fresh:
        return None
    episodes = list(change.get("source_episodes") or [])
    stamps = list(change.get("source_episode_timestamps") or [])
    days: list[str] = []
    if episodes and len(stamps) == len(episodes):
        days = [d for ep, ts in zip(episodes, stamps) if ep in fresh and (d := _extract_date_string(ts))]
    if days:
        return max(days)
    return decay_policy.latest_said(fresh) or _latest_change_date(change)


_STATUS_RANK = {"archived": 0, "decaying": 1, "active": 2}


def _placed_on_time(fm: dict, params: dict, untimed: frozenset[str]) -> dict | None:
    """The decay change that places a page's pending late conversation (``READ_LATE_KEY``) on its day, for a page the
    decay pass does not otherwise touch; ``None`` when it lifts nothing."""
    view = dict(fm)
    late = _extract_date_string(view.pop(decay_policy.READ_LATE_KEY, None))
    if not late:
        return None
    _revive_on_time(view, late, params, untimed)
    if view.get("confidence") == fm.get("confidence"):
        return None
    clear = [decay_policy.READ_LATE_KEY]
    if fm.get(decay_policy.FADED_BY_AGE_KEY) and not view.get(decay_policy.FADED_BY_AGE_KEY):
        clear.append(decay_policy.FADED_BY_AGE_KEY)
    out = {
        "action": "archive" if view.get("status") == "archived" else "decay",
        "new_confidence": view["confidence"], "new_status": view.get("status", "active"),
        "decayed_through": view.get("decayed_through"), "clear": clear,
    }
    if view.get(decay_policy.FADED_BY_AGE_KEY) and not fm.get(decay_policy.FADED_BY_AGE_KEY):
        out[decay_policy.FADED_BY_AGE_KEY] = view[decay_policy.FADED_BY_AGE_KEY]
    return out


def _revive_on_time(fm: dict, said: str, params: dict, untimed: frozenset[str]) -> None:
    """A conversation said before the page's watermark and read late counts as if Cicada had read it the day it was
    said (owner 2026-10-16): revived that day to ``RECOVERY_CONFIDENCE`` and charged the silence since
    (``decay_policy.on_time``) — through the watermark plus at most one pass of live silence for a live page (the next
    pass charges the rest), through today for an archived one (its watermark stopped the day it archived). Only
    raises: a mention never lowers, and a mention from long ago leaves the page where its age puts it. A page the lift leaves below the question line,
    heard late, is ``faded_by_age`` — never asked; one it takes back above the line is asked like any page."""
    status = str(fm.get("status", "active"))
    if status not in _STATUS_RANK:
        return   # dropped (the person dismissed it) or unknown: never resurfaced
    effective = decay_policy.effective(fm, alpha=params["alpha"], floor=params["floor"],
                                       tuning=params.get("tuning") or {}, untimed=untimed)
    if effective.decay_class is DecayClass.evergreen or effective.rate <= 0:
        return
    archived = status == "archived"
    # Through today for an archived page (its watermark stopped the day it archived, so it is never the measure);
    # otherwise the watermark plus at most one pass of live silence (ruling 1), which is what this pass charges.
    through = params["today"] if archived else decay_policy.through_day(
        _extract_date_string(fm.get("decayed_through")), params["today"], MAX_DECAY_DAYS_PER_CYCLE).isoformat()
    lifted = decay_policy.on_time(
        RECOVERY_CONFIDENCE, effective.rate, said, _extract_date_string(fm.get("learned_on")), through,
        conversations=decay_policy.conversations(fm.get("source_episodes"), untimed=untimed),
        nudge_threshold=params["nudge"])
    if lifted is None or lifted <= float(fm.get("confidence", 0.0) or 0.0):
        return
    fm["confidence"] = lifted
    fm["decayed_through"] = through   # charged through here: the next pass charges only what follows
    landed = "active" if lifted >= params["nudge"] else "decaying" if lifted >= params["archive"] else "archived"
    if _STATUS_RANK[landed] > _STATUS_RANK[status]:
        fm["status"] = landed
    if lifted >= params["nudge"]:
        fm.pop(decay_policy.FADED_BY_AGE_KEY, None)   # back above the line on the person's words: asked like any page
    elif decay_policy.heard_late(said, params["today"]):
        fm.setdefault(decay_policy.FADED_BY_AGE_KEY, params["today"])   # its age carried it below: fades quietly


def _settle(fm: dict, params: dict, untimed: frozenset[str]) -> None:
    """Charge a page this decay pass created or referenced the silence its mentions prove (last said ->
    ``learned_on``) — the same arithmetic as the unreferenced-page loop in :func:`resolve_and_prune`, on the page as
    merged. Its live clock starts today, so nothing past ``learned_on`` is charged. Proven silence floors just under
    the question line for a page heard in 2+ conversations (``decay_policy.charge``). Asks nothing; a page heard late
    that it leaves below 0.4 is marked ``faded_by_age`` and fades and archives quietly from here."""
    at_least = fm.pop(MENTION_FLOOR_KEY, None)   # used here once, or never: it never outlives this pass
    late = _extract_date_string(fm.pop(decay_policy.READ_LATE_KEY, None))
    if late:
        _revive_on_time(fm, late, params, untimed)   # a conversation read late, placed on the day it was said
    if str(fm.get("status", "active")) in ("archived", "dropped"):
        return
    effective = decay_policy.effective(fm, alpha=params["alpha"], floor=params["floor"],
                                       tuning=params.get("tuning") or {}, untimed=untimed)
    if effective.decay_class is DecayClass.evergreen or effective.rate <= 0:
        return
    owed = decay_policy.silence(
        _extract_date_string(fm.get("last_referenced")), _extract_date_string(fm.get("decayed_through")),
        _extract_date_string(fm.get("learned_on")), date.fromisoformat(params["today"]), 0)
    if owed is None or owed.days <= 0:
        return
    confidence = decay_policy.charge(
        float(fm.get("confidence", 0.5) or 0.0), effective.rate, owed, nudge_threshold=params["nudge"],
        conversations=decay_policy.conversations(fm.get("source_episodes"), untimed=untimed),
        at_least=at_least)
    fm["confidence"] = confidence
    if confidence < params["nudge"] and decay_policy.heard_late(
            _extract_date_string(fm.get("last_referenced")), _extract_date_string(fm.get("learned_on"))):
        fm.setdefault(decay_policy.FADED_BY_AGE_KEY, params["today"])   # fades quietly from here
    fm["decayed_through"] = owed.watermark.isoformat()
    if confidence < params["archive"]:
        fm["status"] = "archived"
    elif confidence < params["nudge"]:
        fm["status"] = "decaying"


def _selected_page_inputs(entity: dict, sections: dict[str, str],
                          frontmatter: dict | None = None, original_body: str = '') -> dict:
    """Follow exact input text to the one item the bounded writer retained.

    Same-name resolution may move Summary to facts; bounded composition may
    retain that text as Summary instead. Reuse the existing exact carry helper,
    never invent a source or recertify rephrased/uninstrumented text.
    """
    scanned = section_provenance.scan(entity_body.render_sections(sections))
    selected = {
        'summary': next((i.text for i in scanned.get('summary', []) if not i.ambiguous), ''),
        'key_facts': [i.text for i in scanned.get('key_facts', []) if not i.ambiguous],
    }
    # Only currently matched old guards can follow an exact item between the
    # two supported sections. Unmatched/unknown records never enter this map.
    old_records = []
    matched = section_provenance.matched(frontmatter or {}, original_body)
    for field in ('summary', 'key_facts'):
        for item in section_provenance.scan(original_body).get(field, []):
            proof = matched.get(field, {}).get(item.key)
            if proof and not item.ambiguous:
                old_records.append({'field': field, 'text': item.text,
                                    'evidence': [ev.to_dict() for ev in proof[1]]})
    try:
        selected[section_provenance.INPUTS] = section_provenance.merge_selected(
            {section_provenance.INPUTS: old_records}, entity, selected)
    except (KeyError, TypeError, ValueError, AttributeError):
        selected[section_provenance.INPUTS] = section_provenance.merge_selected(
            {section_provenance.INPUTS: old_records}, {}, selected)
    return selected


def _is_human_edited(frontmatter: dict, sections: dict[str, str]) -> bool:
    """Detect a page the human authored/edited (rule 3c, §8).

    A page is treated as human-edited when EITHER the frontmatter carries an
    explicit ``human_edited: true`` flag (set by the manual-edit / companion-app
    write path) OR the lifted body contains a non-canonical hand-added H2 section
    (a heading the agent pipeline never emits). On such a page the agent merge is
    additive-only and the LLM synthesis rewrite is suppressed.
    """
    return entity_body.has_human_prose(frontmatter or {}, sections or {})


def _entity_summary(entity: dict) -> str:
    """The extractor's v2 output uses `summary`; older payloads use `description`."""
    return str(entity.get("summary") or entity.get("description") or "").strip()


def _edges_by_entity(memory_path) -> dict[str, list[dict]]:
    """``graph_edges.yaml`` as each entity's edges, in file order: its own as written, an inbound one mirrored so the
    block reads naturally (a self-loop counts once, as its own). ``{}`` without a file, or when any row cannot be read
    — the per-entity read this replaces dropped every edge then too."""
    edges_file = Path(memory_path) / "graph_edges.yaml"
    by_entity: dict[str, list[dict]] = {}
    if not edges_file.exists():
        return by_entity
    try:
        data = markdown_parser.load_yaml_file(edges_file) or {}
        for edge in data.get("edges", []) or []:
            source, target = edge.get("source"), edge.get("target")
            if isinstance(source, str):
                by_entity.setdefault(source, []).append(edge)
            if isinstance(target, str) and target != source:
                by_entity.setdefault(target, []).append({
                    "source": target, "target": edge.get("source", ""), "label": edge.get("label", ""),
                })
    except Exception:
        return {}
    return by_entity


def _reconcile_related(entity_id: str, frontmatter: dict, memory_path, edges_by_entity: dict[str, list[dict]]) -> str:
    """Rebuild the ``## Related`` block from `related` slugs + graph_edges.yaml.

    Related is a derived view — graph_edges.yaml is canonical, read once per write pass (:func:`_edges_by_entity`).
    Display names are read only for the ids actually referenced, so per-entity cost stays proportional to its degree.
    """
    memory_path = Path(memory_path)
    related_slugs = frontmatter.get("related", []) or []
    edges = list(edges_by_entity.get(entity_id, ()))

    referenced = {str(e.get("target", "")) for e in edges} | {str(s) for s in related_slugs}
    id_to_name: dict[str, str] = {}
    id_to_type: dict[str, str] = {}
    entities_dir = memory_path / "entities"
    for ref in referenced:
        if not ref:
            continue
        filepath = entities_dir / f"{ref}.md"
        if not filepath.exists():
            continue
        try:
            fm = markdown_parser.parse(filepath, ledger=False).frontmatter or {}
            id_to_name[ref] = str(fm.get("name", ref.replace("-", " ").title()))
            id_to_type[ref] = str(fm.get("type") or "")
        except Exception:
            continue

    # Drop dangling references — an edge to a deleted entity shouldn't render.
    edges = [e for e in edges if str(e.get("target", "")) in id_to_name]
    related_slugs = [s for s in related_slugs if str(s) in id_to_name]
    try:   # the bank's own vocabulary decides which labels are facts (`entity_body.relation_family`)
        from api.services import predicates
        normalize = predicates.load_normalizer(memory_path)
    except Exception:  # noqa: BLE001 - no map: the seed's synonyms
        normalize = None
    return entity_body.render_related(related_slugs, edges, id_to_name, id_to_type, normalize)


def _compose_entity_body(description: str, history_entries: list[dict]) -> str:
    """Assemble an entity page body from description + history entries."""
    parts: list[str] = []
    if description.strip():
        parts.append(description.strip())

    if history_entries:
        lines = ["## History"]
        # Sort by date when possible
        def _sort_key(entry):
            return str(entry.get("date", ""))
        for entry in sorted(history_entries, key=_sort_key):
            event_date = str(entry.get("date", "")).strip()
            event = str(entry.get("event", "")).strip()
            if not event:
                continue
            if event_date:
                lines.append(f"- {event_date}: {event}")
            else:
                lines.append(f"- {event}")
        if len(lines) > 1:
            parts.append("\n".join(lines))

    return "\n\n".join(parts).strip()


def _fallback_merge_body(
    existing_body: str, new_description: str, new_history_entries: list[dict]
) -> str:
    """Non-LLM merge used when synthesis is disabled or fails."""
    body = existing_body

    new_desc = (new_description or "").strip()
    if new_desc and len(new_desc) > 50 and new_desc not in body:
        # Insert before any ## History section so prose stays grouped.
        if "## History" in body:
            head, _, tail = body.partition("## History")
            body = f"{head.rstrip()}\n\n{new_desc}\n\n## History{tail}"
        else:
            body = f"{body.rstrip()}\n\n{new_desc}"

    if new_history_entries:
        body = _merge_history_entries(body, new_history_entries)

    return body.strip()


def _merge_history_entries(body: str, new_entries: list[dict]) -> str:
    """Append new history entries to the body's ## History section."""
    new_lines: list[str] = []
    for entry in new_entries:
        event_date = str(entry.get("date", "")).strip()
        event = str(entry.get("event", "")).strip()
        if not event:
            continue
        line = f"- {event_date}: {event}" if event_date else f"- {event}"
        if line in body:
            continue
        new_lines.append(line)

    if not new_lines:
        return body

    if "## History" in body:
        return body.rstrip() + "\n" + "\n".join(new_lines) + "\n"

    return body.rstrip() + "\n\n## History\n" + "\n".join(new_lines) + "\n"


def _change_source_episodes(change: dict) -> list[str]:
    episodes = list(change.get("source_episodes", []) or [])
    fallback = change.get("source_episode", "")
    if fallback and fallback not in episodes:
        episodes.append(fallback)
    return [ep for ep in episodes if ep]


def _extract_date_string(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _latest_change_date(change: dict) -> str | None:
    dates = [
        _extract_date_string(ts)
        for ts in list(change.get("source_episode_timestamps", []) or [])
    ]
    fallback = _extract_date_string(change.get("source_episode_timestamp"))
    if fallback:
        dates.append(fallback)
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _change_dates(change: dict) -> list[str]:
    """Every distinct day the change's information was said, oldest first (G194 A1).

    Stage 1's per-conversation days (``source_episode_days``: the timestamp, else the episode id's date) come first;
    the stored timestamps cover a change built without them. Prompt-only: ``last_referenced``/``created`` still
    come from the timestamps alone (``_latest_change_date``)."""
    dates = [_extract_date_string(d) for d in list(change.get("source_episode_days", []) or [])]
    dates += [_extract_date_string(ts) for ts in list(change.get("source_episode_timestamps", []) or [])]
    dates.append(_extract_date_string(change.get("source_episode_timestamp")))
    return sorted({d for d in dates if d})


def _days_line(days) -> str:
    """Days for a prompt line, oldest first; ``unknown`` when none is known."""
    known = sorted({source_dates.describe(d) for d in days} - {"unknown"})
    return ", ".join(known) if known else "unknown"


def _earliest_change_date(change: dict) -> str | None:
    dates = [
        _extract_date_string(ts)
        for ts in list(change.get("source_episode_timestamps", []) or [])
    ]
    fallback = _extract_date_string(change.get("source_episode_timestamp"))
    if fallback:
        dates.append(fallback)
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def _max_date(left: str | None, right: str | None) -> str | None:
    candidates = [c for c in (left, right) if c]
    return max(candidates) if candidates else None


# The merge prompt in two messages (2026-10-16 perf): the fixed rules as the system message — the same bytes every
# call, so an engine's prompt cache serves them — and the page and its new information as the user message.
# Every line of the one prompt it replaces is in one of the two, in its order within each.
_SYNTHESIS_RULES = """You are updating an entity page in a personal knowledge graph.

INSTRUCTIONS:
1. Merge the new information into the existing page body. The page reads like a short wiki article about this thing as it figures in the person's life.
2. The body is markdown sections in this order: `## Summary`, `## Key Facts`, `## History`, `## Links`, `## Open Questions`. Leave out `## Related` (code rebuilds it). Keep any other section exactly as it is.
3. `## Summary`: one paragraph, 1-3 sentences, at most 600 characters: what it is, what it is to the person (built it, uses it, works with them, is deciding about it) and where it stands as of the latest dated information. Introduce the thing once: never a second sentence that says again what it is. Resolve contradictions by preferring the information with the LATER DATE (under DATES) — not whichever was read last. When the new information is dated earlier than the existing page, it never replaces the page's later statements. Details belong in `## Key Facts`, not in `## Summary`.
4. `## Key Facts`: keep every existing bullet as written. Add a fact from the new information only when no existing bullet already says it, in any words; one fact per bullet, never two bullets for one fact. Never a bullet about the conversation itself ("was mentioned", "asked about").
5. `## History`: add new dated entries in chronological order. Do not duplicate existing entries. If a new fact contradicts an older fact, the Summary takes the latest dated state and the earlier fact becomes a history bullet (e.g., "2026-03-15: Previously used Postgres, switched to SQLite").
6. Preserve every wikilink ([[Entity Name]]) that appears in the existing body.
7. Preserve specific details — dates, names, numbers.
8. If the new information implies a change over time but the extraction did not provide an explicit dated history entry, you may use the source episode date as the fallback date for that change.
9. Write as of when things were said, never as of today. A statement known only from conversations dated more than 90 days before today names its month and year ("In February 2025, …") and is never presented as current. Plans, intentions and states of mind ("considering", "planning", "interested in", "wants", "hopes") always name the month and year they were stated. Keep every date already written on the page. Never write "currently", "now", "recently", "this week" or "soon".

SUMMARY LENGTH (by entity type): skill 1 sentence; person, tool, concept, location 1-2 sentences; project, company 2-3 sentences.

Output ONLY the updated markdown body. Do not include YAML frontmatter, do not wrap in code fences, do not add commentary."""

_SYNTHESIS_INPUT = """ENTITY: {entity_name} (type: {entity_type})

EXISTING PAGE BODY:
{existing_body}

NEW INFORMATION TO INTEGRATE:
Description: {new_description}
New history entries (JSON): {new_history}
Source episode date: {source_reference_date}

DATES (when things were said, and when this is being written):
Today: {today}
The existing page was last mentioned in a conversation dated: {page_last_referenced}
The new information comes from conversation(s) dated: {source_dates}"""


def _owner_line(name: str | None) -> str:
    """G169 — the synthesis prompt's line naming the bank's owner (the same
    convention as Stage 1's ``entity_extractor.owner_block``); empty without an
    owner page."""
    if not name:
        return ""
    from api.services.owner_identity import self_reference_list

    return (
        f'\n\nTHE OWNER: this memory belongs to "{name}". Wherever the existing body or the new information '
        f'means them by {self_reference_list()}, write "{name}".'
    )


async def _synthesize_entity_update(
    entity_name: str,
    entity_type: str,
    existing_body: str,
    new_description: str,
    new_history_entries: list[dict],
    source_reference_date: str | None,
    settings: Settings,
    *,
    page_last_referenced: str | None = None,
    source_dates_seen: list[str] | None = None,
    today: str | None = None,
    new_fields: dict | None = None,
) -> str | None:
    """Call the LLM to merge an existing entity body with new extraction info.

    G194 A1: the prompt also carries today, the day the page was last mentioned and every day the new information was
    said, so "newer" means a later date rather than a later read, and old material is written as of its own date.
    A missing day reads ``unknown`` — never guessed. Prompt guidance only; what is written is unchanged."""
    from api.services.claims import strip_claims_block
    from api.services import entity_orientation

    if getattr(settings, 'summary_synthesis_enabled', False):
        fields = dict(new_fields or {'summary': new_description, 'history_entries': new_history_entries})
        fields.update(name=entity_name, type=entity_type)
        data = entity_orientation.context(
            existing_body, name=entity_name, entity_type=entity_type, fields=fields,
            today=today or date.today().isoformat(),
            source_dates=source_dates_seen or ([source_reference_date] if source_reference_date else []),
            orientation=True)
        try:
            from api.services import owner_identity
            data['owner_instruction'] = _owner_line(owner_identity.owner_name(
                getattr(settings, 'memory_path', None), settings))
        except Exception:  # a missing owner costs the instruction, never the update
            pass
        prompt = entity_orientation.bounded_prompt(data)
        if prompt is None:
            return None
        completion = _litellm().acompletion
        llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model,
                                completion=completion, stage='merge')
        response = await llm_fn(messages=[{'role': 'user', 'content': prompt}])
        try:
            result = json.loads(response.choices[0].message.content or '')
        except (ValueError, TypeError):
            return None
        summary = result.get('summary') if isinstance(result, dict) else None
        if not entity_orientation.valid_summary(summary):
            return None
        restated = entity_orientation.restated_facts(fields, result.get('restated'), summary, existing_body)
        covered = entity_orientation.covered_sentences(existing_body, fields, result.get('covered'), summary)
        if restated or covered:
            logger.debug(f"Synthesis: {len(restated)} incoming fact(s) and {len(covered)} replaced orientation "
                         "sentence(s) restate the page and were not added")
        return entity_orientation.compose(existing_body, fields, summary, restated=restated, covered=covered)

    existing_body = strip_claims_block(existing_body)
    if not existing_body.strip() and not new_description.strip():
        return None

    prompt = _SYNTHESIS_INPUT.format(
        entity_name=entity_name,
        entity_type=entity_type,
        existing_body=existing_body[:6000] or "(empty)",
        new_description=new_description or "(none)",
        new_history=json.dumps(new_history_entries) if new_history_entries else "[]",
        source_reference_date=source_reference_date or "unknown",
        today=source_dates.describe(today or date.today()),
        page_last_referenced=source_dates.describe(page_last_referenced),
        source_dates=_days_line(source_dates_seen or ([source_reference_date] if source_reference_date else [])),
    )
    try:
        from api.services import owner_identity

        prompt += _owner_line(owner_identity.owner_name(getattr(settings, "memory_path", None), settings))
    except Exception:  # noqa: BLE001 - a missing name costs the line, never the merge
        pass
    # Route through the provider factory (CQA-H3) so llm_mode="local" (ollama)
    # and consolidation_model overrides apply uniformly here too. completion
    # stays litellm.acompletion, so this is still awaited exactly as before.
    completion = _litellm().acompletion
    llm_fn = resolve_llm_fn(
        settings, model=settings.effective_consolidation_model,
        completion=completion, stage="merge",
    )
    response = await llm_fn(
        messages=[{"role": "system", "content": _SYNTHESIS_RULES}, {"role": "user", "content": prompt}],
    )
    body = response.choices[0].message.content or ""
    body = body.strip()
    if body.startswith("```"):
        # Strip stray code fences
        body = body.strip("`")
        if body.lower().startswith("markdown"):
            body = body[len("markdown"):]
        body = body.strip()
    return body or None


# Track P R9 — every example in here is a neutral placeholder, never a name.
# This is a module constant built at import, so there is no bank to resolve one
# from; and interpolating a real owner would prime the extractor with a person
# who has nothing to do with the entity it is judging — on a shared or demo
# bank, with somebody else's name.
# The contradiction check in two messages (2026-10-16 perf), as `_SYNTHESIS_RULES`: the fixed definition and answer
# shape as the system message, today and the two descriptions as the user message.
_CONTRADICTION_RULES = """You are checking whether two descriptions of the same entity contain an unresolvable contradiction.

A contradiction is unresolvable when newer information alone does not make it obvious which statement is currently true. For example: two different stacks mentioned across two conversations with no date cue, or two different roles for the same person.

"Newer" means said on a later date (below), not read later: a description from an earlier conversation does not replace a later one, and two statements made months apart can both have been true at their own dates.

Respond with JSON only:
{
  "has_unresolvable_contradiction": true | false,
  "contradiction": "one-sentence description of the contradiction, or empty",
  "question": "ONE short question, in the user's voice, that resolves it (e.g. 'Where does the owner work now?'). Empty when there is no contradiction.",
  "options": [
    {"label": "the existing claim, 1-4 words", "description": "one short clause saying where this came from and when"},
    {"label": "the new claim, 1-4 words", "description": "one short clause saying where this came from and when"},
    {"label": "Both are true (different contexts)", "description": "Keep both, each tagged with its context"}
  ]
}

If there is no contradiction, set has_unresolvable_contradiction to false, question to "", and options to []."""

_CONTRADICTION_INPUT = """TODAY: {today}

ENTITY: {entity_name}

EXISTING DESCRIPTION (last mentioned in a conversation dated {existing_as_of}):
{existing_body}

NEW DESCRIPTION (from conversation(s) dated {new_as_of}):
{new_description}"""


_BOTH_OPTION = {
    "key": "both",
    "label": "Both are true (different contexts)",
    "description": "Keep both claims, each tagged with its context",
    "claim_id": None,
}


def build_entity_question(entity_name: str, raw: dict | None, today: str) -> dict:
    """Normalize an LLM contradiction payload into the G60 question object.

    The entity path has no claims behind its options (it compares page bodies),
    so every option carries ``claim_id: None`` and the item keys on the literal
    predicate ``"description"``. A missing/blank ``question`` or a flat
    ``options: [str]`` payload degrades to the deterministic template rather
    than producing a card with no question — under-specifying is safe here.
    """
    from api.services import predicates

    raw = raw or {}
    question = str(raw.get("question", "") or "").strip()
    if not question:
        question = predicates.predicate_question("description", entity_name)

    options: list[dict] = []
    for key, item in zip(("a", "b"), raw.get("options") or []):
        if isinstance(item, dict):
            label = str(item.get("label", "") or "").strip()
            description = str(item.get("description", "") or "").strip()
        else:
            label = str(item).strip()
            description = ""
        if not label or label == _BOTH_OPTION["label"]:
            continue
        options.append({
            "key": key,
            "label": label,
            "description": description or f"Described on the page as of {today}",
            "claim_id": None,
            "observed_at": today,
            "last_referenced": today,
        })

    options.append(dict(_BOTH_OPTION))
    return {"question": question, "options": options}


async def _detect_contradiction(
    entity_name: str,
    existing_body: str,
    new_description: str,
    settings: Settings,
    *,
    existing_as_of: str | None = None,
    new_as_of: list[str] | None = None,
    today: str | None = None,
) -> dict | None:
    """Call the LLM to check whether existing and new descriptions contradict.

    G194 A1: both descriptions carry the day they were said, and the prompt carries today."""
    from api.services.claims import strip_claims_block

    prompt = _CONTRADICTION_INPUT.format(
        entity_name=entity_name,
        existing_body=strip_claims_block(existing_body)[:4000],
        new_description=new_description[:2000],
        today=source_dates.describe(today or date.today()),
        existing_as_of=source_dates.describe(existing_as_of),
        new_as_of=_days_line(new_as_of or []),
    )
    completion = _litellm().acompletion
    llm_fn = resolve_llm_fn(
        settings, model=settings.effective_consolidation_model,
        completion=completion, stage="conflict",
    )
    response = await llm_fn(
        messages=[{"role": "system", "content": _CONTRADICTION_RULES},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    return json_parse.parse_json_object(raw)

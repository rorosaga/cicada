"""Every conversation tied to a project, and why (TODO ruling 45, Q8 and the addendum's fifth and sixth signals).

A conversation is tied by one of these, **never by co-occurrence** (a word close to the name, a person who also
appears in the project — that would pull in every conversation with a frequent collaborator):

==========  =======================================================================================================
``repo``    the hook observed the session in a checkout of the project's repository (``project_birth.repo_match``,
            or the birth's own repository family) — a fact the harness recorded (G110 D2)
``named``   the person's own turn names the project (its name or an alias, a whole word), located exactly, never
            fuzzy (G118) — only the person's turns, never an agent's reply
``claims``  Sleep wrote a claim on the project (or a sub-project) citing the conversation
``added``   the person or an agent tied it by hand (``conversations_added``)
``provider``  the conversation carries its provider's project id, which the page records (a ChatGPT ``g-p-`` id, a
            Claude project's): "In your <provider> project"
``relay``   a connected app's agent said which project the relayed conversation belongs to (its word, ``evidence_kind:
            assistant``): "the app said"
==========  =======================================================================================================

``conversations_removed`` overrides all of them, and no automatic signal re-adds an untied conversation.

**Cost.** ``named`` needs the conversations' text: the FTS passage index answers which episodes hold the name (one
MATCH per name), and only those are opened to check that the person said it. While the index builds, a raw scan
reads at most :data:`MAX_RAW_SCAN` episodes and the reply says ``partial`` (the timeline's ``_unpin_degraded`` rule).
Pure and engine-free; writes nothing.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from api.services import authorship, evidence, project_birth, project_ownership, promotion, search_index
from api.services.project_timeline import ACTIVITY_DAYS, _Bank, _claim_episodes, _conv_key, _conversation, _ep_day, _sort_ts, _tree

SIGNALS = ("repo", "named", "claims", "added", "provider", "relay")
MAX_RAW_SCAN = 400
MAX_FTS_HITS = 2000
PAGE_SIZE = 50
PROVIDER_LABELS = {"chatgpt": "ChatGPT", "claude": "Claude"}
_EP_KEY = "provider_project"


def _names(fm: dict, stem: str) -> list[str]:
    return project_birth._names({"name": fm.get("name") or stem, "aliases": fm.get("aliases") or []})


def _phrase(name: str) -> str | None:
    words = re.findall(r"\w+", name.lower())
    return '"' + " ".join(words) + '"' if words else None


def _fts_candidates(memory_path: Path, names: list[str]) -> set[str] | None:
    """Episode ids whose text holds one of the names as a phrase, or ``None`` when the index cannot answer."""
    if search_index.ensure_fresh(memory_path) != "ready":
        return None
    out: set[str] = set()
    try:
        with search_index.Reader(memory_path) as r:
            for name in names:
                phrase = _phrase(name)
                if phrase is None:
                    continue
                rows = r.passages(phrase, MAX_FTS_HITS, recent_first=True)
                docs = r.docs(sorted({d for _, d, *_ in rows}))
                out.update(d.ref for d in docs.values() if d.kind == "episode")
    except (sqlite3.Error, OSError):
        return None
    return out


def person_named(text: str, pattern: re.Pattern, fm: dict) -> bool:
    """The person's own turn holds the name as a whole word (exact, any case; never fuzzy, never an agent's turn)."""
    gaps = evidence.gap_ranges(fm, text)
    for turn in evidence.turns(text, override=authorship.of(fm), gaps=gaps):
        if turn.role not in promotion.person_kinds(fm):   # a group member's line is not the person's
            continue
        for m in pattern.finditer(text, turn.content_start, turn.end):
            if not evidence.touches_gap(m.start(), m.end(), gaps):
                return True
    return False


def _provider_ids(fm: dict) -> set[tuple[str, str]]:
    return {(str(r["provider"]), str(r["id"])) for r in project_ownership.provider_projects(fm)}


def ep_provider(efm: dict) -> tuple[str, str] | None:
    raw = efm.get(_EP_KEY)
    if isinstance(raw, dict) and raw.get("provider") and raw.get("id"):
        return str(raw["provider"]), str(raw["id"])
    return None


def ep_relay_project(efm: dict) -> str | None:
    relay = efm.get("relay")
    name = relay.get("project") if isinstance(relay, dict) else None
    return " ".join(str(name).split()) if isinstance(name, str) and name.strip() else None


def tie_reasons(memory_path: Path, stem: str, *, tz_name: str | None, bank: _Bank | None = None
                ) -> tuple[dict[str, set[str]], bool]:
    """``({episode: {signal, …}}, partial)`` for every conversation tied to the project, untied ones dropped."""
    bank = bank or _Bank(memory_path, tz_name)
    fm = bank.fm(stem)
    tree = _tree(bank, stem)[0]
    reasons: dict[str, set[str]] = {}

    def add(ep: str, signal: str) -> None:
        if ep in bank.episodes:
            reasons.setdefault(ep, set()).add(signal)

    # repo: the hook's own observation, read from frontmatter only.
    entity = {"name": fm.get("name") or stem, "aliases": fm.get("aliases") or []}
    born = fm.get("born") if isinstance(fm.get("born"), dict) else {}
    family = str(((born or {}).get("repo") or {}).get("family") or "")
    # G110 D2a: a shared hashed remote ties nothing by itself (`_Bank.page_repo_families`): a renamed checkout judged
    # the same carries the page's alias, and the name rule below ties it.
    for ep, f in bank.episodes.items():
        efm = f.frontmatter or {}
        if "workspace_identity" not in efm:
            continue
        repo = project_birth.observed_repo(efm)
        if repo is None:
            continue
        if (family and str(repo["family"]) == family) or project_birth.repo_match(entity, efm) is not None:
            add(ep, "repo")
    # claims: what Sleep (or an agent) wrote about the project, citing the conversation.
    for page in tree:
        for c in bank.claims(page):
            for ep in _claim_episodes(c):
                add(ep, "claims")
    # added: tied by hand.
    for ep in project_ownership.tied(fm, project_ownership.ADDED_KEY):
        add(ep, "added")
    # provider and relay: the provider's own grouping, the relaying app's word.
    ids = _provider_ids(fm)
    folds = {project_birth.fold(n) for n in _names(fm, stem)}
    for ep, f in bank.episodes.items():
        efm = f.frontmatter or {}
        if ids and (p := ep_provider(efm)) is not None and p in ids:
            add(ep, "provider")
        if (said := ep_relay_project(efm)) is not None and project_birth.fold(said) in folds:
            add(ep, "relay")
    # named: the person's own words, found through FTS, checked in the text.
    partial = False
    names = _names(fm, stem)
    pattern = project_birth._name_pattern(entity)
    if pattern is not None and names:
        candidates = _fts_candidates(bank.path, names)
        if candidates is None:
            partial = True
            candidates = set(sorted(bank.episodes)[-MAX_RAW_SCAN:])
            if len(bank.episodes) <= MAX_RAW_SCAN:
                partial = False
        for ep in sorted(candidates):
            f = bank.episodes.get(ep)
            if f is None:
                continue
            text = bank.episode_text(ep)
            if text and pattern.search(text) and person_named(text, pattern, f.frontmatter or {}):
                add(ep, "named")
    for ep in project_ownership.tied(fm, project_ownership.REMOVED_KEY):
        reasons.pop(ep, None)
    bank.partial = bank.partial or partial
    return reasons, partial


def build(memory_path: Path, stem: str, *, tz_name: str | None, offset: int = 0, limit: int = PAGE_SIZE,
          transcript_exists=None):
    """``GET /projects/{id}/conversations``: newest first, grouped by conversation (G104: one episode per session,
    the newest kept when a conversation still has more), each with why it is tied."""
    from api.models.schemas import ProjectConversationRow, ProjectConversations

    bank = _Bank(memory_path, tz_name, transcript_exists)
    reasons, partial = tie_reasons(memory_path, stem, tz_name=tz_name, bank=bank)
    groups: dict[str, str] = {}
    why: dict[str, set[str]] = {}
    for ep, signals in reasons.items():
        key = _conv_key(bank, ep)
        cur = groups.get(key)
        if cur is None or _sort_ts(bank, ep) > _sort_ts(bank, cur):
            groups[key] = ep
        why.setdefault(key, set()).update(signals)
    ordered = sorted(groups.items(), key=lambda kv: (_sort_ts(bank, kv[1]), kv[1]), reverse=True)
    counts = {s: 0 for s in SIGNALS}
    for key, _ in ordered:
        for s in why[key]:
            counts[s] += 1
    rows = []
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or PAGE_SIZE), 200))
    for key, ep in ordered[offset:offset + limit]:
        conv = _conversation(bank, ep)
        if conv is None:
            continue
        efm = bank.episodes[ep].frontmatter or {}
        provider = ep_provider(efm)
        rows.append(ProjectConversationRow(
            **conv.model_dump(), day=_ep_day(bank, ep), why=[s for s in SIGNALS if s in why[key]],
            relayed=isinstance(efm.get("relay"), dict),
            provider_label=PROVIDER_LABELS.get(provider[0], provider[0]) if provider else None,
            manual=ep in project_ownership.tied(bank.fm(stem), project_ownership.ADDED_KEY)))
    return ProjectConversations(project=stem, total=len(ordered), counts=counts, conversations=rows,
                                offset=offset, partial=partial or bank.partial)


def count(memory_path: Path, stem: str, *, tz_name: str | None, bank: _Bank | None = None,
          reasons: dict[str, set[str]] | None = None) -> int:
    bank = bank or _Bank(memory_path, tz_name)
    if reasons is None:
        reasons, _ = tie_reasons(memory_path, stem, tz_name=tz_name, bank=bank)
    return len({_conv_key(bank, ep) for ep in reasons})


def days(bank: _Bank, reasons: dict[str, set[str]]):
    """The tied conversations per local day, each counted ONCE, on its newest episode's day — so a sum over any window
    is a count of distinct conversations (the pulse's "7 conversations"). Only the `ACTIVITY_DAYS` ending at the newest
    day are sent: anchored to the data, never to today (R-PJB6), so the ETag holds across midnight."""
    from api.models.schemas import ActivityDay

    newest: dict[str, str] = {}
    for ep in reasons:
        key = _conv_key(bank, ep)
        cur = newest.get(key)
        if cur is None or _sort_ts(bank, ep) > _sort_ts(bank, cur):
            newest[key] = ep
    per_day: dict[str, int] = {}
    for ep in newest.values():
        if (day := _ep_day(bank, ep)):
            per_day[day] = per_day.get(day, 0) + 1
    if not per_day:
        return []
    floor = (date.fromisoformat(max(per_day)) - timedelta(days=ACTIVITY_DAYS - 1)).isoformat()
    return [ActivityDay(day=d, n=n) for d, n in sorted(per_day.items()) if d >= floor]

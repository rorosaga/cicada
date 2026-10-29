"""The article carries the beliefs (ruling 48 (16), DR-80): where each line of a page came from, as citation markers.

The owner, 2026-10-28, on the first entity mock: *"so many drop down menus … And the what cicada believes list I don't
really like either."* A belief is a sentence of the article with a quiet superscript per source, like an
encyclopedia's citations; a marker opens a popover with who said it, when and the located words; numbered References
close the page.

**Which sentence a source backs is decided when the page is written, never guessed when it is read.** The article
writer (`entity_article`) is handed numbered inputs and returns each paragraph with the inputs it was written from; the
record merge links each Key Fact to its conversation. Both store that as G118 item provenance (``section_provenance``:
per paragraph and per fact, under the item's exact text guard, so an edit unlinks a line instead of recertifying it).
This module only *numbers* that write-time map: one marker per cited line, at the line's end; one reference per source
(a conversation — a session's or an import's episodes together — a looked-up page, another page of the bank), numbered
in reading order. Nothing is matched by similarity and nothing is fetched or asked of a model.

The numbering is derived on read and cached per page (`_TABLES`, keyed by the page file, its ledger and the
``episodes`` directory's own stamps), so a held card costs a dictionary lookup and a changed page is renumbered once.

A page whose prose cites nothing yet but holds beliefs (a stub, or a page written before the article writer) shows
its current beliefs *as sentences* (``beliefs``) — each with its markers, an ended one saying so in its own words, an
agent's inference worded as one — never as a list or a fold. The article writer folds them into prose at its next run.

``detail`` is the popover's lazy read (≤ 80 ms): one marker's best evidence, with the located words.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from api.services import bank_index, claims_ledger, episode_ids, evidence, section_provenance

#: The References shown under the article (DR-80: at most six lines, then a line pointing to History).
MAX_SHOWN_REFS = 6
#: Markers sent with the card. The owner page's record holds tens of thousands of facts; past this many lines the rest
#: of the page is uncited on the card (``markersTotal`` says how many there were) — the agent door and History still
#: hold every source.
MAX_MARKERS = 3000
#: Belief sentences drawn on a page whose prose cites nothing yet (DR-81: an open section is short).
MAX_BELIEFS = 12
#: The sections whose lines the card draws in its article and that carry markers. The Summary is the header's lead
#: (R-DG15) and never carries one.
CITED_SECTIONS = ("article", "key_facts")
#: An evidence row's kind, best first: the located words of the person, then an agent's, then a page's, then a video's;
#: an inference names its conversation without quoting it.
_RANK = {"user": 0, "speaker": 1, "assistant": 2, "page": 3, "media": 4, "reasoning": 5}
_EPISTEMIC_INFERRED = frozenset({"inductive", "abductive"})


@dataclass
class _Ref:
    n: int
    key: str
    kind: str                       # conversation | web | page
    episodes: list[str] = field(default_factory=list)
    title: str = ""
    origin: str | None = None
    harness: str | None = None
    correspondent: str | None = None
    conversation_id: str | None = None
    first: str | None = None
    last: str | None = None


@dataclass
class _Table:
    refs: list[_Ref]
    #: (served offset of the line's end, ref numbers, the line's evidence rows by ref number)
    markers: list[tuple[int, list[int], dict[int, list]]]
    beliefs: list[dict]
    #: How many beliefs the page holds, or None when part of them is in its claims ledger, which a card read never
    #: opens (an owner-sized page's is megabytes): the count would be the fence's alone.
    beliefs_total: int | None
    claim_evidence: dict[str, dict[int, list]]


_TABLES: dict[tuple[str, str], tuple[str, _Table]] = {}
_LOCK = threading.Lock()
_CAPACITY = 64


def _stat(path: Path) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return "-"
    return f"{st.st_mtime_ns}.{st.st_size}"


def _stamp(memory_path: Path, entity_id: str) -> str:
    entities = memory_path / "entities"
    return "|".join((_stat(entities / f"{entity_id}.md"), _stat(entities / f"{entity_id}.claims.jsonl"),
                     _stat(memory_path / "episodes")))


# ---- grouping sources ----------------------------------------------------------------------------------------------


class _Sources:
    """One reference per source, numbered in the order the page first cites it."""

    def __init__(self, memory_path: Path):
        self._memory_path = memory_path
        self.refs: list[_Ref] = []
        self._by_key: dict[str, _Ref] = {}

    def _meta(self, ep_id: str) -> dict:
        # One stat and a cache hit per cited conversation — never a listing of `episodes/` (~20 ms on an owner-scale
        # bank), which a page citing three conversations would otherwise pay on every renumbering.
        indexed = bank_index.file(self._memory_path, "episodes", f"{ep_id}.md")
        try:
            return dict(indexed.frontmatter or {}) if indexed is not None else {}
        except Exception:  # noqa: BLE001 — an unreadable conversation is a source with no title, never a failed card
            return {}

    def ref(self, doc_id: str) -> _Ref | None:
        """The reference for ``doc_id`` (an episode id or a page id), created on first sight."""
        from api.services import web_settle
        from api.services.provenance import _said

        if not doc_id:
            return None
        if not evidence.is_episode_id(doc_id):
            key = f"page:{doc_id}"
            if key not in self._by_key:
                doc = evidence.source_document(self._memory_path, doc_id)
                title = str((doc[0] if doc else {}).get("name") or doc_id)
                self._add(_Ref(n=0, key=key, kind="page", episodes=[doc_id], title=title))
            return self._by_key[key]
        fm = self._meta(doc_id)
        conversation = _opt(fm.get("session_id")) or _opt(fm.get("source_id"))
        key = f"conv:{conversation}" if conversation else f"ep:{doc_id}"
        said = _said(str(fm.get("timestamp") or ""), doc_id)
        ref = self._by_key.get(key)
        if ref is None:
            kind = "web" if str(fm.get("source") or "") == web_settle.SOURCE else "conversation"
            correspondent = fm.get("correspondent")
            ref = self._add(_Ref(
                n=0, key=key, kind=kind, title=str(fm.get("title") or ""),
                origin=_opt(fm.get("origin")) or _opt(fm.get("source")), harness=_opt(fm.get("harness")),
                correspondent=_opt(correspondent.get("name")) if isinstance(correspondent, dict) else None,
                conversation_id=conversation))
        if doc_id not in ref.episodes:
            ref.episodes.append(doc_id)
            if said:
                # By instant, never by string (G114 R2): a bank holds naive, `Z` and `+00:00` stamps side by side.
                when = episode_ids.timestamp_sort_key
                ref.first = said if ref.first is None or when(said) < when(ref.first) else ref.first
                ref.last = said if ref.last is None or when(said) > when(ref.last) else ref.last
        return ref

    def _add(self, ref: _Ref) -> _Ref:
        ref.n = len(self.refs) + 1
        self.refs.append(ref)
        self._by_key[ref.key] = ref
        return ref


def _opt(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _group(sources: _Sources, rows) -> dict[int, list]:
    """Evidence rows by the reference they cite, in first-cited order."""
    out: dict[int, list] = {}
    for ev in rows:
        ref = sources.ref(ev.episode)
        if ref is not None:
            out.setdefault(ref.n, []).append(ev)
    return out


# ---- the table -----------------------------------------------------------------------------------------------------


def inferred(claim) -> bool:
    """An agent's inference rather than something said or looked up: its reasoning was inductive or abductive, or it
    is an agent's reflection — worded as such wherever it is drawn (DR-80)."""
    return (str(getattr(claim, "epistemic", "") or "") in _EPISTEMIC_INFERRED
            or str(getattr(claim, "source_trust", "") or "") == "agent_reflected")


def _belief_rows(claims, sources: _Sources) -> tuple[list[dict], int, dict[str, dict[int, list]]]:
    from api.services.claims import Evidence, is_current, is_event, is_persons_words, is_record

    kept = []
    for c in claims or []:
        if is_record(c) or c.superseded_by or getattr(c, "recovered_by", None) or is_event(c):
            continue
        if is_current(c) or c.valid_to:
            kept.append(c)
    rows, evidence_by = [], {}
    for c in kept[:MAX_BELIEFS]:
        evs = list(c.evidence or [])
        cited = {ev.episode for ev in evs}
        evs += [Evidence(episode=e) for e in (c.source_episodes or []) if e and e not in cited]
        grouped = _group(sources, evs)
        evidence_by[c.id] = grouped
        rows.append({"claimId": c.id, "text": str(c.text or "").strip(), "refs": list(grouped),
                     "until": str(c.valid_to)[:10] if c.valid_to else None, "inferred": inferred(c),
                     "verbatim": bool(is_persons_words(c))})
    return rows, len(kept), evidence_by


def table(memory_path: Path, entity_id: str, *, fm: dict, body: str, claims) -> _Table:
    """The page's markers, references and belief sentences, from the page as read (``body``: the raw body, claims
    fence included). Cached per page stamp; never raises for a malformed provenance record (it cites nothing)."""
    from api.services.claims import served_prose

    memory_path = Path(memory_path)
    key = (str(memory_path), entity_id)
    stamp = _stamp(memory_path, entity_id)
    with _LOCK:
        hit = _TABLES.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    sources = _Sources(memory_path)
    markers: list[tuple[int, list[int], dict[int, list]]] = []
    try:
        _, to_served = served_prose(body)
        matched = section_provenance.matched(fm or {}, body or "")
        lines = []
        for section, items in section_provenance.scan(body or "").items():
            if section not in CITED_SECTIONS:
                continue
            for item in items:
                record = matched.get(section, {}).get(item.key)
                if record and item.ranges:
                    at = to_served(item.ranges[-1][1])
                    if at is not None:
                        lines.append((at, record[1]))
        lines.sort(key=lambda line: line[0])
        for at, rows in lines:
            grouped = _group(sources, rows)
            if grouped:
                markers.append((at, list(grouped), grouped))
    except Exception:  # noqa: BLE001 — provenance that cannot be read is a page with no markers, never a failed card
        markers = []
    beliefs, total, claim_evidence = ([], 0, {})
    if not markers:
        try:
            beliefs, total, claim_evidence = _belief_rows(claims, sources)
        except Exception:  # noqa: BLE001
            beliefs, total, claim_evidence = [], 0, {}
        if beliefs and claims_ledger.STAMP in (fm or {}):
            total = None
    built = _Table(refs=sources.refs, markers=markers, beliefs=beliefs, beliefs_total=total,
                   claim_evidence=claim_evidence)
    with _LOCK:
        if len(_TABLES) >= _CAPACITY:
            _TABLES.pop(next(iter(_TABLES)))
        _TABLES[key] = (stamp, built)
    return built


def _ref_dict(ref: _Ref) -> dict:
    return {"n": ref.n, "kind": ref.kind, "title": ref.title, "origin": ref.origin, "harness": ref.harness,
            "correspondent": ref.correspondent, "first": ref.first, "last": ref.last,
            "episodeId": ref.episodes[-1] if ref.episodes else None, "conversationId": ref.conversation_id}


def block(memory_path: Path, entity_id: str, *, fm: dict, body: str, claims) -> dict | None:
    """The ``citations`` block of ``GET /entities/{id}``: markers as ``[offset, n, …]`` (offsets into the served prose,
    Python ``str`` offsets — the app's row ranges), the first :data:`MAX_SHOWN_REFS` references for the References
    lines, the counts behind its closing line, and the belief sentences of a page whose prose cites nothing yet.
    ``None`` when the page cites nothing at all."""
    t = table(memory_path, entity_id, fm=fm, body=body, claims=claims)
    if not t.refs and not t.beliefs:
        return None
    kinds = [r.kind for r in t.refs]
    return {"markers": [[at, *ns] for at, ns, _ in t.markers[:MAX_MARKERS]],
            "markersTotal": len(t.markers),
            "refs": [_ref_dict(r) for r in t.refs[:MAX_SHOWN_REFS]],
            "total": len(t.refs), "conversations": kinds.count("conversation"), "web": kinds.count("web"),
            "pages": kinds.count("page"), "beliefs": t.beliefs, "beliefsTotal": t.beliefs_total}


# ---- the popover ---------------------------------------------------------------------------------------------------


def _best(rows: list) -> object | None:
    return min(rows, key=lambda ev: (_RANK.get(ev.kind, 9), 0 if ev.is_span() else 1), default=None)


class StaleMarker(LookupError):
    """The marker asked for (``at`` or ``claim``) no longer cites reference ``n``: the page was renumbered since the
    card drew it. Never answered with ``n``'s current source, which that line may never have cited."""


def detail(memory_path: Path, entity_id: str, n: int, *, at: int | None = None, claim_id: str | None = None,
           fm: dict, body: str, claims) -> dict | None:
    """One marker's popover: reference ``n`` as cited by the line ending at ``at`` (or by belief ``claim_id``; neither:
    its first citing line) — its kind and who and when, and the best evidence row's located words with the cited span
    (one episode read). ``None`` when ``n`` is no reference of this page; :class:`StaleMarker` when ``at`` or
    ``claim_id`` names no current marker citing ``n``."""
    from api.services import provenance

    t = table(memory_path, entity_id, fm=fm, body=body, claims=claims)
    ref = next((r for r in t.refs if r.n == n), None)
    if ref is None:
        return None
    rows: list = []
    if claim_id is not None:
        rows = t.claim_evidence.get(claim_id, {}).get(n, [])
    else:
        for marker_at, ns, by in t.markers:
            if n in ns and (at is None or marker_at == at):
                rows = by.get(n, [])
                break
    if (at is not None or claim_id is not None) and not rows:
        raise StaleMarker(f"no current marker cites {n}")
    best = _best(rows)
    out = _ref_dict(ref)
    out.update({"evidenceKind": best.kind if best is not None else None, "status": None, "span": None,
                "conversations": 1 if ref.kind != "page" else 0, "lines": sum(1 for _, ns, _ in t.markers if n in ns)})
    if best is None or not best.is_span():
        return out
    docs = provenance._Episodes(Path(memory_path))
    allowed = set(ref.episodes) if evidence.is_episode_id(best.episode) else set()
    row = provenance._section_evidence(best, docs, allowed)
    out["status"] = row.status
    out["span"] = row.span.model_dump(by_alias=True) if row.span is not None else None
    return out


# ---- the same citations for an agent -------------------------------------------------------------------------------

OWN_WORDS = "(in the person's own words)"


def for_caller(cites: dict | None, *, verbatim: bool) -> dict | None:
    """The block one agent call may carry: for a caller without ``sources`` (``verbatim=False``) a conversation's title
    (often its first words) and a belief in the person's own sentence are masked, and no reference names a session,
    an episode or a chat partner (`episode_actor.actor_for(ids=False)`'s rule) — `/v1` returns this data as it is. A
    copy."""
    if not cites or verbatim:
        return cites
    out = dict(cites)
    out["refs"] = [dict(r, title="(a conversation)" if r.get("kind") == "conversation" else r.get("title"),
                        conversationId=None, episodeId=None, correspondent=None)
                   for r in cites.get("refs") or []]
    out["beliefs"] = [dict(b, text=OWN_WORDS) if b.get("verbatim") else dict(b) for b in cites.get("beliefs") or []]
    return out


def ref_words(ref: dict) -> str:
    """One reference as an agent reads it: ``[n] kind "title" (app, first – last)``."""
    when = " – ".join(dict.fromkeys(d[:10] for d in (ref.get("first"), ref.get("last")) if d))
    where = ", ".join(b for b in (ref.get("harness") or ref.get("origin"), when) if b)
    title = f' "{ref["title"]}"' if ref.get("title") else ""
    return f"[{ref['n']}] {ref['kind']}{title}" + (f" ({where})" if where else "")


def belief_words(belief: dict) -> str:
    """A belief sentence as the card draws it: an ended one says until when, an inference says so."""
    text = belief["text"]
    if belief.get("inferred"):
        text = f"(inferred) {text}"
    if belief.get("until"):
        text = f"{text} (until {belief['until']})"
    refs = "".join(f"[{n}]" for n in belief.get("refs") or [])
    return f"{text} {refs}".rstrip()

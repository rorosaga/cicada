"""The pending store — names Sleep heard once and has not promoted, and what it
heard about them before they had a page (G141 PJ-0b).

``<bank>/pending_entities.jsonl``, one JSON object per line. Stage 2 parks every
sub-threshold entity here (the promotion model's first rung, CLAUDE.md "Entity
promotion") and promotes it on its next mention (``entity_resolver.resolve``);
G102's link recon parks a first mention the same way. The file used to be read
and written inside ``vector_index.SqliteVecIndexer``. It moved here (R-HP1)
because PJ-0b's hold and release are file work with no embedding — Stage 5.56
must not build a vector index to keep a claim. ``SqliteVecIndexer`` keeps its
embedding of these lines and delegates the file to this module: ONE writer.

Not a derived artifact (TODO ruling 3): deleting it costs facts — a first
mention and, since PJ-0b, the claims Sleep heard about that name. So it stays
where it always was, tracked in the bank's git and committed by the cycle that
changed it.

**The hold.** A line may carry ``held_claims``: the Stage-1 claims whose subject
is this name's slug, each as ``Claim.to_dict()`` — its id, observer, trust,
context, validity and G118 evidence spans (offsets and a hash into the source
episode, never a copy of its text). Omitted when empty, so every line written
before PJ-0b loads and saves byte for byte. A line that holds claims leaves the
store ONLY through :func:`release`, called after Stage 5.56 wrote them onto the
page (R-HP4): :func:`take` (promotion) keeps it, :func:`upsert` (a re-park)
carries its hold, and nothing expires a line (R-HP9).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

from loguru import logger

from api.services.claims import Claim
from api.services.id_utils import bank_file, sanitize_id

PENDING_STORE_FILE = "pending_entities.jsonl"

#: R-HP3 — claims held per name, head-stable. A name promotes on its next
#: conversation (`promotion`), so a held name normally carries a handful; only
#: a name Stage 2 keeps re-parking (an ``unsure`` match, or one conversation
#: read again and again) comes near this. Past it a claim is
#: refused at the door and counted — a claim already held is never evicted.
MAX_HELD_CLAIMS = 50

#: R-HP11 — every read-modify-write below runs under this lock. Stage 2's
#: flush, Stage 5.56 and link recon all write this file; today each does so
#: synchronously on the event loop, and the lock keeps a lost update
#: impossible if one of them moves to a worker thread (`asyncio.to_thread`).
_LOCK = threading.Lock()


@dataclass
class PendingEntity:
    """A sub-threshold entity (first mention) awaiting a promotion trigger."""

    name: str
    type: str
    description: str
    source_episode: str
    confidence: float
    tags: list[str]
    history_entries: list[dict]
    # G141 PJ-0b (R-HP1): what Sleep heard about this name while it had no
    # page, as `Claim.to_dict()` — spans into the episode, never its text.
    held_claims: list[dict] = field(default_factory=list)
    # What the page would have said (page quality, 2026-10-09): a name below the
    # promotion bar used to keep only its description, tags and history, so the
    # summary and facts of its first conversation were gone by the time a second
    # one promoted it. The extraction's own text, never the conversation's; its
    # G118 item records (reasoning rows: an episode id and a body hash) ride along.
    summary: str = ""
    key_facts: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    item_inputs: list[dict] = field(default_factory=list)
    # Every conversation that named it, as {episode, timestamp, day}: promotion
    # credits each one on the page, and "2+ conversations" counts them.
    heard_in: list[dict] = field(default_factory=list)

    _OPTIONAL = ("summary", "key_facts", "links", "open_questions", "aliases", "item_inputs", "heard_in")

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "source_episode": self.source_episode,
            "confidence": self.confidence,
            "tags": self.tags or [],
            "history_entries": self.history_entries or [],
        }
        # Absent when empty: a line from before PJ-0b re-writes byte for byte.
        if self.held_claims:
            data["held_claims"] = list(self.held_claims)
        for key in self._OPTIONAL:  # absent when empty, the same way
            value = getattr(self, key)
            if value:
                data[key] = value
        return data

    def episodes(self) -> list[str]:
        """Every conversation this line heard the name in, the line's own first."""
        out = [self.source_episode] if self.source_episode else []
        for record in self.heard_in:
            episode = str(record.get("episode") or "") if isinstance(record, dict) else ""
            if episode and episode not in out:
                out.append(episode)
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "PendingEntity":
        def strings(key):
            return [str(v) for v in (data.get(key) or []) if isinstance(v, str) and v.strip()]

        def dicts(key):
            return [d for d in (data.get(key) or []) if isinstance(d, dict)]

        return cls(
            name=data.get("name", ""),
            type=data.get("type", "concept"),
            description=data.get("description", ""),
            source_episode=data.get("source_episode", ""),
            confidence=float(data.get("confidence", 0.3)),
            tags=data.get("tags", []) or [],
            history_entries=data.get("history_entries", []) or [],
            held_claims=[
                d for d in (data.get("held_claims") or []) if isinstance(d, dict) and d.get("id")
            ],
            summary=str(data.get("summary") or ""),
            key_facts=strings("key_facts"),
            links=[d for d in dicts("links") if d.get("url")],
            open_questions=strings("open_questions"),
            aliases=strings("aliases"),
            item_inputs=[d for d in dicts("item_inputs") if d.get("text") and isinstance(d.get("evidence"), list)],
            heard_in=[d for d in dicts("heard_in") if d.get("episode")],
        )


def _texts(*lists) -> list[str]:
    out, seen = [], set()
    for values in lists:
        for value in values or []:
            key = " ".join(str(value).split()).lower()
            if key and key not in seen:
                seen.add(key)
                out.append(value)
    return out


def _carry(prior: PendingEntity, entity: PendingEntity) -> None:
    """A re-park keeps what the replaced line heard (page quality, 2026-10-09).

    Stage 2 re-parks a name when the same conversation is read again (a resumed
    one) or its match was ``unsure``: the fresh line knows only this read, and
    replacing the old one dropped the first read's facts. Lists are unions (the
    old line's items first, a fact the old line already says folded away), the
    newer summary and description win as before — the old ones stay as facts
    when they say something the line does not — and every conversation either
    line heard is kept."""
    from api.services import fact_policy

    displaced = [t for t in (prior.summary, prior.description)
                 if t and t not in (entity.summary, entity.description)]
    entity.summary = entity.summary or prior.summary
    entity.description = entity.description or prior.description
    said = fact_policy.sentences(entity.summary or entity.description)
    displaced = [s for t in displaced for s in fact_policy.sentences(t) if not fact_policy.covered(s, said)]
    facts, _ = fact_policy.union(list(prior.key_facts), _texts(entity.key_facts, displaced))
    entity.key_facts = _texts(facts)
    links, urls = [], set()
    for link in list(prior.links) + list(entity.links):
        if link.get("url") not in urls:
            urls.add(link.get("url"))
            links.append(link)
    entity.links = links
    entity.open_questions = _texts(prior.open_questions, entity.open_questions)
    entity.aliases = _texts(prior.aliases, entity.aliases)
    entity.tags = sorted(set(prior.tags or []) | set(entity.tags or []))
    history = list(prior.history_entries or [])
    for item in entity.history_entries or []:
        if item not in history:
            history.append(item)
    entity.history_entries = history
    inputs = list(prior.item_inputs)
    for record in entity.item_inputs:
        if record not in inputs:
            inputs.append(record)
    entity.item_inputs = inputs
    heard = {r["episode"]: r for r in prior.heard_in if r.get("episode")}
    if prior.source_episode and prior.source_episode not in heard:
        heard[prior.source_episode] = {"episode": prior.source_episode}
    for record in entity.heard_in:
        heard.setdefault(record["episode"], record)
    if entity.source_episode and entity.source_episode not in heard:
        heard[entity.source_episode] = {"episode": entity.source_episode}
    entity.heard_in = list(heard.values())
    entity.source_episode = prior.source_episode or entity.source_episode
    entity.confidence = max(float(prior.confidence or 0), float(entity.confidence or 0))


class HoldOutcome(NamedTuple):
    """Of the claims offered for one subject: how many are now held (new, or
    merged into a claim already held under the same id) and how many the
    per-name cap refused (R-HP3)."""

    held: int
    capped: int


@dataclass
class Release:
    """One pending line whose claims can go onto a page now (R-HP5): ``name`` is
    the line's key, ``target`` the page id, ``claims`` re-keyed onto it."""

    name: str
    target: str
    claims: list[Claim]


def store_path(memory_path: Path) -> Path:
    return Path(memory_path) / PENDING_STORE_FILE


def load(memory_path: Path) -> list[PendingEntity]:
    """Every line, in file order. A line that is not JSON is skipped, as
    ``SqliteVecIndexer._load_pending`` always did."""
    path = store_path(memory_path)
    if not path.exists():
        return []
    out: list[PendingEntity] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(PendingEntity.from_dict(json.loads(line)))
        except Exception:
            continue
    return out


def save(memory_path: Path, entries: list[PendingEntity]) -> None:
    """Replace the file with ``entries`` — atomically (R-HP11).

    The file now carries claims, and :func:`load` skips a line it cannot
    parse: a write torn by a killed process would be read back short and saved
    short by the next writer, losing held claims with nothing to count. So the
    text goes to a temp file in the bank directory and replaces the old file in
    one ``os.replace``. A failed write removes the temp file — a stray file in
    the bank would ride the next ``git add -A`` commit — and re-raises."""
    path = store_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(e.to_dict()) for e in entries) + "\n" if entries else ""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pending_entities-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _merge_into(prior: dict, incoming: dict) -> bool:
    """A claim heard again under the same id adds its evidence and episodes —
    G118 R8's rule for a restatement (``claim_reconciler._reinforce``) and
    ``entities_to_claims``'s for overlapping chunks; everything else stays as
    first heard. True when ``prior`` changed."""
    changed = False
    for key in ("evidence", "source_episodes"):
        have = list(prior.get(key) or [])
        for item in incoming.get(key) or []:
            if item not in have:
                have.append(item)
                changed = True
        if have:
            prior[key] = have
    return changed


def _merged(first: list[dict], second: list[dict]) -> list[dict]:
    """Two holds as one, by claim id: ``first`` in order, then what ``second`` adds."""
    out = [dict(d) for d in first]
    by_id = {d.get("id"): d for d in out}
    for data in second:
        prior = by_id.get(data.get("id"))
        if prior is None:
            copy = dict(data)
            out.append(copy)
            by_id[copy.get("id")] = copy
        else:
            _merge_into(prior, data)
    return out


def upsert(memory_path: Path, entity: PendingEntity) -> None:
    """Park ``entity``: append it, or replace the same-named line(s), case-insensitive.

    G141 PJ-0b (R-HP4): the replaced line's hold is CARRIED onto the new one,
    never dropped. Stage 2 re-parks a name it could not settle — an ``unsure``
    match reaches the else-branch every cycle it is heard
    (``entity_resolver.resolve``) — with a fresh ``PendingEntity`` that knows
    nothing of what was held."""
    with _LOCK:
        entries = load(memory_path)
        key = entity.name.lower()
        carried: list[dict] = []
        kept: list[PendingEntity] = []
        for e in entries:
            if e.name.lower() == key:
                carried = _merged(carried, e.held_claims)
                _carry(e, entity)
            else:
                kept.append(e)
        entity.held_claims = _merged(carried, entity.held_claims)
        kept.append(entity)
        save(memory_path, kept)


def take(memory_path: Path, name: str) -> tuple[PendingEntity | None, bool]:
    """Promotion's read-and-remove: ``(line, removed)`` for the first line named
    ``name`` (case-insensitive); ``(None, False)`` when there is none.

    G141 PJ-0b (R-HP4): a line that holds claims is returned but NOT removed.
    Stage 2 flushes this at the end of ``resolve``, before Sleep's last three
    cancel points and before any page exists; the line leaves through
    :func:`release` once Stage 5.56 has written its claims onto the page — so
    a cancel, a failed Stage 5 or a failed claim write between the two leaves
    the claims where they were."""
    with _LOCK:
        entries = load(memory_path)
        key = (name or "").lower()
        for i, e in enumerate(entries):
            if e.name.lower() != key:
                continue
            if e.held_claims:
                return e, False
            del entries[i]
            save(memory_path, entries)
            return e, True
        return None, False


def hold(
    memory_path: Path, offers: dict[str, list[Claim]], *, cap: int = MAX_HELD_CLAIMS,
) -> dict[str, HoldOutcome]:
    """Hold each subject's claims on the pending line whose slug IS that subject (R-HP2).

    ``sanitize_id(line.name)`` is the id Stage 2's promotion gives the page, so
    a held claim lands where the page will be; there is no fuzzy match over
    pending names. A claim already held under its id merges
    (:func:`_merge_into`); a new one is appended until the line holds ``cap``
    (head-stable, R-HP3). One read and at most one write for the whole cycle,
    and nothing is written when nothing changed — a bank with no store never
    gains one. Returns an outcome for every subject offered a non-empty list:
    ``(0, 0)`` for one with no line."""
    offers = {s: list(c) for s, c in offers.items() if c}
    if not offers:
        return {}
    with _LOCK:
        entries = load(memory_path)
        by_slug: dict[str, PendingEntity] = {}
        for e in entries:
            by_slug.setdefault(sanitize_id(e.name), e)
        out: dict[str, HoldOutcome] = {}
        changed = False
        for subject, claims in offers.items():
            line = by_slug.get(subject)
            if line is None:
                out[subject] = HoldOutcome(0, 0)
                continue
            by_id = {d.get("id"): d for d in line.held_claims}
            held = capped = 0
            for claim in claims:
                data = claim.to_dict()
                prior = by_id.get(claim.id)
                if prior is not None:
                    changed = _merge_into(prior, data) or changed
                    held += 1
                elif len(line.held_claims) >= cap:
                    capped += 1
                else:
                    line.held_claims.append(data)
                    by_id[claim.id] = data
                    held += 1
                    changed = True
            out[subject] = HoldOutcome(held, capped)
        if changed:
            save(memory_path, entries)
        return out


def ready(memory_path: Path, target_of: Callable[[str, str], str]) -> list[Release]:
    """Read-only: the holding lines whose claims can go onto a page NOW (R-HP5).

    ``target_of(line_name, subject)`` names the page — Stage 5.56 passes Stage
    2's exact verdict on the name this cycle, else the claims' own subject. A
    line whose target has no page is left for a later cycle. The claims come
    back re-keyed onto the target (R-CS1: a claim follows Stage 2's match),
    everything else as held. Nothing is removed here: that is :func:`release`,
    after the write succeeded (R-HP4). A held dict that no longer parses is
    skipped and counted in a warning — a count, never a name (R-CS3)."""
    entities_dir = Path(memory_path) / "entities"
    out: list[Release] = []
    unreadable = 0
    for line in load(memory_path):
        claims: list[Claim] = []
        for data in line.held_claims:
            try:
                claims.append(Claim.from_dict(data))
            except (TypeError, ValueError):
                unreadable += 1
        if not claims:
            continue
        target = target_of(line.name, claims[0].subject) or claims[0].subject
        page = bank_file(entities_dir, target)
        if page is None or not page.is_file():
            continue
        for claim in claims:
            claim.subject = target
        out.append(Release(line.name, target, claims))
    if unreadable:
        logger.warning(f"pending store: {unreadable} held claim(s) could not be read; they leave with their line")
    return out


def release(memory_path: Path, names: Iterable[str]) -> int:
    """Remove the lines whose claims Stage 5.56 just wrote onto their page — the
    one way a holding line leaves the store (R-HP4). Returns how many lines
    left; writes nothing when there is nothing to remove."""
    keys = {n.lower() for n in names if n}
    if not keys:
        return 0
    with _LOCK:
        entries = load(memory_path)
        kept = [e for e in entries if e.name.lower() not in keys]
        gone = len(entries) - len(kept)
        if gone:
            save(memory_path, kept)
        return gone


def waiting(memory_path: Path) -> tuple[int, int]:
    """``(claims, names)`` still held — R-HP12's ``claims_waiting``. A hold that
    never releases (its name was never mentioned again, or Stage 2 merged it
    into a page with another name and never heard it again) shows up here as a
    number instead of nowhere."""
    lines = [e for e in load(memory_path) if e.held_claims]
    return sum(len(e.held_claims) for e in lines), len(lines)

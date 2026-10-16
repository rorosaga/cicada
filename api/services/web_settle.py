"""A web lookup settles inbox questions about public things (owner ruling 2026-10-16, G61; amends the S3 rail).

The owner, 2026-10-16: "A web lookup answers 'what is X' for public things and closes the question. The answer is saved
with its link and quote, and you can undo it from a 'Settled by a check' list. Never searched: people's names, your own
files, your projects, your life."

This module is the bank side: which questions may be looked up (:func:`classify`), what may leave the machine
(:func:`query_for` — the subject's name plus generic category words, nothing else), and the one writer that settles a
question and undoes it (:func:`settle`, :func:`undo`). The engine side — who searches, on which engine, under which
gate — is ``web_lookup``; the person's own agent settles through ``cicada_record_check(outcome="settles")``.

**Two tiers, kept apart (owner refinement, 2026-10-16).** The answer carries a *citation* — the found URL and a short
quote — on THAT claim only: one ``web-check`` episode holds them (``attachment [<host>]: as <checker> read it at
<url>`` and the quote line, so the quote is a ``page``-kind span, G118) and the claim's evidence points into it. It is
never written to the page's ``sources:`` (the cheat sheet agents re-check, ruling 26): it never joins a re-check set,
never makes a site trusted and never drives a logo. The person may promote it with one tap through the existing
person's source route ("Track this source" in the app), never automatically.

**What a settle writes**, in one commit: the episode; the claim (observer ``agent``, ``source_trust: external``,
``origin: web-check``) on the subject's page — or held on its pending line (``pending_store``) when the name has no
page yet, so no page is ever created by a lookup; for a conflict, every other open option claim closed today in its
favour; and the question moved to ``inbox/settled/<id>.md`` with a ``settled:`` block saying exactly what it wrote.
:func:`undo` reads that block and takes back only that: the claim, the closures (only where the claim still reads as
the settle left it) and the record; the question returns under its id.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, episode_ids, episode_scrub, inbox_questions, markdown_parser, predicates

SOURCE = "web-check"
SETTLED_DIR = "settled"
ORIGIN = "web-check"
KINDS = ("conflict", "clarification")
#: The types a lookup may answer for: a work, product, tool, company or public concept (``media`` holds films, books,
#: papers, videos). Never ``person``, ``project``, ``directory``, ``location``, ``skill`` or ``deadline``.
PUBLIC_TYPES = frozenset({"company", "concept", "tool", "media"})
#: Predicates whose truth lives in the world rather than in the person's life — for a conflict, beside the vocabulary's
#: ``locus: world | artifact``. Anything else stays for the person.
PUBLIC_PREDICATES = frozenset({
    "description", "is-a", "type", "category", "kind", "genre", "made-by", "created-by", "developed-by", "built-by",
    "published-by", "authored-by", "author", "directed-by", "founded-by", "owned-by", "maintained-by", "released",
    "release-date", "released-in", "founded", "founded-in", "headquartered-in", "based-in", "located-in", "part-of",
    "runs-on", "written-in", "language", "license", "year", "website",
})
#: Generic words that may ride with a name to the search engine — and only these. Matched against Cicada's own short
#: description of the subject (local text, never sent itself).
CATEGORY_WORDS = frozenset({
    "film", "movie", "documentary", "series", "show", "book", "novel", "paper", "article", "essay", "album", "song",
    "podcast", "game", "video", "anime", "manga", "comic", "play", "opera", "painting", "artwork", "magazine",
    "journal", "conference", "software", "library", "framework", "language", "tool", "app", "application", "platform",
    "service", "database", "protocol", "model", "dataset", "benchmark", "algorithm", "standard", "browser", "editor",
    "extension", "plugin", "api", "sdk", "cli", "agent", "harness", "company", "startup", "brand", "product", "robot",
    "robotics", "device", "hardware", "chip", "camera", "car", "theory", "concept", "method", "technique", "law",
    "university", "museum", "band", "studio", "publisher", "website", "newsletter", "blog",
})
TYPE_WORDS = {"tool": "software", "company": "company"}
MAX_CATEGORY_WORDS = 3
MAX_ANSWER_CHARS = 200
MAX_QUOTE_CHARS = 240
MAX_NAME_CHARS = 80

#: Words that say the subject is somebody, or the person's own — any one, in Cicada's own description of an untyped
#: subject or in the question, and the question stays for the person ("when in doubt, don't search").
_PERSON_CUES = re.compile(
    r"\b(he|she|him|his|her|hers|my|our|mine|me|i|we|us|friend|colleague|co-?worker|boss|manager|partner|wife|husband|"
    r"girlfriend|boyfriend|mom|mum|mother|dad|father|brother|sister|son|daughter|cousin|uncle|aunt|grandma|grandpa|"
    r"classmate|roommate|flatmate|teacher|professor|tutor|student|person|someone|somebody|guy|girl|man|woman|"
    r"client|customer|family|relative|neighbou?r|contact|people|team ?mate)\b",
    re.IGNORECASE,
)
#: A file, a path, a handle, an address: the person's own things, never searched.
_PRIVATE_NAME = re.compile(
    r"[/\\~@]|://|^\.|\.(md|txt|py|js|ts|swift|json|yaml|yml|toml|csv|xlsx?|docx?|pptx?|key|pages|numbers|pdf|png|"
    r"jpe?g|gif|heic|mov|mp4|zip|sh|rb|go|rs|java|kt|c|h|cpp|sql|ipynb|log)$",
    re.IGNORECASE,
)
#: "did PR #n merge", "is G<n> shipped": answered from the repo's history by a trusted local agent, never searched.
_REPO_STATE = re.compile(r"\b(?:PR|pull request)\s*#?\s*\d{1,6}\b|\bG\d{1,4}[a-z]?\b|#\d{1,6}\b", re.IGNORECASE)
_COMMIT_REF = re.compile(
    r"^(?:commit:[0-9a-f]{7,40}|https://(?:github\.com|gitlab\.com)/[\w.-]+/[\w.-]+/(?:-/)?(?:commit/[0-9a-f]{7,40}|"
    r"pull/\d{1,6}|merge_requests/\d{1,6}))$",
    re.IGNORECASE,
)


class NotSettleable(ValueError):
    """The question cannot be settled this way; the reason is said in words and nothing was written."""


@dataclass
class BankFacts:
    """What the filter needs to know about the bank, read once: the owner's page and the names of every person."""

    owner_id: str | None = None
    person_names: frozenset[str] = frozenset()
    pages: dict[str, dict] = field(default_factory=dict)
    pending: frozenset[str] = frozenset()


@dataclass
class Candidate:
    item_id: str
    kind: str
    scope: str                       # public | repo
    entity_id: str
    name: str
    entity_type: str
    has_page: bool
    predicate: str
    options: list[tuple[str, str]]   # (key, label)
    category: list[str]


def _norm(text) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def bank_facts(memory_path: Path) -> BankFacts:
    """Owner page, person names and aliases (and the owner's), page frontmatter, pending names — from the warm
    frontmatter cache. Never raises: an unreadable bank reads as one where nothing may be searched."""
    from api.services import pending_store
    from api.services.id_utils import sanitize_id

    facts = BankFacts()
    try:
        files = bank_index.files(Path(memory_path), "entities")
    except Exception:  # noqa: BLE001
        return facts
    names: set[str] = set()
    for f in files:
        fm = f.frontmatter or {}
        facts.pages[f.stem] = fm
        is_owner = fm.get("owner") is True
        if is_owner and facts.owner_id is None:
            facts.owner_id = f.stem
        if is_owner or str(fm.get("type") or "").lower() == "person":
            names.add(_norm(fm.get("name")))
            names.update(_norm(a) for a in (fm.get("aliases") or []) if isinstance(a, str))
            names.add(_norm(f.stem.replace("-", " ")))
    names.discard("")
    facts.person_names = frozenset(names)
    try:
        facts.pending = frozenset(sanitize_id(line.name) for line in pending_store.load(Path(memory_path)))
    except Exception:  # noqa: BLE001
        pass
    return facts


def _subject_type(fm: dict, page: dict | None) -> str:
    if page is not None:
        return str(page.get("type") or "").strip().lower()
    return str(fm.get("suggested_classification") or "").split(" ")[0].strip().lower()


def _local_description(fm: dict, page: dict | None, body: str) -> str:
    """Cicada's own words about the subject — read HERE to filter and to pick category words, never sent."""
    parts = [str(fm.get("suggested_classification") or ""), body or ""]
    if page is not None:
        parts.append(str(page.get("description") or page.get("summary") or ""))
    return " ".join(parts)


def classify(memory_path: Path, fm: dict, body: str, facts: BankFacts) -> tuple[str | None, str]:
    """``(scope, reason)``: ``public`` (a lookup may answer it), ``repo`` (a trusted local agent may, from the repo's
    history) or ``None`` with the enum that kept it for the person. Engine-free, network-free."""
    kind = str(fm.get("kind") or "")
    if kind not in KINDS:
        return None, "kind"
    if str(fm.get("status") or "pending") != "pending" or str(fm.get("asks") or "") == "name":
        return None, "kind"
    entity_id = str(fm.get("entity_id") or "")
    name = " ".join(str(fm.get("entity_name") or "").split())
    if not entity_id or not name:
        return None, "no_subject"
    if entity_id == facts.owner_id:
        return None, "owner"
    page = facts.pages.get(entity_id)
    if page is not None and page.get("owner") is True:
        return None, "owner"
    options = inbox_questions.normalize_options(fm.get("options"))
    labels = [str(o.get("label") or "") for o in options]
    asked = " ".join([str(fm.get("question") or ""), str(fm.get("title") or ""), name, *labels])
    if _REPO_STATE.search(asked):
        stype = _subject_type(fm, page)
        if stype == "person" or _norm(name) in facts.person_names:
            return None, "person"
        return "repo", "repo_state"
    stype = _subject_type(fm, page)
    if stype == "person" or str(fm.get("uncertainty_type") or "").lower().startswith("unknown relationship"):
        return None, "person"
    if _norm(name) in facts.person_names:
        return None, "person"
    if stype not in PUBLIC_TYPES:
        return None, "private_type"
    if page is not None and (page.get("path") or page.get("repos")):
        return None, "private_file"
    if len(name) > MAX_NAME_CHARS or len(name) < 2 or _PRIVATE_NAME.search(name):
        return None, "private_file"
    if page is None and _PERSON_CUES.search(_local_description(fm, None, body)):
        return None, "person_context"
    question = " ".join([str(fm.get("question") or ""), str(fm.get("title") or "")])
    if re.search(r"\b(you|your|yours)\b", question, re.IGNORECASE):
        return None, "personal"
    if any(_norm(label) in facts.person_names for label in labels if label):
        return None, "person"
    if kind == "conflict":
        predicate = str(fm.get("predicate") or "")
        if predicates.cardinality(memory_path, predicate) == "multi":
            return None, "informational"
        locus = predicates.locus(memory_path, predicate)
        if locus == "person" or (locus == "unknown" and predicate.lower() not in PUBLIC_PREDICATES):
            return None, "private_predicate"
        if len([o for o in options if str(o.get("key")) not in ("both", "neither")]) < 2:
            return None, "no_options"
    if page is None and entity_id not in facts.pending:
        return None, "no_page"
    return "public", "public"


def _category(fm: dict, page: dict | None, body: str, entity_type: str) -> list[str]:
    words: list[str] = []
    if TYPE_WORDS.get(entity_type):
        words.append(TYPE_WORDS[entity_type])
    for token in re.findall(r"[a-z]+", _local_description(fm, page, body).lower()):
        if token in CATEGORY_WORDS and token not in words:
            words.append(token)
        if len(words) >= MAX_CATEGORY_WORDS:
            break
    return words[:MAX_CATEGORY_WORDS]


def candidate(memory_path: Path, item_path: Path, facts: BankFacts) -> Candidate | None:
    try:
        parsed = markdown_parser.parse(item_path)
    except Exception:  # noqa: BLE001
        return None
    fm = parsed.frontmatter
    scope, _ = classify(memory_path, fm, parsed.body, facts)
    if scope is None:
        return None
    entity_id = str(fm.get("entity_id") or "")
    page = facts.pages.get(entity_id)
    etype = _subject_type(fm, page)
    options = [(str(o.get("key")), str(o.get("label") or "")) for o in inbox_questions.normalize_options(fm.get("options"))
               if str(o.get("key")) not in ("both", "neither")]
    return Candidate(
        item_id=item_path.stem, kind=str(fm.get("kind")), scope=scope, entity_id=entity_id,
        name=" ".join(str(fm.get("entity_name") or "").split()), entity_type=etype, has_page=page is not None,
        predicate=str(fm.get("predicate") or ("" if fm.get("kind") == "conflict" else "description")),
        options=options if fm.get("kind") == "conflict" else [],
        category=_category(fm, page, parsed.body, etype),
    )


def candidates(memory_path: Path, *, scope: str = "public", facts: BankFacts | None = None) -> list[Candidate]:
    """Pending questions of ``scope``, highest priority first (then oldest), deferred ones left out."""
    from api.services import inbox_service

    memory_path = Path(memory_path)
    facts = facts or bank_facts(memory_path)
    visible = {i.id for i in inbox_service.load_inbox(memory_path)}
    out: list[tuple[float, str, Candidate]] = []
    for path in sorted((memory_path / "inbox").glob("inbox-*.md")):
        if path.stem not in visible:
            continue
        c = candidate(memory_path, path, facts)
        if c is not None and c.scope == scope:
            fm = markdown_parser.parse(path).frontmatter
            out.append((-float(fm.get("priority") or 0.0), str(fm.get("created_date") or ""), c))
    out.sort(key=lambda t: (t[0], t[1]))
    return [c for _, _, c in out]


def query_for(c: Candidate) -> str:
    """The ONE thing that leaves the machine for a lookup: the subject's name and generic category words."""
    return " ".join([c.name, *c.category]).strip()


# --------------------------------------------------------------------------- the writer


def _one_line(text, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit].rstrip()


def clean_quote(raw) -> str:
    text, n = episode_scrub.scrub(_one_line(raw, MAX_QUOTE_CHARS).lstrip("> ").strip())
    episode_scrub.record("mcp", n)
    return text


def check_ref(ref: str, scope: str) -> tuple[str, str]:
    """``(ref, host)`` for a citation, or :class:`NotSettleable`. A public answer cites a public web page (never a
    login wall, never a page an agent may not be handed); a repo answer cites a commit or a pull request."""
    from api.services import reading_hosts

    ref = str(ref or "").strip()
    if scope == "repo":
        if not _COMMIT_REF.match(ref):
            raise NotSettleable("A repository answer cites its commit: `commit:<sha>` or the commit or pull "
                                "request's own link.")
        host = reading_hosts.display_host(reading_hosts.host_of(ref)) if "://" in ref else "git"
        return ref, host or "git"
    if not ref.lower().startswith(("https://", "http://")):
        raise NotSettleable("The answer needs the link of the page it came from.")
    verdict = reading_hosts.classify(ref)
    if not verdict.ok or verdict.walled:
        raise NotSettleable("That page is not a public page Cicada may cite. Find the answer on a public page.")
    return ref, reading_hosts.display_host(verdict.host) or "page"


@dataclass
class Settled:
    item_id: str
    entity_id: str
    claim_id: str
    episode_id: str
    paths: list[str]
    lines: list[str]


def _claim_id(entity_id: str, predicate: str, obj: str, today: str) -> str:
    digest = hashlib.sha1(f"{entity_id}\x00{predicate}\x00{obj}\x00web\x00{today}".encode("utf-8")).hexdigest()[:8]
    return f"clm_{today}_web_{digest}"


def _write_episode(memory_path: Path, *, c: Candidate, ref: str, host: str, quote: str, checker_label: str,
                   checker_kind: str, origin: str, session_frontmatter: dict | None) -> str:
    verb = (f"Checked {c.name} in the repository's history." if c.scope == "repo"
            else f"Looked up {c.name} on the web.")
    body = "\n".join([f"assistant: {verb}", "", f"attachment [{host}]: as {checker_label} read it at {ref}",
                      f"> {quote}"])
    content_hash = hashlib.sha256(f"{c.item_id}\x00{ref}\x00{body}".encode("utf-8")).hexdigest()[:12]
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": episode_ids.next_episode_id(episodes_dir, date.today().isoformat()),
        "timestamp": episode_ids.utc_now_iso(),
        "source": SOURCE,
        "origin": origin,
        "title": f"Web check: {c.name}"[:120],
        "processed": True,
        "processed_by": "agent",
        "content_hash": content_hash,
        "checked_ref": ref,
        "checked_host": host,
        "item_id": c.item_id,
        "entity_id": c.entity_id,
        "checker_kind": checker_kind,
        **(session_frontmatter or {}),
    }
    return episode_ids.create_episode(episodes_dir, fm, body)


def _evidence_for(memory_path: Path, episode_id: str, quote: str):
    from api.services import evidence as ev
    from api.services.claims import Evidence

    text = ev.source_text(memory_path, episode_id) or ""
    hit = ev.locate(text, quote)
    if hit is None:   # provenance never blocks memory (G118): the claim is still written
        return [ev.reasoning(episode_id, hash=ev.body_hash(text))]
    return [Evidence(episode=episode_id, start=hit[0], end=hit[1], kind="page", hash=ev.body_hash(text))]


def settle(
    memory_path: Path, item_id: str, *, ref: str, quote: str, option_key: str | None = None, answer: str | None = None,
    checker: str, checker_kind: str, origin: str = "sleep", scopes: tuple[str, ...] = ("public",),
    engine: str | None = None, session_frontmatter: dict | None = None, facts: BankFacts | None = None,
) -> Settled:
    """Settle one question with a cited answer. The caller holds the bank (Sleep's window, or admission + page lock),
    has checked its gates, and commits ``paths``. Raises :class:`NotSettleable` with nothing written."""
    from api.services import pending_store
    from api.services.claims import Claim, MalformedClaimsBlockError, is_event, parse_claims, write_claims

    memory_path = Path(memory_path)
    item_path = memory_path / "inbox" / f"{item_id}.md"
    if not item_path.exists():
        raise NotSettleable("That question is no longer open.")
    facts = facts or bank_facts(memory_path)
    c = candidate(memory_path, item_path, facts)
    if c is None or c.scope not in scopes:
        raise NotSettleable("That question is not one a lookup may answer: it is about a person, the person's own "
                            "files, projects or life, or something only their conversations know. It stays for them.")
    ref, host = check_ref(ref, c.scope)
    quote = clean_quote(quote)
    if not quote:
        raise NotSettleable("The answer needs a short quote from the page, in its own words.")
    today = date.today().isoformat()
    parsed_item = markdown_parser.parse(item_path)
    fm_item = parsed_item.frontmatter
    option_claim: str | None = None
    if c.kind == "conflict":
        key = str(option_key or "").strip()
        chosen = next(((k, label) for k, label in c.options if k == key), None)
        if chosen is None:
            raise NotSettleable("A conflict is settled by one of its own options: give its key.")
        obj = _one_line(chosen[1], MAX_ANSWER_CHARS)
        option_claim = next((str(o.get("claim_id")) for o in inbox_questions.normalize_options(fm_item.get("options"))
                             if str(o.get("key")) == key and o.get("claim_id")), None)
    else:
        obj, n = episode_scrub.scrub(_one_line(answer, MAX_ANSWER_CHARS))
        episode_scrub.record("mcp", n)
        if not obj:
            raise NotSettleable("A 'what is it' question is settled by a short answer (at most 200 characters).")
    predicate = predicates.load_normalizer(memory_path)(c.predicate) or c.predicate or "description"
    label = checker if checker and checker != "agent" else "an agent"
    episode_id = _write_episode(memory_path, c=c, ref=ref, host=host, quote=quote, checker_label=label,
                                checker_kind=checker_kind, origin=origin, session_frontmatter=session_frontmatter)
    paths = [f"episodes/{episode_id}.md"]
    claim = Claim(
        id=_claim_id(c.entity_id, predicate, obj, today), text=predicates.predicate_phrase(predicate, c.name, obj),
        subject=c.entity_id, predicate=predicate, object=obj, object_kind="literal", observer="agent",
        source_trust="external", origin=ORIGIN, authored_by=checker or "agent", confidence=0.8,
        valid_from=today, recorded_at=today, evidence=_evidence_for(memory_path, episode_id, quote),
    )
    closed: list[dict] = []
    held = False
    entity_path = memory_path / "entities" / f"{c.entity_id}.md"
    try:
        if entity_path.exists():
            page = markdown_parser.parse(entity_path)
            try:
                claims = parse_claims(page.body, strict=True)
            except MalformedClaimsBlockError as exc:
                raise NotSettleable("The page's claims could not be read; the question stays for the person.") from exc
            if any(x.id == claim.id for x in claims):
                raise NotSettleable("That answer is already on the page.")
            if c.kind == "conflict":
                option_ids = {str(o.get("claim_id")) for o in inbox_questions.normalize_options(fm_item.get("options"))
                              if o.get("claim_id")}
                for old in claims:
                    # An event (`happened`/`milestone`) is closed only by `progress.py` (G141): never here.
                    if (old.id in option_ids and old.id != option_claim and old.valid_to is None
                            and not is_event(old)):
                        before = old.to_dict()
                        old.valid_to = today
                        old.superseded_by = claim.id
                        closed.append({"id": old.id, "before": json.dumps(before, sort_keys=True),
                                       "after": json.dumps(old.to_dict(), sort_keys=True)})
            claims.append(claim)
            markdown_parser.write(entity_path, page.frontmatter, write_claims(page.body, claims))
            paths.append(f"entities/{c.entity_id}.md")
        else:
            out = pending_store.hold(memory_path, {c.entity_id: [claim]})
            if not out.get(c.entity_id) or out[c.entity_id].held < 1:
                raise NotSettleable("The name has no page and nothing held for it yet; the question stays.")
            held = True
            paths.append(pending_store.PENDING_STORE_FILE)
    except BaseException:
        (memory_path / "episodes" / f"{episode_id}.md").unlink(missing_ok=True)
        bank_index.invalidate(memory_path)
        raise
    settled_dir = memory_path / "inbox" / SETTLED_DIR
    settled_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "at": episode_ids.utc_now_iso(), "by": checker or "agent", "by_kind": checker_kind, "scope": c.scope,
        "ref": ref, "host": host, "quote": quote, "answer": obj, "predicate": predicate,
        "entity_id": c.entity_id, "entity_name": c.name, "claim_id": claim.id, "episode": episode_id,
        "held": held, "closed": closed,
        **({"option_key": option_key} if c.kind == "conflict" else {}),
        **({"engine": engine} if engine else {}),
    }
    markdown_parser.write(settled_dir / f"{item_id}.md", {**fm_item, "settled": record}, parsed_item.body)
    item_path.unlink()
    bank_index.invalidate(memory_path)
    paths += [f"inbox/{item_id}.md", f"inbox/{SETTLED_DIR}/{item_id}.md"]
    trigger = "sleep/web-check" if origin == "sleep" else f"mcp/{checker or 'agent'}"
    lines = [f"episodes/{episode_id}.md: created (source: {item_id}, trigger: {trigger})",
             (f"entities/{c.entity_id}.md: updated (source: {episode_id}, trigger: {trigger})" if not held
              else f"{pending_store.PENDING_STORE_FILE}: updated (source: {episode_id}, trigger: {trigger})"),
             f"inbox/{item_id}.md: settled (source: {episode_id}, trigger: {trigger})"]
    return Settled(item_id=item_id, entity_id=c.entity_id, claim_id=claim.id, episode_id=episode_id,
                   paths=paths, lines=lines)


# --------------------------------------------------------------------------- the list and the undo


def list_settled(memory_path: Path) -> list[dict]:
    """The "Settled by a check" list, newest first: what each check answered, from where, and what it wrote."""
    out: list[dict] = []
    for path in (Path(memory_path) / "inbox" / SETTLED_DIR).glob("inbox-*.md"):
        try:
            parsed = markdown_parser.parse(path)
        except Exception as exc:  # noqa: BLE001 — one unreadable record never hides the others
            logger.warning(f"settled record skipped: {path.name}: {type(exc).__name__}")
            continue
        fm = parsed.frontmatter
        rec = fm.get("settled") if isinstance(fm.get("settled"), dict) else None
        if rec is None:
            continue
        entity_id = str(rec.get("entity_id") or "")
        out.append({
            "id": path.stem, "kind": str(fm.get("kind") or ""), "question": str(fm.get("question") or fm.get("title")
                                                                                  or ""),
            "entity_id": entity_id, "entity_name": str(rec.get("entity_name") or fm.get("entity_name") or ""),
            "answer": str(rec.get("answer") or ""), "predicate": str(rec.get("predicate") or ""),
            "ref": str(rec.get("ref") or ""), "host": str(rec.get("host") or ""),
            "quote": str(rec.get("quote") or ""), "settled_at": str(rec.get("at") or ""),
            "settled_by": str(rec.get("by") or ""), "settled_by_kind": str(rec.get("by_kind") or ""),
            "scope": str(rec.get("scope") or "public"), "claim_id": str(rec.get("claim_id") or ""),
            "episode": str(rec.get("episode") or ""), "held": bool(rec.get("held")),
            "has_page": (Path(memory_path) / "entities" / f"{entity_id}.md").exists(),
        })
    out.sort(key=lambda r: r["settled_at"], reverse=True)
    return out


def undo(memory_path: Path, item_id: str) -> tuple[str, list[str], list[str]]:
    """Take back one settle: withdraw its claim, reopen what it closed (only a claim still as the settle left it), put
    the question back. Returns ``(restored item id, paths, manifest lines)``; :class:`NotSettleable` when there is
    no such record. The episode stays — it is what the lookup read, and git and the timeline keep it either way."""
    from api.services import inbox_service, pending_store
    from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    if not re.fullmatch(r"inbox-\d{3,}", item_id or ""):
        raise NotSettleable("No such settled question.")
    rec_path = memory_path / "inbox" / SETTLED_DIR / f"{item_id}.md"
    if not rec_path.exists():
        raise NotSettleable("No such settled question.")
    parsed = markdown_parser.parse(rec_path)
    fm = dict(parsed.frontmatter)
    rec = fm.pop("settled", None)
    if not isinstance(rec, dict):
        raise NotSettleable("No such settled question.")
    entity_id = str(rec.get("entity_id") or "")
    claim_id = str(rec.get("claim_id") or "")
    paths: list[str] = []
    lines: list[str] = []
    # A held claim may have reached its page since (the name was promoted): both places are looked at.
    if pending_store.unhold(memory_path, entity_id, claim_id):
        paths.append(pending_store.PENDING_STORE_FILE)
        lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {item_id}, trigger: inbox/web-check/undone)")
    entity_path = memory_path / "entities" / f"{entity_id}.md"
    if entity_path.exists():
        page = markdown_parser.parse(entity_path)
        try:
            claims = parse_claims(page.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise NotSettleable("The page's claims could not be read; nothing was changed.") from exc
        kept = [x for x in claims if x.id != claim_id]
        changed = len(kept) != len(claims)
        closed = {str(r.get("id")): r for r in (rec.get("closed") or []) if isinstance(r, dict)}
        for i, x in enumerate(kept):
            row = closed.get(x.id)
            if row and json.dumps(x.to_dict(), sort_keys=True) == row.get("after"):
                kept[i] = Claim.from_dict(json.loads(row["before"]))
                changed = True
        if changed:
            markdown_parser.write(entity_path, page.frontmatter, write_claims(page.body, kept))
            paths.append(f"entities/{entity_id}.md")
            lines.append(f"entities/{entity_id}.md: updated (source: {item_id}, trigger: inbox/web-check/undone)")
    inbox_dir = memory_path / "inbox"
    target = item_id
    if (inbox_dir / f"{target}.md").exists():   # never replace a question that took the number since
        target = f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}"
    markdown_parser.write(inbox_dir / f"{target}.md", fm, parsed.body)
    rec_path.unlink()
    bank_index.invalidate(memory_path)
    paths += [f"inbox/{target}.md", f"inbox/{SETTLED_DIR}/{item_id}.md"]
    lines += [f"inbox/{target}.md: reopened (source: {item_id}, trigger: inbox/web-check/undone)"]
    return target, paths, lines


def commit_message(subject: str, lines: list[str], *, authors: list[str], engine: str | None = None,
                   sessions: list[str] | None = None) -> str:
    from api.services import git_service

    return git_service.build_commit_message(f"{subject} {date.today().isoformat()}", lines, authors=authors,
                                            sessions=sessions, engine=engine)


def commit_sync(memory_path: Path, message: str, paths: list[str]) -> bool:
    """Commit exactly ``paths`` (a moved item's old path as its removal). False when the bank has no git."""
    from api.services import git_service

    if not (Path(memory_path) / ".git").exists():
        return False
    git_service.commit_touched_sync(memory_path, message, paths)
    return True


def record_event(memory_path: Path, *, action: str, item_id: str, entity_id: str | None, by_kind: str,
                 reason: str | None = None, engine: str | None = None, harness: str | None = None) -> None:
    """One ``web_check`` ledger row: ids and enums only — never the query, the link, its host or the quote."""
    from api.services import telemetry

    refs = {"action": action, "item_id": item_id, "entity_id": entity_id, "by": by_kind, "reason": reason,
            "harness": harness}
    try:
        telemetry.record(telemetry.UsageEvent(
            kind=telemetry.WEB_CHECK_KIND, stage="web_check", connection=None, engine=engine, model=None,
            bank=Path(memory_path).name, billing="free", invocations=0,
            refs={k: v for k, v in refs.items() if v is not None},
        ))
    except Exception as exc:  # noqa: BLE001 — a ledger row never fails a settle
        logger.debug(f"web_check ledger row skipped: {type(exc).__name__}")

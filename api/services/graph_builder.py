import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import yaml

from api.models.schemas import GraphLink, GraphNode, GraphResponse
from api.services import bank_index, claim_contexts, decay_policy, logo_service, predicates
from api.services.claims import parse_claims, strip_claims_block
from api.services.id_utils import sanitize_id
from api.services.markdown_parser import parse

_SUMMARY_RE = re.compile(r"^##\s+Summary\s*$", re.IGNORECASE | re.MULTILINE)


def summarize(body: str) -> str | None:
    """Return a short preview: the first non-empty line under a ``## Summary``
    heading, else the first 200 chars of the body with newlines collapsed.

    The ```claims fence is stripped first (F1 R-FX8): `claims.write_claims`
    appends it after the last section, so an empty Summary previewed as the
    fence line and a page with no heading previewed as YAML.
    """
    text = strip_claims_block(body or "").strip()
    if not text:
        return None
    m = _SUMMARY_RE.search(text)
    if m:
        rest = text[m.end():]
        for line in rest.splitlines():
            s = line.strip()
            if s.startswith("#"):
                break
            if s:
                return s[:200]
    flat = " ".join(l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#"))
    return flat[:200] or None


def content_hash(fm: dict, body: str) -> str:
    """sha1 of frontmatter JSON + body, truncated to 12 hex chars."""
    return hashlib.sha1((json.dumps(fm, sort_keys=True, default=str) + "\n" + (body or "")).encode()).hexdigest()[:12]


def synthetic_hash(*parts) -> str:
    """Deterministic 12-hex fingerprint for a node with no file behind it.

    ``hub:*`` and ``repo:*`` nodes are derived at read time, so they have no
    frontmatter/body to hash — they used to ship ``content_hash=""``. The
    companion app's diff treats an empty hash as "assume changed" (the safe
    degradation path for an older backend), so every one of them was re-pushed
    in every single delta. Hashing their defining fields instead means they
    change exactly when they change.
    """
    joined = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(joined.encode()).hexdigest()[:12]


# Module-level mtime cache. The full (unfiltered) graph is expensive to build
# over ~1882 entities; keying on the entities-dir + edges-file + inbox mtimes
# means the first GET after a sleep cycle pays the scan once and every repeat is
# a dict lookup. Filters are applied on top of the cached full graph cheaply.
_CACHE: dict = {"key": None, "value": None}


def build_graph(
    memory_path: Path,
    *,
    types: set[str] | None = None,
    statuses: set[str] | None = None,
    min_confidence: float = 0.0,
    tags: set[str] | None = None,
    include_hubs: bool = True,
    hubs_only: bool = False,
) -> GraphResponse:
    """Build the graph response, with server-side degree/flags and filtering."""
    full = _build_full(Path(memory_path))
    return _apply_filters(
        full,
        types=types,
        statuses=statuses,
        min_confidence=min_confidence,
        tags=tags,
        include_hubs=include_hubs,
        hubs_only=hubs_only,
    )


def _build_full(memory_path: Path) -> GraphResponse:
    entities_dir = memory_path / "entities"
    edges_file = memory_path / "graph_edges.yaml"
    hubs_dir = memory_path / "hubs"

    key = (
        _dir_mtime(entities_dir),
        _mtime(edges_file),
        _dir_mtime(hubs_dir),
        _inbox_mtime(memory_path),
        # G59: the logo cache lives outside the bank, so a warm-up or an
        # on-demand fetch moves no other key here — without this the cached
        # response keeps every node's stale `has_logo` (and `content_hash`).
        _mtime(logo_service.meta_path(logo_service.bank_name(memory_path))),
    )
    if _CACHE["key"] == key:
        return _CACHE["value"]

    pending_ids = _load_pending_entity_ids(memory_path)
    raw_links = _load_edges(memory_path)

    # Degree from canonical edges (string endpoints at this stage).
    degree: Counter = Counter()
    for link in raw_links:
        degree[link.source] += 1
        degree[link.target] += 1

    nodes: list[GraphNode] = []
    entity_ids: set[str] = set()
    # M5b claim overlay (additive): per-subject observers/contexts from valid
    # claims, plus a (subject, predicate, object) -> claim-id/context lookup that
    # tags graph edges with their backing claim. Empty when no page has claims,
    # so a claimless graph behaves exactly as before.
    subject_observers: dict[str, set[str]] = {}
    subject_contexts: dict[str, set[str]] = {}
    edge_claim_index: dict[tuple[str, str, str], tuple[str, str | None]] = {}
    all_observers: set[str] = set()
    # G-repo: read-time repo:<slug> synthetic nodes + "has repo" edges, derived
    # from each entity's declared `repos:` frontmatter — nothing persisted to
    # disk. One node per distinct repo PATH (not per entity), so two entities
    # pointing at the same checkout share a single node with an edge from each
    # owner (mirrors the hub: injection just below).
    repo_node_names: dict[str, str] = {}  # "repo:<slug>" -> display name
    repo_node_paths: dict[str, set[str]] = {}  # "repo:<slug>" -> declared paths
    repo_links: list[GraphLink] = []
    # G59: which entities already have a cached logo. One read of a small JSON
    # index — never a fetch, never a per-node stat storm.
    try:
        logo_ids = logo_service.cached_ids(logo_service.bank_name(memory_path))
    except Exception:
        logo_ids = set()
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        eid = f.stem
        try:
            body = f.body()
        except Exception:
            continue
        entity_ids.add(eid)
        try:
            for claim in parse_claims(body):
                if claim.valid_to is not None or claim.superseded_by:
                    continue  # overlay reflects currently-valid beliefs only
                if claim.observer:
                    subject_observers.setdefault(eid, set()).add(claim.observer)
                    all_observers.add(claim.observer)
                if claim_contexts.is_valid(claim.context):
                    subject_contexts.setdefault(eid, set()).add(claim.context)
                if claim.predicate and claim.object:
                    # F1 R-FX1: a value that is not a context (a `folder:` id,
                    # G60's `as of <date>`) never colours an edge.
                    edge_claim_index.setdefault(
                        (eid, claim.predicate, claim.object),
                        (claim.id, claim.context if claim_contexts.is_valid(claim.context) else None),
                    )
        except Exception:
            pass
        nodes.append(
            GraphNode(
                id=eid,
                name=fm.get("name", eid.replace("-", " ").title()),
                type=fm.get("type", "concept"),
                status=fm.get("status", "active"),
                confidence=fm.get("confidence", 0.5),
                tags=fm.get("tags", []) or [],
                degree=degree.get(eid, 0),
                has_pending=eid in pending_ids,
                observers=sorted(subject_observers.get(eid, set())),
                contexts=sorted(subject_contexts.get(eid, set())),
                summary=summarize(body),
                content_hash=content_hash(fm, body),
                has_logo=eid in logo_ids,
                decay_class=decay_policy.resolve(fm)[0],
                is_owner=bool(fm.get("owner")),
            )
        )
        for repo_decl in fm.get("repos") or []:
            if not isinstance(repo_decl, dict):
                continue
            repo_path = str(repo_decl.get("path", "") or "").strip()
            if not repo_path:
                continue
            display_name = Path(repo_path).name or repo_path
            repo_id = f"repo:{sanitize_id(display_name)}"
            repo_node_names.setdefault(repo_id, display_name)
            repo_node_paths.setdefault(repo_id, set()).add(repo_path)
            repo_links.append(GraphLink(source=eid, target=repo_id, label="has repo"))

    for repo_id, display_name in repo_node_names.items():
        # Paths are sorted so the hash does not depend on entity scan order.
        paths = sorted(repo_node_paths.get(repo_id, set()))
        nodes.append(
            GraphNode(
                id=repo_id,
                name=display_name,
                type="repo",
                status="active",
                confidence=1.0,
                content_hash=synthetic_hash("repo", repo_id, display_name, *paths),
            )
        )

    # Inject hub anchor nodes + `member of` edges from memory/hubs/*.md.
    hub_links: list[GraphLink] = []
    member_to_hub: dict[str, str] = {}
    if hubs_dir.exists():
        for filepath in sorted(hubs_dir.glob("*.md")):
            try:
                fm = parse(filepath).frontmatter
            except Exception:
                continue
            if fm.get("type") != "hub":
                continue
            hub_id = f"hub:{filepath.stem}"
            members = fm.get("members") or []
            nodes.append(
                GraphNode(
                    id=hub_id,
                    name=fm.get("name", filepath.stem),
                    type="hub",
                    status="active",
                    confidence=1.0,
                    tags=[],
                    degree=len(members),
                    is_hub=True,
                    member_count=int(fm.get("member_count", len(members)) or 0),
                    hub_kind=fm.get("hub_kind"),
                    # `len(members)` is in the hash because it is also the
                    # node's `degree`, and because a membership change rewrites
                    # this hub's `member of` edges — the client replaces the
                    # whole link list when the edge set moves, so the hub node
                    # should report as updated in the same delta rather than
                    # lagging a cycle behind its own edges. Note this tracks
                    # the member *count*, not identity: swapping one member for
                    # another leaves the hash unchanged, which is acceptable
                    # because the edge diff carries that change already.
                    content_hash=synthetic_hash(
                        "hub",
                        hub_id,
                        fm.get("name", filepath.stem),
                        fm.get("hub_kind"),
                        int(fm.get("member_count", len(members)) or 0),
                        len(members),
                    ),
                )
            )
            for m in members:
                mid = m.get("id") if isinstance(m, dict) else None
                if not mid or mid not in entity_ids:
                    continue
                hub_links.append(GraphLink(source=hub_id, target=mid, label="member of"))
                # First hub claiming a member wins for the gravity anchor.
                member_to_hub.setdefault(mid, hub_id)

    # Surface hubId on member entity nodes so the d3 layout can apply hub gravity.
    for node in nodes:
        if node.id in member_to_hub:
            node.hub_id = member_to_hub[node.id]

    # Fold the server-derived fields into each entity node's content hash.
    # `degree`, `has_pending` and `hub_id` are computed here, not stored in the
    # entity file, so a change in any of them leaves `content_hash(fm, body)`
    # identical — and the companion app's `GraphDiff` would never report the
    # node as updated (the pending-clarification pulse never appeared live).
    # The file hash stays the base; the extras are folded in deterministically.
    # Runs after hub injection (so `hub_id` is known) and before facet nodes are
    # built (they fold the parent's hash in, so they follow their subject).
    for node in nodes:
        if node.id in entity_ids:
            node.content_hash = synthetic_hash(
                node.content_hash, node.degree, node.has_pending, node.hub_id,
                node.has_logo, node.decay_class.value,
            )

    # Filter canonical edges to endpoints that exist (drops legacy dangling slugs).
    # repo:<slug> ids join valid_ids so `has repo` edges survive filtering too.
    valid_ids = entity_ids | {n.id for n in nodes if n.is_hub} | set(repo_node_names)
    links = [l for l in raw_links if l.source in valid_ids and l.target in valid_ids]
    links.extend(repo_links)

    # M5b: tag each edge with the backing claim's id + context when a valid claim
    # matches (subject, normalized-label, object). Additive — leaves context/
    # claim_id None when no claim backs the edge. The claim index is keyed on the
    # NORMALIZED predicate the seeder writes (e.g. "depends-on"), but raw edge
    # labels are free-form ("depends on"), so normalize the label through the same
    # predicate map before the lookup — otherwise every multi-word edge misses.
    if edge_claim_index:
        normalize = predicates.load_normalizer(memory_path)
        for link in links:
            hit = edge_claim_index.get(
                (link.source, normalize(link.label), link.target)
            )
            if hit:
                link.claim_id, link.context = hit[0], hit[1]

    links.extend(hub_links)

    # M5b: facet sub-nodes for a subject whose claims sit in >= 2 REAL contexts
    # (d2 §2c). F1 R-FX2: `general` is "no particular context" and a non-slug
    # value is not a context at all (claim_contexts), so neither is ever a
    # satellite — the owner's graph had two per annotated paper, one named after
    # a raw folder id. Each satellite is `id: "<subject>#<context>"`,
    # parentId=<subject>, joined to the parent by a short `facetOf` edge routed
    # through the existing node-click channel (the app opens the parent, R-FX3).
    facet_nodes: list[GraphNode] = []
    facet_links: list[GraphLink] = []
    node_by_id = {n.id: n for n in nodes}
    for subject, contexts in subject_contexts.items():
        facets = sorted(c for c in contexts if claim_contexts.is_facet(c))
        if len(facets) < 2 or subject not in node_by_id:
            continue
        parent = node_by_id[subject]
        for ctx in facets:
            name = claim_contexts.display_name(ctx)
            facet_nodes.append(
                GraphNode(
                    id=f"{subject}#{ctx}",
                    name=name,
                    type=parent.type,
                    status=parent.status,
                    confidence=parent.confidence,
                    is_facet=True,
                    parent_id=subject,
                    context=ctx,
                    # Facets are synthetic too — derived from the parent's
                    # claim contexts, with no file of their own. Fold the
                    # parent's own hash in so a facet moves when its subject
                    # does. (Same empty-hash re-push problem as hub:/repo:.)
                    # F1 R-FX3: the display name is folded in as well —
                    # `GraphDiff` re-pushes a node only when its hash moves, so
                    # the relabel ("engineering" → "Engineering") must move it.
                    content_hash=synthetic_hash(
                        "facet", subject, ctx, name, parent.type, parent.status,
                        parent.confidence, parent.content_hash,
                    ),
                )
            )
            facet_links.append(
                GraphLink(source=f"{subject}#{ctx}", target=subject, label="facetOf", context=ctx)
            )
    nodes.extend(facet_nodes)
    links.extend(facet_links)

    resp = GraphResponse(nodes=nodes, links=links, observers=sorted(all_observers))
    _CACHE.update(key=key, value=resp)
    return resp


def _apply_filters(
    full: GraphResponse,
    *,
    types: set[str] | None,
    statuses: set[str] | None,
    min_confidence: float,
    tags: set[str] | None,
    include_hubs: bool,
    hubs_only: bool,
) -> GraphResponse:
    if (
        not types
        and not statuses
        and not tags
        and min_confidence <= 0.0
        and include_hubs
        and not hubs_only
    ):
        return full

    nodes = full.nodes
    if hubs_only:
        kept_hubs = [n for n in nodes if n.is_hub]
        hub_ids = {n.id for n in kept_hubs}
        member_ids = {
            l.target for l in full.links if l.label == "member of" and l.source in hub_ids
        }
        members = [n for n in nodes if n.id in member_ids]
        kept_nodes = kept_hubs + members
        kept_ids = {n.id for n in kept_nodes}
        kept_links = [
            l for l in full.links if l.source in kept_ids and l.target in kept_ids
        ]
        return GraphResponse(nodes=kept_nodes, links=kept_links, observers=full.observers)

    def keep(n: GraphNode) -> bool:
        if n.is_hub:
            return include_hubs
        if types and n.type not in types:
            return False
        if statuses and n.status.value not in statuses:
            return False
        if min_confidence > 0.0 and n.confidence < min_confidence:
            return False
        if tags and not (set(n.tags) & tags):
            return False
        return True

    kept_nodes = [n for n in nodes if keep(n)]
    kept_ids = {n.id for n in kept_nodes}
    kept_links = [l for l in full.links if l.source in kept_ids and l.target in kept_ids]
    return GraphResponse(nodes=kept_nodes, links=kept_links, observers=full.observers)


def _claim_edge_row(claim, page_stem: str) -> dict | None:
    """One claim's row in ``graph_edges.yaml``, or ``None`` (M5e Stage 5.7's rule).

    Shared by :func:`regenerate_edges_from_claims` and :func:`upsert_claim_edges`
    so the full projection Sleep writes and the per-page one a folder sync writes
    can never disagree about a row's shape (F1 R-FX7). Only an open, node-valued
    claim is an edge; closed and superseded beliefs live on in the page and git."""
    if claim.valid_to is not None or claim.superseded_by:
        return None
    if claim.object_kind not in ("", "node"):
        return None
    source = (claim.subject or page_stem).strip()
    target = (claim.object or "").strip()
    label = (claim.predicate or "relates-to").strip()
    if not source or not target or source == target:
        return None
    return {
        "source": source,
        "target": target,
        "label": label,
        "observer": claim.observer or "agent",
        "context": claim.context or "general",
        "claim_id": claim.id,
        "valid_from": claim.valid_from,
    }


def _row_key(row: dict) -> tuple:
    return (row["source"], row["target"], row["label"], row["observer"], row["context"])


def regenerate_edges_from_claims(memory_path: Path) -> int:
    """Refresh the claim-derived edges in ``graph_edges.yaml`` (M5e Stage 5.7).

    Per D2 Stage 5: claim-backed edges in ``graph_edges.yaml`` are a **derived,
    valid-only** projection of the claims layer — each tagged with the backing
    claim's ``observer`` / ``context`` / ``claim_id`` / ``valid_from``. Only claims
    with a node object (``object_kind == 'node'``), an open window, and no
    ``superseded_by`` produce an edge; closed/superseded beliefs are excluded
    (they live on in the page + git for the timeline).

    CRITICAL (M5e review MUST-FIX): this runs AFTER Stage 5 / 5.5 / 5.55 have
    already written relationship, wikilink-``mentions`` and media-``about`` edges
    into the SAME file. It must therefore **merge** — it replaces only the
    claim-derived edges (rows carrying a ``claim_id``, which are the only ones
    this function ever writes) and preserves every non-claim edge verbatim.
    Replacing the file wholesale here silently destroyed the rest of the edge
    graph the first time any page carried a claim.

    Idempotent and non-destructive when there are NO claims: a bank that has not
    been consolidated yet (no ``claims`` blocks on any page) leaves the existing
    ``graph_edges.yaml`` untouched. Returns the number of claim-derived edges
    written (0 = left as-is).
    """
    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return 0

    claim_edges: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    any_claims = False
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = parse(filepath)
        except Exception:
            continue
        for claim in parse_claims(parsed.body):
            any_claims = True
            row = _claim_edge_row(claim, filepath.stem)
            if row is None or _row_key(row) in seen:
                continue
            seen.add(_row_key(row))
            claim_edges.append(row)

    # No claims anywhere => don't clobber a legacy/seeded edge graph.
    if not any_claims:
        return 0

    # Merge: keep every existing NON-claim edge (no ``claim_id`` tag), drop the
    # old claim-derived rows (we are about to rewrite them from the current valid
    # claim set), then append the freshly-projected claim edges. This preserves
    # relationship / mentions / media edges written earlier in the same cycle.
    edges_file = memory_path / "graph_edges.yaml"
    preserved: list[dict] = []
    if edges_file.exists():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        for edge in data.get("edges", []) or []:
            if not isinstance(edge, dict):
                continue
            # A row this function owns is exactly one carrying ``claim_id``.
            if edge.get("claim_id"):
                continue
            preserved.append(edge)

    merged = preserved + claim_edges
    edges_file.write_text(
        yaml.dump({"edges": merged}, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return len(claim_edges)


def upsert_claim_edges(memory_path: Path, page_ids) -> bool:
    """Re-project the claim-derived edges of just the pages ``page_ids`` names (F1 R-FX7).

    A folder sync writes paper claims (``cited-in`` the folder's project,
    ``about`` a concept) that only Sleep's Stage 5.7 used to turn into edges, so
    the owner's papers floated unattached until a cycle ran. This is
    :func:`regenerate_edges_from_claims`'s merge rule at page granularity: the
    rows it owns are those whose ``claim_id`` is a claim on one of these pages
    (open or closed — a closed claim's row must go), and they are replaced by
    those pages' open node-valued claims through the same
    :func:`_claim_edge_row`, so Stage 5.7 later writes the same rows. Every
    other row is kept verbatim — including one whose ``source`` is a named page
    but whose claim lives elsewhere. Writes nothing when the rows already match
    (no git churn on a no-change sync) and never rewrites a file it could not
    parse; a page whose claims block is corrupt owns nothing, so its rows stay.
    A row whose claim was deleted from its page outright (a hand edit, never a
    writer's path) waits for Stage 5.7. Returns True when ``graph_edges.yaml``
    was written."""
    memory_path = Path(memory_path)
    ids = sorted({str(s) for s in (page_ids or ()) if s})
    if not ids:
        return False
    owned: set[str] = set()
    fresh: list[dict] = []
    seen: set[tuple] = set()
    for stem in ids:
        page = memory_path / "entities" / f"{stem}.md"
        if not page.exists():
            continue
        try:
            body = parse(page).body
        except Exception:
            continue
        for claim in parse_claims(body):
            if claim.id:
                owned.add(claim.id)
            row = _claim_edge_row(claim, stem)
            if row is None or _row_key(row) in seen:
                continue
            seen.add(_row_key(row))
            fresh.append(row)
    edges_file = memory_path / "graph_edges.yaml"
    edges: list[dict] = []
    if edges_file.exists():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]

    def mine(edge: dict) -> bool:
        return bool(edge.get("claim_id")) and edge.get("claim_id") in owned

    def canon(rows: list[dict]) -> list[str]:
        return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)

    if canon([e for e in edges if mine(e)]) == canon(fresh):
        return False
    merged = [e for e in edges if not mine(e)] + fresh
    edges_file.write_text(
        yaml.dump({"edges": merged}, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True


def _load_edges(memory_path: Path) -> list[GraphLink]:
    """Load labeled edges from graph_edges.yaml — the sole canonical edge source."""
    edges_file = memory_path / "graph_edges.yaml"
    if not edges_file.exists():
        return []
    try:
        data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    return [
        GraphLink(source=e["source"], target=e["target"], label=e.get("label", "related to"))
        for e in data.get("edges", [])
        if e.get("source") and e.get("target")
    ]


def _load_pending_entity_ids(memory_path: Path) -> set[str]:
    """Entity ids referenced by any pending inbox item.

    Reads memory/inbox/ first; falls back to legacy nudges/+clarifications/ so
    the has_pending flag works both before and after the inbox migration.
    """
    ids: set[str] = set()
    inbox = memory_path / "inbox"
    dirs = [inbox] if inbox.exists() else [
        d for d in (memory_path / "nudges", memory_path / "clarifications") if d.exists()
    ]
    for d in dirs:
        for filepath in d.glob("*.md"):
            try:
                fm = parse(filepath).frontmatter
            except Exception:
                continue
            eid = str(fm.get("entity_id", "") or "")
            if eid:
                ids.add(eid)
    return ids


# ---------- mtime helpers (cache invalidation) ----------


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dir_mtime(path: Path) -> float:
    """Max mtime across a directory's .md files + the dir itself."""
    if not path.exists():
        return 0.0
    latest = _mtime(path)
    for filepath in path.glob("*.md"):
        m = _mtime(filepath)
        if m > latest:
            latest = m
    return latest


def _inbox_mtime(memory_path: Path) -> float:
    latest = 0.0
    for sub in ("inbox", "nudges", "clarifications"):
        m = _dir_mtime(memory_path / sub)
        if m > latest:
            latest = m
    return latest


# Public aliases for callers outside this module (e.g. sync_service) that only
# need the cheap mtime helpers, not the full cached graph build.
dir_mtime = _dir_mtime
file_mtime = _mtime
inbox_mtime = _inbox_mtime

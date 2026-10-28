"""How much of the graph can be recognised at a glance, and where its facts can be checked (vision items 1, 2; G146,
G159, G61) — two read-only reports, ids and enums only.

The owner, 2026-10-28: pictures matter so the person recognises things at a glance, and nobody knew how many pages had
one or why the rest did not. Before this, the only measures were anecdotes ("universities have no picture", ruling 40).

- :func:`pictures` walks every page once and asks the ONE precedence (`entity_picture.resolve_page`) which rung draws
  it. A drawn rung is ``stored`` (bytes on disk: the person's upload, a Contacts photo, a chat's photo, a cached logo,
  profile photo or preview) or ``offered`` (the app asks for it on view and nothing says it will miss). A page with no
  rung — or one offered while its fetch gate is off — gets ONE reason, from the same inputs the precedence reads
  (:data:`REASONS`). Cached logos are also bucketed by their smaller side, so a favicon-sized mark is visible.
- :func:`sources` walks every page's ``sources:`` once and says which write path put each entry there
  (:func:`writer_of`, inferred from the fields each writer stamps — :data:`WRITERS`), whether it is trusted, proposed or
  unconfirmed, how many are tracked for a dated re-check (ruling 26), and which pages carry none, by type. Web
  citations are not sources (rulings 27/44): their claims are counted apart, by origin, so the two never blur.

Neither report fetches, writes, or names anything: no page name, no URL, no handle — page types, enums, counts, and
(only when asked, ``ids=True``) a few entity ids per bucket for a maintainer to open. Caches are read, never created
(each module's own read-only helpers). `cicada coverage pictures|sources` and `GET /diagnostics/coverage/{report}` are
the two doors.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

#: Why a page shows its monogram (or would, with its gate off). One per page; the first that applies.
REASONS = (
    # every type
    "chose_initials",        # the person's own choice: "Use initials" (never counted as missing a picture they want)
    "type_has_no_rung",      # a concept, project, skill … — no rung reaches it but the person's own upload
    "gate_off",              # a rung is offered, but its fetch gate is off and nothing is stored
    "fetch_missed",          # asked, and the source had nothing usable (a fresh miss)
    # a person
    "no_identifier",         # no email (owner only), no own GitHub/X/Instagram/LinkedIn link
    "identifier_proposed",   # a profile link waits in "Confirm N links" (ruling 36 D5) or is nobody's own account
    "identifier_needs_proxy",  # only X/Instagram/LinkedIn links, and the photo proxy gate is off
    # a brand or a public place
    "no_site",               # no website source at all
    "site_proposed",         # a website waits for the person (ruling 36 D5)
    "site_unconfirmed",      # a website Cicada or an agent added that no read confirmed yet
    "site_platform",         # the only trusted site is a platform or walled host (never a mark)
    # a project (owner 2026-10-28, E)
    "repo_proposed",         # no trusted site, and its repository link waits in "Confirm N links" (ruling 36 D5)
    # a media page
    "paper",                 # a paper: its picture is the person's own PDF (G133)
    "no_url",                # nothing to draw a preview from
    "walled",                # a login-walled host: never fetched (the ToS rail)
    "no_preview_declared",   # an ordinary page with no og:image / thumbnail on record
)
RUNGS = ("upload", "contacts", "messages", "profile", "logo", "thumbnail")
#: A cached logo's smaller side, in pixels.
SIZE_BUCKETS = ((32, "under_32"), (64, "32_63"), (128, "64_127"), (None, "128_plus"))

#: Which write path put a source on a page (:func:`writer_of`).
WRITERS = (
    "person",              # the person (Sources, the card, the CLI) — or an entry with no adder (hand-written)
    "agent_tool",          # an agent's `cicada_add_source` / `write_claim(sources=)` / `add_influence`
    "agent_proposal",      # an agent's inferred link (`inferred=true`), waiting for the person
    "remote_agent",        # an app on the remote connector
    "sleep_stage1_site",   # Stage 1's official site at page creation (`conflict_resolver`)
    "sleep_site_backfill",  # the engine-free site backfill (`site_sources`)
    "sleep_org_site",      # ruling 40's organisation site (`org_sites`), trusted
    "sleep_proposal",      # Sleep's inferred link in "Confirm N links" (`source_proposals`, `org_sites`)
    "sleep_cited_url",     # Stage 5.56: a link a claim's own cited words contain (`attach_cited_urls`)
    "linkedin_import",     # the person's LinkedIn connections export (`linkedin_people`)
    "contacts",            # the Contacts sync (`contacts_local`)
    "paper_metadata",      # a paper's DOI (`paper_metadata`)
    "cicada_other",        # another of Cicada's own writers (a skill page's catalogue link …)
)
#: Claim origins whose evidence is a web citation or a re-check — never a tracked source (rulings 26, 27, 44).
CITATION_ORIGINS = ("web-context", "web-check", "source-refresh", "agent/read")
MAX_IDS = 5


def _kind(fm: dict) -> str:
    return str((fm or {}).get("type") or "concept").strip().lower() or "concept"


def _live(fm: dict, include_archived: bool) -> bool:
    status = str((fm or {}).get("status") or "active").strip().lower()
    return status != "dropped" and (include_archived or status != "archived")


def _bucket(side: int | None) -> str:
    if side is None:
        return "unknown"
    for bound, name in SIZE_BUCKETS:
        if bound is None or side < bound:
            return name
    return "128_plus"


# --- pictures ------------------------------------------------------------------------------------------------------


def _website_state(fm: dict) -> str | None:
    """The best state any ``website`` source on the page is in: ``trusted`` (a non-platform host), ``platform``,
    ``proposed``, ``unconfirmed`` — or None when there is none."""
    from api.services import fact_sources, logo_service, site_sources

    states = set()
    for s in fact_sources.as_sources(fm.get("sources")):
        if not fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE):
            continue
        if fact_sources.trusted(s):
            host = logo_service._host(str(s.get("ref") or ""))
            states.add("platform" if not host or site_sources.is_platform(host) else "trusted")
        elif fact_sources.is_proposed(s):
            states.add("proposed")
        else:
            states.add("unconfirmed")
    for state in ("trusted", "platform", "proposed", "unconfirmed"):
        if state in states:
            return state
    return None


def _person_reason(fm: dict, *, owner: dict | None, proxy: bool) -> str:
    """Why a person page with no rung has none — from the identifiers `person_photo.candidates` reads."""
    from api.services import fact_sources, person_photo

    if person_photo.candidates(fm, owner=owner, proxy=True) and not proxy:
        return "identifier_needs_proxy"
    for s in fact_sources.as_sources(fm.get("sources")):
        ref = s.get("ref")
        if any(parse(ref) for parse in person_photo._PARSERS.values()) and not person_photo.is_own_account(s):
            return "identifier_proposed"
    return "no_identifier"


def _brand_reason(fm: dict) -> str:
    from api.services import fact_sources

    state = _website_state(fm)
    if state is None and _kind(fm) == "project" and any(
            fact_sources.is_proposed(s) and (fact_sources.same_predicate(s.get("predicate"), fact_sources.KIND_REPO)
                                             or str(s.get("kind") or "") == fact_sources.KIND_REPO)
            for s in fact_sources.as_sources(fm.get("sources"))):
        return "repo_proposed"
    return {"platform": "site_platform", "proposed": "site_proposed", "unconfirmed": "site_unconfirmed"}.get(
        state or "", "no_site")


def _opportunities(kind: str, fm: dict) -> list[str]:
    """What a page with no picture already holds that a rung awaiting the owner's ruling could draw from (the report's
    "Needs the owner" numbers) — never asked of anything here."""
    from api.services import contacts_local, fact_sources

    out: list[str] = []
    sources = fact_sources.as_sources(fm.get("sources"))
    if kind == "person":
        if _website_state(fm) == "trusted":
            out.append("person_own_website")
        if any(str(s.get("ref") or "").startswith(contacts_local.REF_SCHEME)
               and fact_sources.same_predicate(s.get("predicate"), "email") for s in sources):
            out.append("person_contacts_email")
    return out


def pictures(memory_path, *, include_archived: bool = False, ids: bool = False) -> dict:
    """The picture coverage report (see the module note). Read-only, no network."""
    from api.services import (bank_index, demo_guard, entity_picture, logo_service, media_preview, person_photo)

    memory_path = Path(memory_path)
    bank = logo_service.bank_name(memory_path)
    cached = logo_service.cached_ids(bank) if logo_service.meta_path(bank).exists() else set()
    missed = logo_service.missed_ids(bank) if logo_service.meta_path(bank).exists() else {}
    photos = person_photo.read_meta(bank)
    try:
        from api.services import messages_photos

        chats = messages_photos.links(memory_path)
    except Exception:   # noqa: BLE001 — a broken chat index is no picture, never a failed report
        chats = {}
    demo = demo_guard.is_demo(memory_path)
    gates = {"logo": logo_service.fetch_allowed(), "person_photo": person_photo.fetch_allowed(),
             "person_photo_proxy": person_photo.proxy_allowed()}
    owner = None

    by_type: dict[str, dict] = {}
    rungs: Counter = Counter()
    reasons: Counter = Counter()
    sizes: Counter = Counter()
    chances: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    total = drawn = 0

    def example(key: str, eid: str) -> None:
        if ids and len(examples[key]) < MAX_IDS:
            examples[key].append(eid)

    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if not _live(fm, include_archived):
            continue
        eid, kind = f.stem, _kind(fm)
        row = by_type.setdefault(kind, {"pages": 0, "with_picture": 0, "rungs": Counter(), "none": Counter()})
        row["pages"] += 1
        total += 1
        owner_fm = {} if fm.get("owner") is True and demo else None
        if fm.get("owner") is True and owner_fm is None and owner is None:
            from api.services import owner_identity

            owner = owner_identity.load_owner()
        try:
            picture, inputs = entity_picture.resolve_page(memory_path, eid, fm, "", page_mtime=f.mtime_ns / 1e9,
                                                          cached=cached, missed=missed, photos=photos, chats=chats)
        except Exception:   # noqa: BLE001 — the graph's own rule: a malformed page is a ring, never a failed answer
            picture, inputs = entity_picture.NOTHING, None
        source, reason, state = picture.source, None, None
        if source == "initials":
            reason = "chose_initials"
        elif source in ("upload", "contacts", "messages"):
            state = "stored"
        elif source == "logo":
            if eid in cached:
                state = "stored"
                path = logo_service.cached_path(bank, eid)
                sizes[_bucket(logo_service.min_dimension(path.read_bytes()) if path else None)] += 1
            elif gates["logo"]:
                state = "offered"
            else:
                reason = "gate_off"
        elif source == "profile":
            if inputs is not None and inputs.profile_sha:
                state = "stored"
            elif gates["person_photo"]:
                state = "offered"
            else:
                reason = "gate_off"
        elif source == "thumbnail":
            if media_preview.stored_file(bank, eid) is not None:
                state = "stored"
            elif gates["logo"]:
                state = "offered"
            else:
                reason = "gate_off"
        else:
            if kind == "person":
                entry = photos.get(eid) if isinstance(photos, dict) else None
                if isinstance(entry, dict) and entry.get("miss") and person_photo.candidates(
                        fm, owner=owner_fm if owner_fm is not None else owner,
                        public=person_photo.public_item(memory_path, eid, fm)):
                    reason = "fetch_missed"
                else:
                    reason = _person_reason(fm, owner=owner_fm if owner_fm is not None else owner,
                                            proxy=gates["person_photo_proxy"])
            elif kind == "media":
                key = media_preview.key_for(fm)
                if key and media_preview.fresh_miss(media_preview.read_meta(bank, eid), key):
                    reason = "fetch_missed"
                else:
                    reason = media_preview.missing_reason(fm) or "no_preview_declared"
            elif entity_picture.logo_eligible(fm) or kind in logo_service.SITE_ONLY_TYPES:
                if logo_service.target_for(fm) is not None and eid in missed:
                    reason = "fetch_missed"
                else:
                    reason = _brand_reason(fm)
            else:
                reason = "type_has_no_rung"
        if reason is None:
            drawn += 1
            row["with_picture"] += 1
            row["rungs"][f"{source}:{state}"] += 1
            rungs[f"{source}:{state}"] += 1
            example(f"{kind}/{source}:{state}", eid)
        else:
            row["none"][reason] += 1
            reasons[reason] += 1
            example(f"{kind}/{reason}", eid)
            for chance in _opportunities(kind, fm):
                chances[chance] += 1
                example(f"opportunity/{chance}", eid)

    report = {
        "pages": total,
        "with_picture": drawn,
        "share": round(drawn / total, 3) if total else 0.0,
        "gates": gates,
        "rungs": dict(sorted(rungs.items())),
        "reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_type": {k: {"pages": v["pages"], "with_picture": v["with_picture"],
                        "rungs": dict(sorted(v["rungs"].items())),
                        "none": dict(sorted(v["none"].items(), key=lambda kv: (-kv[1], kv[0])))}
                    for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1]["pages"], kv[0]))},
        "logo_sizes": dict(sorted(sizes.items())),
        "opportunities": dict(sorted(chances.items())),
    }
    if ids:
        report["ids"] = dict(sorted(examples.items()))
    return report


# --- sources -------------------------------------------------------------------------------------------------------


def writer_of(source: dict) -> str:
    """Which write path put this entry on its page (:data:`WRITERS`), from the fields each writer stamps: the adder,
    the role, a proposal or a confirmation, the ref's scheme. Inferred, not stored: a writer stamps no name of its own,
    and a test pins each writer's shape to its enum so a new field cannot silently move one."""
    from api.services import contacts_local, fact_sources, linkedin_people, source_overview

    who = str(source.get("added_by") or fact_sources.USER).strip() or fact_sources.USER
    ref = str(source.get("ref") or "")
    website = fact_sources.same_predicate(source.get("predicate"), fact_sources.WEBSITE)
    verified = source.get("verified") if isinstance(source.get("verified"), dict) else {}
    # A proposal the person took loses `proposed` and gains `accepted`; its `evidence` stays (`_apply_persons_fields`).
    taken = bool(source.get("accepted")) and isinstance(source.get("evidence"), dict)
    if who == fact_sources.USER:
        return "person"
    if str(source.get("origin") or "").startswith(fact_sources.REMOTE_PREFIX):
        return "remote_agent"
    if who == fact_sources.CICADA:
        if ref.startswith(contacts_local.REF_SCHEME):
            return "contacts"
        if fact_sources.is_proposed(source) or (taken and not verified):
            return "sleep_proposal"
        if fact_sources.same_predicate(source.get("predicate"), linkedin_people.SOURCE_PREDICATE):
            return "linkedin_import"
        if website and verified.get("how") in ("record", "record+name", "wikidata+name"):
            return "sleep_org_site"
        if website:
            return "sleep_site_backfill"
        if "doi.org/" in ref:
            return "paper_metadata"
        return "cicada_other"
    if fact_sources.is_proposed(source) or (taken and not verified):
        return "agent_proposal"
    if who == "agent" and website:
        return "sleep_stage1_site"
    if who in source_overview.HARNESS_LABELS or who == "agent":
        return "agent_tool"
    return "sleep_cited_url"   # a model id: Stage 5.56 stamps the claim's author


def _state(source: dict) -> str:
    from api.services import fact_sources

    if fact_sources.trusted(source):
        return "trusted"
    return "proposed" if fact_sources.is_proposed(source) else "unconfirmed"


def _role(source: dict) -> str:
    from api.services import fact_sources, person_photo

    predicate = str(source.get("predicate") or "").strip().lower()
    if predicate == fact_sources.WEBSITE:
        return "website"
    if predicate in person_photo.PROFILE_PREDICATES:
        return "profile"
    if not predicate:
        return "page"
    return "fact"


def sources(memory_path, *, include_archived: bool = False, ids: bool = False, citations: bool = True) -> dict:
    """The sources coverage report (see the module note). Read-only, no network. ``citations`` also folds each page's
    claims (a body read per page) to count web citations by origin."""
    from api.services import bank_index, fact_sources, source_refresh

    memory_path = Path(memory_path)
    by_type: dict[str, dict] = {}
    writers: dict[str, Counter] = defaultdict(Counter)
    roles: Counter = Counter()
    recheck: Counter = Counter()
    cited: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    total = with_sources = entries = 0

    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if not _live(fm, include_archived):
            continue
        eid, kind = f.stem, _kind(fm)
        row = by_type.setdefault(kind, {"pages": 0, "with_sources": 0, "sources": 0, "with_trusted": 0})
        row["pages"] += 1
        total += 1
        listed = fact_sources.as_sources(fm.get("sources"))
        page_writers = set()
        for s in listed:
            writer = writer_of(s)
            writers[writer][_state(s)] += 1
            page_writers.add(writer)
            roles[_role(s)] += 1
            refresh = s.get(source_refresh.STATE_KEY)
            if isinstance(refresh, dict):
                recheck["dead" if refresh.get("dead") else "tracked"] += 1
            if isinstance(s.get("checked"), dict):
                recheck[f"site_check:{s['checked'].get('outcome') or 'unknown'}"] += 1
        for writer in page_writers:
            writers[writer]["pages"] += 1
            if ids and len(examples[f"writer/{writer}"]) < MAX_IDS:
                examples[f"writer/{writer}"].append(eid)
        entries += len(listed)
        row["sources"] += len(listed)
        if listed:
            with_sources += 1
            row["with_sources"] += 1
            if any(fact_sources.trusted(s) for s in listed):
                row["with_trusted"] += 1
        elif ids and len(examples[f"none/{kind}"]) < MAX_IDS:
            examples[f"none/{kind}"].append(eid)
        if citations:
            try:
                from api.services.claims import parse_claims

                for claim in parse_claims(f.body()):
                    origin = str(getattr(claim, "origin", "") or "")
                    if origin in CITATION_ORIGINS:
                        cited[origin] += 1
            except Exception:   # noqa: BLE001 — an unreadable page counts no claims, never fails the report
                pass

    report = {
        "pages": total,
        "with_sources": with_sources,
        "share": round(with_sources / total, 3) if total else 0.0,
        "sources": entries,
        "by_writer": {w: dict(sorted(writers[w].items())) for w in WRITERS if w in writers},
        "roles": dict(sorted(roles.items())),
        "recheck": dict(sorted(recheck.items())),
        "by_type": {k: v for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1]["pages"], kv[0]))},
        "without_sources": {k: v["pages"] - v["with_sources"] for k, v in
                            sorted(by_type.items(), key=lambda kv: (-(kv[1]["pages"] - kv[1]["with_sources"]), kv[0]))
                            if v["pages"] - v["with_sources"]},
    }
    if citations:
        report["citations"] = {o: cited.get(o, 0) for o in CITATION_ORIGINS}
    if ids:
        report["ids"] = dict(sorted(examples.items()))
    return report


def text(kind: str, report: dict) -> str:
    """The CLI's lines for one report: totals, then the biggest buckets."""
    if kind == "pictures":
        lines = [f"{report['with_picture']} of {report['pages']} page(s) show a picture ({report['share']:.0%})."]
        lines.append("Gates: " + ", ".join(f"{k} {'on' if v else 'off'}" for k, v in report["gates"].items()))
        lines.append("Drawn by: " + (", ".join(f"{k} {v}" for k, v in report["rungs"].items()) or "nothing"))
        lines.append("No picture, because: " + (", ".join(f"{k} {v}" for k, v in report["reasons"].items()) or "-"))
        for kind_name, row in report["by_type"].items():
            none = ", ".join(f"{k} {v}" for k, v in row["none"].items())
            lines.append(f"  {kind_name}: {row['with_picture']}/{row['pages']}" + (f" — none: {none}" if none else ""))
        if report["logo_sizes"]:
            lines.append("Cached logos by smaller side: " + ", ".join(f"{k} {v}" for k, v in report["logo_sizes"].items()))
        if report["opportunities"]:
            lines.append("Waiting on a ruling: " + ", ".join(f"{k} {v}" for k, v in report["opportunities"].items()))
        return "\n".join(lines)
    lines = [f"{report['with_sources']} of {report['pages']} page(s) list a source ({report['share']:.0%}); "
             f"{report['sources']} source(s) in all."]
    for writer, counts in report["by_writer"].items():
        lines.append(f"  {writer}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    lines.append("Roles: " + (", ".join(f"{k} {v}" for k, v in report["roles"].items()) or "-"))
    lines.append("Re-checks: " + (", ".join(f"{k} {v}" for k, v in report["recheck"].items()) or "-"))
    lines.append("No source, by type: " + (", ".join(f"{k} {v}" for k, v in report["without_sources"].items()) or "-"))
    if "citations" in report:
        lines.append("Web citations (claims, not sources): " + ", ".join(f"{k} {v}" for k, v in report["citations"].items()))
    return "\n".join(lines)


__all__ = ["CITATION_ORIGINS", "REASONS", "RUNGS", "WRITERS", "pictures", "sources", "text", "writer_of"]

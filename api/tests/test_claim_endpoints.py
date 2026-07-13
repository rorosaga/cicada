"""Tests for M5b Part 2 — claim read endpoints + transclusion resolver.

Per ``docs/goals/d2-companion-showcase.md`` (the authoritative API contract):

- ``GET /entities/{id}/claims`` → ``ClaimListResponse {claims}``
- ``GET /entities/{id}/timeline?predicate=&context=`` → ``ClaimTimeline``
- ``GET /transclude?ref=<urlencoded>`` → ``TransclusionPayload``

All hermetic: tmp memory workspaces, router functions called directly with a
fake Settings (the pattern from test_contributors.py). No live app, no models.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from api.services import markdown_parser
from api.services.claims import Claim, write_claims
from api.services.transclusion_resolver import resolve_transclusion


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _write_page(memory_path, stem, name, claims, body_prose="A page.", **fm_extra):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    fm = {"name": name, "type": "concept", "status": "active"}
    fm.update(fm_extra)
    markdown_parser.write(entities_dir / f"{stem}.md", fm, write_claims(body_prose, claims))


# --------------------------------------------------------------------------- #
# GET /entities/{id}/claims
# --------------------------------------------------------------------------- #


def test_claims_endpoint_returns_valid_claims_only_by_default(tmp_path):
    from api.routers import claims as claims_router

    _write_page(
        tmp_path,
        "cicada",
        "Cicada",
        [
            Claim(id="clm_v", text="Cicada uses sqlite-vec.", subject="cicada",
                  predicate="uses", object="sqlite-vec", context="engineering"),
            Claim(id="clm_c", text="Cicada used postgres.", subject="cicada",
                  predicate="uses", object="postgres", context="engineering",
                  valid_from="2026-01-15", valid_to="2026-05-05", superseded_by="clm_v"),
        ],
    )
    resp = run(claims_router.get_entity_claims("cicada", settings=_FakeSettings(tmp_path)))
    ids = [c.id for c in resp.claims]
    assert ids == ["clm_v"]


def test_claims_endpoint_includes_superseded_when_asked(tmp_path):
    from api.routers import claims as claims_router

    _write_page(
        tmp_path,
        "cicada",
        "Cicada",
        [
            Claim(id="clm_v", text="Cicada uses sqlite-vec.", subject="cicada",
                  predicate="uses", object="sqlite-vec"),
            Claim(id="clm_c", text="Cicada used postgres.", subject="cicada",
                  predicate="uses", object="postgres", valid_to="2026-05-05"),
        ],
    )
    resp = run(claims_router.get_entity_claims(
        "cicada", include_superseded=True, settings=_FakeSettings(tmp_path)
    ))
    assert {c.id for c in resp.claims} == {"clm_v", "clm_c"}


def test_claims_endpoint_missing_entity_404(tmp_path):
    from fastapi import HTTPException

    from api.routers import claims as claims_router

    (tmp_path / "entities").mkdir()
    try:
        run(claims_router.get_entity_claims("nope", settings=_FakeSettings(tmp_path)))
        assert False, "expected 404"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_claims_endpoint_wire_fields_camelcase(tmp_path):
    from api.routers import claims as claims_router

    _write_page(
        tmp_path,
        "cicada",
        "Cicada",
        [Claim(id="clm_v", text="x", subject="cicada", object_kind="node",
               valid_from="2026-05-05", source_episodes=["ep_1"], authored_by="seed")],
    )
    resp = run(claims_router.get_entity_claims("cicada", settings=_FakeSettings(tmp_path)))
    dumped = resp.model_dump(by_alias=True)["claims"][0]
    assert "objectKind" in dumped
    assert "validFrom" in dumped
    assert "sourceEpisodes" in dumped
    assert "authoredBy" in dumped


# --------------------------------------------------------------------------- #
# GET /entities/{id}/timeline
# --------------------------------------------------------------------------- #


def test_timeline_returns_superseded_chain_newest_first(tmp_path):
    from api.routers import claims as claims_router

    _write_page(
        tmp_path,
        "cicada",
        "Cicada",
        [
            Claim(id="clm_old", text="Cicada uses postgres.", subject="cicada",
                  predicate="uses", object="postgres", context="engineering",
                  valid_from="2026-01-15", valid_to="2026-05-05",
                  superseded_by="clm_new"),
            Claim(id="clm_new", text="Cicada uses sqlite-vec.", subject="cicada",
                  predicate="uses", object="sqlite-vec", context="engineering",
                  valid_from="2026-05-05", valid_to=None, supersedes="clm_old"),
            # a different key that must NOT appear in this timeline
            Claim(id="clm_other", text="Cicada relates to fastapi.", subject="cicada",
                  predicate="relates-to", object="fastapi", context="engineering"),
        ],
    )
    tl = run(claims_router.get_entity_timeline(
        "cicada", predicate="uses", context="engineering",
        settings=_FakeSettings(tmp_path),
    ))
    assert tl.subject == "cicada"
    assert tl.predicate == "uses"
    assert tl.context == "engineering"
    # newest first: the currently-valid claim leads, the closed one follows
    assert [c.id for c in tl.claims] == ["clm_new", "clm_old"]


def test_timeline_empty_key_returns_empty_claims(tmp_path):
    from api.routers import claims as claims_router

    _write_page(
        tmp_path, "cicada", "Cicada",
        [Claim(id="clm_v", text="x", subject="cicada", predicate="uses",
               object="sqlite-vec", context="engineering")],
    )
    tl = run(claims_router.get_entity_timeline(
        "cicada", predicate="values", context="family",
        settings=_FakeSettings(tmp_path),
    ))
    assert tl.claims == []
    assert tl.predicate == "values"


def test_timeline_missing_entity_404(tmp_path):
    from fastapi import HTTPException

    from api.routers import claims as claims_router

    (tmp_path / "entities").mkdir()
    try:
        run(claims_router.get_entity_timeline(
            "nope", predicate="uses", context="general",
            settings=_FakeSettings(tmp_path),
        ))
        assert False, "expected 404"
    except HTTPException as exc:
        assert exc.status_code == 404


# --------------------------------------------------------------------------- #
# transclusion resolver (the service) + GET /transclude
# --------------------------------------------------------------------------- #


def test_transclude_bare_subject(tmp_path):
    _write_page(
        tmp_path, "cicada", "Cicada",
        [Claim(id="clm_v", text="Cicada uses sqlite-vec.", subject="cicada",
               predicate="uses", object="sqlite-vec")],
        body_prose="Cicada is a memory system.",
    )
    payload = resolve_transclusion(tmp_path, "cicada")
    assert payload.kind == "entity"
    assert payload.resolved is True
    assert payload.title == "Cicada"
    assert payload.summary  # a one-liner summary


def test_transclude_facet(tmp_path):
    _write_page(
        tmp_path, "rodrigo", "Rodrigo",
        [
            Claim(id="clm_eng", text="Rodrigo values shipping fast.", subject="rodrigo",
                  predicate="values", object="speed", context="engineering"),
            Claim(id="clm_fam", text="Rodrigo values presence.", subject="rodrigo",
                  predicate="values", object="presence", context="family"),
        ],
    )
    payload = resolve_transclusion(tmp_path, "rodrigo#engineering")
    assert payload.kind == "facet"
    assert payload.resolved is True
    assert {c.id for c in payload.claims} == {"clm_eng"}


def test_transclude_single_claim(tmp_path):
    _write_page(
        tmp_path, "cicada", "Cicada",
        [Claim(id="clm_2026-05-05_009", text="Cicada uses sqlite-vec.", subject="cicada",
               predicate="uses", object="sqlite-vec")],
    )
    payload = resolve_transclusion(tmp_path, "claim:clm_2026-05-05_009")
    assert payload.kind == "claim"
    assert payload.resolved is True
    assert [c.id for c in payload.claims] == ["clm_2026-05-05_009"]


def test_transclude_context_query(tmp_path):
    _write_page(
        tmp_path, "rodrigo", "Rodrigo",
        [
            Claim(id="clm_eng", text="Rodrigo values speed.", subject="rodrigo",
                  predicate="values", object="speed", context="engineering"),
            Claim(id="clm_fam", text="Rodrigo values presence.", subject="rodrigo",
                  predicate="values", object="presence", context="family"),
        ],
    )
    payload = resolve_transclusion(tmp_path, "rodrigo?context=engineering")
    # a perspective slice = all valid claims in that context
    assert {c.id for c in payload.claims} == {"clm_eng"}
    assert payload.resolved is True


def test_transclude_missing_subject_soft_stub(tmp_path):
    (tmp_path / "entities").mkdir()
    payload = resolve_transclusion(tmp_path, "ghost")
    assert payload.resolved is False
    assert payload.ref == "ghost"
    # never raises; returns a stub the UI renders as "⚠ not found"


def test_transclude_missing_claim_soft_stub(tmp_path):
    _write_page(
        tmp_path, "cicada", "Cicada",
        [Claim(id="clm_real", text="x", subject="cicada")],
    )
    payload = resolve_transclusion(tmp_path, "claim:clm_ghost")
    assert payload.resolved is False


def test_transclude_excludes_superseded_facet_claims(tmp_path):
    _write_page(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_v", text="uses sqlite-vec", subject="cicada",
                  predicate="uses", object="sqlite-vec", context="engineering"),
            Claim(id="clm_c", text="used postgres", subject="cicada",
                  predicate="uses", object="postgres", context="engineering",
                  valid_to="2026-05-05"),
        ],
    )
    payload = resolve_transclusion(tmp_path, "cicada#engineering")
    assert {c.id for c in payload.claims} == {"clm_v"}


def test_transclude_depth_cap_does_not_loop(tmp_path):
    # a page that transcludes itself by context must not recurse infinitely
    _write_page(
        tmp_path, "cicada", "Cicada",
        [Claim(id="clm_v", text="x", subject="cicada", context="engineering")],
        body_prose="![[cicada#engineering]]",
    )
    # depth-cap + cycle-guard: resolving still returns (no hang / no RecursionError)
    payload = resolve_transclusion(tmp_path, "cicada", depth=0)
    assert payload.resolved is True


def test_transclude_cycle_guard(tmp_path):
    payload = resolve_transclusion(tmp_path, "cicada", visited={"cicada"})
    # already-visited ref degrades to an unresolved stub rather than recursing
    assert payload.resolved is False


def test_transclude_endpoint_urlencoded_ref(tmp_path):
    from api.routers import claims as claims_router

    _write_page(
        tmp_path, "rodrigo", "Rodrigo",
        [Claim(id="clm_eng", text="Rodrigo values speed.", subject="rodrigo",
               context="engineering")],
    )
    # the router receives the already-decoded query param ("rodrigo#engineering")
    payload = run(claims_router.get_transclusion(
        ref="rodrigo#engineering", settings=_FakeSettings(tmp_path)
    ))
    assert payload.kind == "facet"
    assert payload.resolved is True


def test_transclude_endpoint_empty_ref_soft_stub(tmp_path):
    from api.routers import claims as claims_router

    (tmp_path / "entities").mkdir()
    payload = run(claims_router.get_transclusion(ref="", settings=_FakeSettings(tmp_path)))
    assert payload.resolved is False

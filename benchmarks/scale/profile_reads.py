"""(a) + (d): the owner page's two card reads split into steps, then the other O(bank) read paths, timed on a
synthetic bank built by ``benchmarks.scale.synth``.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.profile_reads --bank <dir>/bank
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from . import isolate


def timed(fn, reps: int = 5):
    """(first, median of the rest) in ms, and the last value."""
    out, value = [], None
    for _ in range(reps):
        t = time.perf_counter()
        value = fn()
        out.append((time.perf_counter() - t) * 1000)
    return round(out[0], 1), round(statistics.median(out[1:]) if len(out) > 1 else out[0], 1), value


def atimed(coro_fn, reps: int = 5):
    return timed(lambda: asyncio.run(coro_fn()), reps)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--owner", default="owner-example")
    ap.add_argument("--other", default="")
    ap.add_argument("--skip-e2e", action="store_true")
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)

    from api.config import Settings
    from api.models.schemas import ClaimListResponse, EntityResponse
    from api.routers import claims as claims_router, entities as entities_router
    from api.services import (claims, decay_policy, decay_tuning, entity_picture, git_service, markdown_parser,
                              turn_authorship)
    from api.services.transclusion_resolver import claim_to_model

    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank))
    assert settings.memory_path == bank
    rows: list[dict] = []

    def row(area, step, first, warm, note=""):
        rows.append({"area": area, "step": step, "first_ms": first, "warm_ms": warm, "note": note})

    page = bank / "entities" / f"{a.owner}.md"
    other = a.other or sorted((bank / "entities").glob("alpha-*.md"))[0].stem

    for label, eid in (("owner", a.owner), ("median page", other)):
        path = bank / "entities" / f"{eid}.md"
        area = f"GET /entities ({label})"
        f, w, text = timed(lambda: path.read_text(encoding="utf-8"))
        row(area, "read_text", f, w, f"{len(text.encode()):,} B")
        f, w, parsed = timed(lambda: markdown_parser.parse(path))
        row(area, "markdown_parser.parse (read + frontmatter YAML)", f, w)
        f, w, hist = atimed(lambda: git_service.get_entity_history(eid, bank))
        row(area, "git_service.get_entity_history (blame + 1 git log per commit)", f, w, f"{len(hist)} commits")
        fm = parsed.frontmatter

        def decay():
            decay_policy.resolve(fm)
            alpha, floor = decay_policy.spacing_params(settings)
            return decay_policy.effective(fm, alpha=alpha, floor=floor, tuning=decay_tuning.load(bank))
        f, w, _ = timed(decay)
        row(area, "decay_policy", f, w)
        f, w, _ = timed(lambda: entity_picture.resolve_page(bank, eid, fm, parsed.body,
                                                            page_mtime=path.stat().st_mtime))
        row(area, "entity_picture.resolve_page", f, w)
        f, w, _ = timed(lambda: entities_router._build_media_block(fm, parsed.body))
        row(area, "_build_media_block", f, w)
        resp = asyncio.run(entities_router.get_entity(eid, settings))
        f, w, js = timed(lambda: resp.model_dump_json(by_alias=True))
        row(area, "serialize EntityResponse (model_dump_json)", f, w, f"{len(js):,} B JSON")
        f, w, _ = atimed(lambda: entities_router.get_entity(eid, settings))
        row(area, "handler total (in process, no HTTP)", f, w)

        area = f"GET /entities/claims ({label})"
        f, w, cl = timed(lambda: claims.parse_claims(parsed.body))
        row(area, "parse_claims (regex + CSafeLoader + from_dict)", f, w, f"{len(cl)} claims")
        m = claims._CLAIMS_BLOCK_RE.search(parsed.body)
        f, w, _ = timed(lambda: claims._CLAIMS_BLOCK_RE.search(parsed.body))
        row(area, "  of which fence regex", f, w)
        import yaml
        f, w, loaded = timed(lambda: yaml.load(m.group("payload"), Loader=claims._SAFE_LOADER), reps=3)
        row(area, "  of which yaml.load (CSafeLoader)", f, w)
        f, w, _ = timed(lambda: [claims.Claim.from_dict(d) for d in loaded])
        row(area, "  of which Claim.from_dict", f, w)
        current = [c for c in cl if not claims.is_record(c) and not claims.is_event(c)]
        f, w, turns = timed(lambda: turn_authorship.TurnAuthorship(bank))
        f, w, models = timed(lambda: [claim_to_model(c, turns=turns) for c in current], reps=3)
        row(area, "claim_to_model x N (one TurnAuthorship, as the route)", f, w, "first rep includes the episode index scan")
        f, w, js = timed(lambda: ClaimListResponse(claims=models).model_dump_json(by_alias=True), reps=3)
        row(area, "serialize ClaimListResponse", f, w, f"{len(js):,} B JSON")
        f, w, _ = timed(lambda: claims_router._build_entity_claims(bank, eid, True, False), reps=3)
        row(area, "handler total include_superseded=true (as the app asks)", f, w)

    # End to end through the ASGI app (no lifespan, no network socket): what the app waits for.
    if not a.skip_e2e:
        import httpx
        from api.main import app

        async def e2e(path):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe") as c:
                r = await c.get(path)
                r.raise_for_status()
                return len(r.content)
        for path in (f"/entities/{a.owner}", f"/entities/{a.owner}/claims?include_superseded=true",
                     f"/entities/{a.owner}/provenance", f"/entities/{other}",
                     f"/entities/{other}/claims?include_superseded=true"):
            f, w, n = timed(lambda: asyncio.run(e2e(path)), reps=3)
            row("HTTP (ASGI, in process)", f"GET {path.replace(a.owner, '<owner>').replace(other, '<median>')}",
                f, w, f"{n:,} B")

    print(json.dumps(rows))
    width = max(len(r["step"]) for r in rows)
    for r in rows:
        print(f"{r['area'][:34]:34} {r['step']:{width}} {r['first_ms']:>9} {r['warm_ms']:>9}  {r['note']}")


if __name__ == "__main__":
    main()

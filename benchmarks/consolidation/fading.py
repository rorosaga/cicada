"""Does the right thing fade? (G66, G147, G170; added 2026-11-23.)

Cicada fades what goes unmentioned, and how fast a page fades is its decay class. Whether the class lands on the right
pages is a thing the other checks cannot see: a page can be complete and true and still be on its way to the archive.
This scores the *finished bank* (the pages' own frontmatter), with no model:

* **keeps** - the people and things the person keeps coming back to must not be fading at the clock (a page below
  the question line is "decaying"; a missing page fails).
* **order** - a role-based order that must hold: the job they hold above the job they left; a person in several recent
  conversations above a place named once. A page the bank does not have at all cannot outrank anything, so a missing
  *lower* page is trivially fine and a missing *upper* page fails. Compared by stored confidence. (A thing that ended
  yesterday is no fair "lower" page at the clock: it was said more recently than anything. Its test is the silence
  probe below.)
* **silence** - the same finished bank with the clock moved forward and only Sleep's decay step run (no model, a copy
  of the bank in a scratch folder): which pages would raise a "still relevant?" question, and which would be archived,
  after two weeks and after six weeks of the person saying nothing. The ``lasting`` pages (partner, sister, employer)
  must not be under the line by then; a thing that ended should be.

The gold names roles in the person's life (``gold["fading"]``), never a number, so it does not encode today's rates.
Kept apart from ``run.py`` so it can be changed on its own.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

#: How long the person says nothing, in days; each is run as passes a week apart (ruling 1 caps one pass at a week).
SILENCE_DAYS = (14, 42)
_STEP = 7


def _term_matches(term, text: str) -> bool:
    """``term`` is a word, or a list of alternatives: any one of them at a word start (``run.matches``' spelling:
    accents folded, hyphens as spaces)."""
    from benchmarks.consolidation.run import matches

    return matches(text, [term if isinstance(term, list) else [term]])


def _page_text(page_id: str, claims: list[dict], prose: str) -> str:
    own = [c.get("text") or "" for c in claims if c.get("page") == page_id]
    return " ".join([prose or "", *own])


def find(pages: list[dict], claims: list[dict], spec) -> list[dict]:
    """The non-owner pages a gold term names. ``spec`` is a word, a list of alternatives, or ``{"name": …, "about":
    …}`` where the page's own claims or prose must also say ``about`` (two pages with one name: a colleague and a
    brother-in-law)."""
    name, about = (spec["name"], spec.get("about")) if isinstance(spec, dict) else (spec, None)
    out = []
    for p in pages:
        if p.get("owner"):
            continue
        names = " | ".join([p["id"], str(p.get("name")), *(p.get("aliases") or [])])
        if _term_matches(name, names) and (about is None or _term_matches(about, _page_text(p["id"], claims, p.get("prose")))):
            out.append(p)
    return out


def _label(spec) -> str:
    name = spec["name"] if isinstance(spec, dict) else spec
    return str(name[0] if isinstance(name, list) else name)


def _frontmatter(bank: Path) -> dict[str, dict]:
    from api.services import markdown_parser

    return {path.stem: (markdown_parser.parse(path).frontmatter or {}) for path in sorted((bank / "entities").glob("*.md"))}


def _confidence(fm: dict) -> float:
    try:
        return float(fm.get("confidence"))
    except (TypeError, ValueError):
        return 0.0


def score_state(pages: list[dict], claims: list[dict], fm: dict[str, dict], gold: dict) -> dict:
    """keeps and order, from the finished bank's frontmatter."""
    keeps_spec = gold.get("keeps", [])
    keeps = []
    for spec in keeps_spec:
        found = find(pages, claims, spec)
        rows = [{"page": p["id"], "status": fm[p["id"]].get("status"), "confidence": round(_confidence(fm[p["id"]]), 3),
                 "decay_class": fm[p["id"]].get("decay_class")} for p in found if p["id"] in fm]
        keeps.append({"term": _label(spec), "ok": bool(rows) and all(r["status"] == "active" for r in rows), "pages": rows})

    def conf(spec):
        return [(p["id"], _confidence(fm[p["id"]])) for p in find(pages, claims, spec) if p["id"] in fm]

    pairs = [(row["above"], row["below"], row.get("why", "")) for row in gold.get("outranks", [])]
    order = []
    for above, below, why in pairs:
        up, down = conf(above), conf(below)
        # No upper page: the check fails. No lower page: nothing to outrank, trivially fine.
        ok = bool(up) and all(u > d for _, u in up for _, d in down)
        order.append({"above": _label(above), "below": _label(below), "why": why, "ok": ok,
                      "above_pages": [(i, round(c, 3)) for i, c in up], "below_pages": [(i, round(c, 3)) for i, c in down]})
    return {"keeps": keeps, "order": order}


def probe_silence(bank: Path, clock: date, days: tuple[int, ...] = SILENCE_DAYS) -> dict:
    """The finished bank (a copy; the original is never touched), the clock moved forward, Sleep's decay step only.

    Returns ``{days: {"asked": [ids], "archived": [ids], "below_line": [ids]}}``: the pages whose decay would raise a
    question (``decay_nudge``), would be archived, and sit below the question line at the end. Runs
    ``conflict_resolver.resolve_and_prune`` with nothing to resolve (no model call) and applies its decay changes to the
    copy, one pass a week as a schedule would (ruling 1 caps one pass at a week of live silence)."""
    from api.config import Settings
    from api.services import conflict_resolver
    from api.services.sleep_cycle import _load_existing_entities

    work = Path(tempfile.mkdtemp(prefix="decay-probe-"))
    try:
        copy = work / "bank"
        shutil.copytree(bank, copy, ignore=shutil.ignore_patterns(".git", "episodes", "inbox"))
        settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(copy))
        asked: set[str] = set()
        archived: set[str] = set()
        out: dict = {}
        day = 0
        for target in sorted(days):
            while day < target:
                day = min(day + _STEP, target)
                now = datetime.combine(clock + timedelta(days=day), datetime.min.time())
                existing = _load_existing_entities(copy)
                changes = asyncio.run(conflict_resolver.resolve_and_prune([], existing, settings, now=now, tuning={}))
                asked |= {c["id"] for c in changes if c.get("action") == "decay_nudge"}
                archived |= {c["id"] for c in changes if c.get("action") == "archive"}
                conflict_resolver.apply_changes(changes, copy)
            fm = _frontmatter(copy)
            out[str(target)] = {"asked": sorted(asked), "archived": sorted(archived),
                                "below_line": sorted(i for i, f in fm.items()
                                                     if f.get("status") in ("decaying", "archived") and not f.get("owner"))}
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def score(bank: Path, snap: dict, gold: dict) -> dict:
    """The ``fading`` block of a leg's score: ``summary`` (the counts the report prints) and the evidence."""
    fading = gold.get("fading")
    if not fading:
        return {"summary": {}, "keeps": [], "order": [], "silence": {}}
    pages, claims = snap["pages"], snap["claims"]
    fm = _frontmatter(bank)
    state = score_state(pages, claims, fm, fading)
    silence = probe_silence(bank, date.fromisoformat(snap["clock"]))
    long = silence[str(max(SILENCE_DAYS))]
    below = set(long["below_line"])   # asked about, archived, or already under the line by then

    def ids(spec) -> set[str]:
        return {p["id"] for p in find(pages, claims, spec)}

    keeps_gone = [_label(spec) for spec in fading.get("lasting", []) if ids(spec) & below]
    # An ended thing is settled when every page of it is under the line; one the bank never made has nothing to ask.
    ended_left = [_label(spec) for spec in fading.get("ended", []) if ids(spec) - below]
    for days, row in silence.items():
        lasting_ids = set().union(*[ids(spec) for spec in fading.get("lasting", [])]) if fading.get("lasting") else set()
        row["lasting_asked"] = sorted((set(row["asked"]) | set(row["archived"])) & lasting_ids)
    summary = {
        "fade_keeps_ok": sum(1 for r in state["keeps"] if r["ok"]), "fade_keeps": len(state["keeps"]),
        "fade_order_ok": sum(1 for r in state["order"] if r["ok"]), "fade_order": len(state["order"]),
        # After six weeks of silence: the lasting pages (partner, sister, employer) under the question line (want 0),
        # and the things that ended that would be (want all of them).
        "silence_lasting_fading": len(keeps_gone), "silence_lasting": len(fading.get("lasting", [])),
        "silence_ended_fading": len(fading.get("ended", [])) - len(ended_left), "silence_ended": len(fading.get("ended", [])),
        "silence_all_asked": len(set(long["asked"]) | set(long["archived"])),
    }
    state["silence_lasting_fading"], state["silence_ended_not_fading"] = keeps_gone, ended_left
    return {"summary": summary, **state, "silence": silence}

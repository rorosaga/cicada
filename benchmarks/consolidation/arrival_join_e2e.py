"""The arrival join through the real tail, on a scratch bank (G245, `api/services/arrival_join*.py`).

The battery (`arrival_join_battery.py`) replays the RULES. This runs the product's own tail — `sleep_cycle._run_engine_independent_tail`
with every step that would reach out (the polls, the web checks, a model's reading of a page, the logo warm-up) replaced by a
no-op, and every step the join composes with left real: the refusals before the same-name review, 74a's review, 74b's join, the
catch-up proposers, the link backfill, the LinkedIn and Contacts rematches, the record — on a scratch bank and a scratch
``CICADA_HOME``, a synthetic directory and Contacts file, and git. ``arrival_join.LIVE`` is forced on HERE ONLY (it ships false);
the veto's engine is a stand-in that answers "fits". No model, no key, nothing read from the person's bank or home.

    api/.venv/bin/python -m benchmarks.consolidation.arrival_join_e2e

It tells one story, one night per phase: (1) the join is the alias and its commits, and a Contacts card attaches with its photo;
(2) the next night writes nothing; (3) "Not them" takes everything back as commits that say what they undo, and the page returns
to what it held but for the closed facts and the marks that stop it coming back; (4) nothing joins the pair again, including after
a page of that full name is born. A second story (`birth_story`) tells the same for Route H, a first name still held below the
promotion bar, born as the full name (`arrival_birth`). Exit 0 when every check holds.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60

#: What the tail does that would reach out or read with a model: replaced by a no-op here. The join's neighbours stay real.
STUBBED = ("_refresh_state_safely", "_site_sources_safely", "_source_refresh_safely", "_web_check_safely", "_web_context_safely",
           "_poll_connectors_safely", "_poll_feeds_and_calendars_safely", "_backfill_links_safely", "_resolve_papers_safely",
           "_resolve_books_safely", "_replay_wispr_todos_safely", "_in_short_safely", "_media_read_safely", "_warm_logos_safely",
           "_embed_indexed_episodes_safely", "_refresh_questions_safely")


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], capture_output=True, text=True).stdout


def story(root: Path) -> dict:
    """The whole story on ``root``; ``{"ok": bool, "checks": {name: bool}, ...}``. ``CICADA_HOME`` is set under ``root``."""
    os.environ["CICADA_HOME"] = str(root / "home")
    from api.services import (arrival_join as aj, arrival_join_write as w, bank_index, contacts_local, fact_sources, linkedin_people,
                              markdown_parser, merge_rejections, person_photo, sleep_cycle)
    from benchmarks.consolidation import arrival_join_battery as battery

    async def nothing(*_a, **_k):
        return None

    async def engine(settings, *, user_triggered):
        async def judge(system, prompt):
            return {"verdict": "fits", "quote": "", "reason": "stand-in"}

        return judge, ""

    saved = {name: getattr(sleep_cycle, name) for name in STUBBED}
    saved_engine, saved_live = aj._engine_judge, aj.LIVE
    for name in STUBBED:
        setattr(sleep_cycle, name, nothing)
    aj._engine_judge, aj.LIVE = engine, True
    checks: dict[str, bool] = {}
    try:
        scene = battery.Scene(conns=[battery.conn("Sam", "Okafor", battery.d(2), company="Alpha Robotics", position="Founder")],
                              cards=[("Sam", "Okafor", battery.d(3))])
        bank = battery.build(root, scene)
        contacts_local.save_waiting(bank.name, [{"id": "card-0", "given_name": "Sam", "family_name": "Okafor",
                                                 "has_organization": True, "has_email": True,
                                                 "photo_b64": base64.b64encode(JPEG).decode()}])
        from api.config import Settings

        settings = Settings(memory_path=bank)

        def night() -> None:
            bank_index.invalidate(bank)
            asyncio.run(sleep_cycle._run_engine_independent_tail(
                bank, settings, sleep_cycle._StageOutcome(committed=True), user_triggered=False))
            bank_index.invalidate(bank)

        def page():
            return markdown_parser.parse(bank / "entities" / "sam.md")

        before = page()
        night()
        subjects = _git(bank, "log", "--format=%s").splitlines()
        fm = page().frontmatter
        record = w.latest(fm, w.JOINED) or {}
        checks["the alias is on the page, the title stays"] = fm.get("aliases") == ["Sam Okafor"] and fm.get("name") == "Sam"
        checks["one commit for the join, one for each rematch, one for the record"] = (
            sum(s.startswith("Arrival join 20") for s in subjects) == 1 and sum(s.startswith("LinkedIn connections") for s in subjects) == 1
            and sum(s.startswith("Contacts") for s in subjects) == 1 and sum(s.startswith("Arrival join recorded") for s in subjects) == 1)
        link = next((s for s in fact_sources.as_sources(fm.get("sources")) if s.get("predicate") == "linkedin"), {})
        checks["the LinkedIn link is a guess, never confident, no photo request"] = (
            link.get("match") == "alias" and person_photo.is_own_account(link) is False)
        checks["the card's sources and photo attached"] = (
            any(str(s.get("ref")).startswith("addressbook://") for s in fact_sources.as_sources(fm.get("sources")))
            and bool(fm.get("contacts_photo")))
        checks["the record names the caused commits, claims and links by hash"] = (
            len(record.get("commits") or []) == 3 and len(record.get("claims") or []) == 3 and len(record.get("sources") or []) >= 2
            and "Okafor" not in json.dumps(record))
        head = _git(bank, "rev-parse", "HEAD")
        night()
        night()
        checks["later nights write nothing"] = _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
        out = w.undo(bank, "sam", before=None)
        fm2 = page().frontmatter
        message = _git(bank, "log", "-1", "--format=%B")
        checks["Not them: the name, link, card entries and face are gone"] = (
            "aliases" not in fm2 and not [s for s in fm2.get("sources") or [] if s.get("predicate") == "linkedin"
                                          or str(s.get("ref")).startswith("addressbook://")] and "contacts_photo" not in fm2)
        checks["Not them: its commit says what it undoes"] = all(f"Undoes: {sha}" in message for sha in record.get("commits") or []) \
            and out["commit"] == _git(bank, "rev-parse", "HEAD").strip()
        checks["Not them: the page's prose is what it was"] = (
            page().body.split("```")[0].strip() == before.body.split("```")[0].strip() and fm2["name"] == before.frontmatter["name"])
        head = _git(bank, "rev-parse", "HEAD")
        night()
        checks["nothing joins the pair again"] = _git(bank, "rev-parse", "HEAD") == head
        (bank / "entities" / "sam-okafor.md").write_text("---\nname: Sam Okafor\ntype: person\nstatus: active\n---\n## Summary\nx\n")
        bank_index.invalidate(bank)
        night()
        checks["a page of the full name born later is a refused pair for every joiner"] = (
            merge_rejections.is_rejected(bank, "sam", "sam-okafor") and merge_rejections.arrival_refusals(bank) == [])
        return {"ok": all(checks.values()), "checks": checks, "commits": len(_git(bank, "log", "--format=%h").splitlines()),
                "report": aj.printable(bank.name).get("reasons")}
    finally:
        for name, fn in saved.items():
            setattr(sleep_cycle, name, fn)
        aj._engine_judge, aj.LIVE = saved_engine, saved_live


def birth_story(root: Path) -> dict:
    """Route H through the same real tail (`arrival_birth`): a first name HELD below the promotion bar, and a connection with that
    given name the same week. Phase 0 ships as shipped (the switch false): nothing is written and the report says ``would_birth``.
    Then the switch is forced on HERE ONLY: (1) the page is born under the full name with the said form as an alias, the connection
    attached in the same write and only proposed, the held claims landed, the line gone; (2) the next nights write nothing; (3)
    "Not them" archives the page, puts the held line back byte for byte, and refuses the pair; (4) nothing is born again."""
    os.environ["CICADA_HOME"] = str(root / "home")
    from api.services import (arrival_birth as ab, arrival_join as aj, arrival_join_write as w, bank_index, fact_sources,
                              markdown_parser, merge_rejections, pending_store, person_photo, sleep_cycle)
    from benchmarks.consolidation import arrival_join_battery as battery

    async def nothing(*_a, **_k):
        return None

    async def engine(settings, *, user_triggered):
        async def judge(system, prompt):
            return {"verdict": "fits", "quote": "", "reason": "stand-in"}

        return judge, ""

    saved = {name: getattr(sleep_cycle, name) for name in STUBBED}
    saved_engine, saved_live, saved_birth = aj._engine_judge, aj.LIVE, ab.LIVE
    for name in STUBBED:
        setattr(sleep_cycle, name, nothing)
    aj._engine_judge, aj.LIVE, ab.LIVE = engine, False, False
    checks: dict[str, bool] = {}
    try:
        scene = battery.Scene(held=True, holder_claims=[("works-at", "Alpha Robotics")],
                              conns=[battery.conn("Sam", "Okafor", battery.d(2), company="Alpha Robotics", position="Founder")])
        bank = battery.build(root, scene)
        from api.config import Settings

        settings = Settings(memory_path=bank)

        def night() -> None:
            bank_index.invalidate(bank)
            asyncio.run(sleep_cycle._run_engine_independent_tail(
                bank, settings, sleep_cycle._StageOutcome(committed=True), user_triggered=False))
            bank_index.invalidate(bank)

        store = (bank / "pending_entities.jsonl").read_bytes()
        head = _git(bank, "rev-parse", "HEAD")
        night()
        report = aj.printable(bank.name)
        checks["shipped (switch false): nothing written, the name stays held"] = (
            _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
            and (bank / "pending_entities.jsonl").read_bytes() == store and not (bank / "entities" / "sam-okafor.md").exists())
        checks["shipped: the report says it would have been born, by hash"] = (
            report.get("reasons") == {"would_birth": 1} and report["items"][0]["route"] == "birth"
            and "sam" not in json.dumps(report).lower().replace("namesakes", ""))
        ab.LIVE = True
        night()
        page_path = bank / "entities" / "sam-okafor.md"
        fm = markdown_parser.parse(page_path).frontmatter if page_path.exists() else {}
        subjects = _git(bank, "log", "--format=%s").splitlines()
        record = w.latest(fm, w.JOINED) or {}
        link = next((s for s in fact_sources.as_sources(fm.get("sources")) if s.get("predicate") == "linkedin"), {})
        checks["born under the full name, the said form an alias, the line gone"] = (
            fm.get("name") == "Sam Okafor" and fm.get("aliases") == ["Sam"] and pending_store.held_line(bank, "Sam") is None)
        checks["one birth commit, one record commit"] = (
            sum(s.startswith("Arrival join 20") for s in subjects) == 1 and sum(s.startswith("Arrival join recorded") for s in subjects) == 1)
        checks["the link came with the page and is a guess, never confident, no photo request"] = (
            link.get("match") == "alias" and person_photo.is_own_account(link) is False and not fact_sources.trusted(link))
        checks["the held claim landed on the page"] = any(
            c.id == "clm_sam_0" for c in __import__("api.services.claims", fromlist=["parse_claims"]).parse_claims(
                markdown_parser.parse(page_path).body))
        checks["the record is hashes, not names"] = (
            bool(record.get("birth")) and "Okafor" not in json.dumps({**record, "claims": []}) and len(record.get("commits") or []) >= 1)
        head = _git(bank, "rev-parse", "HEAD")
        night()
        night()
        checks["later nights write nothing"] = _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""
        w.undo(bank, "sam-okafor", before=None)
        fm2 = markdown_parser.parse(page_path).frontmatter
        checks["Not them: the page is archived, undoably, and the name leaves"] = (
            fm2.get("status") == "archived" and fm2["archived_by"]["prior_status"] == "active" and "aliases" not in fm2)
        checks["Not them: the held line is back byte for byte"] = (bank / "pending_entities.jsonl").read_bytes() == store
        checks["Not them: the pair is refused"] = merge_rejections.is_rejected(bank, "sam", "sam-okafor")
        night()
        night()
        # (the "Confirm links" question the proposed link raised is withdrawn by the tail's own "Where to check" step: not a birth)
        checks["nothing is born again"] = (
            sum(s.startswith("Arrival join 20") for s in _git(bank, "log", "--format=%s").splitlines()) == 1
            and pending_store.held_line(bank, "Sam") is not None
            and markdown_parser.parse(page_path).frontmatter.get("status") == "archived")
        return {"ok": all(checks.values()), "checks": checks, "commits": len(_git(bank, "log", "--format=%h").splitlines())}
    finally:
        for name, fn in saved.items():
            setattr(sleep_cycle, name, fn)
        aj._engine_judge, aj.LIVE, ab.LIVE = saved_engine, saved_live, saved_birth


def main() -> int:
    ok = True
    for name, run in (("page", story), ("birth", birth_story)):
        with tempfile.TemporaryDirectory(prefix=f"arrival-e2e-{name}-") as tmp:
            result = run(Path(tmp))
        print(json.dumps({name: result}, indent=1))
        ok = ok and result["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

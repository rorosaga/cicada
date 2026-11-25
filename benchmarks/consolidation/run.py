"""G148: how well a model consolidates, measured on what Sleep wrote rather than on the answers Ask gives.

Invented people's two months (``fixture.json``, ``fixture_noor.json``; one bank each, ``PEOPLE``) go through the production stager and ``sleep_cycle.run(drain=True)``
on a scratch bank in two phases: the first conversations, one drain; then later conversations plus one conversation
edited in place (a revision), and a second drain on the same bank. Then the bank is scored against what the
conversations said, mostly in code with no model:

- **points**: is each fact held as a claim (and, looser, anywhere on a page)? This is extraction recall, as in HaluMem.
- **updates**: when a later conversation changes a value, is the new one current and the old one closed? Each update
  scores *correct*, *both current*, *stale only* or *missing*. One of them is the edited conversation.
- **forbid**: what the assistant said or suggested, and the person declined, must not be held as the person's fact.
- **people**: a nickname and a full name are one page; two people sharing a first name are two.
- **pages**: who and what is mentioned in 2+ conversations gets a page; a one-off mention does not.
- **dated**: "yesterday" in a dated conversation is dated from that conversation, not from the day Sleep ran; the day
  counts on a page's claim or on one held under a waiting name (``held_waiting``).
- **integrity**: a password said in a chat reaches no page; no project is made by Sleep; nothing is evergreen; the share
  of claims whose evidence is a located span.

``judge`` then asks one fixed model, once per conversation, whether each claim citing it is supported, a fair inference,
misattributed (the assistant said it, the claim credits the person) or unsupported. This is extraction precision and
the hallucination rate.

    python -m benchmarks.consolidation.run run --models opus,sonnet,haiku --repeats 2 --out OUT
    python -m benchmarks.consolidation.run judge OUT --judge-model opus
    python -m benchmarks.consolidation.run report OUT

Every leg runs in its own process on its own scratch bank and home (``engine_parity``'s isolation); nothing reads the
person's bank or home. Each leg costs two plan drains over 25 conversations; ``judge`` costs one call per conversation
a leg's claims cite. Read the matched claims in ``score.json`` before quoting a number: matching is by spelling.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIXTURE = Path(__file__).with_name("fixture.json")
#: Every invented person, by the folder name a leg gives them. Each runs on a bank of their own.
PEOPLE = {"ines": FIXTURE, "noor": Path(__file__).with_name("fixture_noor.json")}
MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre")
MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre")
_DAY_TOKEN = re.compile(r"\{day:([+-]\d+)\}")
_DATE_TOKEN = re.compile(r"^\{date:([+-]?\d+)\}$")


# ---- the fixture, on a clock -----------------------------------------------------------------------------------------

def load_fixture(path: Path | str = FIXTURE) -> dict:
    """A fixture by path, or by a person's name in ``PEOPLE``."""
    path = PEOPLE.get(path, path) if isinstance(path, str) else path
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _day(clock: date, offset: int) -> date:
    return clock + timedelta(days=offset)


def _spoken(d: date, lang: str) -> str:
    if lang == "es":
        return f"{d.day} de {MONTHS_ES[d.month - 1]}"
    if lang == "fr":
        return f"{d.day} {MONTHS_FR[d.month - 1]}"
    return f"{d.day} {d.strftime('%B')}"


def _lang(texts: list[str]) -> str:
    """The conversation's language for writing a date, by its common words (a name's accent decides nothing)."""
    words = re.findall(r"[a-zà-ÿ']+", " ".join(texts).lower())
    score = {"es": sum(w in {"el", "la", "que", "mi", "se", "para", "una", "con", "y"} for w in words),
             "fr": sum(w in {"je", "mon", "ma", "les", "des", "une", "et", "est", "vient", "pour"} or w.startswith("j'")
                       for w in words)}
    best = max(score, key=score.get)
    return best if score[best] >= 2 else "en"


def render_texts(texts: list[str], day_offset: int, clock: date, lang: str | None = None) -> list[str]:
    """Texts with ``{day:+N}`` written out from the conversation's own day, in the conversation's language."""
    lang, base = lang or _lang(texts), _day(clock, day_offset)
    return [_DAY_TOKEN.sub(lambda m: _spoken(base + timedelta(days=int(m.group(1))), lang), t) for t in texts]


def render_turns(conv: dict, clock: date) -> list[str]:
    """A chat's turns, or a meeting's lines, with ``{day:+N}`` written out."""
    if conv.get("kind") == "meeting":
        return render_texts([text for _, text in conv["lines"]], conv["day"], clock, conv.get("lang"))
    return render_texts(conv["turns"], conv["day"], clock, conv.get("lang"))


def meeting_markdown(conv: dict, clock: date) -> tuple[str, str]:
    """A meeting as the Hex recorder exports it (``meeting_transcripts`` parses it): its file name and its text."""
    day = _day(clock, conv["day"])
    lines = [f"# {conv['title']}", "", f"- **Date:** {day.isoformat()} 10:00", "", "## Transcript", ""]
    for i, ((label, _), text) in enumerate(zip(conv["lines"], render_turns(conv, clock))):
        lines += [f"**{label}** · {i * 20 // 60:02d}:{i * 20 % 60:02d}", text, ""]
    return f"{day.isoformat()} 1000 {conv['title']}.md", "\n".join(lines)


def date_spellings(d: date) -> list[str]:
    return [d.isoformat(), f"{d.day} {d.strftime('%B')}", f"{d.strftime('%B')} {d.day}",
            f"{d.day} de {MONTHS_ES[d.month - 1]}", f"{d.strftime('%b')} {d.day}", f"{d.day} {d.strftime('%b')}"]


def expand_groups(groups: list, clock: date) -> list[list[str]]:
    """Gold ``says``: each group is one spelling or a list of spellings; every group must match. ``{date:N}`` is the
    clock's day plus N in every way a page may write it."""
    out = []
    for g in groups:
        alts = g if isinstance(g, list) else [g]
        spelled: list[str] = []
        for a in alts:
            m = _DATE_TOKEN.match(a)
            spelled.extend(date_spellings(_day(clock, int(m.group(1)))) if m else [a])
        out.append(spelled)
    return out


# ---- matching --------------------------------------------------------------------------------------------------------

def norm(text: str) -> str:
    """Lower case, accents folded, ids' hyphens and underscores as spaces, one space between words."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", text)).strip()


def _alt_re(alt: str) -> re.Pattern:
    """A spelling at a word start; one that ends in a digit must end there too, so "20" never matches "2026"."""
    spelled = norm(alt)
    return re.compile(r"(?<![a-z0-9])" + re.escape(spelled) + (r"(?![0-9])" if spelled[-1:].isdigit() else ""))


def matches(text: str, groups: list[list[str]]) -> bool:
    t = norm(text)
    return all(any(_alt_re(a).search(t) for a in group) for group in groups)


def claim_text(c: dict) -> str:
    """What a claim says, with its dates: a moved date can live in ``valid_from`` or ``expected_end`` alone."""
    return " ".join(str(c.get(k) or "") for k in ("subject", "predicate", "object", "text", "valid_from", "expected_end"))


ENDED = re.compile(r"\b(?:dropped|left|stopped|no longer|moved off|moved from|switched from|replaced|abandoned)\b")
HAS_ROLE = re.compile(r"^(?:has|have|had|tiene|a pour|a un|a une)\b")
#: A claim can itself say the old value ended ("TypeScript (browser), replacing Python"): that is the change, not the
#: old value held. The ending word and the few words after it (what it ended) are taken out before the stale test.
ENDS_WHAT = re.compile(r"\b(?:dropped|dropping|left|leaving|stopped|stopping|no longer|moved off|moved from|switched from|"
                       r"switching from|replaced|replacing|replaces|replacement of|rewrote|rewritten|instead of|abandoned|"
                       r"abandoning|migrated from|migrating from|ported from)\b(?:\W+\w+){0,3}"
                       # ... or the ending said after the old value: "the Python version was dropped"
                       r"|(?:\w+\W+){1,3}(?:was|were|is|has been|got)\W+(?:dropped|replaced|abandoned|retired|removed|rewritten)\b")
NEGATION = re.compile(r"\b(?:not|never|no|no longer|declined|decided against|rejected|against|won't|doesn't|didn't|"
                      r"too expensive|instead of|stayed? on|staying|hypothetical|if|ruled out|refused|skipped|dropped|skips?|"
                      r"without|sans|sin)\b")


def is_current(c: dict) -> bool:
    return not c.get("valid_to") and not c.get("superseded_by")


def said_by(c: dict) -> str:
    """Whose words a claim rests on, from its evidence spans (``observer`` is ``agent`` on every Sleep claim):
    ``person`` for a span of the person's own turn, ``speaker`` for another person in a meeting, ``assistant`` for the
    assistant's (or a recorder's summary), ``inferred`` for no span."""
    kinds = {e.get("kind") for e in c.get("evidence") or []}
    if "user" in kinds:
        return "person"
    return "speaker" if "speaker" in kinds else "assistant" if "assistant" in kinds else "inferred"


def is_person(c: dict) -> bool:
    return said_by(c) == "person"


# ---- one leg ---------------------------------------------------------------------------------------------------------

def _drafts(convs: list[dict], clock: date, *, revised_at: str | None = None):
    import hashlib

    from api.services import episode_staging, meeting_transcripts

    drafts = []
    for conv in convs:
        day = _day(clock, conv["day"]).isoformat()
        if conv.get("kind") == "meeting":
            name, text = meeting_markdown(conv, clock)
            draft = meeting_transcripts.draft_for_file(
                {"id": "bench-meetings", "recorder": "hex"}, name, text, mtime_iso=f"{day}T11:00:00+00:00",
                sha=hashlib.sha256(text.encode()).hexdigest(), tz_name="UTC")
            if draft is None:
                raise SystemExit(f"{conv['id']}: the meeting parser read no transcript")
            drafts.append(draft)
            continue
        turns = [episode_staging.Turn(text=t, speaker="user" if i % 2 == 0 else "assistant",
                                      ts=f"{day}T10:{i:02d}:00+00:00") for i, t in enumerate(render_turns(conv, clock))]
        drafts.append(episode_staging.EpisodeDraft(
            title=conv["title"], source_id=f"bench:{conv['id']}", timestamp=f"{day}T10:00:00+00:00",
            original_date=day, source="import", origin="chatgpt",
            source_updated_at=revised_at if conv.get("edit") else None,
            extra={"session_id": f"ses_bench_{conv['id']}"}, turns=turns))
    return drafts


def init_bank(bank: Path, owner: str) -> None:
    from api.services import bank_registry, owner_identity, predicates
    from benchmarks.engine_parity import _git

    bank.mkdir(parents=True, exist_ok=True)
    for name in ("entities", "episodes", "inbox"):
        (bank / name).mkdir(exist_ok=True)
    (bank / ".gitignore").write_text("\n".join(bank_registry.DERIVED_ARTIFACTS) + "\n")
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Cicada Bench")
    _git(bank, "config", "user.email", "bench@cicada.local")
    entity_id, _ = owner_identity.ensure_owner_entity(bank, owner)
    owner_identity.save_owner({"name": owner, "handle": None, "email": None, "entity_id": entity_id})
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "Bench seed\n\nCicada-Author: cicada")


def stage(bank: Path, convs: list[dict], clock: date, label: str) -> dict:
    from api.services import episode_staging, git_service

    revised_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = episode_staging.stage(_drafts(convs, clock, revised_at=revised_at), bank / "episodes")
    git_service.commit_paths_sync(bank, git_service.build_commit_message(label, [], authors=["user"]), result.paths)
    return {"created": result.created, "updated": result.updated, "skipped": result.skipped}


def entity_rows(bank: Path) -> tuple[list[dict], list[dict]]:
    """Every page (name, type, aliases, decay class) and every claim with what scoring reads."""
    from api.services import claims as claims_module, markdown_parser

    pages, claims = [], []
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        aliases = fm.get("aliases") or []
        pages.append({"id": path.stem, "name": fm.get("name") or fm.get("title") or path.stem, "type": fm.get("type"),
                      "status": fm.get("status"), "decay_class": fm.get("decay_class"), "owner": bool(fm.get("owner")),
                      "aliases": [str(a) for a in aliases] if isinstance(aliases, list) else [str(aliases)],
                      "prose": claims_module.strip_claims_block(parsed.body)})
        for c in claims_module.parse_claims(parsed.body):
            ev = list(getattr(c, "evidence", None) or [])
            claims.append({
                "page": path.stem, "id": c.id, "text": c.text, "subject": c.subject, "predicate": c.predicate,
                "object": str(c.object), "observer": c.observer, "valid_from": c.valid_from, "valid_to": c.valid_to,
                "superseded_by": c.superseded_by, "expected_end": getattr(c, "expected_end", None),
                "target": getattr(c, "target", None),
                "confidence": c.confidence, "source_episodes": list(c.source_episodes or []),
                "evidence": [{"episode": e.episode, "kind": e.kind, "start": e.start, "end": e.end} for e in ev]})
    return pages, claims


#: The plan's names for the three tiers, and the tier each is on a Claude key.
TIERS = {"haiku": "small", "sonnet": "standard", "opus": "top"}


def engine_model(engine: str, name: str) -> str:
    """What ``settings_for`` takes: the plan's alias as is, a key's full id for the same tier."""
    if engine == "plan":
        return name
    from api.services import anthropic_models

    return anthropic_models.tier(TIERS.get(name, name)) or name if name in TIERS else name


def leg_label(engine: str, model: str, judge: str) -> str:
    return f"{engine}:{model}" + ("" if judge == model else f" judge:{judge}")


def run_leg(model: str, out: Path, *, clock: date, engine: str = "plan", judge: str | None = None,
            person: str = "ines") -> dict:
    """One model, both phases, on a fresh bank under ``out``. Runs in its own process (see ``main``). ``judge`` is
    Sleep's own Stage 2 judge; unset, the product's default for the engine (the small tier on both)."""
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    _refuse_real_paths(out)
    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture(person)
    with _leg_environment(home, bank):
        return _run_leg(model, out, bank, home, fixture, clock, engine, judge or "haiku")


def _run_leg(model: str, out: Path, bank: Path, home: Path, fixture: dict, clock: date, engine: str,
             judge: str) -> dict:
    import asyncio
    from unittest.mock import patch

    from api.services import entity_resolver, providers, sleep_cycle
    from benchmarks.engine_parity import _usage_events, _by_stage, settings_for
    from benchmarks.system.engine import embed

    init_bank(bank, fixture["owner"])
    settings = settings_for("plan" if engine == "plan" else "key", bank, model=engine_model(engine, model),
                            judge=engine_model(engine, judge))
    fake_embed = lambda *a, **k: (embed, "fake-hash-v1")  # noqa: E731 — the search model is not what is compared
    phases = []
    # Every same-name judge call (`same_name_people`), as asked and as answered, beside the bank: the replay battery
    # (`same_name_battery.py`) is built from these, so it tests the inputs the pipeline really produces.
    asked = entity_resolver._same_name_ask
    calls_path = out / "same_name_calls.jsonl"

    async def recording_ask(settings_, system, prompt, *args, **kwargs):
        answer = await asked(settings_, system, prompt, *args, **kwargs)
        with open(calls_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"system": system, "prompt": prompt, "answer": answer}, ensure_ascii=False) + "\n")
        return answer

    for phase in sorted({c["phase"] for c in fixture["conversations"]}):
        convs = [c for c in fixture["conversations"] if c["phase"] == phase]
        staged = stage(bank, convs, clock, f"Bench intake, phase {phase}")
        started = time.perf_counter()
        with patch.object(providers, "resolve_embed_fn", fake_embed), \
                patch.object(entity_resolver, "_same_name_ask", recording_ask), \
                patch.object(providers, "resolve_embed_fn_for_model", fake_embed), \
                patch.object(providers, "cached_embed_fn_for_model", fake_embed):
            asyncio.run(sleep_cycle.run(settings, f"sleep_bench_{phase}", user_triggered=True, drain=True))
        state = sleep_cycle.get_sleep_state()
        ds = state.drain
        phases.append({"phase": phase, "staged": staged, "seconds": round(time.perf_counter() - started, 1),
                       "error": state.error, "stop": ds.stop.reason if ds and ds.stop else None,
                       "parked": dict(getattr(ds, "parked", {}) or {}),
                       "unread": dict(getattr(ds, "unread", {}) or {})})
    from api.services import markdown_parser

    pages, claims = entity_rows(bank)
    questions = []
    for path in sorted((bank / "inbox").rglob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        questions.append({"kind": fm.get("kind") or fm.get("type"), "entity": fm.get("entity") or fm.get("entity_id"),
                          "status": fm.get("status")})
    unprocessed = sum(1 for p in (bank / "episodes").glob("*.md")
                      if not (markdown_parser.parse(p).frontmatter or {}).get("processed"))
    events = _usage_events(home)
    snap = {
        "model": leg_label(engine, model, judge), "engine": engine, "clock": clock.isoformat(), "phases": phases, "pages": pages, "claims": claims,
        "questions": questions, "episodes_unprocessed": unprocessed,
        "usage": {"calls": len(events), "failed": sum(1 for e in events if not e.get("ok", True)),
                  "input": sum(e.get("input_tokens") or 0 for e in events),
                  "cache_read": sum(e.get("cache_read_tokens") or 0 for e in events),
                  "output": sum(e.get("output_tokens") or 0 for e in events),
                  "models": sorted({e["model"] for e in events if e.get("model")}),
                  "cost_usd": round(sum(e.get("cost_usd") or 0.0 for e in events), 4),
                  "by_stage": _by_stage(events)},
    }
    (out / "snapshot.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "score.json").write_text(json.dumps(score(snap, bank, fixture), indent=1, ensure_ascii=False),
                                    encoding="utf-8")
    return snap


# ---- scoring, no model -----------------------------------------------------------------------------------------------

def _page_names(p: dict) -> str:
    return " | ".join([p["id"], str(p["name"]), *p["aliases"]])


def held_lines(bank: Path) -> list[dict]:
    """The people held below the promotion bar (`pending_entities.jsonl`): name and, for a second person of a name, title."""
    path = bank / "pending_entities.jsonl"
    found: list[dict] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if isinstance(line, dict) and line.get("type") == "person":
                found.append({"name": str(line.get("name") or ""), "title": str(line.get("title") or "")})
    return found


def held_claims(bank: Path) -> list[dict]:
    """The claims held under a waiting name (``held_claims`` in ``pending_entities.jsonl``): Stage 1 wrote the claim,
    but its subject is below the promotion bar, so it waits with the name and is written when a page is made. A held
    claim is a claim (subject, predicate, object, its dates, a located span), not prose; it is just not on a page yet."""
    path = bank / "pending_entities.jsonl"
    held: list[dict] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            held.extend(c for c in ((line.get("held_claims") or []) if isinstance(line, dict) else [])
                        if isinstance(c, dict))
    return held


def held_claim_texts(bank: Path) -> list[str]:
    """What the claims held under a waiting name say (`held_claims`)."""
    return [claim_text(c) for c in held_claims(bank)]


def score(snap: dict, bank: Path, fixture: dict) -> dict:
    clock = date.fromisoformat(snap["clock"])
    gold = fixture["gold"]
    claims, pages = snap["claims"], snap["pages"]
    prose = [_page_names(p) + " " + (p.get("prose") or "") for p in pages]

    def held(groups):
        hit = [c for c in claims if matches(claim_text(c), groups)]
        return hit

    points = []
    waiting = held_claim_texts(bank)
    for row in gold["points"]:
        groups = expand_groups(row["says"], clock)
        hit = held(groups)
        # ``held_waiting``: no claim on a page, but one held under a waiting name (a one-off person or thing, below the
        # promotion bar by design) says it. Apart from ``claim``, which stays "on a page".
        waits = [t for t in waiting if matches(t, groups)] if not hit else []
        points.append({"id": row["id"], "claim": bool(hit), "anywhere": bool(hit) or any(matches(t, groups) for t in prose),
                       "held_waiting": bool(waits), "matched": [claim_text(c) for c in hit[:3]] or waits[:3]})

    owner_id = next((p["id"] for p in pages if p["owner"]), None)

    def about(row, c) -> bool:
        """An update ``on_owner`` is about the owner's own job, home, ...: another person's claim that happens to name the
        same employer (a colleague's "works at <the old employer>", true of them) is neither its old nor its new value."""
        return not row.get("on_owner") or owner_id in (c.get("subject"), c.get("object"))

    updates = []
    for row in gold["updates"]:
        # A row with no ``current`` is a thing that only ENDS (a job left with no new one named): correct when nothing
        # stale is current.
        cur = ([c for c in held(expand_groups(row["current"], clock)) if is_current(c) and about(row, c)]
               if "current" in row else [])
        # A claim that says the old value ended ("dropped Python") is the change itself, never the stale value.
        stale_groups = expand_groups(row["stale"], clock)
        stale = [c for c in held(stale_groups) if is_current(c) and about(row, c)
                 and not ENDED.search(norm(c.get("predicate") or ""))
                 and matches(ENDS_WHAT.sub(" ", norm(claim_text(c))), stale_groups)]
        verdict = ("correct" if (cur or "current" not in row) and not stale else "both_current" if cur
                   else "stale_only" if stale else "missing")
        updates.append({"id": row["id"], "why": row["why"], "verdict": verdict,
                        "current": [claim_text(c) for c in cur[:3]], "stale_current": [claim_text(c) for c in stale[:3]]})

    # Two real attributes of one thing (a postcard's price and a print's) said apart must both stay current.
    apart = []
    for row in gold.get("apart_values", []):
        cur_a = [c for c in held(expand_groups(row["a"], clock)) if is_current(c)]
        cur_b = [c for c in held(expand_groups(row["b"], clock)) if is_current(c)]
        apart.append({"id": row["id"], "why": row["why"],
                      "ok": any(x["id"] != y["id"] for x in cur_a for y in cur_b),
                      "a": [claim_text(c) for c in cur_a[:3]], "b": [claim_text(c) for c in cur_b[:3]]})

    forbid = []
    for row in gold["forbid"]:
        bad = [c for c in held(expand_groups(row["says"], clock))
               if is_current(c) and (is_person(c) or not row.get("person_only"))
               and (not row.get("on_owner") or c.get("subject") == owner_id)
               and not NEGATION.search(norm(c.get("text") or ""))]
        forbid.append({"id": row["id"], "why": row["why"], "ok": not bad, "violations": [claim_text(c) for c in bad[:3]]})

    # A role one person holds to the owner ("my brother-in-law Marc") must read true as written: never the owner as the
    # holder ("<owner> brother-in-law of Marc"), never the holder as having it ("Marc has brother-in-law <owner>").
    roles = []
    for row in gold.get("roles", []):
        role, holder = [norm(t) for t in row["role"]], [norm(t) for t in row["holder"]]
        bad = []
        for c in claims:
            if not is_current(c):
                continue
            label = norm(str(c.get("predicate") or "").replace("-", " "))
            if not any(t in label for t in role):
                continue
            has = bool(HAS_ROLE.match(label))
            subject, obj = norm(str(c.get("subject") or "")), norm(str(c.get("object") or ""))
            if ((c.get("subject") == owner_id and any(t in obj for t in holder) and not has)
                    or (c.get("object") == owner_id and any(t in subject for t in holder) and has)):
                bad.append(c)
        roles.append({"id": row["id"], "why": row["why"], "ok": not bad, "violations": [claim_text(c) for c in bad[:3]]})

    people = []
    for row in gold["people"]["same"]:
        named = [p["id"] for p in pages if matches(_page_names(p), [row["names"]])]
        people.append({"id": row["id"], "why": row["why"], "ok": len(named) == 1, "pages": named})
    for row in gold["people"]["apart"]:
        joined = [p["id"] for p in pages if matches(_page_names(p), [[row["a"]], [row["b"]]])]
        people.append({"id": row["id"], "why": row["why"], "ok": not joined, "pages": joined})
    for row in gold["people"].get("apart_facts", []):
        # Two people one name can mean: no page may hold what is said about each (a merge keeps both).
        a_groups, b_groups = expand_groups(row["a"], clock), expand_groups(row["b"], clock)
        joined = []
        for page in pages:
            own = [c for c in claims if page["id"] in (c.get("subject"), c.get("object"))]
            if any(matches(claim_text(c), a_groups) for c in own) and any(matches(claim_text(c), b_groups) for c in own):
                joined.append(page["id"])
        people.append({"id": row["id"], "why": row["why"], "ok": not joined, "pages": joined})

    # One real person must stay one: no second page under the same name (`<slug>-2`), and no line held below the promotion
    # bar that carries a `title` (the mark of a second person Sleep decided is someone else, `same_name_people`). A
    # person page is counted by its name, a line by its title, so a held line nobody sees is caught too (the first check
    # of this kind counted pages alone and missed three of four).
    one_person = []
    for row in gold["people"].get("one", []):
        names = [norm(n) for n in row["names"]]
        same_name = [p["id"] for p in pages if p.get("type") == "person" and not p["owner"] and norm(str(p["name"])) in names]
        titled = [ln for ln in held_lines(bank) if norm(ln.get("title") or "") in names]
        one_person.append({"id": row["id"], "why": row["why"], "ok": len(same_name) <= 1 and not titled,
                           "pages": same_name, "held_lines": [ln["name"] for ln in titled]})

    # A full name said once and a nickname with a page are one person (2026-11-24, ruling 74b): the person's own words named
    # both as one, so Sleep joins them itself. Held apart this is the question "Is <Full Name> the same as <Short>?". The
    # alias must be on the page, the full name held nowhere else (no page, no waiting line) and the question gone. The
    # earlier "people" and "one person" checks do not see this: they pass with the page alone.
    name_joined = []
    held_names = {norm(ln["name"]) for ln in held_lines(bank)}
    for row in gold["people"].get("joined", []):
        alias, page_name = norm(row["alias"]), norm(row["page"])
        carriers = [p["id"] for p in pages if norm(str(p["name"])) == page_name and alias in {norm(a) for a in p["aliases"]}]
        own = [p["id"] for p in pages if norm(str(p["name"])) == alias]
        asked = []
        for f in sorted((bank / "inbox").glob("inbox-*.md")):   # the open ones: a settled record lives under settled/
            from api.services import markdown_parser

            fm = markdown_parser.parse(f).frontmatter or {}
            if (str(fm.get("kind") or "") == "merge_suggestion" and str(fm.get("status") or "pending") == "pending"
                    and norm(str(fm.get("entity_name") or "")) == alias):
                asked.append(f.stem)
        name_joined.append({"id": row["id"], "why": row["why"], "ok": bool(carriers) and not own and alias not in held_names and not asked,
                            "pages": carriers, "own_page": own, "held": alias in held_names, "open_questions": len(asked)})

    def has_page(term) -> list[str]:
        return [p["id"] for p in pages if not p["owner"] and matches(_page_names(p), [term if isinstance(term, list) else [term]])]

    expected = [{"term": t, "ok": bool(has_page(t)), "pages": has_page(t)} for t in gold["pages"]["expected"]]
    not_expected = [{"term": t, "ok": not has_page(t), "pages": has_page(t)} for t in gold["pages"]["not_expected"]]

    def days_of(hit: list[dict]) -> list[str]:
        return sorted(({str(c.get(k) or "")[:10] for c in hit for k in ("valid_from", "expected_end", "target")}
                       | {d for c in hit for d in re.findall(r"\d{4}-\d{2}(?:-\d{2})?", str(c.get("object") or ""))})
                      - {""})

    # A relative date is right when a claim carries the day, on a page or held under a waiting name (2026-11-25): a
    # one-off thing the person named once ("my review is in two weeks", the review its own entity) is below the
    # promotion bar by design, so the claim that dates it waits in the pending store. Read on a page alone, the check
    # measured where Stage 1 put the value, not whether the day was resolved. ``held_waiting`` says which.
    waiting_claims = held_claims(bank)
    dated = []
    for row in gold["dated"]:
        groups = expand_groups(row["says"], clock)
        on_page = held(groups)
        waits = [c for c in waiting_claims if matches(claim_text(c), groups)]

        if row.get("month_of"):
            # A month said without a year or a day ("in March"): any date in that month, or the month's name.
            month = int(row["month_of"])
            want = f"month {month:02d}"

            def right(hit):
                return (any(len(d) >= 7 and d[5:7] == f"{month:02d}" for d in days_of(hit))
                        or any(matches(claim_text(c), [[date(2000, month, 1).strftime("%B"), MONTHS_FR[month - 1]]])
                               for c in hit))
        else:
            want = _day(clock, row["date"]).isoformat()

            def right(hit):
                return want in days_of(hit)
        page_ok = right(on_page)
        ok = page_ok or right(waits)
        froms = days_of(on_page + waits)
        dated.append({"id": row["id"], "why": row["why"], "want": want, "ok": ok, "on_page": page_ok,
                      "held_waiting": ok and not page_ok, "valid_from": froms, "page_days": days_of(on_page),
                      "held_days": days_of(waits), "on_run_day": date.today().isoformat() in froms})

    # The conversations keep the person's words as said (the sensitive rail holds a secret back from engines and pages,
    # never rewrites the record), and the derived search indexes are built from them: only what Sleep wrote counts.
    from api.services import bank_registry

    derived = set(bank_registry.DERIVED_ARTIFACTS)
    leaked = []
    for path in bank.rglob("*"):
        if path.is_file() and ".git" not in path.parts and "episodes" not in path.parts and path.name not in derived:
            try:
                if gold.get("secret") and gold["secret"] in path.read_text(encoding="utf-8", errors="ignore"):
                    leaked.append(str(path.relative_to(bank)))
            except OSError:
                pass
    spans = [c for c in claims if any(e["kind"] != "reasoning" and e["start"] is not None and e["end"] is not None
                                      and 0 <= e["start"] < e["end"] for e in c["evidence"])]
    integrity = {
        "secret_leaked_to": leaked,
        "project_pages_made": [p["id"] for p in pages if p.get("type") == "project"],
        "evergreen_pages": [p["id"] for p in pages if p.get("decay_class") == "evergreen" and not p["owner"]],
        "claims_with_span": len(spans), "claims": len(claims),
        "span_rate": round(len(spans) / len(claims), 3) if claims else 0.0,
        "unprocessed_episodes": snap.get("episodes_unprocessed"),
        "failures": [ph for ph in snap["phases"] if ph.get("error") or ph.get("stop")],
    }

    matched = bank.parent / "match.json"
    judged_ids = set(json.loads(matched.read_text(encoding="utf-8")).get("held", [])) if matched.exists() else None
    for pt in points:
        pt["judged"] = pt["claim"] or (judged_ids is not None and pt["id"] in judged_ids)
    total = lambda rows, key="ok": sum(1 for r in rows if r[key])  # noqa: E731
    from benchmarks.consolidation import fading as fading_check   # does the right thing fade? (`fading.py`)

    fading = fading_check.score(bank, snap, gold)
    return {
        "model": snap["model"],
        "summary": {
            "points_claim": total(points, "claim"), "points_held": total(points, "held_waiting"),
            "points_anywhere": total(points, "anywhere"), "points": len(points),
            "points_judged": total(points, "judged") if judged_ids is not None else None,
            "updates_correct": sum(1 for u in updates if u["verdict"] == "correct"),
            "updates_both": sum(1 for u in updates if u["verdict"] == "both_current"),
            "updates_missing": sum(1 for u in updates if u["verdict"] in ("missing", "stale_only")),
            "updates": len(updates),
            "apart_ok": total(apart), "apart": len(apart),
            "forbid_ok": total(forbid), "forbid": len(forbid),
            "roles_ok": total(roles), "roles": len(roles),
            "people_ok": total(people), "people": len(people),
            "one_person_ok": total(one_person), "one_person": len(one_person),
            "name_joined_ok": total(name_joined), "name_joined": len(name_joined),
            "pages_ok": total(expected) + total(not_expected), "pages_checks": len(expected) + len(not_expected),
            "dated_ok": total(dated), "dated_held": total(dated, "held_waiting"), "dated": len(dated),
            "pages_total": len(pages), "claims_total": len(claims), "questions": len(snap["questions"]),
            "span_rate": integrity["span_rate"],
            "integrity_breaks": len(leaked) + len(integrity["project_pages_made"]) + len(integrity["evergreen_pages"]),
            **fading["summary"],
        },
        "points": points, "updates": updates, "apart_values": apart, "forbid": forbid, "roles": roles, "people": people,
        "one_person": one_person, "name_joined": name_joined,
        "pages": {"expected": expected, "not_expected": not_expected}, "dated": dated, "integrity": integrity,
        "fading": fading,
    }


# ---- the precision judge ---------------------------------------------------------------------------------------------

JUDGE_PROMPT = """You check a memory system's notes against the conversation they cite.

The memory is {owner}'s. In each conversation, lines starting "user:" are {owner}'s own words, "assistant:" an AI
assistant's (or, in a meeting, the recorder's summary), and "speaker:<name>:" another person in a meeting. A claim
about {owner} is a claim about the user. Each claim says whose words it rests on: "the person" means the memory treats
it as something {owner} said, did or holds; "the assistant" or "another speaker" means it is recorded as theirs; "an
inference" means the memory cites no line for it.

Label every claim with exactly one of:
- "supported": the conversation says it, credited to the right speaker (a plain rewording counts, and so does a date
  worked out from the conversation's date, like "yesterday").
- "inferred": not said in so many words, but a safe, obvious inference from what was said.
- "misattributed": the content is in the conversation, but only the assistant or another speaker said or suggested it
  while the claim credits {owner} (or {owner} declined it).
- "unsupported": the conversation does not say it, contradicts it, or it gets a name, value or date wrong.

Conversation{plural}:
{conversations}

Claims:
{claims}

Reply with JSON only: {{"labels": [{{"n": <claim number>, "label": "<one label>", "why": "<under 15 words>"}}]}}"""

LABELS = ("supported", "inferred", "misattributed", "unsupported")


def _credited(c: dict) -> str:
    return {"person": "the person", "assistant": "the assistant",
            "speaker": "another speaker"}.get(said_by(c), "an inference, no quote")


def _cited(c: dict) -> list[str]:
    eps = [e["episode"] for e in c["evidence"] if str(e.get("episode") or "").startswith("ep_")]
    eps += [e for e in c["source_episodes"] if str(e).startswith("ep_")]
    return sorted(dict.fromkeys(eps))[:3]


def _json_reply(judge_fn, prompt: str) -> dict:
    """One judge call, read as JSON; asked twice before giving up. ``{}`` leaves what it covers ungraded, never wrong."""
    for _ in range(2):
        try:
            reply = judge_fn(prompt)
            return json.loads(reply[reply.find("{"): reply.rfind("}") + 1])
        except Exception as exc:  # noqa: BLE001
            print(f"judge retry ({type(exc).__name__})", file=sys.stderr)
    return {}


def _label_groups(unit: Path, judge_fn, owner: str, claims: list[dict]) -> tuple[list[dict], int]:
    """Every claim labelled against the conversations it cites, one call per group of cited conversations."""
    from api.services import markdown_parser

    groups: dict[tuple, list[dict]] = {}
    unsourced = 0
    for c in claims:
        eps = tuple(_cited(c))
        if not eps:
            unsourced += 1
            continue
        groups.setdefault(eps, []).append(c)
    labels: list[dict] = []
    for eps, cs in groups.items():
        convs = []
        for ep in eps:
            path = unit / "bank" / "episodes" / f"{ep}.md"
            parsed = markdown_parser.parse(path) if path.exists() else None
            when = str((parsed.frontmatter or {}).get("timestamp") or "")[:10] if parsed else ""
            convs.append(f"--- {ep}, dated {when or 'unknown'} ---\n{parsed.body.strip() if parsed else '(missing)'}")
        lines = [f"{i + 1}. [{_credited(c)}] {c['text'] or claim_text(c)}" for i, c in enumerate(cs)]
        reply = _json_reply(judge_fn, JUDGE_PROMPT.format(owner=owner, plural="s" if len(eps) > 1 else "",
                                                          conversations="\n\n".join(convs), claims="\n".join(lines)))
        verdicts = {int(v["n"]): v for v in reply.get("labels", []) if isinstance(v, dict) and v.get("label") in LABELS}
        for i, c in enumerate(cs):
            v = verdicts.get(i + 1)
            labels.append({"claim": c["id"], "page": c["page"], "credited": _credited(c), "text": c["text"],
                           "episodes": list(eps), "label": v["label"] if v else None, "why": v.get("why") if v else None})
    return labels, unsourced


def _rates(counts: dict, graded: int) -> dict:
    return {"precision": round((counts["supported"] + counts["inferred"]) / graded, 3) if graded else None,
            "hallucination": round(counts["unsupported"] / graded, 3) if graded else None,
            "misattribution": round(counts["misattributed"] / graded, 3) if graded else None}


def judge_leg(unit: Path, judge_fn, owner: str) -> dict:
    """Precision: every claim of one person's bank against its conversations (``judge.json``)."""
    snap = json.loads((unit / "snapshot.json").read_text(encoding="utf-8"))
    labels, unsourced = _label_groups(unit, judge_fn, owner, snap["claims"])
    graded = [x for x in labels if x["label"]]
    counts = {k: sum(1 for x in graded if x["label"] == k) for k in LABELS}
    result = {"counts": counts, "graded": len(graded), "ungraded": len(labels) - len(graded), "unsourced": unsourced,
              **_rates(counts, len(graded)), "labels": labels}
    _write(unit / "judge.json", result)
    return result


MATCH_PROMPT = """A memory system read {owner}'s conversations and wrote the claims below. For each FACT, say whether
one or more claims state it, in any words or language: a claim that says less (a different value, only part of it) does
not hold it. Use only the claims.

Claims:
{claims}

Facts:
{facts}

Reply with JSON only: {{"held": [<fact id>, ...]}}"""


def match_missed(unit: Path, judge_fn, fixture: dict) -> dict:
    """The facts the spelling match missed, asked of the judge against every claim (``match.json``). A fact the
    spelling found is never asked: the judge can only add, so ``points_judged`` >= ``points_claim``."""
    snap = json.loads((unit / "snapshot.json").read_text(encoding="utf-8"))
    sc = score(snap, unit / "bank", fixture)
    missed = {p["id"] for p in sc["points"] if not p["claim"]}
    facts = [r for r in fixture["gold"]["points"] if r["id"] in missed and r.get("fact")]
    held: list[str] = []
    if facts:
        claims = "\n".join(f"- {c['text'] or claim_text(c)}" for c in snap["claims"])
        reply = _json_reply(judge_fn, MATCH_PROMPT.format(owner=fixture["owner"], claims=claims,
                                                          facts="\n".join(f"{r['id']}: {r['fact']}" for r in facts)))
        held = sorted(i for i in (reply.get("held") or []) if i in missed)
    result = {"asked": sorted(missed), "held": held}
    _write(unit / "match.json", result)
    return result


def _plant(claims: list[dict], pages: list[dict], n: int) -> list[dict]:
    """``n`` copies of real claims made wrong in ways that read as plausible, so a judge that waves things through
    shows: a date one day off, a number a little off, or the thing pointed at swapped for another page of the SAME
    type (a person for a person, a place for a place). Same evidence, so the judge reads the same conversation."""
    import random

    rng = random.Random(7)
    by_id = {p["id"]: p for p in pages if not p["owner"]}
    pool = [c for c in sorted(claims, key=lambda c: c["id"]) if _cited(c)]
    rng.shuffle(pool)
    def mutate(c: dict, kind: str) -> dict | None:
        text, obj = c["text"] or "", str(c["object"])
        if kind == "date" and (m := re.search(r"\d{4}-\d{2}-\d{2}", text + " " + obj)):
            wrong = (date.fromisoformat(m.group()) + timedelta(days=1)).isoformat()
            return {**c, "kind": "date", "text": text.replace(m.group(), wrong) if m.group() in text
                    else f"{text} on {wrong}", "object": obj.replace(m.group(), wrong)}
        if kind == "number" and (m := re.search(r"(?<![\d-])\d{1,4}(?![\d-])", text)):
            value = int(m.group())
            wrong = str(value + 1 if value < 20 else round(value * 1.2))
            return {**c, "kind": "number", "text": text[:m.start()] + wrong + text[m.end():],
                    "object": obj.replace(m.group(), wrong, 1)}
        if kind == "swap" and obj in by_id and str(by_id[obj]["name"]) in text:
            same = [p for p in by_id.values() if p["id"] != obj and p.get("type") == by_id[obj].get("type")
                    and str(p["name"]).lower() not in text.lower()]
            if same:
                other = rng.choice(same)
                return {**c, "kind": "swap", "text": text.replace(str(by_id[obj]["name"]), str(other["name"])),
                        "object": other["id"]}
        return None

    # Each kind in turn takes the first claim left that it can be planted in, so the mix never hangs on the order.
    planted: list[dict] = []
    used: set[str] = set()
    kinds = ["date", "number", "swap"]
    while len(planted) < n and kinds:
        for kind in list(kinds):
            if len(planted) >= n:
                break
            hit = next(((c, w) for c in pool if c["id"] not in used and (w := mutate(c, kind))), None)
            if hit is None:
                kinds.remove(kind)
                continue
            used.add(hit[0]["id"])
            planted.append({**hit[1], "id": f"planted_{len(planted)}"})
    return planted


def plant_errors(unit: Path, judge_fn, owner: str, n: int) -> dict:
    """How many planted errors the judge catches (``canary.json``), each judged among the real claims citing the same
    conversations, as precision judges them — so a judge that waves things through shows here."""
    snap = json.loads((unit / "snapshot.json").read_text(encoding="utf-8"))
    planted = _plant(snap["claims"], snap["pages"], n)
    shown = list(planted)
    for c in snap["claims"]:
        if any(tuple(_cited(c)) == tuple(_cited(p)) for p in planted):
            shown.append(c)
    labels, _ = _label_groups(unit, judge_fn, owner, shown)
    ids = {p["id"] for p in planted}
    mine = [x for x in labels if x["claim"] in ids]
    caught = sum(1 for x in mine if x["label"] in ("unsupported", "misattributed"))
    result = {"planted": len(planted), "graded": sum(1 for x in mine if x["label"]), "caught": caught,
              "labels": mine, "kinds": {p["id"]: p["kind"] for p in planted}}
    _write(unit / "canary.json", result)
    return result


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def units(leg: Path) -> list[tuple[str, Path]]:
    """The people a leg ran, each with their own folder; a leg from before people were split is Ines's alone."""
    found = [(p.name, p) for p in sorted(leg.iterdir()) if p.name in PEOPLE and (p / "snapshot.json").exists()]
    return found or ([("ines", leg)] if (leg / "snapshot.json").exists() and (leg / "bank").exists() else [])


def aggregate(leg: Path) -> None:
    """A leg's own score, snapshot and judge files: the sum over its people (rates recomputed from the sums)."""
    people = [(name, unit) for name, unit in units(leg) if unit != leg]
    if not people:
        return
    scores = {name: json.loads((u / "score.json").read_text(encoding="utf-8")) for name, u in people
              if (u / "score.json").exists()}
    snaps = {name: json.loads((u / "snapshot.json").read_text(encoding="utf-8")) for name, u in people}
    if len(scores) != len(people):
        return
    summary: dict = {}
    for sc in scores.values():
        for k, v in sc["summary"].items():
            if k == "span_rate":
                continue
            if v is None or summary.get(k, 0) is None:
                summary[k] = None
            else:
                summary[k] = summary.get(k, 0) + v
    spans = sum(sc["integrity"]["claims_with_span"] for sc in scores.values())
    summary["span_rate"] = round(spans / summary["claims_total"], 3) if summary.get("claims_total") else 0.0
    first = next(iter(snaps.values()))
    _write(leg / "score.json", {"model": first["model"], "summary": summary, "people": {
        n: sc["summary"] for n, sc in scores.items()}})
    usage = {k: sum(sn["usage"].get(k) or 0 for sn in snaps.values())
             for k in ("calls", "failed", "input", "cache_read", "output")}
    usage["cost_usd"] = round(sum(sn["usage"].get("cost_usd") or 0 for sn in snaps.values()), 4)
    _write(leg / "snapshot.json", {"model": first["model"], "engine": first.get("engine"), "clock": first["clock"],
                                   "usage": usage, "phases": [p for sn in snaps.values() for p in sn["phases"]],
                                   "episodes_unprocessed": sum(sn.get("episodes_unprocessed") or 0
                                                               for sn in snaps.values())})
    judged = [json.loads((u / "judge.json").read_text(encoding="utf-8")) for _, u in people
              if (u / "judge.json").exists()]
    if len(judged) == len(people):
        counts = {k: sum(j["counts"][k] for j in judged) for k in LABELS}
        graded = sum(j["graded"] for j in judged)
        out = {"counts": counts, "graded": graded, **_rates(counts, graded)}
        canaries = [json.loads((u / "canary.json").read_text(encoding="utf-8")) for _, u in people
                    if (u / "canary.json").exists()]
        if len(canaries) == len(people):
            out.update(canary_planted=sum(c["graded"] for c in canaries), canary_caught=sum(c["caught"] for c in canaries))
        _write(leg / "judge.json", out)


def make_judge(model: str, home: Path):
    os.environ["CICADA_HOME"] = str(home)
    os.environ.setdefault("CICADA_TELEMETRY", "off")
    from api.config import Settings
    from api.services import providers

    home.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, llm_mode="agent", agent_model=model, CICADA_MEMORY_PATH=str(home / "nobank"))
    llm = providers.resolve_llm_fn(settings, stage="judge", is_async=False)

    def judge_fn(prompt: str) -> str:
        reply = llm(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return reply.choices[0].message.content or ""

    return judge_fn


# ---- report ----------------------------------------------------------------------------------------------------------

def legs(out: Path) -> list[Path]:
    return sorted(p for p in out.iterdir() if (p / "score.json").exists())


def _spread(values: list) -> str:
    """Mean, and the min–max across repeats when they differ. Rates (0–1 floats) print as percentages."""
    if not values:
        return "—"
    rate = all(isinstance(v, float) and 0 <= v <= 1 for v in values)
    fmt = (lambda v: f"{v:.0%}") if rate else (lambda v: f"{v:.3g}")
    mean = sum(values) / len(values)
    return fmt(mean) if min(values) == max(values) else f"{fmt(mean)} ({fmt(min(values))}–{fmt(max(values))})"


def report(out: Path) -> str:
    by_model: dict[str, list[dict]] = {}
    for leg in legs(out):
        s = json.loads((leg / "score.json").read_text(encoding="utf-8"))
        snap = json.loads((leg / "snapshot.json").read_text(encoding="utf-8"))
        j = json.loads((leg / "judge.json").read_text(encoding="utf-8")) if (leg / "judge.json").exists() else {}
        row = dict(s["summary"])
        if j.get("canary_planted"):
            row["canary"] = round(j["canary_caught"] / j["canary_planted"], 3)
        elif (leg / "canary.json").exists():
            c = json.loads((leg / "canary.json").read_text(encoding="utf-8"))
            row["canary"] = round(c["caught"] / c["graded"], 3) if c.get("graded") else None
        row.update({"precision": j.get("precision"), "hallucination": j.get("hallucination"),
                    "misattribution": j.get("misattribution"),
                    "calls": snap["usage"]["calls"], "failed_calls": snap["usage"]["failed"],
                    "unread": snap.get("episodes_unprocessed") or 0,
                    "input_k": round((snap["usage"]["input"]) / 1000, 1), "output_k": round(snap["usage"]["output"] / 1000, 1),
                    "minutes": round(sum(p["seconds"] for p in snap["phases"]) / 60, 1),
                    "cost_usd": snap["usage"].get("cost_usd") or None})
        # One column per folder name less its repeat suffix, so legs of one setting group whatever their label.
        by_model.setdefault(re.sub(r"-r\d+$", "", leg.name), []).append(row)
    first = next(iter(by_model.values()), [{}])[0]
    cols = [("points_claim", f"facts held as claims /{first.get('points', '?')}"),
            ("points_held", "facts held as a claim under a waiting name, not on a page"),
            ("points_judged", "facts held, judge-matched"),
            ("points_anywhere", "facts anywhere on a page"),
            ("updates_correct", f"updates correct /{first.get('updates', '?')}"),
            ("updates_both", "updates: old still current"),
            ("updates_missing", "updates: new value missing"),
            ("apart_ok", f"two real values kept apart /{first.get('apart', '?')}"),
            ("forbid_ok", f"others' words kept off the person /{first.get('forbid', '?')}"),
            ("roles_ok", f"a role reads true as written /{first.get('roles', '?')}"),
            ("people_ok", f"people joined/kept apart right /{first.get('people', '?')}"),
            ("one_person_ok", f"one person kept as one (no second page, no held second line) /{first.get('one_person', '?')}"),
            ("name_joined_ok", f"a full name and its nickname's page joined by Sleep /{first.get('name_joined', '?')}"),
            ("pages_ok", f"page made / not made right /{first.get('pages_checks', '?')}"),
            ("dated_ok", f"relative dates right /{first.get('dated', '?')}"),
            ("dated_held", "relative dates right only on a claim held under a waiting name"),
            ("fade_keeps_ok", f"pages kept coming back to, not fading /{first.get('fade_keeps', '?')}"),
            ("fade_order_ok", f"fading order right (held job above left job, person above a place named once) /{first.get('fade_order', '?')}"),
            ("silence_lasting_fading", f"after 6 weeks' silence: partner, sister, employer under the question line (want 0) /{first.get('silence_lasting', '?')}"),
            ("silence_ended_fading", f"after 6 weeks' silence: ended things under it /{first.get('silence_ended', '?')}"),
            ("silence_all_asked", "after 6 weeks' silence: pages that raise a question or archive"),
            ("precision", "claims supported (judge)"), ("hallucination", "claims unsupported (judge)"),
            ("misattribution", "claims misattributed (judge)"), ("canary", "planted errors the judge caught"),
            ("span_rate", "claims with a located span"), ("integrity_breaks", "integrity breaks"),
            ("claims_total", "claims"), ("pages_total", "pages"), ("questions", "inbox questions"),
            ("calls", "model calls"), ("failed_calls", "failed calls"), ("unread", "conversations left unread"), ("input_k", "input tokens (k)"),
            ("output_k", "output tokens (k)"), ("minutes", "minutes"), ("cost_usd", "cost on a key (USD)")]
    models = list(by_model)
    lines = ["| measure | " + " | ".join(f"{m} (n={len(by_model[m])})" for m in models) + " |",
             "|---|" + "---|" * len(models)]
    for key, label in cols:
        cells = []
        for m in models:
            vals = [r[key] for r in by_model[m] if r.get(key) is not None]
            if key == "cost_usd" and vals:
                mean = sum(vals) / len(vals)
                cells.append(f"${mean:.2f}" + ("" if min(vals) == max(vals) else f" (${min(vals):.2f}–${max(vals):.2f})"))
                continue
            cells.append(_spread(vals))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---- CLI -------------------------------------------------------------------------------------------------------------

def _leg_name(engine: str, model: str, judge: str, k: int) -> str:
    return f"{engine}-{model}" + ("" if judge == model else f"-j{judge}") + f"-r{k}"


def rescore(leg: Path) -> None:
    for name, unit in units(leg):
        snap = json.loads((unit / "snapshot.json").read_text(encoding="utf-8"))
        _write(unit / "score.json", score(snap, unit / "bank", load_fixture(name)))
    aggregate(leg)


def compare(out: Path, a: str, b: str) -> str:
    """Two settings' legs side by side: each measure's means, and whether the gap is wider than both settings' own
    spreads (their ranges do not overlap). Then each fact and update that one setting gets in every run and the other
    in none."""
    def group(name: str) -> list[Path]:
        return [leg for leg in legs(out) if re.sub(r"-r\d+$", "", leg.name) == name]

    ga, gb = group(a), group(b)
    if not ga or not gb:
        return f"no legs named {a if not ga else b} in {out}"
    rows = ["| measure | " + a + f" (n={len(ga)}) | " + b + f" (n={len(gb)}) | clear |", "|---|---|---|---|"]
    sa = [json.loads((x / "score.json").read_text(encoding="utf-8"))["summary"] for x in ga]
    sb = [json.loads((x / "score.json").read_text(encoding="utf-8"))["summary"] for x in gb]
    for key in ("points_claim", "points_held", "points_judged", "updates_correct", "apart_ok", "forbid_ok", "roles_ok", "people_ok", "one_person_ok", "name_joined_ok", "pages_ok", "dated_ok",
                "dated_held", "claims_total", "pages_total"):
        va = [s[key] for s in sa if s.get(key) is not None]
        vb = [s[key] for s in sb if s.get(key) is not None]
        if not va or not vb:
            continue
        clear = "yes" if min(va) > max(vb) or min(vb) > max(va) else ""
        rows.append(f"| {key} | {sum(va) / len(va):.3g} | {sum(vb) / len(vb):.3g} | {clear} |")

    def facts(legs_: list[Path]) -> dict[str, list[bool]]:
        out_: dict[str, list[bool]] = {}
        for leg in legs_:
            for name, unit in units(leg):
                sc = json.loads((unit / "score.json").read_text(encoding="utf-8"))
                for p in sc["points"]:
                    out_.setdefault(f"{name}:{p['id']}", []).append(p["claim"])
                for u in sc["updates"]:
                    out_.setdefault(f"{name}:{u['id']}", []).append(u["verdict"] == "correct")
                for u in sc.get("apart_values", []):
                    out_.setdefault(f"{name}:{u['id']}", []).append(u["ok"])
        return out_

    fa, fb = facts(ga), facts(gb)
    only_a = sorted(k for k in fa if all(fa[k]) and k in fb and not any(fb[k]))
    only_b = sorted(k for k in fb if all(fb[k]) and k in fa and not any(fa[k]))
    rows += ["", f"always in {a}, never in {b}: {', '.join(only_a) or 'none'}",
             f"always in {b}, never in {a}: {', '.join(only_b) or 'none'}"]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="benchmarks.consolidation.run", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run each model REPEATS times, each person of each leg in its own process")
    r.add_argument("--models", default="haiku", help="tiers, comma separated (opus,sonnet,haiku)")
    r.add_argument("--engine", choices=("plan", "key"), default="plan",
                   help="plan: the signed-in Claude plan; key: ANTHROPIC_API_KEY from --key-file (spends money)")
    r.add_argument("--sleep-judge", default="haiku", help="Sleep's Stage 2 judge tier (the product default: haiku)")
    r.add_argument("--people", default=",".join(PEOPLE), help=f"comma separated, of {', '.join(PEOPLE)}")
    r.add_argument("--parallel", type=int, default=1, help="processes at once (a key takes several; keep 1 on a plan)")
    r.add_argument("--key-file", type=Path, default=Path("~/.cicada/secrets.env"))
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--clock", help="the day the fixtures' days count from (default today, UTC)")
    leg = sub.add_parser("leg", help="one model, one person, one fresh bank (what `run` spawns)")
    leg.add_argument("--model", required=True)
    leg.add_argument("--out", type=Path, required=True)
    leg.add_argument("--clock", required=True)
    leg.add_argument("--engine", choices=("plan", "key"), default="plan")
    leg.add_argument("--sleep-judge", default="haiku")
    leg.add_argument("--person", default="ines", choices=list(PEOPLE))
    sc = sub.add_parser("score", help="re-score legs from their banks, no model")
    sc.add_argument("out", type=Path)
    j = sub.add_parser("judge", help="precision, judge-matched facts and planted errors, per person")
    j.add_argument("out", type=Path)
    j.add_argument("--judge-model", default="opus")
    j.add_argument("--fresh", action="store_true", help="re-judge what is already judged")
    j.add_argument("--no-match", action="store_true", help="skip asking the judge about the facts spelling missed")
    j.add_argument("--plant", type=int, default=6, help="planted errors per person (0: none)")
    cmp_ = sub.add_parser("compare", help="two settings (folder names less -rN) side by side")
    cmp_.add_argument("out", type=Path)
    cmp_.add_argument("a")
    cmp_.add_argument("b")
    rep = sub.add_parser("report")
    rep.add_argument("out", type=Path)
    a = p.parse_args(argv)

    if a.cmd == "leg":
        snap = run_leg(a.model, a.out, clock=date.fromisoformat(a.clock), engine=a.engine, judge=a.sleep_judge,
                       person=a.person)
        print(json.dumps({"model": a.model, "person": a.person, "phases": snap["phases"],
                          "claims": len(snap["claims"]), "pages": len(snap["pages"]), "calls": snap["usage"]["calls"]},
                         ensure_ascii=False))
        return 0
    if a.cmd == "run":
        from concurrent.futures import ThreadPoolExecutor

        clock = a.clock or datetime.now(timezone.utc).date().isoformat()
        a.out.mkdir(parents=True, exist_ok=True)
        if a.engine == "key":
            from benchmarks.engine_parity import read_key_file

            key = read_key_file(a.key_file) if a.key_file.expanduser().exists() else os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                print("No ANTHROPIC_API_KEY in --key-file or the environment.", file=sys.stderr)
                return 2
            os.environ["ANTHROPIC_API_KEY"] = key   # the legs inherit it; never printed or written
        people = [x.strip() for x in a.people.split(",") if x.strip()]
        jobs: list[tuple[Path, str, str]] = []
        for k in range(1, a.repeats + 1):
            for model in [m.strip() for m in a.models.split(",") if m.strip()]:
                leg_dir = a.out / _leg_name(a.engine, model, a.sleep_judge, k)
                for person in people:
                    if (leg_dir / person / "score.json").exists():
                        print(f"{leg_dir.name}/{person}: done already, skipped")
                    else:
                        jobs.append((leg_dir, model, person))

        def one(job: tuple[Path, str, str]) -> int:
            leg_dir, model, person = job
            (leg_dir / person).mkdir(parents=True, exist_ok=True)
            print(f"{leg_dir.name}/{person}: running", flush=True)
            with open(leg_dir / f"{person}.log", "w") as log:
                return subprocess.run([sys.executable, "-m", "benchmarks.consolidation.run", "leg", "--model", model,
                                       "--out", str(leg_dir / person), "--clock", clock, "--engine", a.engine,
                                       "--sleep-judge", a.sleep_judge, "--person", person],
                                      cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode

        with ThreadPoolExecutor(max_workers=max(1, a.parallel)) as pool:
            codes = list(pool.map(one, jobs))
        for leg_dir in sorted({j[0] for j in jobs}):
            aggregate(leg_dir)
        print(report(a.out))
        return next((c for c in codes if c), 0)
    if a.cmd == "score":
        for leg_dir in sorted(x for x in a.out.iterdir() if units(x)):
            rescore(leg_dir)
        print(report(a.out))
        return 0
    if a.cmd == "judge":
        judge_fn = make_judge(a.judge_model, a.out / "_judge_home")
        for leg_dir in sorted(x for x in a.out.iterdir() if x.is_dir() and units(x)):
            for name, unit in units(leg_dir):
                owner = load_fixture(name)["owner"]
                if a.fresh or not (unit / "judge.json").exists():
                    res = judge_leg(unit, judge_fn, owner)
                    print(f"{leg_dir.name}/{name}: precision {res['precision']} hallucination {res['hallucination']} "
                          f"misattribution {res['misattribution']} ({res['graded']} graded, {res['ungraded']} ungraded)")
                if not a.no_match and (a.fresh or not (unit / "match.json").exists()):
                    m = match_missed(unit, judge_fn, load_fixture(name))
                    print(f"{leg_dir.name}/{name}: the judge found {len(m['held'])} of {len(m['asked'])} missed facts")
                if a.plant and (a.fresh or not (unit / "canary.json").exists()):
                    c = plant_errors(unit, judge_fn, owner, a.plant)
                    print(f"{leg_dir.name}/{name}: caught {c['caught']} of {c['graded']} planted errors")
            rescore(leg_dir)
        print(report(a.out))
        return 0
    if a.cmd == "compare":
        print(compare(a.out, a.a, a.b))
        return 0
    print(report(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

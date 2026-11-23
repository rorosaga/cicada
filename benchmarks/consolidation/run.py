"""G148: how well a model consolidates, measured on what Sleep wrote rather than on the answers Ask gives.

An invented person's two months (``fixture.json``) go through the production stager and ``sleep_cycle.run(drain=True)``
on a scratch bank in two phases: the first conversations, one drain; then later conversations plus one conversation
edited in place (a revision), and a second drain on the same bank. Then the bank is scored against what the
conversations said, mostly in code with no model:

- **points**: is each fact held as a claim (and, looser, anywhere on a page)? This is extraction recall, as in HaluMem.
- **updates**: when a later conversation changes a value, is the new one current and the old one closed? Each update
  scores *correct*, *both current*, *stale only* or *missing*. One of them is the edited conversation.
- **forbid**: what the assistant said or suggested, and the person declined, must not be held as the person's fact.
- **people**: a nickname and a full name are one page; two people sharing a first name are two.
- **pages**: who and what is mentioned in 2+ conversations gets a page; a one-off mention does not.
- **dated**: "yesterday" in a dated conversation is dated from that conversation, not from the day Sleep ran.
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
MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre")
_DAY_TOKEN = re.compile(r"\{day:([+-]\d+)\}")
_DATE_TOKEN = re.compile(r"^\{date:([+-]?\d+)\}$")


# ---- the fixture, on a clock -----------------------------------------------------------------------------------------

def load_fixture(path: Path = FIXTURE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _day(clock: date, offset: int) -> date:
    return clock + timedelta(days=offset)


def _spoken(d: date, spanish: bool) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]}" if spanish else f"{d.day} {d.strftime('%B')}"


def render_turns(conv: dict, clock: date) -> list[str]:
    """A conversation's turns with ``{day:+N}`` written out from the conversation's own day."""
    spanish = any(ch in "".join(conv["turns"]) for ch in "ñáéíóú¿¡")
    base = _day(clock, conv["day"])
    return [_DAY_TOKEN.sub(lambda m: _spoken(base + timedelta(days=int(m.group(1))), spanish), t) for t in conv["turns"]]


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
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm(alt)))


def matches(text: str, groups: list[list[str]]) -> bool:
    t = norm(text)
    return all(any(_alt_re(a).search(t) for a in group) for group in groups)


def claim_text(c: dict) -> str:
    """What a claim says, with its dates: a moved date can live in ``valid_from`` or ``expected_end`` alone."""
    return " ".join(str(c.get(k) or "") for k in ("subject", "predicate", "object", "text", "valid_from", "expected_end"))


NEGATION = re.compile(r"\b(?:not|never|no longer|declined|decided against|rejected|against|won't|doesn't|didn't|"
                      r"too expensive|instead of|stayed? on|staying|hypothetical|if)\b")


def is_current(c: dict) -> bool:
    return not c.get("valid_to") and not c.get("superseded_by")


def said_by(c: dict) -> str:
    """Whose words a claim rests on, from its evidence spans (``observer`` is ``agent`` on every Sleep claim):
    ``person`` for a span of the person's own turn, ``assistant`` for the assistant's, ``inferred`` for no span."""
    kinds = {e.get("kind") for e in c.get("evidence") or []}
    return "person" if kinds & {"user", "speaker"} else "assistant" if "assistant" in kinds else "inferred"


def is_person(c: dict) -> bool:
    return said_by(c) == "person"


# ---- one leg ---------------------------------------------------------------------------------------------------------

def _drafts(convs: list[dict], clock: date, *, revised_at: str | None = None):
    from api.services import episode_staging

    drafts = []
    for conv in convs:
        day = _day(clock, conv["day"]).isoformat()
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


def run_leg(model: str, out: Path, *, clock: date) -> dict:
    """One model, both phases, on a fresh bank under ``out``. Runs in its own process (see ``main``)."""
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    _refuse_real_paths(out)
    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture()
    with _leg_environment(home, bank):
        return _run_leg(model, out, bank, home, fixture, clock)


def _run_leg(model: str, out: Path, bank: Path, home: Path, fixture: dict, clock: date) -> dict:
    import asyncio
    from unittest.mock import patch

    from api.services import providers, sleep_cycle
    from benchmarks.engine_parity import _usage_events, _by_stage, settings_for
    from benchmarks.system.engine import embed

    init_bank(bank, fixture["owner"])
    settings = settings_for("plan", bank, model=model, judge=None)
    fake_embed = lambda *a, **k: (embed, "fake-hash-v1")  # noqa: E731 — the search model is not what is compared
    phases = []
    for phase in sorted({c["phase"] for c in fixture["conversations"]}):
        convs = [c for c in fixture["conversations"] if c["phase"] == phase]
        staged = stage(bank, convs, clock, f"Bench intake, phase {phase}")
        started = time.perf_counter()
        with patch.object(providers, "resolve_embed_fn", fake_embed), \
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
        "model": model, "clock": clock.isoformat(), "phases": phases, "pages": pages, "claims": claims,
        "questions": questions, "episodes_unprocessed": unprocessed,
        "usage": {"calls": len(events), "failed": sum(1 for e in events if not e.get("ok", True)),
                  "input": sum(e.get("input_tokens") or 0 for e in events),
                  "cache_read": sum(e.get("cache_read_tokens") or 0 for e in events),
                  "output": sum(e.get("output_tokens") or 0 for e in events),
                  "models": sorted({e["model"] for e in events if e.get("model")}),
                  "by_stage": _by_stage(events)},
    }
    (out / "snapshot.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "score.json").write_text(json.dumps(score(snap, bank, fixture), indent=1, ensure_ascii=False),
                                    encoding="utf-8")
    return snap


# ---- scoring, no model -----------------------------------------------------------------------------------------------

def _page_names(p: dict) -> str:
    return " | ".join([p["id"], str(p["name"]), *p["aliases"]])


def score(snap: dict, bank: Path, fixture: dict) -> dict:
    clock = date.fromisoformat(snap["clock"])
    gold = fixture["gold"]
    claims, pages = snap["claims"], snap["pages"]
    prose = [_page_names(p) + " " + (p.get("prose") or "") for p in pages]

    def held(groups):
        hit = [c for c in claims if matches(claim_text(c), groups)]
        return hit

    points = []
    for row in gold["points"]:
        groups = expand_groups(row["says"], clock)
        hit = held(groups)
        points.append({"id": row["id"], "claim": bool(hit), "anywhere": bool(hit) or any(matches(t, groups) for t in prose),
                       "matched": [claim_text(c) for c in hit[:3]]})

    updates = []
    for row in gold["updates"]:
        cur = [c for c in held(expand_groups(row["current"], clock)) if is_current(c)]
        stale = [c for c in held(expand_groups(row["stale"], clock)) if is_current(c)]
        verdict = ("correct" if cur and not stale else "both_current" if cur else "stale_only" if stale else "missing")
        updates.append({"id": row["id"], "why": row["why"], "verdict": verdict,
                        "current": [claim_text(c) for c in cur[:3]], "stale_current": [claim_text(c) for c in stale[:3]]})

    owner_id = next((p["id"] for p in pages if p["owner"]), None)
    forbid = []
    for row in gold["forbid"]:
        bad = [c for c in held(expand_groups(row["says"], clock))
               if is_current(c) and (is_person(c) or not row.get("person_only"))
               and (not row.get("on_owner") or c.get("subject") == owner_id)
               and not NEGATION.search(norm(c.get("text") or ""))]
        forbid.append({"id": row["id"], "why": row["why"], "ok": not bad, "violations": [claim_text(c) for c in bad[:3]]})

    people = []
    for row in gold["people"]["same"]:
        named = [p["id"] for p in pages if matches(_page_names(p), [row["names"]])]
        people.append({"id": row["id"], "why": row["why"], "ok": len(named) == 1, "pages": named})
    for row in gold["people"]["apart"]:
        joined = [p["id"] for p in pages if matches(_page_names(p), [[row["a"]], [row["b"]]])]
        people.append({"id": row["id"], "why": row["why"], "ok": not joined, "pages": joined})

    def has_page(term) -> list[str]:
        return [p["id"] for p in pages if not p["owner"] and matches(_page_names(p), [term if isinstance(term, list) else [term]])]

    expected = [{"term": t, "ok": bool(has_page(t)), "pages": has_page(t)} for t in gold["pages"]["expected"]]
    not_expected = [{"term": t, "ok": not has_page(t), "pages": has_page(t)} for t in gold["pages"]["not_expected"]]

    dated = []
    for row in gold["dated"]:
        want = _day(clock, row["date"]).isoformat()
        hit = held(expand_groups(row["says"], clock))
        froms = sorted({str(c.get(k) or "")[:10] for c in hit for k in ("valid_from", "expected_end", "target")} - {""})
        dated.append({"id": row["id"], "why": row["why"], "want": want, "ok": want in froms, "valid_from": froms,
                      "on_run_day": date.today().isoformat() in froms})

    # The conversations keep the person's words as said (the sensitive rail holds a secret back from engines and pages,
    # never rewrites the record), and the derived search indexes are built from them: only what Sleep wrote counts.
    from api.services import bank_registry

    derived = set(bank_registry.DERIVED_ARTIFACTS)
    leaked = []
    for path in bank.rglob("*"):
        if path.is_file() and ".git" not in path.parts and "episodes" not in path.parts and path.name not in derived:
            try:
                if gold["secret"] in path.read_text(encoding="utf-8", errors="ignore"):
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

    total = lambda rows, key="ok": sum(1 for r in rows if r[key])  # noqa: E731
    return {
        "model": snap["model"],
        "summary": {
            "points_claim": total(points, "claim"), "points_anywhere": total(points, "anywhere"), "points": len(points),
            "updates_correct": sum(1 for u in updates if u["verdict"] == "correct"),
            "updates_both": sum(1 for u in updates if u["verdict"] == "both_current"),
            "updates_missing": sum(1 for u in updates if u["verdict"] in ("missing", "stale_only")),
            "updates": len(updates),
            "forbid_ok": total(forbid), "forbid": len(forbid),
            "people_ok": total(people), "people": len(people),
            "pages_ok": total(expected) + total(not_expected), "pages_checks": len(expected) + len(not_expected),
            "dated_ok": total(dated), "dated": len(dated),
            "pages_total": len(pages), "claims_total": len(claims), "questions": len(snap["questions"]),
            "span_rate": integrity["span_rate"],
            "integrity_breaks": len(leaked) + len(integrity["project_pages_made"]) + len(integrity["evergreen_pages"]),
        },
        "points": points, "updates": updates, "forbid": forbid, "people": people,
        "pages": {"expected": expected, "not_expected": not_expected}, "dated": dated, "integrity": integrity,
    }


# ---- the precision judge ---------------------------------------------------------------------------------------------

JUDGE_PROMPT = """You check a memory system's notes against the conversation they cite.

The conversation is between a person (USER), whose name is {owner}, and an AI assistant (ASSISTANT). The memory is
{owner}'s, so a claim about {owner} is a claim about the USER. The memory system read it and wrote the
claims below. Each claim says whose words it rests on: "the person" means the memory treats it as something the person
said, did or holds; "the assistant" means it is recorded as the assistant's statement; "an inference" means the memory
cites no line for it.

Label every claim with exactly one of:
- "supported": the conversation says it, credited to the right speaker (a plain rewording counts, and so does a date
  worked out from the conversation's date, like "yesterday").
- "inferred": not said in so many words, but a safe, obvious inference from what was said.
- "misattributed": the content is in the conversation, but only the ASSISTANT said or suggested it while the claim
  credits the person (or the person declined it).
- "unsupported": the conversation does not say it, contradicts it, or it gets a name, value or date wrong.

Conversation{plural}:
{conversations}

Claims:
{claims}

Reply with JSON only: {{"labels": [{{"n": <claim number>, "label": "<one label>", "why": "<under 15 words>"}}]}}"""

LABELS = ("supported", "inferred", "misattributed", "unsupported")


def _credited(c: dict) -> str:
    return {"person": "the person", "assistant": "the assistant"}.get(said_by(c), "an inference, no quote")


def _cited(c: dict) -> list[str]:
    eps = [e["episode"] for e in c["evidence"] if str(e.get("episode") or "").startswith("ep_")]
    eps += [e for e in c["source_episodes"] if str(e).startswith("ep_")]
    return sorted(dict.fromkeys(eps))[:3]


def judge_leg(leg: Path, judge_fn, owner: str) -> dict:
    from api.services import markdown_parser

    snap = json.loads((leg / "snapshot.json").read_text(encoding="utf-8"))
    groups: dict[tuple, list[dict]] = {}
    unsourced = 0
    for c in snap["claims"]:
        eps = tuple(_cited(c))
        if not eps:
            unsourced += 1
            continue
        groups.setdefault(eps, []).append(c)
    labels: list[dict] = []
    for eps, cs in groups.items():
        convs = []
        for ep in eps:
            path = leg / "bank" / "episodes" / f"{ep}.md"
            parsed = markdown_parser.parse(path) if path.exists() else None
            when = str((parsed.frontmatter or {}).get("timestamp") or "")[:10] if parsed else ""
            convs.append(f"--- {ep}, dated {when or 'unknown'} ---\n{parsed.body.strip() if parsed else '(missing)'}")
        lines = [f"{i + 1}. [{_credited(c)}] {c['text'] or claim_text(c)}" for i, c in enumerate(cs)]
        prompt = JUDGE_PROMPT.format(owner=owner, plural="s" if len(eps) > 1 else "", conversations="\n\n".join(convs),
                                     claims="\n".join(lines))
        verdicts = {}
        for _ in range(2):
            try:
                reply = judge_fn(prompt)
                body = reply[reply.find("{"): reply.rfind("}") + 1]
                verdicts = {int(v["n"]): v for v in json.loads(body).get("labels", []) if v.get("label") in LABELS}
                break
            except Exception as exc:  # noqa: BLE001 — a judge failure leaves the claims ungraded, never wrong
                verdicts = {}
                print(f"judge retry ({type(exc).__name__})", file=sys.stderr)
        for i, c in enumerate(cs):
            v = verdicts.get(i + 1)
            labels.append({"claim": c["id"], "page": c["page"], "credited": _credited(c), "text": c["text"],
                           "episodes": list(eps), "label": v["label"] if v else None, "why": v.get("why") if v else None})
    graded = [x for x in labels if x["label"]]
    counts = {k: sum(1 for x in graded if x["label"] == k) for k in LABELS}
    result = {"counts": counts, "graded": len(graded), "ungraded": len(labels) - len(graded), "unsourced": unsourced,
              "precision": round((counts["supported"] + counts["inferred"]) / len(graded), 3) if graded else None,
              "hallucination": round(counts["unsupported"] / len(graded), 3) if graded else None,
              "misattribution": round(counts["misattributed"] / len(graded), 3) if graded else None,
              "labels": labels}
    (leg / "judge.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


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
        row.update({"precision": j.get("precision"), "hallucination": j.get("hallucination"),
                    "misattribution": j.get("misattribution"),
                    "calls": snap["usage"]["calls"], "failed_calls": snap["usage"]["failed"],
                    "unread": snap.get("episodes_unprocessed") or 0,
                    "input_k": round((snap["usage"]["input"]) / 1000, 1), "output_k": round(snap["usage"]["output"] / 1000, 1),
                    "minutes": round(sum(p["seconds"] for p in snap["phases"]) / 60, 1)})
        by_model.setdefault(s["model"], []).append(row)
    first = next(iter(by_model.values()), [{}])[0]
    cols = [("points_claim", f"facts held as claims /{first.get('points', '?')}"),
            ("points_anywhere", "facts anywhere on a page"),
            ("updates_correct", f"updates correct /{first.get('updates', '?')}"),
            ("updates_both", "updates: old still current"),
            ("updates_missing", "updates: new value missing"),
            ("forbid_ok", f"others' words kept off the person /{first.get('forbid', '?')}"),
            ("people_ok", f"people joined/kept apart right /{first.get('people', '?')}"),
            ("pages_ok", f"page made / not made right /{first.get('pages_checks', '?')}"),
            ("dated_ok", f"relative dates right /{first.get('dated', '?')}"),
            ("precision", "claims supported (judge)"), ("hallucination", "claims unsupported (judge)"),
            ("misattribution", "claims misattributed (judge)"),
            ("span_rate", "claims with a located span"), ("integrity_breaks", "integrity breaks"),
            ("claims_total", "claims"), ("pages_total", "pages"), ("questions", "inbox questions"),
            ("calls", "model calls"), ("failed_calls", "failed calls"), ("unread", "conversations left unread"), ("input_k", "input tokens (k)"),
            ("output_k", "output tokens (k)"), ("minutes", "minutes")]
    models = list(by_model)
    lines = ["| measure | " + " | ".join(f"{m} (n={len(by_model[m])})" for m in models) + " |",
             "|---|" + "---|" * len(models)]
    for key, label in cols:
        cells = []
        for m in models:
            vals = [r[key] for r in by_model[m] if r.get(key) is not None]
            cells.append(_spread(vals))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---- CLI -------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="benchmarks.consolidation.run", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run each model REPEATS times, each leg in its own process")
    r.add_argument("--models", default="haiku", help="plan models, comma separated (opus,sonnet,haiku)")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--clock", help="the day the fixture's days count from (default today, UTC)")
    leg = sub.add_parser("leg", help="one model on one fresh bank (what `run` spawns)")
    leg.add_argument("--model", required=True)
    leg.add_argument("--out", type=Path, required=True)
    leg.add_argument("--clock", required=True)
    sc = sub.add_parser("score", help="re-score legs from their banks, no model")
    sc.add_argument("out", type=Path)
    j = sub.add_parser("judge", help="grade each leg's claims against the conversations they cite")
    j.add_argument("out", type=Path)
    j.add_argument("--judge-model", default="opus")
    j.add_argument("--fresh", action="store_true", help="re-judge legs that already have judge.json")
    rep = sub.add_parser("report")
    rep.add_argument("out", type=Path)
    a = p.parse_args(argv)

    if a.cmd == "leg":
        snap = run_leg(a.model, a.out, clock=date.fromisoformat(a.clock))
        print(json.dumps({"model": a.model, "phases": snap["phases"], "claims": len(snap["claims"]),
                          "pages": len(snap["pages"]), "calls": snap["usage"]["calls"]}, ensure_ascii=False))
        return 0
    if a.cmd == "run":
        clock = a.clock or datetime.now(timezone.utc).date().isoformat()
        a.out.mkdir(parents=True, exist_ok=True)
        status = 0
        for k in range(1, a.repeats + 1):
            for model in [m.strip() for m in a.models.split(",") if m.strip()]:
                out = a.out / f"{model}-r{k}"
                if (out / "score.json").exists():
                    print(f"{out.name}: done already, skipped")
                    continue
                print(f"{out.name}: running", flush=True)
                proc = subprocess.run([sys.executable, "-m", "benchmarks.consolidation.run", "leg", "--model", model,
                                       "--out", str(out), "--clock", clock], cwd=REPO)
                status = status or proc.returncode
        print(report(a.out))
        return status
    if a.cmd == "score":
        fixture = load_fixture()
        for leg_dir in sorted(x for x in a.out.iterdir() if (x / "snapshot.json").exists()):
            snap = json.loads((leg_dir / "snapshot.json").read_text(encoding="utf-8"))
            (leg_dir / "score.json").write_text(json.dumps(score(snap, leg_dir / "bank", fixture), indent=1,
                                                           ensure_ascii=False), encoding="utf-8")
        print(report(a.out))
        return 0
    if a.cmd == "judge":
        judge_fn = make_judge(a.judge_model, a.out / "_judge_home")
        for leg_dir in legs(a.out):
            if (leg_dir / "judge.json").exists() and not a.fresh:
                continue
            res = judge_leg(leg_dir, judge_fn, load_fixture()["owner"])
            print(f"{leg_dir.name}: precision {res['precision']} hallucination {res['hallucination']} "
                  f"misattribution {res['misattribution']} ({res['graded']} graded, {res['ungraded']} ungraded)")
        print(report(a.out))
        return 0
    print(report(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

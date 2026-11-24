"""The saves battery (G245, ruling 80's plan, Track M): what reading a save costs, and what it writes, on a scratch bank.

The owner's rule (2026-11-24): a save already has a reason, so Sleep reads every save, as the page's and the author's
words, never his. Before that is built, this measures today: how many model calls, input tokens and **output tokens**
each stage spends per save, and whether the traps (a fact stated 50 times, a stranger's "Sam", a post saying "I", a 2021
fact in the present tense, a connector tweet read as his own words, a 200-row list) end well. The fixture is
``saves_fixture.py``; the counts and gates below are the plan's section 6, Track M.

Legs (one scratch bank each, one process each, ``--leg``):

* ``baseline``: dev as it was before ruling 80's switch, which is ``history_index.SAVES_READ = False``: saves are captured by
  the production writers and indexed (bookmarks, list saves, tab groups, open tabs), Sleep reads what it read then (a save with
  a reason or a note, a feed item).
* ``single``: **the real path** (G246, Track 1; it was a ``wake`` shortcut before). Capture writes each save as it does now: a
  save made singly waits for tonight, the 200 list rows are a bulk door (``bulk=True``, the pile), a 40-day-old bookmark
  arrives late (the pile), a video's title and link has nothing to read. Sleep's own first step releases the day's number
  from the pile (``history_index.take_turns``) and reads the whole queue in its order, with the saved-item reading of Tracks
  2a to 2c. ``--wake-bulk`` is retired (the bulk waits its turn; nothing is woken by hand).
* ``grouped``: the Track 3 leg (G246, ``grouped_save_read``): the single leg's real path with the one constant on, so short saves of
  one origin ride one Stage 1 call (up to 25) and a batch of background saves alone holds up to 50. The grouped switch is set
  in this process only; the product's constant stays off until this leg is read against the single one
  (``report OUT/single OUT/grouped`` prints the comparison and says whether the plan's bar is met).

    api/.venv/bin/python -m benchmarks.consolidation.saves_battery run --leg baseline --out OUT/baseline
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery run --leg single   --out OUT/single
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery run --leg grouped  --out OUT/grouped
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery report OUT/baseline OUT/single OUT/grouped
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery selfcheck     # no model, a few seconds

Isolation is the verify-cicada skill's: the process runs on a scratch HOME, ``CICADA_HOME``, bank and ledger with capture,
recall and every fetch off; the engine's ``claude`` is the skill's ``plan-claude`` shim, which gives the real HOME back to
that one child only (for the plan's sign-in), refuses any argv Cicada's engine does not build and any model but the one
named (``haiku``). Nothing reads the person's bank or ``~/.cicada``. The model is the Claude plan at its cheapest model.

Read the numbers as counts and ranges, never one score: two runs of a small model on one input share about a quarter of
their exact claims (``README.md``), so a gate that fails once is a finding to repeat, not a verdict.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SHIM = REPO / ".claude" / "skills" / "verify-cicada" / "bin" / "plan-claude"
#: One day's allowance of saves entering the queue (``history_index.SAVES_PER_DAY``, read when the gate is judged).
DAY_ALLOWANCE = 100
#: At most this many open save-derived claims on one page (plan invariant 12).
PAGE_CLAIM_CAP = 12
#: Ruling 62's retrieval cases, words and the hook's note: all of them (12/12).
MODEL = "haiku"
HELD_PER_100_LIMIT = 250
#: Groups whose save carries words of the person's own (a reason): what they say is theirs, so a claim from one is not a defect
#: and no gate counts it (``his_words`` reports it apart). Every other group, the connector tweet in today's shape included,
#: is somebody else's text.
HIS_WORDS_GROUPS = frozenset({"own-reason"})


# ---- isolation ---------------------------------------------------------------------------------------------------------

def isolate(out: Path, *, stand_in: bool, fresh: bool = True) -> None:
    """Pin every root to ``out`` before the first ``api`` import (the verify skill's scratch HOME, CICADA_HOME, bank)."""
    from benchmarks.engine_parity import _refuse_real_paths

    if fresh:
        _refuse_real_paths(out)
    elif any(real in out.resolve().parents or out.resolve() == real for real in (Path.home() / ".cicada", Path.home() / ".claude")):
        raise SystemExit("--out must be a scratch folder")
    if any(name == "api" or name.startswith("api.") for name in sys.modules):
        raise RuntimeError("isolate() must run before any api module is imported")
    real_claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    home = (out / "home").resolve()
    (home / ".cicada").mkdir(parents=True, exist_ok=True)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        os.environ.pop(name, None)
    os.environ.update({
        "HOME": str(home), "CICADA_HOME": str(home / ".cicada"), "CICADA_MEMORY_PATH": str((out / "bank").resolve()),
        "CICADA_CAPTURE": "off", "CICADA_RECALL": "off", "CICADA_TELEMETRY": "on", "CICADA_API_AUTH": "off",
        "CICADA_ALLOW_CONNECTOR_FETCH": "off", "CICADA_ALLOW_FEED_FETCH": "off", "CICADA_ALLOW_LOGO_FETCH": "off",
        "LITELLM_MODE": "PRODUCTION", "LITELLM_LOCAL_MODEL_COST_MAP": "True", "HF_HUB_OFFLINE": "1", "CICADA_LLM_MODE": "agent",
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "gc.auto", "GIT_CONFIG_VALUE_0": "0",   # no background gc while a bank is copied
        "GIT_AUTHOR_NAME": "Saves Battery", "GIT_AUTHOR_EMAIL": "battery@example.invalid",
        "GIT_COMMITTER_NAME": "Saves Battery", "GIT_COMMITTER_EMAIL": "battery@example.invalid",
        # the engine's `claude` is the skill's shim: the real HOME for that child alone, the pinned argv, one model
        "CICADA_CLAUDE_CLI": str(SHIM), "CICADA_VERIFY_REAL_CLAUDE": real_claude, "CICADA_VERIFY_MODEL": MODEL,
    })
    if stand_in:
        os.environ.pop("CICADA_CLAUDE_CLI", None)


def settings_for(bank: Path):
    """The product's own settings on the plan at the cheapest model; only the steps that spend a web search are off (the
    shim lets one model through, and a web lookup is not what is measured). Page articles and summary synthesis stay at
    their defaults (off)."""
    from benchmarks.engine_parity import settings_for as parity_settings

    base = parity_settings("plan", bank, model=MODEL, judge=MODEL)
    return base.model_copy(update={"web_check_per_run": 0, "web_context_per_run": 0})


# ---- the stand-in engine (selfcheck and --stand-in: no model, no plan) ------------------------------------------------------

def stand_in_runner(calls: list):
    """A ``claude -p`` that answers every extraction with nothing and every judge with 'different'. It exercises the whole
    path (stager, drain, tail, git, ledger) with no spend; its numbers are the stand-in's, never a measurement."""
    from api.services.connections.base import CliResult

    def run(argv, *, stdin=None, timeout=None, cwd=None, env_overrides=None):
        if "auth" in argv[:3]:
            return CliResult(rc=0, stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai"}), stderr="")
        system = next((a[len("--system-prompt="):] for a in argv if a.startswith("--system-prompt=")), "")
        calls.append(argv)
        low = system[:600].lower()
        if "SEVERAL SAVED ITEMS" in system:   # a grouped read: one empty result per save, so the grouped path is what runs
            n = len(re.findall(r"<<<SAVE \d+>>>", stdin or ""))
            text = json.dumps({"results": [{"save": k, "entities": [], "relationships": []} for k in range(1, n + 1)]})
        elif "entities" in low:
            text = json.dumps({"entities": [], "relationships": [], "claims": []})
        elif "same" in low and "decision" in low:
            text = json.dumps({"decision": "different", "reason": "stand-in"})
        else:
            text = "{}"
        result = {"type": "result", "subtype": "success", "is_error": False, "result": text, "stop_reason": "end_turn", "num_turns": 1,
                  "total_cost_usd": 0.0, "usage": {"input_tokens": 2, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50,
                                                   "output_tokens": 20},
                  "modelUsage": {"claude-haiku-5-5": {"outputTokens": 20, "costUSD": 0.0}}}
        return CliResult(rc=0, stdout=json.dumps(result) + "\n", stderr="")

    return run


# ---- reading the bank (no model) ---------------------------------------------------------------------------------------------

def _pages(bank: Path) -> dict[str, dict]:
    """Every page by id: frontmatter and its claims as ``benchmarks.consolidation.run.entity_rows`` reads them."""
    from api.services import markdown_parser
    from benchmarks.consolidation import run as bench

    rows, claims = bench.entity_rows(bank)
    by_id = {r["id"]: {**r, "front": {}, "claims": []} for r in rows}
    for pid in by_id:
        by_id[pid]["front"] = markdown_parser.parse(bank / "entities" / f"{pid}.md").frontmatter or {}
    for c in claims:
        by_id[c["page"]]["claims"].append(c)
    return by_id


def _claim_eps(c: dict) -> set[str]:
    return {str(e) for e in c.get("source_episodes") or []} | {str(e["episode"]) for e in c.get("evidence") or [] if e.get("episode")}


def _open(c: dict) -> bool:
    return not c.get("valid_to") and not c.get("superseded_by")


def _snip(text: str, n: int = 110) -> str:
    return " ".join(str(text).split())[:n]


def measure(bank: Path, manifest: dict, rows_by_key: dict, clock: date) -> dict:
    """Everything the gates read, counted from the finished bank with no model. Counts and short examples only."""
    from api.services import markdown_parser, quiet_pages, saved_reading
    from benchmarks.consolidation import saves_fixture as fx

    saves = set(manifest)
    group_of = {ep: m["group"] for ep, m in manifest.items()}
    key_of = {ep: m["key"] for ep, m in manifest.items()}
    text_of = {ep: (m.get("text") or "") for ep, m in manifest.items()}
    pages = _pages(bank)
    owner_id = next((p for p, v in pages.items() if v["front"].get("owner")), None)
    seeded = set(fx.SEEDED_PAGE_IDS) | {owner_id}

    his = {ep for ep in saves if group_of[ep] in HIS_WORDS_GROUPS}
    others = saves - his

    def from_saves(c): return bool(_claim_eps(c) & others)
    def saves_only(c): return bool(_claim_eps(c) & saves) and not (_claim_eps(c) - saves)
    his_claims = [(pid, c) for pid, v in pages.items() for c in v["claims"] if _claim_eps(c) & his and not _claim_eps(c) & others]

    save_claims = [(pid, c) for pid, v in pages.items() for c in v["claims"] if from_saves(c)]
    out: dict = {"claims_from_saves_with_his_words": {"count": len(his_claims), "examples": [_snip(c.get("text")) for _, c in his_claims[:4]],
                                                       "note": "a reason of his own: not counted by any gate"},
                 "episodes": {"saves_captured": len(saves), "conversations": len(list((bank / "episodes").glob("*.md"))) - len(saves)}}

    # --- what was read
    read_saves = unread_saves = with_words = 0
    read_by_group: Counter = Counter()
    for ep in saves:
        parsed = markdown_parser.parse(bank / "episodes" / f"{ep}.md")
        fm = parsed.frontmatter or {}
        if fm.get("processed") and fm.get("processed_by") != "index":
            read_saves += 1
            read_by_group[group_of[ep]] += 1
            # a save whose body holds a section (or no link at all, a tab group) is sent to a model; a title and a link is not
            if not saved_reading.holds_no_words(parsed.body or "") or not fm.get("url"):
                with_words += 1
        else:
            unread_saves += 1
    out["saves_read_by_a_model"], out["saves_left_indexed"], out["saves_read_by_group"] = read_saves, unread_saves, dict(sorted(read_by_group.items()))
    out["saves_with_words_read"] = with_words   # the ones a model was actually sent: what "per save" divides by when legs are compared

    # --- pages made
    kind_of = quiet_pages.episode_lookup(bank)
    new_pages, media_pages = [], 0
    for pid, v in pages.items():
        if pid in seeded:
            continue
        if v["front"].get("type") == "media":
            media_pages += 1
            continue
        srcs = [str(s) for s in v["front"].get("source_episodes") or []]
        n_save, n_conv = sum(s in saves for s in srcs), sum(s not in saves for s in srcs)
        old = any(rows_by_key.get(key_of.get(s), {}).get("age", 0) >= 30 or rows_by_key.get(key_of.get(s), {}).get("posted") for s in srcs if s in saves)
        new_pages.append({"id": pid, "type": v["front"].get("type"), "status": v.get("status"), "decay_class": v.get("decay_class"),
                          "save_sources": n_save, "conversation_sources": n_conv, "quiet": bool(quiet_pages.page_is_quiet(bank, pid, kind_of=kind_of)),
                          "from_old_saves": bool(old and not n_conv), "confidence": v["front"].get("confidence")})
    out["media_pages"] = media_pages
    out["pages_made"] = {"count": len(new_pages), "from_saves_only": sum(p["conversation_sources"] == 0 for p in new_pages),
                         "from_a_single_save": sum(p["conversation_sources"] == 0 and p["save_sources"] == 1 for p in new_pages),
                         "quiet": sum(p["quiet"] for p in new_pages), "pages": new_pages}
    out["decay_of_pages_born_from_old_saves"] = dict(Counter(f"{p['status']}/{p['decay_class']}" for p in new_pages if p["from_old_saves"]))

    # --- claims
    out["save_claims"] = {"total": len(save_claims), "saves_only": sum(saves_only(c) for _, c in save_claims),
                          "by_observer": dict(Counter(("external" if str(c.get("observer") or "").startswith("external:") else str(c.get("observer") or "none")) for _, c in save_claims)),
                          "saves_only_not_external": sum(saves_only(c) and not str(c.get("observer") or "").startswith("external:") for _, c in save_claims)}
    kinds = Counter(); located = reasoning = 0; claims_unlocated = 0
    for _, c in save_claims:
        spans = c.get("evidence") or []
        if not any(str(e.get("kind")) != "reasoning" and e.get("start") is not None for e in spans):
            claims_unlocated += 1   # a fact none of whose quotes was found in its own save
        for e in spans:
            kinds[str(e.get("kind"))] += 1
            if str(e.get("kind")) == "reasoning" or e.get("start") is None:
                reasoning += 1
            else:
                located += 1
    out["save_claim_evidence"] = {"spans_by_kind": dict(kinds), "located": located, "reasoning_or_unlocated": reasoning,
                                  "reasoning_share": round(reasoning / max(1, located + reasoning), 3),
                                  "claims": len(save_claims), "claims_without_located_evidence": claims_unlocated,
                                  "claims_without_located_share": round(claims_unlocated / max(1, len(save_claims)), 3)}
    per_page = Counter(pid for pid, c in save_claims if _open(c))
    out["open_save_claims_per_page"] = {"max": max(per_page.values(), default=0), "top": per_page.most_common(4), "quillnote": per_page.get("quillnote", 0)}
    owner_claims = [(pid, c) for pid, c in save_claims if pid == owner_id or owner_id in (c.get("subject"), c.get("object"))]
    # "Alex saved X" is true of the act of saving; what a post says about him ("joined the logistics team", "next project")
    # is a stranger's words on his page. A predicate that starts with saved or bookmarked is the act; every other is content.
    content = [(pid, c) for pid, c in owner_claims if not str(c.get("predicate") or "").startswith(("saved", "bookmarked"))]

    def first_group(c): return group_of.get(next(iter(_claim_eps(c) & others)), "?")

    out["claims_on_owner_from_saves"] = {
        "count": len(content), "saving_acts": len(owner_claims) - len(content), "all": len(owner_claims),
        "by_group": dict(Counter(first_group(c) for _, c in content)),
        "examples": [_snip(c.get("text")) for _, c in content[:6]],
        "note": "count = claims that are not the act of saving (what a post says, put on his page); saving_acts are 'saved/bookmarked X'"}

    # --- people
    person_ids = [p for p, v in pages.items() if v["front"].get("type") == "person" and p != owner_id]
    leaks, aliases_added = [], []
    for pid in person_ids:
        v, name = pages[pid], str(pages[pid]["name"] or "")
        if pid in seeded and v["aliases"]:
            aliases_added += [f"{pid}:{a}" for a in v["aliases"]]
        for c in v["claims"] + [x for q, w in pages.items() if q != pid for x in w["claims"] if pid in (x.get("subject"), x.get("object"))]:
            eps = _claim_eps(c) & others
            if not eps or pid not in seeded:
                continue
            exact = any(name.lower() in text_of[e].lower() or any(a.lower() in text_of[e].lower() for a in v["aliases"]) for e in eps)
            leaks.append({"page": pid, "exact_name_in_the_save": exact, "groups": sorted({group_of[e] for e in eps}), "claim": _snip(c.get("text"))})
    out["person_pages_from_saves"] = {"claims": len(leaks), "without_exact_name": sum(not l["exact_name_in_the_save"] for l in leaks),
                                      "sam_without_exact_name": sum(not l["exact_name_in_the_save"] and l["page"] == "sam-example" for l in leaks),
                                      "aliases_on_seeded_people": aliases_added, "examples": leaks[:6]}
    doubts = bank / "_same_name_doubts.yaml"
    joined = 0
    if doubts.exists():
        import yaml
        joined = len((yaml.safe_load(doubts.read_text(encoding="utf-8")) or {}).get("joined") or [])
    out["same_name_joins_by_sleep"] = joined

    # --- held names
    held = []
    path = bank / "pending_entities.jsonl"
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []:
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        eps = {str(line.get("source_episode") or "")} | {str(h.get("episode")) for h in line.get("heard_in") or [] if isinstance(h, dict)}
        eps.discard("")
        held.append({"name": line.get("name"), "from_saves_only": bool(eps) and eps <= saves, "held_claims": len(line.get("held_claims") or [])})
    from_saves = [h for h in held if h["from_saves_only"]]
    out["held_names"] = {"total": len(held), "from_saves_only": len(from_saves),
                         "per_100_saves": round(100 * len(from_saves) / max(1, read_saves), 1),
                         "per_100_saves_read_or_captured": round(100 * len(from_saves) / max(1, len(saves)), 1),
                         "max_held_claims_on_a_name": max((h["held_claims"] for h in from_saves), default=0)}

    # --- questions
    questions, save_only_q = 0, []
    saves_only_pages = {p["id"] for p in new_pages if p["conversation_sources"] == 0}
    for path in sorted((bank / "inbox").rglob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        questions += 1
        if str(fm.get("source_episode") or "") in saves or str(fm.get("entity_id") or "") in saves_only_pages:
            save_only_q.append(str(fm.get("kind") or fm.get("type") or "?"))
    out["questions"] = {"total": questions, "with_only_a_save_behind": len(save_only_q), "kinds": dict(Counter(save_only_q))}

    # --- the 2021 fact, written as current?
    old_ep = next((ep for ep, m in manifest.items() if m["key"] == "old2021"), None)
    stale = []
    for pid, c in save_claims:
        if old_ep in _claim_eps(c) and _open(c) and any(w in str(c.get("text") or "").lower() for w in ("ceo", "casey", "employee", "porto", "run by", "office")):
            dated_2021 = str(c.get("valid_from") or "").startswith("2021")
            stale.append({"page": pid, "valid_from": c.get("valid_from"), "dated_2021": dated_2021, "claim": _snip(c.get("text"))})
    cited = sum(1 for _, c in save_claims if old_ep in _claim_eps(c))
    held_cited = sum(1 for line in (path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []) if old_ep and old_ep in line)
    out["old_post_fact"] = {"claims_citing_the_post": cited, "claims_open": len(stale), "held_lines_citing_it": held_cited,
                            "written_as_current": sum(not s["dated_2021"] for s in stale), "claims": stale[:5]}
    return out


def retrieval(bank: Path, manifest: dict, rows_by_key: dict) -> dict:
    """Ruling 62's retrieval cases: a message about a topic finds the save (the saved lookup by words, and the hook's note)."""
    from api.services import bank_index, hook_recall, saved_lookup, search_index
    from benchmarks.consolidation import saves_fixture as fx

    bank_index.invalidate()
    search_index.refresh(bank)
    words = hook = 0
    missed = []
    feed_key, feed_query = fx.FEED_CASE
    feed_url = (rows_by_key.get(feed_key) or {}).get("url")
    feed_found = bool(feed_url and any(h.url == feed_url for h in saved_lookup.find(bank, feed_query, min_shared=1, episodes=True)))
    for key, query in fx.RETRIEVAL_CASES:
        row = rows_by_key.get(key) or {}
        url = row.get("url")
        query = query or row.get("title")
        is_group = row.get("via") == "tab-group"
        episode = next((ep for ep, m in manifest.items() if m["key"] == key), None)
        hits = saved_lookup.find(bank, query, min_shared=1, episodes=True)
        found_words = any((h.episode == episode) if is_group else (h.url == url) for h in hits)
        note = hook_recall.prompt_context(bank, query)
        found_hook = bool(note.text and (row["title"] in note.text if is_group else url and url in note.text))
        words += found_words
        hook += found_hook
        if not (found_words and found_hook):
            missed.append({"case": key, "words": found_words, "hook": found_hook})
    return {"cases": len(fx.RETRIEVAL_CASES), "words": words, "hook_note": hook, "missed": missed, "feed_item_found_by_words": feed_found,
            "meaning": "not measured: the search model is not loaded (fake hash embedder), so meaning cases are not run"}


def usage(home: Path) -> dict:
    """The scratch ledger by stage: calls, input, cache, output tokens, model seconds (``benchmarks.perf.ledger``)."""
    from benchmarks.engine_parity import _usage_events
    from benchmarks.perf import ledger

    lines = [line for p in sorted((home / ".cicada" / "telemetry").glob("events-*.jsonl")) for line in p.read_text(encoding="utf-8").splitlines()]
    result = ledger.summarize(lines)
    by_stage = {r["stage"]: r for r in result["rows"]}
    events = _usage_events(home / ".cicada")
    return {"total": result["total"], "by_stage": by_stage, "failed_calls": sum(1 for e in events if not e.get("ok", True)),
            "models": sorted({e["model"] for e in events if e.get("model")}), "table": ledger.render(result)}


def gates(m: dict, ret: dict, ret_before: dict, waiting_if_all_woken: int) -> list[dict]:
    """The plan's gates as counts: ``pass`` is True/False; a gate that cannot be judged says why."""
    sam = m["person_pages_from_saves"]
    return [
        {"gate": "zero claims on the owner's page from a save with no words of his", "value": m["claims_on_owner_from_saves"]["count"], "pass": m["claims_on_owner_from_saves"]["count"] == 0,
         "note": f"by group {m['claims_on_owner_from_saves']['by_group']}; plus {m['claims_on_owner_from_saves']['saving_acts']} 'saved X' acts, not counted (the connector tweet in today's shape is expected to fail, the fixed shape to pass)"},
        {"gate": "zero pages from a single save", "value": m["pages_made"]["from_a_single_save"], "pass": m["pages_made"]["from_a_single_save"] == 0},
        {"gate": "zero pages from saves alone (plan invariants 3 and 4: no rung of promotion fires from saves)", "value": m["pages_made"]["from_saves_only"],
         "pass": m["pages_made"]["from_saves_only"] == 0, "note": f"{m['pages_made']['quiet']} of the pages made are quiet; ids {[p['id'] for p in m['pages_made']['pages'] if p['conversation_sources'] == 0]}"},
        {"gate": "every claim from a save with no words of his is external:", "value": m["save_claims"]["saves_only_not_external"], "pass": m["save_claims"]["saves_only_not_external"] == 0,
         "note": f"{m['save_claims']['saves_only']} claims rest on saves alone"},
        {"gate": f"at most {PAGE_CLAIM_CAP} open save-derived claims on the page 50 posts name", "value": m["open_save_claims_per_page"]["quillnote"],
         "pass": m["open_save_claims_per_page"]["quillnote"] <= PAGE_CLAIM_CAP},
        {"gate": "zero save-derived claims or aliases on a person page without an exact name (the Sam case)",
         "value": sam["sam_without_exact_name"], "pass": sam["without_exact_name"] == 0,
         "note": f"{sam['without_exact_name']} claims on any seeded person page without the exact name in the save; aliases now on seeded people (attribution to a save is not possible, a conversation may have added them): {sam['aliases_on_seeded_people']}"},
        {"gate": "questions with only a save behind them at or near zero (at most 2)", "value": m["questions"]["with_only_a_save_behind"], "pass": m["questions"]["with_only_a_save_behind"] <= 2},
        {"gate": "the 2021 fact never written as current", "value": m["old_post_fact"]["written_as_current"], "pass": m["old_post_fact"]["written_as_current"] == 0,
         "note": f"{m['old_post_fact']['claims_citing_the_post']} claims and {m['old_post_fact']['held_lines_citing_it']} held lines cite the 2021 post"
                 + ("; VACUOUS: Sleep wrote nothing from it, so this gate cannot fail here" if not (m['old_post_fact']['claims_citing_the_post'] or m['old_post_fact']['held_lines_citing_it']) else "")},
        {"gate": f"waiting saves after the bulk list at most one day's allowance ({DAY_ALLOWANCE})", "value": waiting_if_all_woken, "pass": waiting_if_all_woken <= DAY_ALLOWANCE,
         "note": "the 200 list rows right after the list was read (ruling 80: a bulk waits its turn in the pile; a day's number is released at Sleep's start, `history_index.take_turns`)"},
        {"gate": "retrieval cases unchanged (words and the hook's note: no fewer found after Sleep than when capture left them, which is dev today)",
         "value": f"at capture {ret_before['words']}/{ret_before['cases']} words, {ret_before['hook_note']}/{ret_before['cases']} hook; after {ret['words']}/{ret['cases']}, {ret['hook_note']}/{ret['cases']}",
         "pass": ret["words"] >= ret_before["words"] and ret["hook_note"] >= ret_before["hook_note"],
         "note": f"missed after: {[x['case'] for x in ret['missed']]}; a feed item has no page and is {'found' if ret['feed_item_found_by_words'] else 'not found'} by words"},
        {"gate": "grouped reads' reasoning share no higher than single reads'", "value": m["save_claim_evidence"]["reasoning_share"], "pass": None,
         "note": "this leg's share of save-claim evidence that is not located; judged against the single leg by `report`"},
        {"gate": f"held names per 100 saves reported (entity cap drops from 8 to 5 above {HELD_PER_100_LIMIT})", "value": m["held_names"]["per_100_saves"],
         "pass": m["held_names"]["per_100_saves"] <= HELD_PER_100_LIMIT, "note": "per 100 saves a model read"},
    ]


# ---- one leg ------------------------------------------------------------------------------------------------------------------

def prepare(out: Path, leg: str, clock: date) -> dict:
    """Seed, capture and (single leg) wake: everything before Sleep, no model. Returns what the leg needs afterwards."""
    from benchmarks.consolidation import saves_fixture as fx

    bank = out / "bank"
    if leg == "baseline":
        from api.services import history_index

        history_index.SAVES_READ = False   # ruling 62's pass whole: what dev did before ruling 80 switched reading on
    built = fx.build_bank(bank, clock)
    rows = fx.all_saves()
    rows_by_key = {r["key"]: r for r in rows}
    manifest = fx.capture_saves(bank, clock, rows)
    fx.write_manifest(out / "manifest.json", manifest)
    at_capture = fx.capture_state(bank, manifest)
    waiting_at_capture = fx.waiting_for_model(bank)
    # Ruling 80: how many of the bulk list's saves wait for Sleep right after the list was read (the gate: at most the day's number).
    waiting_if_all_woken = {"waiting_saves": fx.waiting_group(bank, manifest, "bulk-list")}
    ret_at_capture = retrieval(bank, manifest, rows_by_key)    # dev's own state: the index has read the bookmarks
    woke = None   # nothing is woken by hand any more: the real path is what is measured (ruling 80)
    ret_before = ret_at_capture
    return {"built": built, "saves": len(rows), "at_capture": at_capture, "waiting_at_capture": waiting_at_capture,
            "waiting_if_all_woken": waiting_if_all_woken, "woke": woke, "retrieval_at_capture": ret_at_capture, "retrieval_before_sleep": ret_before,
            "waiting_before_sleep": fx.waiting_for_model(bank), "manifest": manifest, "rows_by_key": rows_by_key}


def run_sleep(out: Path, *, stand_in: bool) -> dict:
    import asyncio
    from unittest.mock import patch

    from api.services import agent_engine, providers, sleep_cycle
    from benchmarks.system.engine import embed

    bank = out / "bank"
    settings = settings_for(bank)
    fake_embed = lambda *a, **k: (embed, "fake-hash-v1")  # noqa: E731 — the search model is not what is measured
    calls: list = []
    patches = [patch.object(providers, "resolve_embed_fn", fake_embed), patch.object(providers, "resolve_embed_fn_for_model", fake_embed),
               patch.object(providers, "cached_embed_fn_for_model", fake_embed)]
    if stand_in:
        patches.append(patch.object(agent_engine, "_default_runner", lambda: stand_in_runner(calls)))
    started = time.perf_counter()
    for p in patches:
        p.start()
    try:
        asyncio.run(sleep_cycle.run(settings, "sleep_saves_battery", user_triggered=True, drain=True))
    finally:
        for p in patches:
            p.stop()
    state = sleep_cycle.get_sleep_state()
    ds = state.drain
    return {"seconds": round(time.perf_counter() - started, 1), "error": state.error,
            "stop": ds.stop.reason if ds and ds.stop else None, "stop_sentence": ds.stop.sentence if ds and ds.stop else None,
            "parked": dict(getattr(ds, "parked", {}) or {}), "unread": dict(getattr(ds, "unread", {}) or {}), "stand_in_calls": len(calls)}


def run_leg(args) -> int:
    out: Path = args.out
    isolate(out, stand_in=args.stand_in)
    out.mkdir(parents=True, exist_ok=True)
    clock = date.today()
    if args.leg == "grouped":
        from api.services import grouped_save_read

        grouped_save_read.ON = True   # this process only: the product's constant stays off until the legs are compared
    prep = prepare(out, args.leg, clock)
    sleep = run_sleep(out, stand_in=args.stand_in)
    return finish(out, args.leg, prep, sleep, clock, stand_in=args.stand_in)


def finish(out: Path, leg: str, prep: dict, sleep: dict, clock: date, *, stand_in: bool) -> int:
    from api.services import markdown_parser

    manifest, rows_by_key = prep["manifest"], prep["rows_by_key"]
    m = measure(out / "bank", manifest, rows_by_key, clock)
    ret_after = retrieval(out / "bank", manifest, rows_by_key)
    spent = usage(out / "home")
    m["released_from_the_pile"] = sum(1 for p in (out / "bank" / "episodes").glob("*.md")
                                      if (markdown_parser.parse(p).frontmatter or {}).get("turn_released_on"))
    result = {
        "leg": leg, "model": MODEL, "stand_in": stand_in, "clock": clock.isoformat(),
        "prepare": {k: v for k, v in prep.items() if k not in ("manifest", "rows_by_key")},
        "sleep": sleep, "measure": m, "retrieval_after_sleep": ret_after, "usage": spent,
        "gates": gates(m, ret_after, prep["retrieval_at_capture"], prep["waiting_if_all_woken"]["waiting_saves"]),
    }
    (out / "battery.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(render_leg(result))
    return 0


def render_leg(r: dict) -> str:
    m, u, p = r["measure"], r["usage"], r["prepare"]
    lines = [f"== leg {r['leg']} (model {r['model']}{', STAND-IN: no model was called, numbers are not a measurement' if r['stand_in'] else ''})",
             f"saves captured {p['saves']} (two of them tab groups): left by capture as {p['at_capture']}",
             f"waiting for a model before Sleep: {p['waiting_before_sleep']}; bulk-list saves waiting after the list was read: {p['waiting_if_all_woken']['waiting_saves']}",
             f"Sleep: {r['sleep']['seconds']} s, error={r['sleep']['error']}, stop={r['sleep']['stop']}, parked={r['sleep']['parked']}",
             f"saves read by a model: {m['saves_read_by_a_model']} (indexed only: {m['saves_left_indexed']}); by group {m['saves_read_by_group']}",
             "", u["table"], ""]
    convs = p["built"]["conversations"]
    reads = max(1, m["saves_read_by_a_model"] + convs)
    t = u["total"]
    lines.append(f"per episode read (saves + {convs} conversations = {reads}): {t['calls'] / reads:.2f} calls, "
                 f"{t['input_tokens'] / reads:.0f} input tokens, {t['output_tokens'] / reads:.0f} output tokens")
    lines += ["", "gates:"]
    for g in r["gates"]:
        verdict = {True: "PASS", False: "FAIL", None: "n/a "}[g["pass"]]
        lines.append(f"  {verdict}  {g['gate']}: {g['value']}" + (f"  [{g['note']}]" if g.get("note") else ""))
    return "\n".join(lines)


def rescore(out: Path) -> int:
    """Measure a finished leg's bank again with no model (a gate or a count was changed): same bank, same ledger."""
    old = json.loads((out / "battery.json").read_text(encoding="utf-8"))
    isolate(out, stand_in=old["stand_in"], fresh=False)
    from benchmarks.consolidation import saves_fixture as fx

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rows_by_key = {r["key"]: r for r in fx.all_saves()}
    prep = {**old["prepare"], "manifest": manifest, "rows_by_key": rows_by_key}
    return finish(out, old["leg"], prep, old["sleep"], date.fromisoformat(old["clock"]), stand_in=old["stand_in"])


# ---- compare legs ---------------------------------------------------------------------------------------------------------------

def report(paths: list[Path]) -> int:
    legs = [json.loads((p / "battery.json").read_text(encoding="utf-8")) for p in paths]
    for r in legs:
        print(render_leg(r))
        print()
    base = next((r for r in legs if r["leg"] == "baseline"), None)
    for r in legs:
        if r["leg"] not in ("single", "grouped") or base is None:
            continue
        extra = r["measure"]["saves_read_by_a_model"] - base["measure"]["saves_read_by_a_model"]
        print(f"== marginal cost of reading a save today ({r['leg']} minus baseline, over {extra} extra saves read)")
        if extra <= 0:
            print("  no extra saves were read: nothing to divide by")
            continue
        stages = sorted(set(r["usage"]["by_stage"]) | set(base["usage"]["by_stage"]))
        for s in stages:
            a, b = r["usage"]["by_stage"].get(s, {}), base["usage"]["by_stage"].get(s, {})
            d = {k: (a.get(k, 0) - b.get(k, 0)) / extra for k in ("calls", "input_tokens", "output_tokens", "cache_read")}
            print(f"  {s:28} calls {d['calls']:6.2f}  input {d['input_tokens']:8.0f}  cache_read {d['cache_read']:8.0f}  output {d['output_tokens']:7.0f}  per save")
        tot = {k: (r["usage"]["total"][k] - base["usage"]["total"][k]) / extra for k in ("calls", "input_tokens", "output_tokens", "cache_read")}
        print(f"  {'TOTAL':28} calls {tot['calls']:6.2f}  input {tot['input_tokens']:8.0f}  cache_read {tot['cache_read']:8.0f}  output {tot['output_tokens']:7.0f}  per save")
    single = next((r for r in legs if r["leg"] == "single"), None)
    grouped = next((r for r in legs if r["leg"] == "grouped"), None)
    if single is not None and grouped is not None:
        print()
        print("\n".join(compare(single, grouped)))
    return 0


#: The plan's bar for turning the grouped read on (``docs/plans/2026-11-24-saves-are-read.md`` 3.5), and what "a real token
#: saving" is taken to mean here: total tokens (input, cache reads and output) per save read at least this much lower.
MAX_CALLS_PER_SAVE = 2.0
REAL_SAVING = 0.25


def compare(single: dict, grouped: dict) -> list[str]:
    """Single against grouped, per save a model read: calls, input, cache and output tokens (Stage 1 and every stage), the share
    of save-claim evidence that could not be located, and every gate count; then whether the plan's bar is met."""
    def per(r: dict, stage: str | None) -> dict:
        row = r["usage"]["total"] if stage is None else r["usage"]["by_stage"].get(stage, {})
        n = max(1, r["measure"].get("saves_with_words_read") or r["measure"]["saves_read_by_a_model"])
        return {k: row.get(k, 0) / n for k in ("calls", "input_tokens", "cache_read", "output_tokens")}

    out = ["== single against grouped (per save a model was sent, whole run: the 8 conversations and every later stage included; one run each, "
           "a small model's single run is a range, not a point)",
           f"  saves read: single {single['measure']['saves_read_by_a_model']}, grouped {grouped['measure']['saves_read_by_a_model']}; "
           f"of them sent to a model (a section of words): single {single['measure'].get('saves_with_words_read')}, grouped {grouped['measure'].get('saves_with_words_read')}"]
    for label, stage in (("Stage 1 (extraction)", "extraction"), ("every stage", None)):
        a, b = per(single, stage), per(grouped, stage)
        out.append(f"  {label}:")
        for k, name in (("calls", "calls"), ("input_tokens", "input tokens"), ("cache_read", "cache reads"), ("output_tokens", "output tokens")):
            ratio = f"{b[k] / a[k]:.2f}x" if a[k] else "n/a"
            out.append(f"    {name:14} single {a[k]:9.2f}   grouped {b[k]:9.2f}   ({ratio})")
    es, eg = single["measure"]["save_claim_evidence"], grouped["measure"]["save_claim_evidence"]
    out.append(f"  evidence not located: single {es['reasoning_or_unlocated']} of {es['located'] + es['reasoning_or_unlocated']} spans "
               f"({es['reasoning_share']:.1%}), grouped {eg['reasoning_or_unlocated']} of {eg['located'] + eg['reasoning_or_unlocated']} ({eg['reasoning_share']:.1%})")
    out.append(f"  facts (claims) with no located evidence: single {es['claims_without_located_evidence']} of {es['claims']} "
               f"({es['claims_without_located_share']:.1%}), grouped {eg['claims_without_located_evidence']} of {eg['claims']} "
               f"({eg['claims_without_located_share']:.1%})")
    cs, cg = single["measure"]["save_claims"]["total"], grouped["measure"]["save_claims"]["total"]
    out.append(f"  facts kept (claims drawn from saves): single {cs}, grouped {cg} ({cg / max(1, cs):.0%}); a leg that kept fewer read less, "
               "which makes its later stages cheaper too: not a bar of the plan, but read it before the per-save cost")
    out.append("  gates (value, pass):")
    for gs, gg in zip(single["gates"], grouped["gates"]):
        out.append(f"    {gs['gate'][:84]:84}  single {gs['value']!s:>14} {gs['pass']!s:5}  grouped {gg['value']!s:>14} {gg['pass']!s:5}")
    ts, tg = per(single, None), per(grouped, None)
    tokens = lambda t: t["input_tokens"] + t["output_tokens"]   # noqa: E731 - the ledger's input already counts cache reads
    saving = 1 - tokens(tg) / max(1.0, tokens(ts))
    checks = [("grouped evidence locates at least as well (spans and facts)",
               eg["reasoning_share"] <= es["reasoning_share"] and eg["claims_without_located_share"] <= es["claims_without_located_share"],
               f"spans {eg['reasoning_share']:.1%} against {es['reasoning_share']:.1%} not located; facts "
               f"{eg['claims_without_located_share']:.1%} against {es['claims_without_located_share']:.1%}"),
              (f"calls per save under {MAX_CALLS_PER_SAVE:g} over this fixture's mixed origins", tg["calls"] < MAX_CALLS_PER_SAVE,
               f"{tg['calls']:.2f} (single {ts['calls']:.2f})"),
              (f"a real token saving (at least {REAL_SAVING:.0%} fewer tokens per save)", saving >= REAL_SAVING, f"{saving:.1%} fewer")]
    gate_regressions = [gg["gate"] for gs, gg in zip(single["gates"], grouped["gates"]) if gs["pass"] is True and gg["pass"] is False]
    checks.append(("no gate that passed on the single read fails on the grouped one", not gate_regressions, ", ".join(gate_regressions) or "none"))
    out.append("  the plan's bar:")
    for what, ok, detail in checks:
        out.append(f"    {'MET    ' if ok else 'NOT MET'}  {what}: {detail}")
    fewer = cg < 0.8 * cs
    out.append(f"  verdict: {'the bar is met on this run' if all(ok for _w, ok, _d in checks) else 'the bar is NOT met on this run'}"
               + ("; BUT the grouped leg kept fewer than 80% as many facts: repeat the legs before turning it on" if fewer else "")
               + "; the product's constant (`grouped_save_read.ON`) stays off either way and the coordinator flips it.")
    return out


# ---- selfcheck ---------------------------------------------------------------------------------------------------------------------

def selfcheck(out: Path, grouped: bool = False) -> int:
    """No model, a few seconds: the fixture builds, capture stores each kind of save as dev stores it, a woken save waits,
    ruling 62's retrieval cases pass on the pile, and the whole path (Sleep through a stand-in engine, the ledger, the
    measures, the gates) runs and reports. Nothing here is a measurement."""
    isolate(out, stand_in=True)
    from benchmarks.consolidation import saves_fixture as fx

    clock = date.today()
    fails: list[str] = []

    def expect(cond: bool, what: str) -> None:
        print(("ok    " if cond else "FAIL  ") + what)
        if not cond:
            fails.append(what)

    rows = fx.all_saves()
    expect(len({r["key"] for r in rows}) == len(rows), f"{len(rows)} saves, keys unique")
    expect(sum(r["group"] == "page-50" for r in rows) == 50, "50 posts about the one existing page")
    expect(sum(r["group"] == "bulk-list" for r in rows) == 200, "a bulk list of 200 rows")
    expect(len(rows) - 200 - 50 + 50 in range(70, 100), f"about 80 non-bulk saves ({len(rows) - 200})")
    if grouped:
        from api.services import grouped_save_read

        grouped_save_read.ON = True
    prep = prepare(out, "grouped" if grouped else "single", clock)
    s, st = prep["at_capture"], prep["waiting_at_capture"]
    expect(len(prep["manifest"]) >= len(rows) - 1, f"every save written ({len(prep['manifest'])} episodes)")
    expect(s.get("model/waiting-for-model", 0) > 60, f"capture leaves the saves made singly waiting for Sleep (ruling 80): {s}")
    waiting_groups = Counter(prep["manifest"][ep]["group"] for ep in prep["manifest"]
                             if (out / "bank" / "episodes" / f"{ep}.md").exists())
    expect(st["waiting_saves"] > 60, f"the saves made singly wait for a model: {st}")
    expect(prep["waiting_if_all_woken"]["waiting_saves"] == 0, f"the bulk list waits its turn, none of it waits tonight: {prep['waiting_if_all_woken']}")
    r = prep["retrieval_at_capture"]
    expect(r["words"] == r["cases"] and r["hook_note"] >= r["cases"] - 2, f"retrieval cases on the pile (the hook never brings up a list row, so 10 of 12 is dev today): {r['words']}/{r['cases']} words, {r['hook_note']}/{r['cases']} hook, missed {r['missed']}")
    sleep = run_sleep(out, stand_in=True)
    expect(sleep["error"] is None and sleep["stand_in_calls"] > 0, f"Sleep ran through the stand-in engine ({sleep['stand_in_calls']} calls, error {sleep['error']})")
    code = finish(out, "grouped" if grouped else "single", prep, sleep, clock, stand_in=True)
    result = json.loads((out / "battery.json").read_text(encoding="utf-8"))
    if grouped:
        stage_one = result["usage"]["by_stage"].get("extraction", {}).get("calls", 0)
        read = result["measure"]["saves_read_by_a_model"]
        expect(0 < stage_one < read, f"short saves of one origin were read together: {stage_one} Stage 1 calls for {read} saves")
    expect(code == 0 and len(result["gates"]) == 12, "the gates are computed")
    expect(result["measure"]["saves_read_by_a_model"] > 60, f"the saves that waited were read: {result['measure']['saves_read_by_a_model']}")
    print("\nselfcheck:", "FAILED " + str(fails) if fails else "passed")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="one leg on a fresh scratch bank")
    r.add_argument("--leg", choices=["baseline", "single", "grouped"], required=True)
    r.add_argument("--out", type=Path, required=True, help="a new folder: the scratch HOME, ledger and bank are made in it")
    r.add_argument("--stand-in", action="store_true", help="a stand-in engine instead of the plan: no spend, not a measurement")
    rs = sub.add_parser("rescore", help="measure a finished leg's bank again with no model")
    rs.add_argument("out", type=Path)
    rp = sub.add_parser("report", help="print finished legs and the marginal cost of a read")
    rp.add_argument("legs", nargs="+", type=Path)
    s = sub.add_parser("selfcheck", help="the fixture and the whole path through a stand-in engine, no model")
    s.add_argument("--out", type=Path, default=None)
    s.add_argument("--grouped", action="store_true", help="with the grouped read on: the stand-in answers a group, so that path runs")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run_leg(a)
    if a.cmd == "report":
        return report(a.legs)
    if a.cmd == "rescore":
        return rescore(a.out)
    import tempfile
    out = a.out or Path(tempfile.mkdtemp(prefix="saves-battery-selfcheck-"))
    return selfcheck(out, grouped=a.grouped)


if __name__ == "__main__":
    sys.exit(main())

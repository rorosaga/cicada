"""The connection handshake (G75): Cicada teaches an agent how to use it.

The MCP ``initialize`` result carries an optional ``instructions`` string
("a hint to the model … MAY be added to the system prompt" — MCP schema
2024-11-05 and later). Until G75 Cicada returned none; G48 only captured
the INBOUND ``clientInfo``. This module builds the outbound half, and the
same text is served by the ``cicada_handshake`` tool (harnesses that drop
``instructions``) and ``GET /handshake`` (the app, AGENTS.md pointers, the
G49/G76 SessionStart hook — out of scope here beyond ``HOOK_POINTER``).

Shape: what Cicada is (3 lines) → a 2–3 line per-harness prelude (R11) →
the contract → the now-view from ``_state.md`` → capability notes. The
contract's inbox paragraph is FIXED BY G115 (quoted verbatim from the G75
row); the G121 sentence comes from ``state_dictionary.WORLD_FACTS_NOTE`` so
there is exactly one source. Zero LLM, ≤ ``MAX_TOKENS`` by the chars/4
proxy (R10 — no tokenizer, ``tiktoken`` fetches its BPE files over the
network on first use and the suite is offline), cached under
``$CICADA_HOME/handshake/<bank>.<variant>.json`` keyed on the state file's
mtime+size and ``CONTRACT_VERSION``. Reads ``_state.md`` as it is (R4): a
stale file is served with its ``generated_at``; no file at all degrades to
the static contract plus a one-line "no state yet" note — an agent is never
blocked on a projection.

Privacy: everything in the now-view is already in ``_state.md`` (ids, names
on entity pages, one-liners, conversation titles, counts, enums — never
claim text, never a transcript line, never a key or an account). The ledger
row ``record`` writes is ids/enums only (R14).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import state_dictionary
from api.services.auth import cicada_home

# Bump when the contract or capability copy changes: the cache key carries
# it, so an upgraded backend never serves last version's text from disk.
# 2: item 2 made honest against the tools (skip=true exists, normalization
# filtered, Cause/Recommended stated as conditional) — final review.
CONTRACT_VERSION = 2
MAX_TOKENS = 1800
VARIANTS = ("claude-code", "codex", "generic")

# The one line a SessionStart hook or AGENTS.md injects (R15). Portable by
# construction: no owner, no machine path — the token location is stated
# relative to $CICADA_HOME. The hook that emits it is G49/G76.
HOOK_POINTER = (
    "Cicada memory is connected: before anything else call the `cicada_handshake` MCP tool "
    "(or GET http://127.0.0.1:8000/handshake with the bearer token in $CICADA_HOME/api_token) "
    "and follow the contract it returns."
)

_WHAT = (
    "# Cicada — personal memory for this person\n"
    "Cicada is a git-versioned markdown knowledge graph of what this person said, did and decided, "
    "consolidated nightly from captured conversations (Sleep) and readable now through these tools. "
    "Beliefs carry provenance (who observed it, from which conversation, which model wrote it) and fade "
    "when unmentioned — silence is a signal, not an error."
)

# R11: the variant is the prelude and nothing else. Resume is stated as a
# CAPABILITY of the harness (R5), never as "this transcript exists".
_PRELUDE = {
    "claude-code": (
        "## Claude Code\n"
        "- Your session id is stamped on every episode you save; this conversation is resumable later with "
        "`claude --resume <id>`.\n"
        "- The `cicada` skill (~/.claude/skills/cicada) is the long-form policy; this text is the contract."
    ),
    "codex": (
        "## Codex\n"
        "- Set `CICADA_SESSION_ID` (and `CICADA_SESSION_HARNESS=codex`) in the MCP env so your episodes group as "
        "one conversation; Codex sessions are not resumable from Cicada.\n"
        "- AGENTS.md points here; there is no separate policy file."
    ),
    "generic": (
        "## Your harness\n"
        "- Set `CICADA_SESSION_ID` (and `CICADA_SESSION_HARNESS`) in the MCP env so your episodes group as one "
        "conversation; without it Cicada mints a per-process id that never resumes.\n"
        "- The tools are the whole interface; nothing needs a file on disk."
    ),
}

# G115 discipline — item 2 is the G75 row's paragraph, with one honesty
# edit (final review, 2026-09-03): the Cause line and the `(Recommended)`
# marker are G115 Phase 1 card work the inbox files do not carry yet, so the
# sentence says "when the item shows them" instead of promising them; every
# argument it names (`entity_ids`, `skip=true`) is in the tool schema and
# `normalization` items really are filtered by `handle_check_nudges` (R12: a
# primer naming behaviour the tools lack is a bug, not aspiration). Copy,
# not filter: the server-side gate is G115 Phase 2 and does not depend on
# this being read. Item 5 is G121 in one sentence, sourced from
# `state_dictionary` so the state file and the primer can never drift apart.
_CONTRACT = (
    "## Contract\n"
    "1. Recall first: `cicada_recall(query)` at the start of a topic, `cicada_recall_detail(id)` for a page, "
    "`cicada_ask` for a direct factual question. State only what the tools returned.\n"
    "2. After `cicada_recall`, call `cicada_check_nudges(entity_ids=<recall ids>)`; at most one question per "
    "turn, after the user's request is done; quote the Cause line and lead with the Recommended option when the "
    "item shows them; never a blocking question at the end of an unrelated turn; "
    "`cicada_resolve_inbox(id, skip=true)` when unanswered — it writes nothing and the item is not re-asked "
    "that session; resolve only with the person's own answer; say what changed in one line; `normalization` "
    "items are app-only and the ask path never returns them.\n"
    "3. Save as you learn: `cicada_save_episode(content, title)` for a decision, plan or fact worth keeping; "
    "`cicada_save_url` for a link.\n"
    "4. Write facts as claims: `cicada_write_claim(subject, predicate, object, evidence=[{episode, quote}], "
    "sources=[url])` — quote the exact words you relied on, and give `sources` for anything you looked up.\n"
    f"5. {state_dictionary.WORLD_FACTS_NOTE}\n"
    "6. Ask before assuming: a pending clarification on an entity you are about to use means the person has "
    "not settled it — ask in flow, do not guess.\n"
    "7. Never edit `entities/`, `hubs/` or `_index.md` directly; every write goes through a tool so provenance "
    "and dedup hold."
)

_CAPABILITIES = (
    "## Capabilities\n"
    "- Resume: Claude Code sessions resume with `claude --resume <id>` (POST /conversations/{id}/resume "
    "validates it); other harnesses group but do not resume.\n"
    "- Decay: every entity has a `decay_class` (evergreen | durable | active | volatile); a claim's evidence is a "
    "span, readable via GET /episodes/{id}/span?start=&end=&hash=.\n"
    "- Repos: `cicada_repo_context(entity_id|path)` returns live git state on demand; the branches below are as "
    "of `repos_probed_at`.\n"
    "- Map: `cicada_open_hub('projects')` etc. walks `_index.md` → hubs → entities without search."
)


def variant_for(client_name: str | None) -> str:
    """Substring match on the captured ``clientInfo.name`` (R11): a name
    containing ``claude`` → ``claude-code``, ``codex`` → ``codex``, anything
    else (Cursor, a raw client, none at all) → ``generic``."""
    name = (client_name or "").strip().lower()
    if "claude" in name:
        return "claude-code"
    if "codex" in name:
        return "codex"
    return "generic"


def _now_block(state: dict | None, bank: str) -> str:
    if state is None:
        return (
            "## Now\n"
            f"- Bank `{bank}` has no `_state.md` yet — run a Sleep cycle or `GET /state?refresh=true` "
            "to generate the now-view; the contract above still applies."
        )
    eng = state.get("engine") or {}
    slp = state.get("sleep") or {}
    inb = state.get("inbox") or {}
    lines = [
        "## Now",
        f"- Bank `{state.get('bank', bank)}` · engine {eng.get('engine')} ({eng.get('model') or 'unset'}) · "
        f"inbox: {inb.get('pending', 0)} pending · Sleep queue {slp.get('queue_depth', 0)} · "
        f"last Sleep {slp.get('last_at') or 'never'} · as of {state.get('generated_at')}",
    ]
    if state.get("owner_id"):
        lines.append(f"- The person's own entity: `{state['owner_id']}`.")
    projects = state.get("projects") or []
    lines.append("- Current projects:" if projects else "- No active projects recorded yet.")
    for p in projects:
        repos = ", ".join(
            f"{r['path']}@{r.get('branch')}" + (f" dirty {r['dirty']}" if r.get("dirty") else "")
            for r in p.get("repos", []) or [] if r.get("state") == "ok"
        )
        tail = f" — {p['one_liner']}" if p.get("one_liner") else ""
        lines.append(f"  - `{p['id']}` {p['name']}{tail}" + (f" [{repos}]" if repos else ""))
    people = state.get("people") or []
    if people:
        lines.append("- People recently in play: " + ", ".join(f"`{p['id']}`" for p in people))
    convs = state.get("conversations") or []
    if convs:
        lines.append("- Recent conversations (id · harness · title):")
        for c in convs:
            lines.append(f"  - `{c['id']}` · {c.get('harness') or 'unknown'} · {c.get('title', '')}")
    prefs = state.get("preferences") or []
    if prefs:
        lines.append("- Standing preferences: " + "; ".join(p.get("one_liner") or p["name"] for p in prefs))
    return "\n".join(lines)


def _assemble(state: dict | None, variant: str, bank: str) -> str:
    return "\n\n".join([_WHAT, _PRELUDE[variant], _CONTRACT, _now_block(state, bank), _CAPABILITIES])


def build(state: dict | None, *, variant: str, bank: str) -> str:
    """Pure: the primer for a parsed state (or none) and a variant.

    The state block is the only elastic part (the contract is verbatim by
    ruling); when the chars/4 proxy overshoots ``MAX_TOKENS`` rows are
    dropped in the same order the state file itself trims (R10): people,
    then preferences, then conversations, then project one-liners — the
    projects list is what a cursor exists for, so it is given up last.
    """
    variant = variant if variant in VARIANTS else "generic"
    text = _assemble(state, variant, bank)
    if len(text) // 4 > MAX_TOKENS and state is not None:
        slim = dict(state)
        for key in ("people", "preferences", "conversations"):
            slim[key] = []
            text = _assemble(slim, variant, bank)
            if len(text) // 4 <= MAX_TOKENS:
                return text
        slim["projects"] = [{**p, "one_liner": ""} for p in slim.get("projects", []) or []]
        text = _assemble(slim, variant, bank)
    return text


def _cache_dir() -> Path:
    return cicada_home() / "handshake"


def _state_age_hours(state: dict | None) -> int | None:
    if not state or not state.get("generated_at"):
        return None
    try:
        then = datetime.fromisoformat(str(state["generated_at"]))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - then).total_seconds() // 3600))
    except ValueError:
        return None


def load_or_build(
    memory_path: Path, client_name: str | None = None, *, cache_dir: Path | None = None,
) -> tuple[str, dict]:
    """The primer for this bank + client, from cache when the state file is unchanged.

    Never refreshes ``_state.md`` (R4 — connect latency stays one file read,
    and the MCP process never dirties the bank with a projection). A cache
    failure of any kind falls back to a fresh build: the cache is a
    convenience, never a dependency. Returns ``(text, meta)`` where ``meta``
    is ``{variant, state_present, state_age_hours, cached}`` — the fields
    ``record`` puts in the ledger.
    """
    memory_path = Path(memory_path)
    variant = variant_for(client_name)
    path = state_dictionary.state_path(memory_path)
    try:
        st = path.stat()
        key = f"{CONTRACT_VERSION}:{variant}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        key = f"{CONTRACT_VERSION}:{variant}:absent"
    cache_dir = Path(cache_dir) if cache_dir is not None else _cache_dir()
    cache_file = cache_dir / f"{memory_path.name}.{variant}.json"
    state = state_dictionary.read_state(memory_path)
    meta = {
        "variant": variant,
        "state_present": state is not None,
        "state_age_hours": _state_age_hours(state),
        "cached": False,
    }
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("key") == key and isinstance(cached.get("text"), str):
            meta["cached"] = True
            return cached["text"], meta
    except (OSError, ValueError):
        pass
    text = build(state, variant=variant, bank=memory_path.name)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"key": key, "text": text}), encoding="utf-8")
    except OSError as exc:
        logger.debug(f"handshake cache write skipped: {exc}")
    return text, meta


def record(
    delivery: str, meta: dict, *, bank: str, harness: str | None = None, client_name: str | None = None,
) -> None:
    """One ``handshake`` ledger row — ids/enums only (R14). Never raises.

    ``stage="handshake"`` is its own label: every existing ``stage`` value is
    a Sleep/ask stage name and ``consumption_stats.stats()`` groups
    ``by_stage`` over ALL events, so borrowing one would mislabel the row.
    ``connection=None`` + ``billing="free"`` — the kind is in
    ``telemetry.NON_SPEND_KINDS`` so it never surfaces as an "unknown"
    connection (G113 R7's reasoning).
    """
    try:
        from api.services import telemetry

        telemetry.record(telemetry.UsageEvent(
            kind="handshake", stage="handshake", connection=None, engine=None, model=None, bank=bank,
            billing="free", invocations=1,
            refs={
                "delivery": delivery,
                "variant": meta.get("variant"),
                "state_present": bool(meta.get("state_present")),
                "state_age_hours": meta.get("state_age_hours"),
                "harness": harness,
                "client_name": client_name,
            },
        ))
    except Exception as exc:  # the ledger never blocks a connect
        logger.debug(f"handshake telemetry skipped: {exc}")

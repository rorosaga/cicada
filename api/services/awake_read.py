"""A conversation is usable as soon as it lands, before Sleep reads it (G207, ruling 36 D2).

Two steps, both a separate job after capture. Capture itself stays file I/O: a capture route calls
:func:`after_capture` only once its writer has returned, and that call just queues a job.

**Step 0, no model.** The episode's passages are embedded with the on-device search model into the episode table
(``vector_index.index_episode_stems``), so recall's excerpt leg finds it by meaning as well as by words. The job
does nothing while Sleep runs, while a search-model re-embed is running, waiting or due, when the table's model is
not one this machine runs, and in a demo bank.

**Step 1, the quick read.** Once the conversation ends (a ``SessionEnd`` flush, an import, or :data:`QUIET_S` with no
new turn), one pass over the capped conversation runs, using the person's engine with its small model. It is Stage 1's
own extractor (``entity_extractor.extract``), so it produces the same G118 evidence spans and the same deterministic
claim ids. Only claims on pages that already exist are kept. A name with no page is *held* in the record, never
minted and never parked in ``pending_store``: Sleep reads the conversation itself and promotes it there. The result is
a provisional record, ``<bank>/.awake/<episode>.json``. That record is a derived artifact outside git
(``bank_registry.DERIVED_ARTIFACTS``). Recall shows it while the episode is unread, and Sleep settles it when it
retires the episode (:func:`settle`: confirmed / corrected / dropped, counted and logged as numbers only). Nothing
provisional writes a page, a claim fence or a commit.

The engine is resolved like a scheduled run (``user_triggered=False``), so the person's plan is used only under
"Scheduled runs may use my plan" (ruling 4) and Auto never falls to a metered key (ruling 31). The record's write is
admitted (G177/G183: admission, then the file), never held across the model call, and never made while Sleep holds
the pages. The same revision is never read twice (:func:`episode_ids.body_revision`).

``CICADA_AWAKE_READ``: ``off`` (neither step), ``index`` (step 0 only), ``on`` (both). When unset, step 0 runs and
step 1 follows :data:`QUICK_READ_DEFAULT`, which is set from the measurement in ``benchmarks/awake_bench.py``.
There is no Settings switch (owner D2).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

ENV = "CICADA_AWAKE_READ"
#: Step 1 when ``CICADA_AWAKE_READ`` is unset. Set from the benchmark (see the PR and capture-and-sleep.md).
QUICK_READ_DEFAULT = False
#: A harness Stop fires on every turn, so a conversation counts as ended after this long without a new capture.
QUIET_S = 600.0
#: A conversation that said it ended (``SessionEnd``), or arrived whole (an import), is read after this settle.
ENDED_S = 5.0
#: Step 0 waits this long after a capture, so a burst of turns embeds once.
INDEX_SETTLE_S = 3.0
#: An import of more conversations than this gets step 0 only and waits for Sleep. Reading a whole export on the
#: person's plan, unasked, is not a quick read.
IMPORT_READ_MAX = 5
#: A big import is embedded in jobs of this many conversations, so what finished stays when Sleep cuts in.
IMPORT_INDEX_BATCH = 64
#: At most this many quick reads per hour per process. Past it, a conversation waits for Sleep (logged).
READS_PER_HOUR = 20
#: How long a job waits before trying again when Sleep, a re-embed or the admission held it back.
RETRY_S = 120.0
#: A job held back this many times is dropped (a switch that never comes, a night-long drain): Sleep's own index
#: sync and its reading cover the conversation anyway.
MAX_TRIES = 30
STORE_DIR = ".awake"
ENDED_EVENTS = frozenset({"SessionEnd", "session_end", "sessionend"})


def mode(environ=os.environ) -> str:
    """``off`` | ``index`` | ``on``: what runs after a capture."""
    raw = (environ.get(ENV) or "").strip().lower()
    if raw in ("off", "0", "false", "no"):
        return "off"
    if raw in ("index", "step0", "vectors"):
        return "index"
    if raw in ("on", "1", "true", "yes", "read"):
        return "on"
    return "on" if QUICK_READ_DEFAULT else "index"


def _env_seconds(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "")))
    except ValueError:
        return default


# --------------------------------------------------------------------------- the queue


@dataclass(order=True)
class _Job:
    due: float
    bank: str = field(compare=False)
    episode: str = field(compare=False)
    kind: str = field(compare=False)          # "index" | "read"
    settings: object = field(compare=False, default=None)
    tries: int = field(compare=False, default=0)
    #: An import's ids, embedded in one upsert (``episode`` is then the import's key, not an id).
    many: tuple[str, ...] = field(compare=False, default=())


class _Queue:
    """One daemon worker per process. A job is keyed by (bank, episode, kind), so a later capture of the same
    conversation pushes its due time back (the debounce) instead of adding a second job."""

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.jobs: dict[tuple[str, str, str], _Job] = {}
        self.thread: threading.Thread | None = None
        self.reads: list[float] = []

    def put(self, job: _Job) -> None:
        with self.cond:
            self.jobs[(job.bank, job.episode, job.kind)] = job
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, name="cicada-awake-read", daemon=True)
                self.thread.start()
            self.cond.notify_all()

    def take_due(self, now: float) -> list[_Job]:
        with self.cond:
            due = sorted(j for j in self.jobs.values() if j.due <= now)
            for j in due:
                self.jobs.pop((j.bank, j.episode, j.kind), None)
            return due

    def _loop(self) -> None:
        while True:
            with self.cond:
                while not self.jobs:
                    self.cond.wait()
                wait = min(j.due for j in self.jobs.values()) - time.monotonic()
                if wait > 0:
                    self.cond.wait(timeout=min(wait, 60.0))
                    continue
            for job in self.take_due(time.monotonic()):
                try:
                    run_job(job)
                except Exception as exc:  # noqa: BLE001 - a background job never takes the worker down
                    logger.warning(f"awake_read: {job.kind} job failed: {type(exc).__name__}")

    def spend(self, now: float) -> bool:
        """Count one quick read against :data:`READS_PER_HOUR`; False when the hour's budget is used."""
        with self.cond:
            self.reads = [t for t in self.reads if now - t < 3600.0]
            if len(self.reads) >= READS_PER_HOUR:
                return False
            self.reads.append(now)
            return True


QUEUE = _Queue()


def after_capture(memory_path: Path, episode_id: str | None, *, status: str | None, settings=None,
                  hook_event: str | None = None, ended: bool = False) -> None:
    """A capture route's one call after its writer returned: queue step 0 and, when on, step 1. Never raises, never
    reads, embeds or calls a model in the caller's thread. ``memory_path`` is the bank the capture was filed in.
    Only a ``created`` or ``updated`` write queues anything."""
    try:
        if not episode_id or status not in ("created", "updated"):
            return
        which = mode()
        if which == "off":
            return
        bank = str(Path(memory_path))
        now = time.monotonic()
        QUEUE.put(_Job(now + _env_seconds("CICADA_AWAKE_INDEX_SETTLE_S", INDEX_SETTLE_S), bank, episode_id,
                       "index", settings))
        if which == "on":
            ended = ended or (hook_event or "") in ENDED_EVENTS
            wait = (_env_seconds("CICADA_AWAKE_ENDED_S", ENDED_S) if ended
                    else _env_seconds("CICADA_AWAKE_QUIET_S", QUIET_S))
            QUEUE.put(_Job(now + wait, bank, episode_id, "read", settings))
    except Exception as exc:  # noqa: BLE001 - capture's answer never depends on this
        logger.debug(f"awake_read: not queued: {type(exc).__name__}")


def after_import(memory_path: Path, episode_ids: list[str], *, settings=None) -> None:
    """An import's touched conversations: step 0 for each, and step 1 when the import is small enough
    (:data:`IMPORT_READ_MAX`)."""
    ids = [e for e in dict.fromkeys(episode_ids or []) if e]
    small = len(ids) <= IMPORT_READ_MAX
    if not small:
        logger.info(f"awake_read: an import of {len(ids)} conversations — indexed now, read by Sleep")
    if small:
        for ep in ids:
            after_capture(memory_path, ep, status="created", settings=settings, ended=True)
    elif mode() != "off":
        for at in range(0, len(ids), IMPORT_INDEX_BATCH):
            part = ids[at: at + IMPORT_INDEX_BATCH]
            QUEUE.put(_Job(time.monotonic() + INDEX_SETTLE_S, str(Path(memory_path)), f"import:{part[0]}:{len(part)}",
                           "index", settings, many=tuple(part)))


def run_job(job: _Job) -> str:
    """Run one job now; a job held back by Sleep, a re-embed or the admission is queued again after
    :data:`RETRY_S`. Returns the outcome (an enum word, for tests and the log)."""
    bank = Path(job.bank)
    if job.kind == "index":
        outcome = index_now(bank, list(job.many) or job.episode, settings=job.settings)
    else:
        outcome = asyncio.run(quick_read(bank, job.episode, settings=job.settings))
    if outcome in ("sleep_running", "reindexing", "admission") and job.tries + 1 < MAX_TRIES:
        QUEUE.put(_Job(time.monotonic() + RETRY_S, job.bank, job.episode, job.kind, job.settings, job.tries + 1,
                       job.many))
    logger.debug(f"awake_read: {job.kind} → {outcome}")
    return outcome


# --------------------------------------------------------------------------- shared guards


def _sleep_running() -> bool:
    """Never start while a Sleep run is on, writing or not (a drain's reads would race this one). The write window
    is read through ``write_admission`` only (G183); the record's own write asks again inside its admission."""
    from api.services import sleep_cycle, write_admission

    return sleep_cycle.get_sleep_state().status == "running" or write_admission.probe()


def _settings(settings):
    if settings is not None:
        return settings
    from api.config import get_settings

    return get_settings()


# --------------------------------------------------------------------------- step 0


def index_now(memory_path: Path, episode_id: str | list[str], *, settings=None) -> str:
    """Step 0 for one episode (or an import's list, in one upsert). ``indexed`` | ``unchanged`` | ``skipped`` |
    ``demo_bank`` | ``sleep_running`` | ``reindexing`` | ``hosted_model`` | ``no_episode`` | ``failed``."""
    from api.services import demo_guard, embedding_models, vector_index

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return "demo_bank"
    ids = [episode_id] if isinstance(episode_id, str) else list(episode_id)
    ids = [e for e in ids if (memory_path / "episodes" / f"{e}.md").is_file()]
    if not ids:
        return "no_episode"
    if _sleep_running():
        return "sleep_running"
    if embedding_models.REINDEX.snapshot(memory_path)["state"] in ("running", "waiting"):
        return "reindexing"
    settings = _settings(settings)
    try:
        if embedding_models.pending_switch(memory_path, settings) is not None:
            return "reindexing"
        # Review of #423: the embed gives way to Sleep within one chunk (STOPPABLE_CHUNK texts), as the background
        # re-embed does, so Sleep's own index sync never waits on this job's write lock for a whole import.
        indexer = vector_index.SqliteVecIndexer(memory_path, defer_model_switch=True, should_stop=_sleep_running)
        recorded = (indexer.index_info("episodes") or {}).get("model")
        model = recorded or embedding_models.build_model(memory_path, settings)
        if not vector_index.runs_on_device(model):
            return "hosted_model"
        stats = indexer.index_episode_stems(ids)
    except vector_index.IndexSyncStopped:
        return "sleep_running"   # nothing of this batch was written; retried after Sleep
    except Exception as exc:  # noqa: BLE001 - a derived index: never an error, Sleep's sync catches up
        logger.info(f"awake_read: step 0 not done ({type(exc).__name__}); Sleep's index sync will do it")
        return "failed"
    if stats.get("skipped"):
        return "skipped"
    return "indexed" if stats.get("embedded") or stats.get("removed") else "unchanged"


# --------------------------------------------------------------------------- step 1


def store_dir(memory_path: Path) -> Path:
    return Path(memory_path) / STORE_DIR


def record_path(memory_path: Path, episode_id: str) -> Path:
    return store_dir(memory_path) / f"{episode_id}.json"


def load_record(memory_path: Path, episode_id: str) -> dict | None:
    try:
        data = json.loads(record_path(memory_path, episode_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_record(memory_path: Path, episode_id: str, record: dict) -> None:
    path = record_path(memory_path, episode_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _small_settings(resolved):
    """The resolved engine with its small model: the disambiguation model each rung already names."""
    updates = {}
    for big, small in (("agent_model", "agent_disambiguation_model"), ("codex_model", "codex_disambiguation_model"),
                       ("litellm_model", "litellm_disambiguation_model")):
        value = str(getattr(resolved, small, "") or "").strip()
        if value and hasattr(resolved, big):
            updates[big] = value
    try:
        return resolved.model_copy(update=updates) if updates else resolved
    except Exception:  # noqa: BLE001 - a stand-in settings object keeps its own models
        return resolved


def _page_table(memory_path: Path) -> tuple[dict[str, str], set[str], list[dict]]:
    """``(name_to_id, page ids, [{id, frontmatter}])`` from the pages' headers: names and aliases, lower-cased."""
    from api.services import bank_index

    table: dict[str, str] = {}
    ids: set[str] = set()
    pages: list[dict] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        ids.add(f.stem)
        pages.append({"id": f.stem, "frontmatter": fm})
        names = [fm.get("name")] + list(fm.get("aliases") or [] if isinstance(fm.get("aliases"), list) else [])
        for name in names:
            key = str(name or "").strip().lower()
            if key:
                table.setdefault(key, f.stem)
    return table, ids, pages


async def quick_read(memory_path: Path, episode_id: str, *, settings=None, extract=None) -> str:
    """Step 1 for one episode. ``read`` | ``unchanged`` | ``demo_bank`` | ``processed`` | ``sleep_running`` |
    ``no_engine`` | ``budget`` | ``admission`` | ``failed``. ``extract`` replaces Stage 1's extractor (tests)."""
    from api.services import claim_pipeline, demo_guard, engine_select, entity_extractor, owner_identity, sleep_cycle

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return "demo_bank"
    if _sleep_running():
        return "sleep_running"
    episodes = sleep_cycle._get_unprocessed_episodes(memory_path, only_ids={episode_id})
    if not episodes:
        return "processed"   # read already, index-only, or gone
    episode = episodes[0]
    prior = load_record(memory_path, episode_id)
    if prior and prior.get("revision") == episode["revision"]:
        return "unchanged"
    settings = _settings(settings)
    resolved, _why = await engine_select.resolve_settings(settings, user_triggered=False)
    if engine_select.no_engine(resolved):
        return "no_engine"
    if not QUEUE.spend(time.monotonic()):
        logger.info("awake_read: this hour's quick reads are used; the conversation waits for Sleep")
        return "budget"
    small = _small_settings(resolved)
    started = time.monotonic()
    try:
        extracted = await (extract or entity_extractor.extract)([episode], small, stage="quick_read")
    except Exception as exc:  # noqa: BLE001 - Sleep reads it anyway
        logger.info(f"awake_read: quick read failed ({type(exc).__name__}); Sleep will read it")
        return "failed"
    if not extracted:
        return "failed"
    table, page_ids, pages = _page_table(memory_path)
    refs = owner_identity.self_references(pages, extracted, None, settings)
    resolve = claim_pipeline.subject_resolver(table, refs.owner_id, refs)
    claims = entity_extractor.entities_to_claims(extracted, memory_path, resolve_id=resolve)
    kept, held_counts = [], {}
    for claim in claims:
        if claim.subject in page_ids:
            kept.append(claim)
        else:
            held_counts[claim.subject] = held_counts.get(claim.subject, 0) + 1
    held, held_ids = [], set()
    for result in extracted:
        for ent in result.get("entities", []) or []:
            name = str((ent or {}).get("name") or "").strip()
            if not name:
                continue
            pid = resolve(name)
            if pid in page_ids or pid in held_ids:
                continue
            held_ids.add(pid)
            held.append({"name": name, "type": str(ent.get("type") or ""), "id": pid,
                         "claims": held_counts.get(pid, 0)})
    record = {
        "episode": episode_id,
        "revision": episode["revision"],
        "read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": engine_select.engine_label(small),
        "model": engine_select.author_model(small),
        "seconds": round(time.monotonic() - started, 1),
        "claims": [{**c.to_dict(), "predicate_raw": getattr(c, "predicate_raw", "")} for c in kept],
        "held": held,
    }
    written = await asyncio.to_thread(_admit_and_write, memory_path, episode_id, record)
    if written != "read":
        return written
    logger.info(f"awake_read: quick read of one conversation: {len(kept)} provisional claim(s), "
                f"{len(held)} name(s) held for Sleep")
    return "read"


def _admit_and_write(memory_path: Path, episode_id: str, record: dict) -> str:
    """The record's write under the bank's admission (G183: admission, then the file), off the event loop. Sleep
    holding the pages, or having read the episode while the model ran, means no record."""
    from api.services import sleep_cycle, write_admission

    try:
        with write_admission.admitted(memory_path):
            if not sleep_cycle._get_unprocessed_episodes(memory_path, only_ids={episode_id}, with_body=False):
                return "processed"   # Sleep read it while the model ran: its reading is the one that counts
            _write_record(memory_path, episode_id, record)
    except write_admission.SleepHolding:
        return "admission"
    return "read"


# --------------------------------------------------------------------------- read path (recall)


def _unprocessed(memory_path: Path, episode_id: str) -> bool:
    from api.services import bank_index

    f = bank_index.file(memory_path, "episodes", f"{episode_id}.md")
    return f is not None and not (f.frontmatter or {}).get("processed")


def records(memory_path: Path) -> list[dict]:
    """Every provisional record whose episode Sleep has not read yet, newest read first. The caller passes the
    active bank."""
    folder = store_dir(memory_path)
    if not folder.is_dir():
        return []
    out = []
    for path in folder.glob("*.json"):
        rec = load_record(memory_path, path.stem)
        if rec and _unprocessed(memory_path, path.stem):
            out.append(rec)
    out.sort(key=lambda r: str(r.get("read_at") or ""), reverse=True)
    return out


_WORD = re.compile(r"[\w'-]{3,}", re.UNICODE)


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")}


def provisional_lines(memory_path: Path, query: str, subject_ids: list[str], *, names: dict[str, str] | None = None,
                      max_claims: int = 12, max_held: int = 5) -> list[str]:
    """Recall's provisional block: claims on the top hits' pages or sharing a word with the query, those sharing the
    most of the query's words first, then by their page's rank among the hits; then held names that match a query
    word. Empty when nothing qualifies."""
    recs = records(memory_path)
    if not recs:
        return []
    names = names or {}
    want = list(dict.fromkeys(s for s in subject_ids if s))
    rank = {sid: i for i, sid in enumerate(want)}
    q = _words(query)
    scored: list[tuple[tuple[int, int, int], dict, dict]] = []
    seen: set[str] = set()
    n = 0
    for rec in recs:
        for c in rec.get("claims") or []:
            cid = f"{rec.get('episode')}:{c.get('id')}"
            if cid in seen:
                continue
            seen.add(cid)
            overlap = len(q & _words(" ".join(str(c.get(k) or "") for k in ("text", "subject", "object",
                                                                             "predicate"))))
            on_hit = c.get("subject") in rank
            if not (on_hit or overlap):
                continue
            # The query's own words first, then the page's rank among recall's hits, then the newest read.
            scored.append(((-overlap, rank.get(c.get("subject"), len(want)), n), rec, c))
            n += 1
    scored.sort(key=lambda t: t[0])
    chosen = [(rec, c) for _k, rec, c in scored]
    lines = []
    for rec, c in chosen[:max_claims]:
        subject = names.get(c.get("subject")) or c.get("subject")
        lines.append(f"- [[{subject}]] {c.get('text') or ''} — `{c.get('id')}`, from {rec.get('episode')}")
    held = []
    for rec in recs:
        for h in rec.get("held") or []:
            if q & _words(h.get("name", "")) and h.get("name") not in {x[0] for x in held}:
                held.append((h.get("name"), rec.get("episode")))
    if held:
        lines.append("- Named, no page yet (Sleep decides): " + ", ".join(
            f"{n} ({ep})" for n, ep in held[:max_held]))
    return lines


# --------------------------------------------------------------------------- Sleep settles


def settle(memory_path: Path, episode_ids: list[str]) -> dict[str, int]:
    """After Sleep retired ``episode_ids``: classify each provisional claim of theirs against the pages now, then
    delete the record. Confirmed = the same claim id is on its page; corrected = the page holds a claim from that
    conversation with the same subject and predicate; dropped = anything else. Returns the counts; logs numbers only.
    Never raises."""
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    counts = {"confirmed": 0, "corrected": 0, "dropped": 0, "records": 0}
    for ep in dict.fromkeys(episode_ids or []):
        rec = load_record(memory_path, ep)
        if rec is None:
            continue
        if _unprocessed(memory_path, ep):
            continue   # a newer revision is queued: its record waits for the run that reads it
        cache: dict[str, list] = {}
        for c in rec.get("claims") or []:
            subject = str(c.get("subject") or "")
            if subject not in cache:
                try:
                    parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{subject}.md")
                    cache[subject] = parse_claims(parsed.body)
                except Exception:  # noqa: BLE001 - a page gone or malformed: nothing confirms it
                    cache[subject] = []
            on_page = cache[subject]
            if any(x.id == c.get("id") for x in on_page):
                counts["confirmed"] += 1
            elif any(x.predicate == c.get("predicate") and ep in (x.source_episodes or []) for x in on_page):
                counts["corrected"] += 1
            else:
                counts["dropped"] += 1
        try:
            record_path(memory_path, ep).unlink()
        except OSError:
            pass
        counts["records"] += 1
    if counts["records"]:
        logger.info(f"awake_read: Sleep settled {counts['records']} quick read(s): {counts['confirmed']} confirmed, "
                    f"{counts['corrected']} corrected, {counts['dropped']} dropped")
    return counts

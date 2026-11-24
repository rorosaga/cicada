"""The folders a platform's own save is filed in, and the one reason the person may give a whole folder (G221, owner
2026-11-23).

People file their saves into folders on the platform itself: X bookmark folders, Instagram collections, Pinterest boards,
TikTok collections, YouTube playlists. A save can sit in several of them, and any door that sees the save may report them
(the site-save route, a saved-list read, later a connector). This module holds what Cicada keeps of that and nothing else.

**Where it lives**

* On the save's episode, ``save_folders: {<origin>: [<folder name>, ...]}`` — the names exactly as the site shows them
  (secrets scrubbed, a cap each). Keyed by the site's origin (``x-bookmarks``), not by the episode's own, because one post
  is one save however it first arrived (a browser bookmark of the same post is the row an X folder is reported on). The
  fixed label a platform's whole list carries (``folder: Bookmarks``) is untouched: ``history_index.LIST_FOLDERS`` and
  ``history_index.kind`` read it as before. A YouTube playlist save already keeps its playlist as ``folder``, so that
  counts as its folder here too (:func:`folders_of`). Filing a save into a folder, or out of one, rewrites that one
  episode's frontmatter in place (:func:`file_save`): never a second episode, never a reason to ask the person again.
* In the bank, ``sources/folder_reasons.json`` — ``{"version": 1, "folders": {<origin>: {<folder name>: <reason>}}}``,
  one reason a folder, the shape of a save's own (``reasons`` keys from ``saved_why.LABELS``, ``text`` a few words, ``at``,
  ``edited_at``, ``before``). The person's own words about a folder, scrubbed (writer ``folder-reason``), committed alone
  as the person by the routes.

**A folder is a filing label (owner 2026-10-29, 2026-10-19).** It is never the person's words, never a page or a hub and
never a conversation for the 2+ promotion rule: nothing here writes a page, a claim or a link, and a folder's name is no
evidence of anything. Only the *reason the person gave a folder* is theirs, and it is theirs about the folder.

**Inheritance.** A save with no reason of its own reads its folders' reasons (:func:`inherited`), marked as the folder's:
``saved_why.reason_of`` hands every reader a :class:`~api.services.saved_why.Reason` whose text begins ``From its folder
"<name>":`` and whose ``inherited_from`` names the folders, and ``GET /sources`` serves them as ``folderWhy``, never as
``savedWhy`` (which stays the save's own). A save's own reason always wins. The reason is read from the folder's record
every time, never copied onto the save, so an edit or a clear reaches every member at once.

**What makes a save readable.** An index-only save (ruling 62) is read by no model. A folder's reason is the person's
reason for everything filed there, so those saves become readable: ``history_index.kind`` sees the stamp
``readable_by_folder`` (``{at, folders}``, in ``PERSON_KEYS``) and a save the index had read is queued again. That is paid
model work at the next Sleep, so the stamp is never a silent bulk write: :func:`set_reason` counts the saves it would make
readable first, answers the count, writes nothing on ``dry_run``, and past :data:`CONFIRM_ABOVE` writes nothing until the
caller says ``confirm``. Clearing a reason removes the stamp; a save nothing read goes back to index-only at Sleep's next
retirement (``history_index.retire``), one a model read keeps what it made. A save filed later into a folder that has a
reason is stamped by the same step that files it.

Rails: no model and no fetch; every writer inside the bank's write admission (the routes and tools own that); the
episode edits go through ``episode_staging.amend_frontmatter`` under the episode lock.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from api.services import bank_index, episode_ids, episode_scrub, episode_staging, history_index, saved_why
from api.services.saved_why import SavedWhyError

#: The episode's folders, ``{origin: [name, ...]}``.
FOLDERS_KEY = "save_folders"
#: The stamp that makes a save readable (``history_index.FOLDER_READ_KEY``).
STAMP_KEY = history_index.FOLDER_READ_KEY
STORE = "sources/folder_reasons.json"
WRITER = "folder-reason"
TRIGGER = "user/folder_reason"
FILED_TRIGGER = "user/save_folders"
#: A folder name is a label, never a paragraph; a save sits in a handful of folders, never hundreds.
NAME_MAX = 80
MAX_PER_SAVE = 30
#: More saves than this made readable by one reason need the caller's ``confirm`` (the spend guard: each is a model read).
CONFIRM_ABOVE = 100
#: Origins whose own ``folder`` field is already the site's folder (a Takeout playlist, Watch later included).
OWN_FOLDER_ORIGINS = frozenset({"youtube-playlist"})
_LOCK = threading.Lock()


# ---- names -----------------------------------------------------------------------------------------------------------

def origin_of(site: str | None) -> str | None:
    """The origin a ``site`` names: a platform key (``x``, ``instagram``, ``pinterest``, ``tiktok``, ``youtube``…) or an
    origin a platform's saved list writes. ``None`` for anything else — a folder of no known site is not kept."""
    from api.services import saved_lists

    key = str(site or "").strip().lower()
    if key == "youtube":
        return "youtube-playlist"
    platform = saved_lists.PLATFORMS.get(key)
    if platform is not None:
        return platform.origin or None
    known = history_index.LIST_ORIGINS | frozenset(history_index.LIST_FOLDERS)
    return key if key in known else None


def clean_name(raw) -> str | None:
    """A folder's name as stored: one line, named secret shapes out, at most :data:`NAME_MAX` characters; ``None`` for
    nothing."""
    text = " ".join(str(raw or "").split())
    if not text:
        return None
    text, _ = episode_scrub.scrub_value(text)
    text = text.strip()
    if len(text) > NAME_MAX:
        text = text[: NAME_MAX - 1].rstrip() + "…"
    return text or None


def clean_names(raw) -> list[str]:
    """Several names (a list, or one string), cleaned, without repeats (a folder is the same folder in any case), in the
    order given."""
    items = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (list, tuple)) else []
    out: list[str] = []
    for item in items:
        name = clean_name(item)
        if name and not any(_same(name, seen) for seen in out):
            out.append(name)
    return out[:MAX_PER_SAVE]


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def explicit_of(fm: dict | None) -> dict[str, list[str]]:
    """``save_folders`` as stored: ``{origin: [name, ...]}``, only well-formed entries."""
    raw = (fm or {}).get(FOLDERS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(o): [str(n) for n in names if isinstance(n, str) and n.strip()]
            for o, names in raw.items() if isinstance(names, list)}


def folders_of(fm: dict | None) -> list[tuple[str, str]]:
    """Every folder the save is filed in, ``(origin, name)``: the reported ones, then a playlist's own ``folder``."""
    fm = fm or {}
    out = [(o, n) for o, names in explicit_of(fm).items() for n in names]
    origin = str(fm.get("origin") or "")
    own = str(fm.get("folder") or "").strip()
    if origin in OWN_FOLDER_ORIGINS and own and not any(o == origin and _same(n, own) for o, n in out):
        out.append((origin, own))
    return out


# ---- the folders' reasons (in the bank) ------------------------------------------------------------------------------

#: path -> ((mtime_ns, size), the folders table): a reader asks per episode, so the file is parsed once per change.
_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}


def load(memory_path: Path) -> dict[str, dict[str, dict]]:
    """``{origin: {name: reason}}`` — shared and read-only; a writer copies it. ``{}`` for none, an unreadable file too."""
    path = Path(memory_path) / STORE
    try:
        st = os.stat(path)
    except OSError:
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(str(path))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("folders") if isinstance(data, dict) else None
    table = {str(o): {str(n): r for n, r in names.items() if isinstance(r, dict)}
             for o, names in (raw or {}).items() if isinstance(names, dict)}
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[str(path)] = (stamp, table)
    return table


def _write(memory_path: Path, table: dict) -> None:
    target = Path(memory_path) / STORE
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": 1, "folders": {o: dict(sorted(names.items())) for o, names in sorted(table.items()) if names}}
    fd, tmp = tempfile.mkstemp(prefix=".folder_reasons.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _find(bucket: dict, name: str) -> str | None:
    """The stored spelling of ``name`` in an origin's folders, or ``None``."""
    if name in bucket:
        return name
    return next((k for k in bucket if _same(k, name)), None)


def reason_for(memory_path: Path, origin: str, name: str) -> dict | None:
    bucket = load(memory_path).get(origin) or {}
    key = _find(bucket, name)
    return bucket[key] if key is not None else None


def _reasoned(table: dict, folders: list[tuple[str, str]]) -> list[tuple[str, str, dict]]:
    out = []
    for origin, name in folders:
        bucket = table.get(origin) or {}
        key = _find(bucket, name)
        if key is not None and (bucket[key].get("reasons") or bucket[key].get("text")):
            out.append((origin, key, bucket[key]))
    return out


def inherited(memory_path: Path, fm: dict | None) -> list[dict]:
    """The reasons a save inherits from its folders, in the order it is filed: ``[{origin, folder, reasons, labels, text,
    at, edited_at}]``. Empty for a save in no folder that has one. Says nothing of the save's own reason."""
    folders = folders_of(fm)
    if not folders:
        return []
    out = []
    for origin, name, record in _reasoned(load(memory_path), folders):
        shaped = saved_why.wire(record, added_at=None) or {}
        out.append({"origin": origin, "folder": name, "reasons": shaped.get("reasons") or [],
                    "labels": shaped.get("labels") or [], "text": shaped.get("text"), "at": shaped.get("at"),
                    "edited_at": shaped.get("edited_at")})
    return out


def compose(entries: list[dict]) -> tuple[str, str]:
    """``(text, at)`` for a reader that shows one line: each folder's labels and words behind ``From its folder "<name>":``
    — said about the folder, never the save — and the newest time any of them was said or edited."""
    parts = []
    for e in entries:
        words = [" ".join(str(e["text"]).split())] if e.get("text") else []
        said = "; ".join([*(e.get("labels") or []), *words])
        parts.append(f'From its folder "{e["folder"]}": {said}')
    at = max((str(e.get("edited_at") or e.get("at") or "") for e in entries), default="")
    return " | ".join(parts), at


def reason_state(memory_path: Path, fm: dict | None) -> str | None:
    """``own`` (the person said why they saved this), ``folder`` (only a folder's reason covers it) or ``None``."""
    if saved_why.records_of(fm):
        return "own"
    return "folder" if inherited(memory_path, fm) else None


# ---- readiness: what a folder's reason makes of a save ---------------------------------------------------------------

def reconcile_fm(fm: dict, table: dict, now: str) -> tuple[bool, bool]:
    """Bring one save's stamp in line with its folders and ``table``; mutates ``fm``. ``(changed, newly_readable)``:
    ``newly_readable`` is true when an index-only save just became one a model will read. A save already readable by
    its own reason, one a model read, one removed from its source: left as it is."""
    if fm.get("source_deleted_at"):
        return False, False
    hit = [name for _o, name, _r in _reasoned(table, folders_of(fm))]
    if hit:
        stamp = fm.get(STAMP_KEY)
        if isinstance(stamp, dict):
            if list(stamp.get("folders") or []) == hit:
                return False, False
            fm[STAMP_KEY] = {**stamp, "folders": hit}
            return True, False
        # Ruling 80: a save waiting for tonight carries the folder's reason too (the stamp makes the reason the person's
        # words when it is read); only one in the pile is queued by it.
        if history_index.save_state(fm) not in ("pile", "waiting", "no-words") if history_index.SAVES_READ \
                else history_index.kind(fm) not in ("list", "saved"):
            return False, False
        if fm.get("processed", False) and fm.get("processed_by") not in (history_index.INDEXED_BY, history_index.NO_WORDS_BY):
            return False, False     # a model read it: it keeps what it made
        fm[STAMP_KEY] = {"at": now, "folders": hit}
        if fm.get("processed_by") in (history_index.INDEXED_BY, history_index.NO_WORDS_BY):
            fm["processed"] = False     # the index's read was of the words alone: queue the real one
            fm.pop("processed_by", None)     # G114 R6: written only beside processed: true
            return True, True
        return True, False
    if STAMP_KEY in fm:
        fm.pop(STAMP_KEY)
        return True, False
    return False, False


@dataclass
class Sweep:
    """What setting or clearing one folder's reason does to the saves filed there."""
    saves: int = 0
    makes_readable: int = 0      # index-only saves that a model will now read (paid work at the next Sleep)
    already_readable: int = 0    # filed there but readable already (their own reason, a note, a read)
    no_longer_readable: int = 0  # stamped saves a clear took the stamp from
    paths: list[str] = field(default_factory=list)   # memory-relative episode files rewritten

    def wire(self) -> dict:
        return {"saves": self.saves, "makesReadable": self.makes_readable, "alreadyReadable": self.already_readable,
                "noLongerReadable": self.no_longer_readable}


def _members(memory_path: Path, origin: str, name: str | None = None):
    for f in bank_index.files(Path(memory_path), "episodes"):
        for o, n in folders_of(f.frontmatter):
            if o == origin and (name is None or _same(n, name)):
                yield f
                break


def _sweep(memory_path: Path, origin: str, name: str, table: dict, now: str, *, write: bool) -> Sweep:
    out = Sweep()
    for f in _members(memory_path, origin, name):
        fm = f.frontmatter or {}
        if fm.get("source_deleted_at"):
            continue
        out.saves += 1
        probe = copy.deepcopy(fm)
        changed, new = reconcile_fm(probe, table, now)
        if new:
            out.makes_readable += 1
        elif history_index.kind(fm) is None:
            out.already_readable += 1
        if changed and STAMP_KEY in fm and STAMP_KEY not in probe:
            out.no_longer_readable += 1
        if write and changed:
            episode_staging.amend_frontmatter(f.path, lambda cur: reconcile_fm(cur, table, now)[0])
            out.paths.append(f"episodes/{f.path.name}")
    return out


# ---- setting, editing and clearing a folder's reason -----------------------------------------------------------------

def resolve(site: str, folder: str) -> tuple[str, str]:
    origin = origin_of(site)
    if origin is None:
        raise SavedWhyError(422, "That is not a site Cicada keeps saves for.")
    name = clean_name(folder)
    if name is None:
        raise SavedWhyError(422, "Name the folder.")
    return origin, name


def _same_words(a: dict, b: dict) -> bool:
    return (set(a.get("reasons") or []) == set(b.get("reasons") or [])
            and (a.get("text") or None) == (b.get("text") or None))


def set_reason(memory_path: Path, *, site: str, folder: str, answer: saved_why.Answer, bank: str | None = None,
               dry_run: bool = False, confirm: bool = False, now: str | None = None) -> dict:
    """Give a folder ONE reason, or change the one it has (the earlier words stay under ``before``, as a save's edited
    answer's do). The answer is :func:`saved_why.validate`'s (its reasons and words; never a project). Counts the saves
    that become readable (:class:`Sweep`) before it writes: ``dry_run`` writes nothing, and more than
    :data:`CONFIRM_ABOVE` of them write nothing until ``confirm``. Returns ``{origin, folder, reason, changed, applied,
    needsConfirm, counts, paths}``; ``paths`` are the files to commit (the caller commits, inside its write admission)."""
    memory_path = Path(memory_path)
    origin, name = resolve(site, folder)
    now = now or episode_ids.utc_now_seconds()
    text = (episode_scrub.scrub_body(answer.text, writer=WRITER, bank=bank or memory_path.name)
            if answer.text else None)
    fresh = {"reasons": list(answer.reasons), "text": text, "at": now}
    with _LOCK:
        table = copy.deepcopy(load(memory_path))
        bucket = table.setdefault(origin, {})
        key = _find(bucket, name) or name
        old = bucket.get(key)
        if old is not None and _same_words(old, fresh):
            record, changed = old, False
        elif old is not None:
            record = {**fresh, "at": old.get("at") or now, "edited_at": now, "before": saved_why._before(old)}
            changed = True
        else:
            record, changed = fresh, True
        bucket[key] = record
        plan = _sweep(memory_path, origin, key, table, now, write=False)
        base = {"origin": origin, "folder": key, "reason": saved_why.wire(record, added_at=None), "changed": changed,
                "counts": plan.wire(), "paths": []}
        if dry_run:
            return {**base, "applied": False, "needsConfirm": False}
        if plan.makes_readable > CONFIRM_ABOVE and not confirm:
            return {**base, "applied": False, "needsConfirm": True}
        paths: list[str] = []
        if changed:
            _write(memory_path, table)
            paths.append(STORE)
        done = _sweep(memory_path, origin, key, table, now, write=True)
        return {**base, "applied": True, "needsConfirm": False, "counts": done.wire(),
                "paths": paths + done.paths}


def clear_reason(memory_path: Path, *, site: str, folder: str, now: str | None = None) -> dict:
    """Take a folder's reason away. Saves it made readable lose the stamp (what no model read goes back to index-only at
    Sleep's next retirement). 404 for a folder with no reason. Same answer shape as :func:`set_reason`."""
    memory_path = Path(memory_path)
    origin, name = resolve(site, folder)
    now = now or episode_ids.utc_now_seconds()
    with _LOCK:
        table = copy.deepcopy(load(memory_path))
        bucket = table.get(origin) or {}
        key = _find(bucket, name)
        if key is None:
            raise SavedWhyError(404, "That folder has no reason to clear.")
        del bucket[key]
        _write(memory_path, table)
        done = _sweep(memory_path, origin, key, table, now, write=True)
        return {"origin": origin, "folder": key, "reason": None, "changed": True, "applied": True,
                "needsConfirm": False, "counts": done.wire(), "paths": [STORE] + done.paths}


# ---- filing a save into folders, and out of them ---------------------------------------------------------------------

def file_save(memory_path: Path, episode_id: str, origin: str, *, add=(), remove=(), now: str | None = None) -> dict:
    """The folders a site shows for one save, reported by whichever door saw them: ``add`` joins them to the save's
    folders under ``origin`` and ``remove`` takes some out, on the one episode, in place. A folder with a reason makes the
    save readable in the same step (:func:`reconcile_fm`). ``{changed, folders, reason, path}``; ``path`` is the
    memory-relative file to commit, only when it changed. A missing episode changes nothing."""
    memory_path = Path(memory_path)
    path = memory_path / "episodes" / f"{episode_id}.md"
    if not episode_id or "/" in episode_id or not path.is_file():
        return {"changed": False, "folders": [], "reason": None, "path": None}
    add, remove = clean_names(add), clean_names(remove)
    now = now or episode_ids.utc_now_seconds()
    table = load(memory_path)
    seen: dict = {}

    def edit(fm: dict) -> bool:
        mapping = explicit_of(fm)
        held = list(mapping.get(origin, []))
        kept = [n for n in held if not any(_same(n, r) for r in remove)]
        kept += [n for n in add if not any(_same(n, k) for k in kept)]
        kept = kept[:MAX_PER_SAVE]
        changed = kept != held
        if changed:
            if kept:
                mapping[origin] = kept
            else:
                mapping.pop(origin, None)
            if mapping:
                fm[FOLDERS_KEY] = mapping
            else:
                fm.pop(FOLDERS_KEY, None)
        moved, _new = reconcile_fm(fm, table, now)
        seen["fm"] = dict(fm)
        return changed or moved

    changed = episode_staging.amend_frontmatter(path, edit)
    fm = seen.get("fm") or {}
    return {"changed": changed, "folders": [n for o, n in folders_of(fm) if o == origin],
            "reason": reason_state(memory_path, fm), "path": f"episodes/{episode_id}.md" if changed else None}


# ---- listing a site's folders ----------------------------------------------------------------------------------------

def list_folders(memory_path: Path, site: str) -> dict:
    """A site's folders: each with how many saves are filed there, how many of those no model would read yet
    (``indexOnly``: what a reason would make readable) and its reason when it has one. A folder with a reason and no saves
    is listed too. ``unfiled`` counts the site's saves in none."""
    memory_path = Path(memory_path)
    origin = origin_of(site)
    if origin is None:
        raise SavedWhyError(422, "That is not a site Cicada keeps saves for.")
    table = load(memory_path).get(origin) or {}
    counts: dict[str, dict] = {}
    unfiled = total = 0
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if fm.get("source_deleted_at"):
            continue
        mine = [n for o, n in folders_of(fm) if o == origin]
        if str(fm.get("origin") or "") == origin or mine:
            total += 1
        if str(fm.get("origin") or "") == origin and not mine:
            unfiled += 1
        for n in mine:
            row = counts.setdefault(_find(counts, n) or n, {"saves": 0, "indexOnly": 0})
            row["saves"] += 1
            row["indexOnly"] += int(history_index.kind(fm) in ("list", "saved"))
    for name in table:
        counts.setdefault(_find(counts, name) or name, {"saves": 0, "indexOnly": 0})
    rows = []
    for name, row in sorted(counts.items(), key=lambda kv: (-kv[1]["saves"], kv[0].casefold())):
        key = _find(table, name)
        reason = saved_why.wire(table[key], added_at=None) if key is not None else None
        rows.append({"name": name, **row, "reason": reason})
    return {"site": str(site).strip().lower(), "origin": origin, "saves": total, "unfiled": unfiled, "folders": rows}


def commit_message(paths: list[str], *, trigger: str = TRIGGER) -> str:
    from api.services import git_service

    subject = "Why a folder was saved" if trigger == TRIGGER else "Folders of a save"
    return git_service.build_commit_message(
        subject, [f"{p}: updated (trigger: {trigger})" for p in paths], authors=[git_service.USER_AUTHOR])

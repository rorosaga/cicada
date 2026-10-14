"""A page's claims ledger — where a very large page's older claims live, beside the page (owner page, 2026-10-14).

The owner's page carried ~5,900 claims — a per-conversation activity log ("<owner> asked about X") — in its claims
fence: 4.5 MB of a 4.7 MB file that every reader and writer moved, that put the page's article writer over its input
budget, and whose first `cicada_recall_detail` part was mostly frontmatter. The record is the claims: none may be lost
(G118), and nothing may change for the ~70 readers and writers that take a page's claims from its fence.

So a page's claims are its fence **plus**, once the fence passes :data:`FENCE_MAX_CHARS`, a ledger file beside it,
``entities/<id>.claims.jsonl`` — one claim per line, the fence's own JSON Lines (``claims._jsonl_line``), oldest
first, tracked by git like the page. The split is invisible above ``markdown_parser``:

* **Read** (:func:`fold`): ``markdown_parser.parse`` of a page whose frontmatter carries the :data:`STAMP` returns the
  body with the ledger's lines put back at the head of the fence, so every claim reader sees one set, as before. A
  frontmatter-only scan passes ``ledger=False`` and never opens it.
* **Write** (:func:`split`): ``markdown_parser.write`` leaves in the ledger every ledger line the body carries back
  byte for byte. A ledger line the body does not carry leaves the ledger only when the writer hands back the
  frontmatter :func:`fold` marked (:data:`READ`, the hash of the ledger it read) and that ledger is unchanged: the
  body is then the page's whole claim set, and the line was changed or removed by the writer (a rename re-subjects
  every claim; a pass edits each). Any other body — read without the ledger, or against a ledger changed since —
  leaves every ledger line as it is. Nothing is matched by id: ids come from the fact, so a withdrawn or expired claim
  and its restatement share one, and both are the record. When the fence is over the budget, its oldest lines
  (closed ones first, then a log's — :func:`_spill_order`) move into the ledger until it is under :data:`SPILL_TO`,
  so a page spills in steps. :func:`remove` (a merged-away page) and :func:`move` (a renamed page) take a ledger
  away, both after or with its claims.
* The page's frontmatter stamp ``claims_ledger: {claims: N, hash: <12 hex>}`` is rewritten with every ledger write,
  so the page's bytes change whenever its ledger does (every cache keyed on the page's mtime, size or hash sees it),
  and a raw reader — `cicada_recall_detail`, the Source view — can say the ledger is there. It is a pointer, not a
  changelog: git holds the history of both files.

Crash order (:func:`write_plan`): lines the ledger gains are written before the page, lines it loses after it. A crash
between the two leaves a claim in both files — the same bytes, which :func:`fold` reads once, or an old version beside
its new one — never in neither.

Git: a page and its ledger are one unit. ``git_service`` adds the ledger to every commit and checkout that names its
page (:func:`with_ledgers`); a dedup merge's footprint names it too.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

import yaml

from api.services import claims, entity_body

SUFFIX = ".claims.jsonl"
STAMP = "claims_ledger"
#: The in-memory mark :func:`fold` leaves on the frontmatter it folded for: the hash of the ledger it read.
READ = "read"
#: Above this many characters of claim lines, a write moves the page's oldest claims into its ledger. About one
#: `cicada_recall_detail` part: every page but a few hubs stays far below it (a median page holds a few KB of claims).
FENCE_MAX_CHARS = 64_000
#: ...until the fence is under this, so the next spill is many writes away.
SPILL_TO = FENCE_MAX_CHARS // 2

_ID_RE = re.compile(r'^\{"id":\s*"((?:[^"\\]|\\.)*)"')


def is_page(path) -> bool:
    """An entity page: ``<bank>/entities/<id>.md``."""
    path = Path(path)
    return path.suffix == ".md" and path.parent.name == "entities" and not path.name.startswith(".")


def path_for(page) -> Path:
    page = Path(page)
    return page.with_name(page.stem + SUFFIX)


def rel_for(rel: str) -> str | None:
    """``entities/<id>.claims.jsonl`` for a memory-relative ``entities/<id>.md``, else ``None``."""
    rel = str(rel)
    if rel.startswith("entities/") and rel.endswith(".md") and rel.count("/") == 1:
        return rel[:-3] + SUFFIX
    return None


def line_id(line: str) -> str:
    """The claim id a JSON line holds (``""`` when it has none or is not JSON)."""
    match = _ID_RE.match(line)
    if match:
        try:
            return json.loads(f'"{match.group(1)}"')
        except ValueError:
            pass
    try:
        entry = json.loads(line)
    except ValueError:
        return ""
    return str(entry.get("id") or "") if isinstance(entry, dict) else ""


#: Per-process memo of each ledger's lines and their ids, keyed on the file's (mtime, size): an owner-sized page is
#: parsed many times a Sleep batch and its ledger rarely changes between them. Disposable, like `bank_index`.
_MEMO: dict[str, tuple[tuple[int, int], list[str], list[str] | None]] = {}
_MEMO_MAX = 32


def _memo(ledger: Path):
    try:
        st = os.stat(ledger)
    except FileNotFoundError:
        return None
    key, stamp = str(ledger), (st.st_mtime_ns, st.st_size)
    hit = _MEMO.get(key)
    if hit is not None and hit[0] == stamp:
        return hit
    text = Path(ledger).read_text(encoding="utf-8")
    entry = (stamp, [line for line in text.split("\n") if line.strip()], None)
    while len(_MEMO) >= _MEMO_MAX:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = entry
    return entry


def read_lines(ledger: Path) -> list[str]:
    hit = _memo(ledger)
    return list(hit[1]) if hit else []


def _ids(ledger: Path) -> list[str]:
    """The id of each of the ledger's lines, in order (memoized with them)."""
    hit = _memo(ledger)
    if hit is None:
        return []
    if hit[2] is None:
        hit = (hit[0], hit[1], [line_id(line) for line in hit[1]])
        _MEMO[str(ledger)] = hit
    return hit[2]


def _fence(body: str):
    """``(match, lines)`` for the page's one claims fence: ``(None, [])`` without one, ``(None, None)`` when it cannot
    be read — an unterminated or repeated fence, or a legacy one whose YAML will not load, is never folded or split.
    A JSON Lines fence is taken line by line without decoding: lines only move between files, and a line with no
    readable id never moves (:func:`line_id`), so even a damaged line is kept where it is. One scan of the body: the
    fence pattern is slow on a megabyte page, so it runs once and the rest is searched only past the fence."""
    body = body or ""
    openings = len(claims._FENCE_OPEN_RE.findall(body))
    if openings == 0:
        return None, []
    match = claims._CLAIMS_BLOCK_RE.search(body)
    if openings != 1 or match is None or claims._CLAIMS_BLOCK_RE.search(body, match.end()) is not None:
        return None, None
    payload = match.group("payload")
    if claims.is_jsonl_payload(payload):
        return match, [line for line in payload.split("\n") if line.strip()]
    if payload.strip() in ("", "[]"):
        return match, []
    try:
        loaded = claims.load_fence_payload(payload) or []
    except (ValueError, yaml.YAMLError):
        return None, None
    if not isinstance(loaded, list) or not all(isinstance(entry, dict) for entry in loaded):
        return None, None
    return match, [claims._jsonl_line(entry) for entry in loaded]


def _with_fence(body: str, match, lines: list[str]) -> str:
    """``body`` with its fence's payload replaced by ``lines`` (``[]`` when none), every other byte kept; a page with
    no fence gets one after its prose, where ``claims.write_claims`` puts it."""
    payload = "\n".join(lines) or "[]"
    if match is None:
        stripped = (body or "").rstrip()
        return f"{stripped}\n\n```{claims.CLAIMS_FENCE_LANG}\n{payload}\n```" if stripped else \
            f"```{claims.CLAIMS_FENCE_LANG}\n{payload}\n```"
    return body[:match.start("payload")] + payload + "\n" + body[match.end("payload"):]


def fold(page, frontmatter: dict, body: str) -> str:
    """The body with the page's ledger lines at the head of its fence — what every claim reader takes as the page's
    claims. Untouched when the page carries no :data:`STAMP`, has no ledger, or its fence cannot be read.

    When it folds, it marks ``frontmatter`` (the dict ``markdown_parser.parse`` returns with this body) with the hash of
    the ledger it read (:data:`READ`): a writer that hands that frontmatter back to ``markdown_parser.write`` with the
    body it read and changed is writing the page's whole claim set, and :func:`split` files it exactly. The mark never
    reaches disk — :func:`split` rewrites the stamp on every write."""
    if not isinstance(frontmatter, dict) or STAMP not in frontmatter:
        return body
    ledger_path = path_for(page)
    ledger = read_lines(ledger_path)
    if not ledger:
        return body
    folded = merged(body, ledger)
    if folded is not body:
        stamp = frontmatter.get(STAMP)
        frontmatter[STAMP] = {**(stamp if isinstance(stamp, dict) else {}), READ: _stamp(ledger)[0]["hash"]}
    return folded


def merged(body: str, ledger: list[str]) -> str:
    """``body`` with ``ledger`` lines at the head of its fence. A ledger line byte-identical to a fence line is read once
    (after a crash between the two writes, both files hold the same moved line); every other line is kept, two copies
    under one id included — ids come from the fact, so a withdrawn or expired claim and its restatement share one, and
    both are the record (review 2026-10-14). ``body`` as given when its fence cannot be read."""
    match, fence = _fence(body)
    if fence is None or not ledger:
        return body
    on_page = Counter(fence)
    kept = []
    for line in ledger:
        if on_page[line] > 0:
            on_page[line] -= 1
            continue
        kept.append(line)
    return _with_fence(body, match, kept + fence)


#: A predicate a page holds for at most this many objects is a fact about it ("studies at", "lives in"); one it holds
#: for hundreds is a log ("asked about"). One line for the ledger, the article's inputs and a hub's Related.
FACT_FAMILY_MAX = entity_body.RELATION_FAMILY_MAX


def _spill_order(lines: list[str]) -> list[tuple]:
    """Each line's place in the spill order: closed claims first (``valid_to`` or ``superseded_by`` set), then a log's
    (a predicate the page holds for more than :data:`FACT_FAMILY_MAX` objects: "<owner> asked about X" — activity,
    not a fact about the page), then the rest; within each, the longest ago recorded first. What stays on the page is
    what it most says about its subject, and the newest of the rest."""
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        entries.append(entry if isinstance(entry, dict) else {})
    objects: dict[str, set] = {}
    for entry in entries:
        objects.setdefault(str(entry.get("predicate") or ""), set()).add(str(entry.get("object") or ""))
    keys = []
    for entry in entries:
        closed = bool(entry.get("valid_to") or entry.get("superseded_by"))
        log = len(objects.get(str(entry.get("predicate") or ""), ())) > FACT_FAMILY_MAX
        keys.append((0 if closed else 1 if log else 2, str(entry.get("recorded_at") or entry.get("valid_from") or "")))
    return keys


def _stamp(lines: list[str]) -> tuple[dict, bytes]:
    data = ("\n".join(lines) + "\n").encode("utf-8")
    return {"claims": len(lines), "hash": hashlib.sha256(data).hexdigest()[:12]}, data


def split(page, frontmatter: dict, body: str) -> tuple[dict, str, bytes | None]:
    """What a write of ``(frontmatter, body)`` to ``page`` puts on the page and in its ledger: ``(frontmatter, body,
    ledger bytes)``, the last ``None`` when the ledger needs no write and ``b""`` when it goes. Never drops a claim:
    a ledger line leaves the ledger only for a writer that read it through :func:`fold` and wrote its change back."""
    frontmatter = dict(frontmatter or {})
    ledger_path = path_for(page)
    has_ledger = ledger_path.exists()
    if not has_ledger and len(body or "") <= FENCE_MAX_CHARS:
        frontmatter.pop(STAMP, None)
        return frontmatter, body, None
    match, fence = _fence(body)
    if not has_ledger and (match is None or len(match.group("payload")) <= FENCE_MAX_CHARS):
        frontmatter.pop(STAMP, None)
        return frontmatter, body, None
    old = read_lines(ledger_path) if has_ledger else []
    if fence is None:   # an unreadable fence is written as given; the ledger and its stamp stay as they are
        if old:
            frontmatter[STAMP] = _stamp(old)[0]
        return frontmatter, body, None
    # The ledger lines the body carries back byte for byte stay in the ledger, where they are.
    in_body = Counter(fence)
    carried: list[bool] = []
    for line in old:
        carried.append(in_body[line] > 0)
        if carried[-1]:
            in_body[line] -= 1
    consumed = Counter(line for line, kept in zip(old, carried) if kept)
    stay: list[str] = []
    for line in fence:
        if consumed[line] > 0:
            consumed[line] -= 1
        else:
            stay.append(line)
    # A ledger line the body does not carry: when the writer read this very ledger through `fold` (the mark on the
    # frontmatter it hands back), the body is the page's whole claim set and the writer changed or removed that line —
    # its new version, if any, is in ``stay``: the ledger keeps only what was carried (owner page review 2026-10-14: a
    # rename re-subjects every claim; a pass edits every one). Any other body — read without the ledger, or from a
    # ledger changed since — knows nothing of those lines: they stay as they are. Never matched by id: a withdrawn
    # claim and its restatement share one, and both are the record.
    read = (frontmatter.get(STAMP) or {}).get(READ) if isinstance(frontmatter.get(STAMP), dict) else None
    whole_set = bool(old) and read == _stamp(old)[0]["hash"]
    ledger = [line for line, kept in zip(old, carried) if kept] if whole_set else list(old)
    size = sum(len(line) + 1 for line in stay)
    if size > FENCE_MAX_CHARS:
        order = _spill_order(stay)
        movable = sorted(range(len(stay)), key=lambda i: (order[i], i))
        moved: set[int] = set()
        for i in movable:
            if size <= SPILL_TO:
                break
            moved.add(i)
            size -= len(stay[i]) + 1
        ledger += [stay[i] for i in sorted(moved)]
        stay = [line for i, line in enumerate(stay) if i not in moved]
    if not ledger and old:
        # The writer held every ledger line and kept none there: the ledger goes (an empty file says nothing).
        frontmatter.pop(STAMP, None)
        return frontmatter, _with_fence(body, match, stay), b""
    if not ledger:
        frontmatter.pop(STAMP, None)
        return frontmatter, body, None
    frontmatter[STAMP], data = _stamp(ledger)
    new_body = _with_fence(body, match, stay)
    return frontmatter, new_body, (None if ledger == old else data)


def write_plan(page, data: bytes) -> tuple[bytes | None, bytes | None]:
    """How a ledger write is ordered around its page's write, so a crash never loses a claim: ``(before the page,
    after the page)``. Lines it adds go in before the page (a crash then leaves a moved line in both files, which a
    read takes once); lines it drops go after the page has their new versions (a crash then leaves the old version
    beside the new one — a duplicate, never a loss). ``b""`` after the page: the ledger goes."""
    old = read_lines(path_for(page))
    new = [line for line in data.decode("utf-8").split("\n") if line.strip()]
    added = Counter(new) - Counter(old)
    dropped = Counter(old) - Counter(new)
    if not dropped:
        return data, None
    if not added:
        return None, data
    staging = list(old)
    for line in new:
        if added[line] > 0:
            added[line] -= 1
            staging.append(line)
    return _stamp(staging)[1], data


def ledger_lines(page) -> list[str]:
    """The ledger's lines as stored (oldest first), for a raw reader that shows them after the page."""
    return read_lines(path_for(page))


def with_ledgers(memory_path, rels, *, existing_only: bool = False) -> list[str]:
    """``rels`` with each page's ledger after it: always when it exists on disk; otherwise only when
    ``existing_only`` is false (a commit records its removal, a footprint its absence)."""
    out: list[str] = []
    for rel in rels:
        out.append(rel)
        companion = rel_for(rel)
        if companion and (not existing_only or (Path(memory_path) / companion).exists()):
            out.append(companion)
    return list(dict.fromkeys(out))


def remove(page) -> bool:
    """Delete a page's ledger, after its claims went elsewhere (a merged-away page). ``True`` when one was there."""
    try:
        os.unlink(path_for(page))
        return True
    except FileNotFoundError:
        return False


def move(src, dst) -> bool:
    """Rename a page's ledger with its page. ``True`` when one was moved."""
    source = path_for(src)
    if not source.exists():
        return False
    os.replace(source, path_for(dst))
    return True

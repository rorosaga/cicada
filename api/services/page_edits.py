"""An agent edits a page's prose or aliases directly, with blame (owner ruling 2026-10-14, G198).

Until this an agent could write and withdraw facts (claims), add sources and save episodes, but only Sleep wrote a
page's prose. The owner: "it would be nice to have a list of trusted models or agents that we give permission to write
into the page directly … we also record what part they contributed, the same as a doc in git … the agent gives a
reason through a commit message … the edits apply immediately."

**What an edit is.** One call (``cicada_edit_page``) carries a required ``reason`` and any of:

* ``edits`` — exact words → new words in the page's prose. Each ``old`` must be on the page exactly once, or ``all``
  replaces every occurrence. The claims fence (and the ledger beside it) is never read or written here: the prose is
  the body *before* the fence, edited as a string, and the fence and everything after it are put back byte for byte.
  Facts stay with the claim tools.
* ``section`` + ``text`` — the whole content of one section (a ``## `` title, or a ``### `` title inside the Article).
  ``Related`` is refused: Sleep rebuilds it from the graph on every update, so an edit there could not stand — a
  relation is a claim.
* ``add_aliases`` / ``remove_aliases`` — another name the page goes by. A removal is remembered
  (``aliases_removed:``), like ``sources_removed``: no automatic writer (Sleep's alias merge, a page merge) adds it back;
  adding it again by an edit lifts the mark.

Neither ``old``, ``new`` nor a section's text may hold a code fence or a ``#``/``##`` heading line: those would move
the fence or the page's sections, which this tool does not do.

**Sleep must not undo it.** Two mechanisms, by what the edit is:

* *A word-level fix is pinned* — ``corrections: [{old, new, by, on}]`` in the frontmatter, when the edit asks
  (``pin``; on by default with ``all``, the misspelling case). Every machine prose writer (Stage 3's update in
  ``conflict_resolver``, ``page_article_rebuild``, ``source_rewrite``) runs :func:`apply_corrections` over the prose it
  is about to write, and the article writer is told them (``entity_article``). Replacement is exact, whole-word at
  word edges, and idempotent (a ``new`` that contains its ``old`` is never re-applied inside itself). The page stays
  the writer's: a stamped article is restamped (``entity_article.carry_stamp``), so it keeps growing with the fix in.
* *A rewritten Summary or Article section is the editor's from then on* — ``human_edited: true``, exactly as a
  person's edit of those halves already makes a page additive-only (``entity_body.has_human_prose``). The record
  sections (Key Facts, History, Links, Open Questions) need no mark: Sleep unions into them and never shortens them.

**Blame is git.** The edit commits alone under the harness (``Cicada-Author``), with the conversation
(``Cicada-Session``); the reason is a ``Reason:`` line of its own and cited words are ``Evidence:`` lines (spans,
never copies — G118). ``page_blame`` reads them back per section and per line.

**Trust** (``page_editors``): a trusted harness's edit applies at once; any other agent's becomes a ``page_edit``
proposal in the inbox — validated now, so the person is never offered an edit that cannot apply — which the person
applies or leaves with one tap (UX principle 3). An applied proposal commits under the agent that wrote the words and
the person who accepted them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from api.services import alias_policy, claims, entity_article, entity_body, markdown_parser, section_provenance

MAX_REASON = 500
MAX_EDITS = 20
MAX_OLD = 2000
MAX_NEW = 4000
MAX_SECTION_TEXT = 20000
MAX_ALIAS = 120
MAX_ALIAS_CHANGES = 10
#: An ``old → new`` fix whose ``old`` is at most this long can be pinned (a name, a phrase — not a paragraph).
PIN_MAX = 200
MAX_CORRECTIONS = 30
MAX_ALIASES_REMOVED = 50

CORRECTIONS = "corrections"
ALIASES_REMOVED = "aliases_removed"
#: The halves of a page the article writer owns; a rewrite of one makes the page the editor's.
MACHINE_SECTIONS = ("Summary", entity_article.SECTION)
#: Rebuilt by a machine writer on every update, so an edit could not stand: ``Related`` by Sleep from the graph, ``Looks``
#: by ``design_refs`` from the look records (owner 2026-10-20).
REBUILT_SECTIONS = ("Related", "Looks")


def _rebuilt_why(title: str) -> str:
    """Why an edit in a rebuilt section would not last, and what to do instead."""
    if title == "Looks":
        return ("'Looks' is written from the look records on every change, so an edit there would not last. Move or "
                "remove a look from the page's Looks section in the app (or save one with cicada_save_design) instead.")
    return (f"'{title}' is rebuilt from the graph on every update, so an edit there would not last. Record the "
            "relation as a claim instead.")

KIND = "page_edit"            # the inbox kind of a proposal
TRIGGER_APPLY = "inbox/page_edit/resolved:apply"
TRIGGER_DISMISS = "inbox/page_edit/resolved:dismiss"
COMMIT_SUBJECT = "Page edit"
PROPOSAL_SUBJECT = "Page edit proposed"
REASON_PREFIX = "Reason: "
EVIDENCE_PREFIX = "Evidence: "
ACCEPTED_LINE = "Accepted by the person in the inbox."

_FENCE_LINE = re.compile(r"^ {0,3}(`{3,}|~{3,})", re.MULTILINE)
_TOP_HEADING = re.compile(r"^ {0,3}#{1,2}(?:\s|$)", re.MULTILINE)
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_WORD = re.compile(r"\w", re.UNICODE)


def _flag(value, default: bool, where: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise EditError(f"{where} must be true or false.")


class EditError(ValueError):
    """An edit Cicada refuses, with a sentence the agent (or the person) can act on. Nothing was written."""


# --------------------------------------------------------------------------- the request


@dataclass
class Request:
    edits: list[dict] = field(default_factory=list)       # {old, new, all, pin}
    section: str | None = None
    text: str | None = None
    add_aliases: list[str] = field(default_factory=list)
    remove_aliases: list[str] = field(default_factory=list)
    #: Ruling 45 (Q5): a project's display name and the person's header line (`project_ownership.apply_header`).
    name: str | None = None
    description: str | None = None

    def to_dict(self) -> dict:
        out: dict = {}
        if self.edits:
            out["edits"] = [dict(e) for e in self.edits]
        if self.section is not None:
            out["section"], out["text"] = self.section, self.text or ""
        if self.add_aliases:
            out["add_aliases"] = list(self.add_aliases)
        if self.remove_aliases:
            out["remove_aliases"] = list(self.remove_aliases)
        if self.name is not None:
            out["name"] = self.name
        if self.description is not None:
            out["description"] = self.description
        return out


def _structural(text: str) -> str | None:
    if _FENCE_LINE.search(text or ""):
        return "a code fence"
    if _TOP_HEADING.search(text or ""):
        return "a # or ## heading"
    return None


def _names(raw, label: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise EditError(f"`{label}` must be a list of names.")
    out: list[str] = []
    for value in raw:
        name = " ".join(str(value or "").split())
        if not name:
            continue
        if len(name) > MAX_ALIAS:
            raise EditError(f"An alias is at most {MAX_ALIAS} characters.")
        if name.casefold() not in {n.casefold() for n in out}:
            out.append(name)
    if len(out) > MAX_ALIAS_CHANGES:
        raise EditError(f"At most {MAX_ALIAS_CHANGES} aliases in `{label}` per call.")
    return out


def parse_request(edits=None, section=None, text=None, add_aliases=None, remove_aliases=None, name=None,
                  description=None) -> Request:
    """The call's arguments as a :class:`Request`, or :class:`EditError` saying what is wrong."""
    from api.services import project_ownership

    request = Request()
    try:
        if name is not None and str(name).strip():
            request.name = project_ownership.clean_name(name)
        if description is not None:
            request.description = project_ownership.clean_description(description)
    except project_ownership.OwnershipError as exc:
        raise EditError(str(exc)) from None
    if edits is not None:
        if isinstance(edits, dict):
            edits = [edits]
        if not isinstance(edits, (list, tuple)):
            raise EditError("`edits` must be a list of {old, new}.")
        if len(edits) > MAX_EDITS:
            raise EditError(f"At most {MAX_EDITS} edits per call.")
        for i, raw in enumerate(edits, 1):
            if not isinstance(raw, dict):
                raise EditError(f"Edit {i} must be an object with `old` and `new`.")
            old, new = raw.get("old"), raw.get("new")
            if not isinstance(old, str) or not old.strip():
                raise EditError(f"Edit {i}: `old` must be the exact words on the page.")
            if not isinstance(new, str):
                raise EditError(f"Edit {i}: `new` must be text (an empty string deletes the words).")
            if old == new:
                raise EditError(f"Edit {i}: `old` and `new` are the same.")
            if len(old) > MAX_OLD or len(new) > MAX_NEW:
                raise EditError(f"Edit {i}: `old` is at most {MAX_OLD} characters and `new` at most {MAX_NEW}.")
            for part, value in (("old", old), ("new", new)):
                if (bad := _structural(value)) is not None:
                    raise EditError(f"Edit {i}: `{part}` holds {bad}; edit the words inside a section, or use "
                                    "`section` to rewrite one.")
            # G199 fix round: `"false"` (a CLI's JSON, an agent's string) is false — `bool("false")` made it true.
            every = _flag(raw.get("all"), False, f"Edit {i}: `all`")
            pin = _flag(raw.get("pin"), every, f"Edit {i}: `pin`")
            if pin and len(old) > PIN_MAX:
                pin = False
            request.edits.append({"old": old, "new": new, "all": every, "pin": pin})
    if section is not None and str(section).strip():
        request.section = " ".join(str(section).split())
        if text is None or not isinstance(text, str):
            raise EditError("`section` needs `text`: the section's new content.")
        if len(text) > MAX_SECTION_TEXT:
            raise EditError(f"A section's text is at most {MAX_SECTION_TEXT} characters.")
        if (bad := _structural(text)) is not None:
            raise EditError(f"The section's text holds {bad}.")
        request.text = text.strip()
    elif text is not None and str(text).strip():
        raise EditError("`text` needs `section`: the title of the section it replaces.")
    request.add_aliases = _names(add_aliases, "add_aliases")
    request.remove_aliases = _names(remove_aliases, "remove_aliases")
    both = {a.casefold() for a in request.add_aliases} & {a.casefold() for a in request.remove_aliases}
    if both:
        raise EditError("The same alias can't be added and removed in one call.")
    if not (request.edits or request.section or request.add_aliases or request.remove_aliases
            or request.name is not None or request.description is not None):
        raise EditError("Nothing to change: give `edits`, `section` and `text`, `add_aliases`, `remove_aliases`, "
                        "`name` or `description`.")
    return request


def request_from_dict(raw) -> Request:
    raw = raw if isinstance(raw, dict) else {}
    return parse_request(raw.get("edits"), raw.get("section"), raw.get("text"), raw.get("add_aliases"),
                         raw.get("remove_aliases"), raw.get("name"), raw.get("description"))


def clean_reason(reason) -> str:
    """One line, at most :data:`MAX_REASON` characters. A line break would let a reason pose as a trailer."""
    text = " ".join(str(reason or "").split())
    if not text:
        raise EditError("`reason` is required: say why, in a sentence. It becomes the commit message.")
    return text[:MAX_REASON]


# --------------------------------------------------------------------------- the page


def split_prose(body: str) -> tuple[str, str]:
    """``(prose, rest)``: the body before its claims fence, and the fence with everything after it, untouched."""
    start = claims.claims_block_start(body or "")
    if start is None:
        return body or "", ""
    return body[:start], body[start:]


@dataclass
class _Heading:
    level: int
    title: str
    start: int          # the heading line's offset
    content: int        # where its content starts (after the heading line)
    end: int = 0        # where its content ends (the next heading at its level or above)


def headings(prose: str) -> list[_Heading]:
    """Every ``## `` and ``### `` heading outside a code fence, with its content span."""
    found: list[_Heading] = []
    fence = None
    offset = 0
    for raw in prose.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        marker = _FENCE_LINE.match(line)
        if fence is None and marker:
            fence = marker.group(1)[0]
        elif fence is not None and marker and marker.group(1)[0] == fence:
            fence = None
        elif fence is None and (m := _HEADING.match(line)):
            found.append(_Heading(len(m.group(1)), m.group(2).strip(), offset, offset + len(raw)))
        offset += len(raw)
    for i, h in enumerate(found):
        later = [x for x in found[i + 1:] if x.level <= h.level]
        h.end = later[0].start if later else len(prose)
    return found


def section_at(prose: str, offset: int, marks: list[_Heading] | None = None) -> str:
    """The ``## `` section an offset of the prose falls in (``""`` for a lead before any heading)."""
    title = ""
    for h in marks if marks is not None else headings(prose):
        if h.level == 2 and h.start <= offset:
            title = h.title
    return title


def _find_section(prose: str, wanted: str) -> tuple[_Heading, str]:
    """The heading a ``section`` names: an ``## `` title, else an ``### `` title inside the Article. Case aside."""
    marks = headings(prose)
    key = wanted.casefold().removeprefix("## ").removeprefix("### ").strip()
    for h in marks:
        if h.level == 2 and h.title.casefold() == key:
            return h, h.title
    for h in marks:
        if h.level == 3 and h.title.casefold() == key and section_at(prose, h.start, marks) == entity_article.SECTION:
            return h, entity_article.SECTION
    names = [h.title for h in marks if h.level == 2] + [
        f"{h.title} (in the Article)" for h in marks
        if h.level == 3 and section_at(prose, h.start, marks) == entity_article.SECTION]
    listed = ", ".join(names) if names else "none"
    raise EditError(f"No section '{wanted}' on this page. Its sections: {listed}.")


def _occurrences(text: str, old: str) -> list[int]:
    if _is_link(old):
        return [m.start() for m in _pattern(old).finditer(text)]
    out, at = [], text.find(old)
    while at != -1:
        out.append(at)
        at = text.find(old, at + len(old))
    return out


# --------------------------------------------------------------------------- corrections


#: A link or a URL in an edit is one whole token (owner rulings 2026-10-14, the link-view switch): never inside a
#: longer URL (``…/a`` in ``…/a/b``), a link's target (``(…)``) or label (``[…]``), or an image (``![…](…)``).
_LINK_LEAD = r"(?<![\w!\[(/<\"'=.:#?&%~+-])"
_LINK_TAIL = r"(?![\w/(\[\]\-?#=&%~+:\"'>]|\.[\w/])"


def _is_link(old: str) -> bool:
    return "://" in old


def _pattern(old: str) -> re.Pattern[str]:
    """``old`` as written, whole-word at an edge that is a word character (``Jon`` never matches inside ``Jonas``);
    a link or URL only as a whole token (``_LINK_LEAD`` / ``_LINK_TAIL``)."""
    if _is_link(old):
        return re.compile(_LINK_LEAD + re.escape(old) + _LINK_TAIL)
    lead = r"(?<!\w)" if _WORD.match(old[:1]) else ""
    tail = r"(?!\w)" if _WORD.match(old[-1:]) else ""
    return re.compile(lead + re.escape(old) + tail)


def corrections(frontmatter: dict) -> list[dict]:
    raw = (frontmatter or {}).get(CORRECTIONS)
    out: list[dict] = []
    for row in raw if isinstance(raw, list) else []:
        if isinstance(row, dict) and isinstance(row.get("old"), str) and row["old"] and isinstance(row.get("new"), str):
            out.append(row)
    return out


_ANY_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:\s+(.*?))?\s*$")
_CLAIMS_OPEN = re.compile(r"^```claims[ \t]*\r?$", re.MULTILINE)


def shape(text: str) -> tuple:
    """What an edit or a pinned fix must leave as it was (G198 review B2): how many ``claims`` openers the text holds,
    where its claims block starts (counted from the end, so words changed before it do not move it), its ``#``/``##``
    headings outside code fences in order, and whether a code fence is left open at its end."""
    text = text or ""
    start = claims.claims_block_start(text)
    tops: list[tuple[int, str]] = []
    fence = None
    for raw in text.splitlines():
        marker = _FENCE_LINE.match(raw)
        if fence is None and marker:
            fence = marker.group(1)
        elif fence is not None and marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) \
                and not raw[raw.index(marker.group(1)) + len(marker.group(1)):].strip():
            fence = None
        elif fence is None and (m := _ANY_HEADING.match(raw)) and len(m.group(1)) <= 2:
            tops.append((len(m.group(1)), (m.group(2) or "").strip()))
    return (len(_CLAIMS_OPEN.findall(text)), None if start is None else len(text) - start, tuple(tops),
            fence is not None)


def _structure_lines(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every heading line and code-fence marker line — what a pinned fix never rewrites."""
    out, offset = [], 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if _ANY_HEADING.match(line) or _FENCE_LINE.match(line):
            out.append((offset, offset + len(line)))
        offset += len(raw)
    return out


def _correct_one(text: str, old: str, new: str) -> tuple[str, int]:
    if old not in text:
        return text, 0
    # Headings and fence lines are the page's frame: masked, so a fix never renames a section or opens a fence.
    frame: list[str] = []
    for start, end in reversed(_structure_lines(text)):
        frame.append(text[start:end])
        text = text[:start] + f"\x01{len(frame) - 1}\x01" + text[end:]
    held: list[str] = []
    if new and old in new:
        # Mask every place the fix already stands, so its own `old` is not replaced inside it.
        def keep(m):
            held.append(m.group(0))
            return f"\x00{len(held) - 1}\x00"
        text = re.sub(re.escape(new), keep, text)
    text, n = _pattern(old).subn(lambda _m: new, text)
    if held:
        text = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], text)
    if frame:
        text = re.sub(r"\x01(\d+)\x01", lambda m: frame[int(m.group(1))], text)
    return text, n


def correct_text(text: str, rows: list[dict]) -> tuple[str, int]:
    """Every pinned correction applied to ``text``: ``(text, replacements)``. Idempotent — where ``new`` already
    stands (and contains ``old``) nothing changes. Never on a heading or fence line, and a fix whose result would
    change the text's :func:`shape` anyway (a claims opener assembled across words) is skipped (G198 review B2)."""
    count = 0
    base = shape(text)
    for row in rows:
        candidate, n = _correct_one(text, row["old"], row["new"])
        if n and shape(candidate) == base:
            text, count = candidate, count + n
    return text, count


def apply_corrections(frontmatter: dict, body: str) -> tuple[str, int]:
    """A machine writer's prose with the page's pinned corrections applied — the prose before the claims fence only,
    and never inside ``## Related`` (rebuilt from the graph). ``(body, replacements)``; the body is returned as given
    when the page pins none."""
    rows = corrections(frontmatter)
    if not rows or not body:
        return body, 0
    prose, rest = split_prose(body)
    rebuilt = sorted((h for h in headings(prose) if h.level == 2 and h.title in REBUILT_SECTIONS),
                     key=lambda h: h.start)
    parts: list[str] = []
    n = at = 0
    for h in rebuilt:   # every rebuilt section is kept as its writer left it; the prose between them is corrected
        if h.start < at:
            continue
        fixed, k = correct_text(prose[at:h.start], rows)
        parts += [fixed, prose[h.start:h.end]]
        n, at = n + k, h.end
    fixed, k = correct_text(prose[at:], rows)
    parts.append(fixed)
    n += k
    return ("".join(parts) + rest, n) if n else (body, 0)


def apply_corrections_to_sections(frontmatter: dict, sections: dict[str, str]) -> dict[str, str]:
    """The same, for a writer that holds ``{title: content}`` before rendering (Stage 3)."""
    rows = corrections(frontmatter)
    if not rows:
        return sections
    return {title: (content if title in REBUILT_SECTIONS or not isinstance(content, str)
                    else correct_text(content, rows)[0])
            for title, content in sections.items()}


def correct_article(frontmatter: dict, article: dict | None) -> dict | None:
    """The article writer's payload (``entity_article.payload``) with the page's pinned corrections applied to its lead,
    its paragraphs, the paragraphs' provenance records and the sentences it retains — before Stage 5 composes it, so each
    paragraph keeps its evidence under its corrected text instead of losing it to a fix applied after."""
    rows = corrections(frontmatter)
    if not rows or not article:
        return article
    fix = lambda text: correct_text(text, rows)[0] if isinstance(text, str) else text  # noqa: E731
    out = dict(article)
    out["lead"] = fix(article.get("lead"))
    out["markdown"] = fix(article.get("markdown"))
    out["records"] = [{**r, "text": fix(r.get("text"))} for r in article.get("records") or []]
    out["retain"] = [fix(t) for t in article.get("retain") or []]
    return out


def removed_aliases(frontmatter: dict) -> set[str]:
    """The aliases removed by an edit (casefolded; accents kept — ``é`` is not ``e``)."""
    raw = (frontmatter or {}).get(ALIASES_REMOVED)
    out: set[str] = set()
    for row in raw if isinstance(raw, list) else []:
        name = row.get("alias") if isinstance(row, dict) else row
        if isinstance(name, str) and name.strip():
            out.add(" ".join(name.split()).casefold())
    return out


def keep_aliases(frontmatter: dict, aliases) -> list[str]:
    """``aliases`` an automatic writer is about to add, without the ones an edit removed."""
    gone = removed_aliases(frontmatter)
    return [a for a in aliases or [] if not (isinstance(a, str) and " ".join(a.split()).casefold() in gone)]


def carry_marks(winner_fm: dict, loser_fm: dict) -> None:
    """A page merge keeps both pages' pinned corrections and removed aliases, and drops a removed alias the merge
    unioned back in."""
    rows = corrections(winner_fm)
    seen = {r["old"] for r in rows}
    for row in corrections(loser_fm):
        if row["old"] not in seen:
            rows.append(row)
            seen.add(row["old"])
    if rows:
        winner_fm[CORRECTIONS] = rows[-MAX_CORRECTIONS:]
    removed = list(winner_fm.get(ALIASES_REMOVED) or []) if isinstance(winner_fm.get(ALIASES_REMOVED), list) else []
    have = removed_aliases(winner_fm)
    for row in loser_fm.get(ALIASES_REMOVED) or [] if isinstance(loser_fm.get(ALIASES_REMOVED), list) else []:
        name = row.get("alias") if isinstance(row, dict) else row
        if isinstance(name, str) and name.casefold() not in have:
            removed.append(row)
            have.add(name.casefold())
    if removed:
        winner_fm[ALIASES_REMOVED] = removed[-MAX_ALIASES_REMOVED:]
    if isinstance(winner_fm.get("aliases"), list):
        winner_fm["aliases"] = keep_aliases(winner_fm, winner_fm["aliases"])
        if not winner_fm["aliases"]:
            winner_fm.pop("aliases")


# --------------------------------------------------------------------------- the plan


@dataclass
class Outcome:
    frontmatter: dict
    body: str
    changes: list[str]
    sections: list[str]
    pinned: int = 0


def plan(frontmatter: dict, body: str, request: Request, *, author: str, day: str | None = None) -> Outcome:
    """The page after ``request``: pure, writes nothing. ``body`` is the page file's own (``parse(ledger=False)``),
    so its fence is exactly what is on disk and comes back untouched. Raises :class:`EditError`."""
    day = day or date.today().isoformat()
    fm = dict(frontmatter or {})
    original = body or ""
    if (request.edits or request.section is not None) and claims.fence_state(original) == claims.FENCE_UNREADABLE:
        # An unclosed or repeated fence has no safe "before the claims": an edit could land inside one.
        raise EditError("this page's claims block can't be read, so its words can't be edited safely. Its aliases "
                        "can still be changed.")
    prose, rest = split_prose(original)
    changes: list[str] = []
    touched: list[str] = []
    rewrote_machine = False

    for i, edit in enumerate(request.edits, 1):
        old, new = edit["old"], edit["new"]
        hits = _occurrences(prose, old)
        if not hits:
            where = " (it is in the claims, which this tool never edits — use the claim tools)" if old in rest else ""
            raise EditError(f"Edit {i}: those exact words are not on the page{where}. Copy them from "
                            "cicada_recall_detail, character for character.")
        if len(hits) > 1 and not edit["all"]:
            raise EditError(f"Edit {i}: those words are on the page {len(hits)} times. Give more of the "
                            "surrounding words, or set `all` to change every one.")
        marks = headings(prose)
        for at in hits:
            title = section_at(prose, at, marks)
            if title in REBUILT_SECTIONS:
                raise EditError(f"Edit {i}: {_rebuilt_why(title)}")
            if title not in touched:
                touched.append(title)
        if _is_link(old):
            prose = _pattern(old).sub(lambda _m: new, prose, count=0 if edit["all"] else 1)
        else:
            prose = prose.replace(old, new) if edit["all"] else prose.replace(old, new, 1)
        n = len(hits) if edit["all"] else 1
        changes.append(f"replaced {n} passage{'s' if n != 1 else ''}" + (" (pinned)" if edit["pin"] else ""))

    if request.section is not None:
        heading, owner_section = _find_section(prose, request.section)
        if heading.title in REBUILT_SECTIONS:
            raise EditError(_rebuilt_why(heading.title))
        before, after = prose[:heading.content], prose[heading.end:]
        if not before.endswith("\n"):
            before += "\n"
        text = request.text or ""
        if after.strip():
            prose = before + ((text + "\n\n") if text else "\n") + after.lstrip("\n")
        else:
            prose = before + ((text + "\n") if text else "")
        name = heading.title if heading.level == 2 else f"{owner_section} › {heading.title}"
        if name not in touched:
            touched.append(name)
        if heading.level == 3 or heading.title in MACHINE_SECTIONS:
            rewrote_machine = True
        changes.append(f"rewrote the {name} section")

    new_body = original
    if prose != split_prose(original)[0]:
        # The fence starts on its own line after a blank one, as every writer leaves it; it and all after it are
        # the page's own bytes.
        new_body = prose.rstrip() + "\n\n" + rest if rest else prose.strip()
        # G198 review B2: the request was checked, now the result — words that only together make a claims opener,
        # a code fence or a heading ("``" + "`claims"; "Summary" → "Overview" with `all`) move the page's frame.
        if shape(new_body) != shape(original) or claims.fence_state(new_body) != claims.fence_state(original):
            raise EditError("that change would alter the page's sections or its claims block (a heading, a code "
                            "fence or a claims opener). Edit the words inside a section only.")
    elif request.edits or request.section is not None:
        raise EditError("That leaves the page's words as they are.")

    # Aliases.
    aliases = [a for a in (fm.get("aliases") or []) if isinstance(a, str)] if isinstance(fm.get("aliases"), list) else []
    removed_rows = list(fm.get(ALIASES_REMOVED) or []) if isinstance(fm.get(ALIASES_REMOVED), list) else []
    page_name = str(fm.get("name") or "").strip()
    for alias in request.remove_aliases:
        match = [a for a in aliases if " ".join(a.split()).casefold() == alias.casefold()]
        if not match:
            listed = ", ".join(aliases) if aliases else "none"
            raise EditError(f"'{alias}' is not one of this page's aliases (they are: {listed}). An alias is "
                            "matched exactly, accents included.")
        aliases = [a for a in aliases if a not in match]
        removed_rows = [r for r in removed_rows
                        if " ".join(str(r.get("alias") if isinstance(r, dict) else r).split()).casefold()
                        != alias.casefold()]
        removed_rows.append({"alias": match[0], "by": author, "on": day})
        changes.append(f"removed the alias '{match[0]}'")
    for alias in request.add_aliases:
        if page_name and alias.casefold() == page_name.casefold():
            raise EditError(f"'{alias}' is the page's own name, not another one.")
        if alias_policy.is_reference(alias):
            raise EditError(f"'{alias}' reads as a reference ('the …'), not a name the thing goes by.")
        if alias.casefold() in {" ".join(a.split()).casefold() for a in aliases}:
            raise EditError(f"'{alias}' is already an alias of this page.")
        aliases.append(alias)
        removed_rows = [r for r in removed_rows
                        if " ".join(str(r.get("alias") if isinstance(r, dict) else r).split()).casefold()
                        != alias.casefold()]
        changes.append(f"added the alias '{alias}'")
    if request.add_aliases or request.remove_aliases:
        if aliases:
            fm["aliases"] = aliases
        else:
            fm.pop("aliases", None)
        if removed_rows:
            fm[ALIASES_REMOVED] = removed_rows[-MAX_ALIASES_REMOVED:]
        else:
            fm.pop(ALIASES_REMOVED, None)
        touched.append("aliases")

    # Ruling 45 (Q5): a project's name and the person's description — the header Sleep never rewrites.
    if request.name is not None or request.description is not None:
        from api.services import project_ownership

        if not project_ownership.is_project_like(fm):
            raise EditError("`name` and `description` change a project's header; this page is not a project.")
        header = project_ownership.apply_header(fm, name=request.name, desc=request.description, by=author, day=day)
        if not header and not changes:
            raise EditError("That leaves the project's name and description as they are.")
        changes += header
        touched.append("header")

    # Pinned corrections: kept on the page so Sleep's next rewrite writes the fix, never the old words.
    pinned = 0
    rows = corrections(fm)
    for edit in request.edits:
        new_rows = [r for r in rows if r["old"] not in (edit["old"], edit["new"])]
        if edit["pin"]:
            new_rows.append({"old": edit["old"], "new": edit["new"], "by": author, "on": day})
            pinned += 1
        rows = new_rows
    if request.edits:
        if rows:
            fm[CORRECTIONS] = rows[-MAX_CORRECTIONS:]
        else:
            fm.pop(CORRECTIONS, None)

    if new_body != original:
        if rewrote_machine:
            # The lead or the Article, rewritten whole: the editor's from now on, like a person's edit of them.
            fm["human_edited"] = True
        else:
            # A word-level fix keeps a machine article the writer's (it restamps only a stamp that held).
            entity_article.carry_stamp(fm, original, new_body)
        # An edited item's evidence rows go (its exact-text guard no longer matches); the rest stay.
        section_provenance.refresh(fm, original, new_body, {})
    return Outcome(fm, new_body, changes, [t or "(lead)" for t in touched], pinned)


def read(page: Path):
    """The page as this tool edits it: the file's own body, its ledger never opened (``ledger=False``)."""
    return markdown_parser.parse(page, ledger=False)


def write(page: Path, outcome: Outcome) -> None:
    """The page written atomically. A body read without the ledger leaves every ledger line where it is
    (``claims_ledger``): the fence is the page's own, byte for byte."""
    markdown_parser.write(page, outcome.frontmatter, outcome.body)


# --------------------------------------------------------------------------- the commit


def evidence_lines(spans) -> list[str]:
    """``Evidence: <episode> <start>-<end> <kind> <hash>`` per located span — offsets, never the words (G118)."""
    out = []
    for ev in spans or []:
        row = ev.to_dict() if hasattr(ev, "to_dict") else dict(ev)
        if row.get("kind") == "reasoning" or int(row.get("start", -1)) < 0:
            continue
        out.append(f"{EVIDENCE_PREFIX}{row['episode']} {row['start']}-{row['end']} {row['kind']} {row.get('hash', '')}"
                   .rstrip())
    return out


def commit_lines(rel: str, trigger: str, reason: str, spans=None, *, accepted: bool = False,
                 extra: list[str] | None = None) -> list[str]:
    """The commit body: the manifest line(s), then the reason (its own paragraph) and the cited spans."""
    lines = [f"{rel}: edited (trigger: {trigger})", *(extra or []), "", f"{REASON_PREFIX}{reason}"]
    if accepted:
        lines.append(ACCEPTED_LINE)
    lines += evidence_lines(spans)
    return lines


def parse_reason(body: str) -> str | None:
    for line in (body or "").splitlines():
        if line.startswith(REASON_PREFIX):
            return line[len(REASON_PREFIX):].strip() or None
    return None


# --------------------------------------------------------------------------- proposals


def preview(name: str, request: Request, reason: str) -> str:
    """What the inbox card shows: why, then each change in plain words."""
    lines = [f"Why: {reason}", ""]
    for edit in request.edits:
        every = " (every time it appears)" if edit["all"] else ""
        lines.append(f"- Replace “{edit['old']}” with “{edit['new']}”{every}" if edit["new"]
                     else f"- Delete “{edit['old']}”{every}")
    if request.section is not None:
        lines.append(f"- Rewrite the {request.section} section as:")
        lines += [f"  > {line}" if line else "  >" for line in (request.text or "").splitlines()]
    lines += [f"- Add the alias “{a}”" for a in request.add_aliases]
    lines += [f"- Remove the alias “{a}”" for a in request.remove_aliases]
    if request.name is not None:
        lines.append(f"- Rename it “{request.name}” (the old name stays findable)")
    if request.description is not None:
        lines.append(f"- Set its description to “{request.description}”" if request.description
                     else "- Clear its description")
    return "\n".join(lines)


def write_proposal(memory_path: Path, *, entity_id: str, name: str, request: Request, reason: str, author: str,
                   session: str | None, spans=None, day: str | None = None) -> str:
    """One ``page_edit`` inbox item; returns its bank-relative path. Never replaces an item (``write_new``)."""
    from api.services import inbox_service

    inbox_dir = Path(memory_path) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    day = day or date.today().isoformat()
    fm = {
        "kind": KIND, "required_input": "choice", "status": "pending", "priority": 0.5,
        "entity_id": entity_id, "entity_name": name, "title": f"Change {name}?",
        "created_date": day,
        "question": f"An agent suggests a change to {name}: {reason}",
        # Leave first is not a recommendation: Cicada proposes nothing here, the agent did.
        "options": [{"key": "apply", "label": "Apply the change"},
                    {"key": "dismiss", "label": "Leave the page as it is"}],
        "allow_other": False, "allow_defer": True,
        "proposed_by": author, "reason": reason, "edit": request.to_dict(),
        "trigger": f"mcp/{author}",
    }
    if session:
        fm["session_id"] = session
    rows = [ev.to_dict() if hasattr(ev, "to_dict") else dict(ev) for ev in spans or []]
    rows = [r for r in rows if r.get("kind") != "reasoning"]
    if rows:
        fm["evidence"] = rows
        fm["source_episode"] = rows[0]["episode"]
    body = preview(name, request, reason)
    for _ in range(50):
        path = inbox_dir / f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}.md"
        try:
            markdown_parser.write_new(path, fm, body)
        except FileExistsError:
            continue
        return f"inbox/{path.name}"
    raise EditError("Could not file the proposal: the inbox is busy. Try again.")

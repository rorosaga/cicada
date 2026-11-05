"""Repositories on the graph (G230): the one writer of a repository's page, its README preview, and the links between
a project and its repositories.

**What a repository is in the closed set of 10.** A repository Cicada learns of from GitHub — one the person owns, or
one they starred — is a ``media`` page (``media.kind: repository``), born here and never by a model (Stage 1 never
produces ``media``), quiet until the person mentions it (``quiet_pages``), like a bookmark. It is not a ``tool`` (that
page is the thing a conversation says the person uses, made by Sleep from their words) and not a ``project`` (ruling
36 D4 / 45: only a repository the hook observed, the person's own words, or the person's act make one) — a project is
the work, and a project may span several repositories. **Every repository the person owns gets its page on sync**
(owner 2026-11-03: "there shouldn't be added manually, always sync and make their initial markdowns, and develop them
if needed"), with a first markdown — its description, a summary of its README, its link, language and topics
(:func:`initial_body`) — that Sleep develops from what conversations say, like any page. Nothing is added by hand.

**A project lists its repositories** (owner 2026-11-03: "a project might reference several repos so take that into
account") in ``repositories:`` — ``[{entity, url, how, by, day, session?}]``, this module its one writer — and each
repository page names its projects back (``github.projects``, re-derived from every project on each write). A link is
made by :func:`link` on the person's act or a trusted agent's (``how: user|agent``), or by Cicada when the hook's D2a
salted origin hash of the project's own checkout is this repository's (``how: origin``, :func:`link_by_origin`) —
never by a name alone, which stays a suggestion (:func:`project_match`, ``how: name``). The person's unlink is
remembered (``repositories_removed``) and no automatic link puts it back. ``repos:`` stays what it was: the person's
local checkouts (``path``/``device``), which the app runs git in.

**The page** carries the usual media frontmatter plus one ``github:`` block this module alone writes —
``{id, full_name, owner, owner_kind, description, language, topics, private, archived, fork, default_branch,
starred, starred_at, unstarred_on, added, owned, projects}`` — and one trusted ``website`` source: the repository's own
GitHub URL, the person's (they own it, starred it, or added it before adds were retired). Its picture is the media preview rung (``entity_picture`` 4): ``media.
thumbnail`` is the owner's avatar ONLY when an organisation owns the repository (owner 2026-10-28, E) — a personal
account's avatar is never asked — fetched and kept by ``media_preview`` on the ToS rail. A later sync rewrites the
block in place when GitHub's record changed and leaves the page alone when it did not; a repository no longer starred
keeps its page with ``starred: false`` and the day it was seen gone. Nothing here deletes a page or an episode.

**The README preview** is read through the official API (``GET /repos/{full_name}/readme``, the person's token when
connected, none for a public repository) when a sync makes one of the person's own repositories its page, and when the
person opens a repository's page; it is kept
outside every bank at ``$CICADA_HOME/readmes/<bank>/<entity id>.json`` — like a media preview, a cache of the outside
world: rebuilt, never an error, read again when a week old, gone with Disconnect. The preview is text only: HTML, images and badges are dropped, at
most :data:`PREVIEW_CHARS` kept; the app never loads a picture or a link the README names.

**Matching a project** (:func:`project_match`, derived on read): a project whose ``repositories:`` (or, from before
the list, a trusted ``repo`` source) names this repository is it (``linked``); one whose own checkout's origin the hook
hashed (D2a: ``born.repo.remote``, its current remote) to the hash of this URL with this install's salt is the same
repository (``origin``) — the salt is read, never made, and nothing is stored but the link; a project page with the
repository's exact name is a suggestion (``name``) the person confirms in one click (:func:`link`).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from api.services import bank_index, markdown_parser, page_lock, source_names

KIND = "repository"
GITHUB_KEY = "github"
SITE = "github.com"
WEBSITE = "website"
REPO_PREDICATE = "repo"
#: On the repository's own source: GitHub's record behind this link is kept by the GitHub sync (and a page's open),
#: so Cicada's own fetcher never visits the github.com page for it (``source_refresh.checker``).
KEPT_BY = "kept_by"
KEPT_BY_GITHUB = "github"
#: A page the person added by its link before adds were retired (owner 2026-11-03): read, never written any more.
ADDED_ORIGIN = "github-added"
#: A project's repositories (this module its one writer), the ones the person unlinked, and the back-link key in a
#: repository page's ``github:`` block.
REPOS_KEY = "repositories"
REPOS_REMOVED_KEY = "repositories_removed"
PROJECTS_KEY = "projects"
#: How a link was made: the person's act, a trusted agent's, or the hook's D2a origin hash (Cicada's own).
HOW_USER, HOW_AGENT, HOW_ORIGIN = "user", "agent", "origin"
#: The author Cicada's own links commit under.
CICADA = "cicada"
#: The first summary taken from a README, at most.
SUMMARY_CHARS = 500
#: Projects a repository card offers to link to, and repositories a project offers, at most.
MAX_CANDIDATES = 50
README_DIR = "readmes"
PREVIEW_CHARS = 6000
README_MAX_BYTES = 400_000
_AVATAR_HOST = "avatars.githubusercontent.com"
_HTML_TAG = re.compile(r"<[^>]{0,2000}>")
_IMAGE = re.compile(r"!\[[^\]]{0,500}\]\([^)]{0,2000}\)")
_LINK = re.compile(r"\[([^\]]{0,500})\]\([^)]{0,2000}\)")
_REF_LINE = re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", re.MULTILINE)
_BLANKS = re.compile(r"\n{3,}")
#: The block's fields GitHub's record gives (``relation`` keys are this module's own). Never the star count or the
#: last push: both move every day on an active repository, and a page rewritten on every sync is a commit of noise.
_RECORD_KEYS = ("id", "full_name", "owner", "owner_kind", "description", "language", "topics", "private",
                "archived", "fork", "default_branch")
#: How long a kept README preview is fresh before the page's next open reads it again.
README_TTL = timedelta(days=7)


def _text(value, cap: int = 500) -> str:
    return " ".join(str(value or "").split())[:cap]


@dataclass
class Repo:
    """One repository as GitHub's REST record states it — nothing derived, nothing guessed."""

    id: int
    full_name: str
    name: str
    owner: str
    owner_kind: str
    url: str
    description: str = ""
    language: str | None = None
    topics: list[str] = field(default_factory=list)
    stars: int = 0
    private: bool = False
    archived: bool = False
    fork: bool = False
    default_branch: str | None = None
    pushed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    owner_avatar: str | None = None

    @classmethod
    def from_api(cls, raw) -> "Repo | None":
        """A repository record, or ``None`` when it is not one this module trusts (its ``html_url`` must be its own
        ``https://github.com/<full_name>`` — no other host ever becomes a page's link)."""
        from api.services.connectors import github

        if not isinstance(raw, dict):
            return None
        full = str(raw.get("full_name") or "")
        if github.parse_repo(full) != full or not isinstance(raw.get("id"), int):
            return None
        url = str(raw.get("html_url") or "")
        if url.rstrip("/").lower() != github.repo_url(full).lower():
            return None
        owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
        avatar = str(owner.get("avatar_url") or "")
        try:
            avatar_ok = urlparse(avatar).scheme == "https" and (urlparse(avatar).hostname or "") == _AVATAR_HOST
        except ValueError:
            avatar_ok = False
        topics = [_text(t, 50) for t in raw.get("topics") or [] if isinstance(t, str) and t.strip()][:20]
        return cls(
            id=int(raw["id"]), full_name=full, name=full.split("/", 1)[1], owner=full.split("/", 1)[0],
            owner_kind="Organization" if owner.get("type") == "Organization" else "User",
            url=github.repo_url(full), description=_text(raw.get("description")),
            language=_text(raw.get("language"), 40) or None, topics=topics,
            stars=int(raw.get("stargazers_count") or 0) if str(raw.get("stargazers_count") or "0").isdigit() else 0,
            private=bool(raw.get("private")), archived=bool(raw.get("archived")), fork=bool(raw.get("fork")),
            default_branch=_text(raw.get("default_branch"), 100) or None,
            pushed_at=_stamp(raw.get("pushed_at")), created_at=_stamp(raw.get("created_at")),
            updated_at=_stamp(raw.get("updated_at")), owner_avatar=avatar if avatar_ok else None)

    @classmethod
    def from_block(cls, block: dict | None) -> "Repo | None":
        """A repository from a GitHub block a sync wrote (no network) — the same trust checks as the API's record."""
        if not isinstance(block, dict):
            return None
        from api.services.connectors import github

        full = str(block.get("full_name") or "")
        return cls.from_api({**block, "html_url": github.repo_url(full),
                             "owner": {"type": block.get("owner_kind")}, "topics": block.get("topics") or []})

    def record(self) -> dict:
        return {"id": self.id, "full_name": self.full_name, "owner": self.owner, "owner_kind": self.owner_kind,
                "description": self.description or None, "language": self.language, "topics": list(self.topics),
                "private": self.private, "archived": self.archived, "fork": self.fork,
                "default_branch": self.default_branch}

    def block(self, relation: str | None = None) -> dict:
        out = {k: v for k, v in self.record().items() if v not in (None, [], "")}
        if relation == "owned":
            out["owned"] = True
        return out

    @property
    def picture(self) -> str | None:
        """The page's preview source: the owner's avatar only when an organisation owns the repository."""
        if self.owner_kind != "Organization" or not self.owner_avatar:
            return None
        return self.owner_avatar + ("&" if "?" in self.owner_avatar else "?") + "s=256"


def _stamp(value) -> str | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(timezone.utc).isoformat() if at.tzinfo else None


def login_key(login: str) -> str:
    """The connected account, as the cursor keeps it: a hash, never the login."""
    return hashlib.sha256((login or "").lower().encode()).hexdigest()[:16]


# --- the page ------------------------------------------------------------------------------------------------------


def is_repository_page(fm: dict | None) -> bool:
    fm = fm or {}
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    return str(fm.get("type") or "") == "media" and media.get("kind") == KIND


def _pages_by_id(memory_path: Path) -> dict[int, str]:
    """Every page carrying a GitHub block, by the repository's numeric id (a renamed repository keeps its page)."""
    out: dict[int, str] = {}
    for f in bank_index.files(Path(memory_path), "entities"):
        block = (f.frontmatter or {}).get(GITHUB_KEY)
        if isinstance(block, dict) and isinstance(block.get("id"), int) and is_repository_page(f.frontmatter):
            out.setdefault(block["id"], f.stem)
    return out


def _source(fm: dict, url: str, predicate: str, today: str) -> bool:
    """The repository's own URL as a trusted source of ``predicate`` on the page — the person's: they starred it,
    pasted it or linked it. A source the person removed is never put back (``sources_removed``)."""
    from api.services import fact_sources

    if fact_sources.find_tombstone(fm, url, predicate) is not None:
        return False
    sources = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    if any(str(s.get("ref") or "").rstrip("/").lower() == url.lower()
           and fact_sources.same_predicate(s.get("predicate"), predicate) for s in sources):
        return False
    fm["sources"] = [*sources, {"ref": url, "kind": fact_sources.KIND_URL, "predicate": predicate,
                                "added_by": fact_sources.USER, "added_at": today, KEPT_BY: KEPT_BY_GITHUB}]
    return True


def _merge_block(fm: dict, repo: Repo, *, starred: bool | None = None, starred_at: str | None = None,
                 added: bool = False, owned: bool | None = None) -> bool:
    """Rewrite the page's GitHub block from ``repo``'s record; the relation keys change only when given. ``True``
    when anything changed (an unchanged record writes nothing, so a re-sync makes no commit)."""
    old = fm.get(GITHUB_KEY) if isinstance(fm.get(GITHUB_KEY), dict) else {}
    new = {k: v for k, v in old.items() if k not in _RECORD_KEYS}
    new.update(repo.block())
    if starred is not None:
        new["starred"] = starred
        if starred:
            new.pop("unstarred_on", None)
            if starred_at:
                new["starred_at"] = starred_at
        elif old.get("starred"):
            new["unstarred_on"] = date.today().isoformat()
    if added:
        new["added"] = True
    if owned is not None:
        new["owned"] = owned
    changed = new != old
    fm[GITHUB_KEY] = new
    media = fm.get("media") if isinstance(fm.get("media"), dict) else None
    if media is not None and is_repository_page(fm):
        if media.get("thumbnail") != repo.picture:
            media["thumbnail"] = repo.picture
            changed = True
    return changed


def _new_page(memory_path: Path, repo: Repo, idx: dict, *, origin: str, starred_at: str | None) -> tuple[str, str]:
    """A repository's page and its save episode, through ``media_ingestor``'s own write path (the url index, the
    episode's id rule, the scrub) with the record GitHub gave — the github.com page itself is never fetched."""
    from api.services import media_ingestor, saved_at

    instant = saved_at.validate_instant(starred_at) if starred_at else None
    item = media_ingestor.RawItem(url=repo.url, title=repo.full_name, origin=origin,
                                  added=instant[:10] if instant else None, added_at=instant)
    meta = media_ingestor.MediaMeta(title=repo.full_name, description=repo.description, site=SITE,
                                    thumbnail=repo.picture, media_type=KIND)
    result = media_ingestor.write_prepared(media_ingestor.PreparedItem(item, meta), memory_path, idx)
    return result.media_entity_id, result.episode_id


def _known_entity(memory_path: Path, repo: Repo, idx: dict, known: dict[int, str]) -> str | None:
    """The page id the record already names for ``repo`` — by GitHub's id, else the saved link — whether or not the
    page is still there."""
    from api.services import media_ingestor

    entity_id = known.get(repo.id)
    if entity_id is None:
        hit = idx.get(media_ingestor.url_hash(repo.url)) or {}
        hit = idx.get(hit.get("alias_of"), hit) if hit.get("alias_of") else hit
        entity_id = str(hit.get("media_entity_id") or "") or None
    return entity_id


def pages_to_make(memory_path: Path, repos: list[Repo]) -> list[Repo]:
    """The repositories a sync would make a NEW page for: none on the record yet. One whose page exists is updated in
    place (its words are kept), and one whose page the person merged or removed is never made again — so a README is
    read only for a page about to be born. Reads only."""
    from api.services import media_ingestor

    known = _pages_by_id(Path(memory_path))
    idx = media_ingestor.load_url_index(Path(memory_path))
    return [r for r in repos if _known_entity(memory_path, r, idx, known) is None]


def readme_summary(markdown: str | None) -> str:
    """A README's first paragraph of prose, as words (:func:`preview_text`): no heading, badge, table, quote, list or
    fenced code, at least 40 letters, at most :data:`SUMMARY_CHARS` (cut at a sentence when one ends in the second
    half). ``""`` when there is none. Pure."""
    if not markdown:
        return ""
    text = re.sub(r"```.*?```|~~~.*?~~~", "", markdown.replace("\r\n", "\n"), flags=re.DOTALL)
    words, _ = preview_text(text)
    for block in re.split(r"\n\s*\n", words):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines or any(ln.startswith(("#", "|", ">", "- ", "* ", "+ ", "    ")) for ln in lines):
            continue
        para = " ".join(lines)
        if sum(ch.isalpha() for ch in para) < 40:
            continue
        para = para.replace("**", "").replace("`", "")
        if len(para) <= SUMMARY_CHARS:
            return para
        cut = para[:SUMMARY_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        return cut[: end + 1] if end >= SUMMARY_CHARS // 2 else cut[: cut.rfind(" ")].rstrip(",;:") + "…"
    return ""


def initial_body(repo: Repo, readme: str | None = None) -> str:
    """The first markdown of one of the person's own repositories: what it is (its description, else its name), a
    summary of its README, then its link, language and topics. Written once, when the page is born; after that the
    page is Sleep's and the person's to develop, and a sync rewrites only the ``github:`` block."""
    from api.services import episode_scrub

    lead = repo.description or f"{repo.full_name}, one of your repositories on GitHub."
    lines = ["## Summary", lead]
    summary, _ = episode_scrub.scrub(readme_summary(readme)) if readme else ("", 0)
    if summary and summary.strip() != repo.description.strip():
        lines += ["", summary]
    lines += ["", "## Repository", f"- [{repo.full_name}]({repo.url})"]
    if repo.language:
        lines.append(f"- Language: {repo.language}")
    if repo.topics:
        lines.append("- Topics: " + ", ".join(repo.topics))
    flags = [w for w, on in (("private", repo.private), ("archived", repo.archived), ("a fork", repo.fork)) if on]
    if flags:
        lines.append("- " + ", ".join(flags).capitalize())
    return "\n".join(lines)


def upsert(memory_path: Path, repo: Repo, idx: dict, *, origin: str, starred: bool | None = None,
           starred_at: str | None = None, added: bool = False, owned: bool | None = None,
           known: dict[int, str] | None = None, remake: bool = False,
           body: str | None = None) -> tuple[str, str, list[str]]:
    """Make or update ``repo``'s page: ``(entity id, "created"|"updated"|"same", paths written)``. The caller holds
    the bank's admission and page lock and saves ``idx``. ``body`` is a new page's first markdown (an existing page's
    words are never touched).

    A link row whose page is gone is one of two things. The person merged the page into another
    (``page_redirects``): that page is the repository's now — updated when it is a ``media`` page, left alone when it
    is any other kind (a ``tool`` the person folded it into). Or the page went with no redirect: only the person's own
    add (``remake``) makes it again; a sync never brings back a page the person removed."""
    from api.services import media_ingestor, page_redirects

    memory_path = Path(memory_path)
    known = _pages_by_id(memory_path) if known is None else known
    entity_id = _known_entity(memory_path, repo, idx, known)
    paths: list[str] = []
    status = "same"
    page = memory_path / "entities" / f"{entity_id}.md" if entity_id else None
    if page is not None and not page.exists():
        moved = page_redirects.resolve(memory_path, entity_id)
        if moved:
            entity_id, page = moved, memory_path / "entities" / f"{moved}.md"
        elif not remake:
            return entity_id, "same", paths
        else:
            # The save path would answer "already saved" with no page behind it: the stale row goes first.
            idx.pop(media_ingestor.url_hash(repo.url), None)
            page = None
    if page is None:
        entity_id, episode_id = _new_page(memory_path, repo, idx, origin=origin, starred_at=starred_at)
        page = memory_path / "entities" / f"{entity_id}.md"
        paths += [f"episodes/{episode_id}.md", "sources/url_index.json"]
        status = "created"
        known[repo.id] = entity_id
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    if str(fm.get("type") or "") != "media":
        # The link is already saved as another kind of page (a paper's alias, say): that page is left as it is.
        return entity_id, "same", paths
    # A saved github.com link (a bookmark of it) becomes the repository's page: the same page, now with its record.
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    before = dict(media)
    media["kind"] = KIND
    media["media_type"] = KIND
    fm["media"] = media
    changed = before != media
    was = (fm.get(GITHUB_KEY) or {}).get("full_name") if isinstance(fm.get(GITHUB_KEY), dict) else None
    changed |= _merge_block(fm, repo, starred=starred, starred_at=starred_at, added=added, owned=owned)
    if status != "created":
        # ROR-122: GitHub's id found the page across a rename; its name follows the repository's newest one.
        changed |= source_names.apply(fm, "github", repo.full_name, day=date.today().isoformat(), was=was,
                                      door_was=was) not in (source_names.SAME,)
    else:
        source_names.wrote(fm, "github", repo.full_name, date.today().isoformat())
    changed |= _source(fm, repo.url, WEBSITE, date.today().isoformat())
    if changed or status == "created":
        markdown_parser.write(page, fm, body if status == "created" and body else parsed.body)
        paths.append(f"entities/{entity_id}.md")
        status = status if status == "created" else "updated"
    return entity_id, status, paths


def apply_stars(memory_path: Path, stars: list[tuple[Repo, str | None]], *, login: str = "",
                complete: bool = True) -> dict:
    """A sync's starred list onto the graph (run inside the sync's admitted transaction, ``tier2.Batch.after``): a
    page per starred repository, made or updated in place; with the whole list read (``complete``), a page whose
    repository is no longer starred is marked so and kept. Returns ``{paths, created, updated, live, unstarred}``."""
    from api.services import media_ingestor
    from api.services.connectors import github

    memory_path = Path(memory_path)
    out = {"paths": [], "created": 0, "updated": 0, "live": len(stars), "unstarred": 0}
    with page_lock.page_lock(memory_path):
        idx = media_ingestor.load_url_index(memory_path)
        known = _pages_by_id(memory_path)
        seen: set[int] = set()
        for repo, starred_at in stars:
            seen.add(repo.id)
            owned = repo.owner.lower() == login.lower() if login else None
            try:
                _, status, paths = upsert(memory_path, repo, idx, origin=github.ORIGIN_STARRED, starred=True,
                                          starred_at=_stamp(starred_at), owned=owned, known=known)
            except Exception as exc:  # noqa: BLE001 — one repository never stops the rest; the class only
                logger.warning(f"github: a starred repository was not written ({type(exc).__name__})")
                continue
            out["paths"] += paths
            out[status] = out.get(status, 0) + 1
        if complete:
            for repo_id, entity_id in known.items():
                if repo_id in seen:
                    continue
                page = memory_path / "entities" / f"{entity_id}.md"
                parsed = markdown_parser.parse(page)
                block = parsed.frontmatter.get(GITHUB_KEY) or {}
                if not block.get("starred"):
                    continue
                block = {**block, "starred": False, "unstarred_on": date.today().isoformat()}
                parsed.frontmatter[GITHUB_KEY] = block
                markdown_parser.write(page, parsed.frontmatter, parsed.body)
                out["paths"].append(f"entities/{entity_id}.md")
                out["unstarred"] += 1
        media_ingestor.save_url_index(memory_path, idx)
    bank_index.invalidate(memory_path)
    out["paths"] = list(dict.fromkeys(out["paths"]))
    out.pop("same", None)
    if out["unstarred"]:
        n = out["unstarred"]
        out["words"] = (f"{n} {'repository is' if n == 1 else 'repositories are'} no longer starred on GitHub; "
                        f"{'its page stays' if n == 1 else 'their pages stay'}.")
    return out


def apply_owned(memory_path: Path, repos: list[Repo], *, readmes: dict[int, str] | None = None) -> dict:
    """A sync's list of the person's own repositories onto the graph (inside the sync's admitted transaction,
    ``tier2.Batch.after``): a page for each — made with its first markdown (:func:`initial_body`, the README read for
    it beside the sync and kept outside the bank as its preview too), or its ``github:`` block updated in place. A page
    the person merged follows its redirect; one they removed is never made again. Returns ``{paths, created,
    updated}``."""
    from api.services import media_ingestor
    from api.services.connectors import github

    memory_path = Path(memory_path)
    readmes = readmes or {}
    out = {"paths": [], "created": 0, "updated": 0}
    born: list[tuple[str, str]] = []
    with page_lock.page_lock(memory_path):
        idx = media_ingestor.load_url_index(memory_path)
        known = _pages_by_id(memory_path)
        for repo in repos:
            try:
                entity_id, status, paths = upsert(memory_path, repo, idx, origin=github.ORIGIN_OWNED, owned=True,
                                                  known=known, body=initial_body(repo, readmes.get(repo.id)))
            except Exception as exc:  # noqa: BLE001 — one repository never stops the rest; the class only
                logger.warning(f"github: one of your repositories was not written ({type(exc).__name__})")
                continue
            out["paths"] += paths
            if status in ("created", "updated"):
                out[status] += 1
            if status == "created" and repo.id in readmes:
                born.append((entity_id, readmes[repo.id]))
        media_ingestor.save_url_index(memory_path, idx)
    bank_index.invalidate(memory_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for entity_id, markdown in born:
        text, truncated = preview_text(markdown)
        _write_readme(memory_path.name, entity_id, {"text": text, "truncated": truncated, "path": "README",
                                                    "fetched_at": now})
    out["paths"] = list(dict.fromkeys(out["paths"]))
    if out["created"]:
        n = out["created"]
        out["words"] = f"{n} of your repositor{'y' if n == 1 else 'ies'} got {'its' if n == 1 else 'their'} page."
    return out


# --- the person's own repositories ---------------------------------------------------------------------------------


def owned(memory_path: Path) -> list[dict]:
    """The repositories the last sync found the person owns: each staged episode's GitHub block, live ones only."""
    from api.services.connectors import github

    rows = []
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if fm.get("origin") != github.ORIGIN_OWNED or fm.get("source_deleted_at"):
            continue
        block = fm.get(GITHUB_KEY)
        if isinstance(block, dict) and isinstance(block.get("id"), int) and block.get("full_name"):
            rows.append({**block, "episode": f.stem})
    return sorted(rows, key=lambda r: str(r.get("full_name") or "").lower())


def starred(memory_path: Path) -> list[dict]:
    """Every repository page, starred ones first (newest star first), then the rest."""
    rows = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        block = fm.get(GITHUB_KEY)
        if is_repository_page(fm) and isinstance(block, dict) and block.get("full_name"):
            rows.append({**block, "entity_id": f.stem})
    rows.sort(key=lambda r: str(r.get("starred_at") or ""), reverse=True)
    return sorted(rows, key=lambda r: not r.get("starred"))


def _salt() -> str | None:
    """This install's remote salt (D2a), read only — never made here. ``None`` when the hook never made one."""
    from api.hooks import workspace_identity as hook_identity
    from api.services.auth import cicada_home

    path = cicada_home() / hook_identity.SALT_FILE
    try:
        if path.is_symlink():
            return None
        value = path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return None
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else None


def remote_hash(url: str, salt: str | None) -> str | None:
    """The hash a hook would have sent for a checkout cloned from ``url`` — compared, never stored."""
    from api.hooks import workspace_identity as hook_identity

    if not salt:
        return None
    normalised = hook_identity.normalise_remote(url.encode())
    return hook_identity.remote_hash(normalised, salt) if normalised else None


def _projects(memory_path: Path) -> list:
    return [f for f in bank_index.files(Path(memory_path), "entities")
            if str((f.frontmatter or {}).get("type") or "") == "project"
            and str((f.frontmatter or {}).get("status") or "") not in ("archived", "dropped")]


def _norm(url) -> str:
    return str(url or "").strip().rstrip("/").lower()


def _github_url(value) -> str | None:
    """``https://github.com/<owner>/<name>`` (lowercased) for a link to a repository, else ``None``."""
    from api.services.connectors import github

    full = github.parse_repo(str(value or ""))
    return github.repo_url(full).lower() if full and "github.com" in str(value or "").lower() else None


def link_entries(fm: dict | None) -> list[dict]:
    """A project's ``repositories:`` as written: ``{entity, url, how, by, day, session?}`` rows with a URL."""
    rows = (fm or {}).get(REPOS_KEY)
    return [r for r in rows if isinstance(r, dict) and r.get("url")] if isinstance(rows, list) else []


def removed_urls(fm: dict | None) -> set[str]:
    rows = (fm or {}).get(REPOS_REMOVED_KEY)
    return {_norm(r) for r in rows if isinstance(r, str)} if isinstance(rows, list) else set()


def project_urls(fm: dict | None) -> list[str]:
    """Every repository a project names, lowercased, in order: its ``repositories:``, then what came before the list
    — a trusted ``repo`` source, a GitHub URL in ``repos:`` (or a declared checkout's ``remote``), the one ``github:``
    block a project carried — less the ones the person unlinked. Derived on read."""
    from api.services import fact_sources

    fm = fm or {}
    out = [_norm(r["url"]) for r in link_entries(fm)]
    for s in fm.get("sources") or []:
        if isinstance(s, dict) and fact_sources.same_predicate(s.get("predicate"), REPO_PREDICATE) \
                and fact_sources.trusted(s) and (url := _github_url(s.get("ref"))):
            out.append(url)
    for r in fm.get("repos") or []:
        ref = r if isinstance(r, str) else (r.get("remote") if isinstance(r, dict) else None)
        if url := _github_url(ref):
            out.append(url)
    block = fm.get(GITHUB_KEY)
    if isinstance(block, dict) and block.get("full_name") and not is_repository_page(fm):
        from api.services.connectors import github

        out.append(github.repo_url(str(block["full_name"])).lower())
    gone = removed_urls(fm)
    return [u for u in dict.fromkeys(out) if u not in gone]


def named_urls(fm: dict | None) -> list[str]:
    """:func:`project_urls` less Cicada's own ``how: origin`` links: the repositories the person or a trusted agent named.
    Only these may tie a session by a shared remote (ruling 56). Cicada's own link proves the same repository, not the
    same project, and a remote alone never ties a conversation (`capture-and-sleep.md`)."""
    own = {_norm(r["url"]) for r in link_entries(fm or {}) if str(r.get("how") or "") == HOW_ORIGIN}
    return [u for u in project_urls(fm) if u not in own]


def linked_projects(memory_path: Path, projects=None) -> dict[str, list[dict]]:
    """``{repository url: [{project, name, how}]}`` over every live project (``how`` the link's own, ``linked`` for one
    from before the list). Derived on read."""
    out: dict[str, list[dict]] = {}
    for f in _projects(memory_path) if projects is None else projects:
        fm = f.frontmatter or {}
        label = str(fm.get("name") or f.stem)
        hows = {_norm(r["url"]): str(r.get("how") or HOW_USER) for r in link_entries(fm)}
        for url in project_urls(fm):
            out.setdefault(url, []).append({"project": f.stem, "name": label, "how": hows.get(url, "linked")})
    return out


def _sessions(memory_path: Path) -> list:
    from api.services import project_birth

    return project_birth.remote_sessions(memory_path)


def project_match(memory_path: Path, full_name: str, *, salt: str | None = None, projects=None,
                  sessions=None, links=None) -> dict | None:
    """``{project, name, how}`` — a project this repository already belongs to (``linked``/``user``/``agent``/
    ``origin``: on its ``repositories:`` or an older link), one whose own checkout points at it now by the hook's salted
    origin hash (``origin``, not written yet), or a suggestion (``name``: a project with exactly its name). ``None``
    when nothing matches. Derived on read; writes nothing."""
    from api.services import project_birth
    from api.services.connectors import github

    url = github.repo_url(full_name).lower()
    links = linked_projects(memory_path, projects) if links is None else links
    if links.get(url):
        return links[url][0]
    name = full_name.split("/", 1)[1]
    pages = _projects(memory_path) if projects is None else projects
    wanted = remote_hash(github.repo_url(full_name), salt)
    sessions = (_sessions(memory_path) if wanted else []) if sessions is None else sessions
    by_name = None
    for f in pages:
        fm = f.frontmatter or {}
        if url in removed_urls(fm):
            continue
        label = str(fm.get("name") or f.stem)
        if wanted and wanted in project_birth.page_remotes(fm, sessions):
            return {"project": f.stem, "name": label, "how": HOW_ORIGIN}
        if by_name is None and project_birth.fold(name) in project_birth.name_folds(fm | {"name": label}):
            by_name = {"project": f.stem, "name": label, "how": "name"}
    return by_name


def with_matches(memory_path: Path, rows: list[dict]) -> list[dict]:
    """Each row with ``project`` (:func:`project_match`) and ``projects`` (every project it is linked to)."""
    from api.services.connectors import github

    salt = _salt()
    projects = _projects(memory_path)
    links = linked_projects(memory_path, projects)
    sessions = _sessions(memory_path) if salt else []
    return [{**r, "project": project_match(memory_path, r["full_name"], salt=salt, projects=projects,
                                           sessions=sessions, links=links),
             "projects": links.get(github.repo_url(r["full_name"]).lower(), [])} for r in rows]


def repository_page(memory_path: Path, full_name: str) -> str | None:
    """The repository page for ``owner/name`` (any case), or ``None``."""
    want = full_name.lower()
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        block = fm.get(GITHUB_KEY)
        if is_repository_page(fm) and isinstance(block, dict) and str(block.get("full_name") or "").lower() == want:
            return f.stem
    return None


class LinkRefused(Exception):
    """A link that is not made, in words (an agent re-adding what the person unlinked; not a project)."""


def _write_backlink(memory_path: Path, entity_id: str, projects: list[str]) -> bool:
    page = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not page.exists():
        return False
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    block = fm.get(GITHUB_KEY) if isinstance(fm.get(GITHUB_KEY), dict) else None
    if block is None or not is_repository_page(fm):
        return False
    new = {k: v for k, v in block.items() if k != PROJECTS_KEY}
    if projects:
        new[PROJECTS_KEY] = list(projects)
    if new == block:
        return False
    fm[GITHUB_KEY] = new
    markdown_parser.write(page, fm, parsed.body)
    return True


def sync_backlinks(memory_path: Path, entity_ids: list[str] | None = None) -> list[str]:
    """Each repository page's ``github.projects`` set to the projects that name it (:func:`linked_projects`) — for
    ``entity_ids``, or every repository page. Returns the paths written. The caller holds the page lock."""
    from api.services.connectors import github

    memory_path = Path(memory_path)
    bank_index.invalidate(memory_path)
    links = linked_projects(memory_path)
    paths = []
    for row in starred(memory_path):
        if entity_ids is not None and row["entity_id"] not in entity_ids:
            continue
        mine = [p["project"] for p in links.get(github.repo_url(str(row["full_name"])).lower(), [])]
        if _write_backlink(memory_path, row["entity_id"], mine):
            paths.append(f"entities/{row['entity_id']}.md")
    bank_index.invalidate(memory_path)
    return paths


def backlink_pages(memory_path: Path, page_ids, fms=()) -> list[str]:
    """The repository pages whose back-link may change when ``page_ids`` change (a merge, ``entity_merge``): each one
    naming any of them, any of them that is itself a repository page, and each one a frontmatter in ``fms`` lists.
    Reads only — a merge's footprint and its write share it."""
    from api.services.connectors import github

    ids = set(page_ids)
    urls = {u for fm in fms for u in project_urls(fm)}
    out = []
    for row in starred(Path(memory_path)):
        named = {str(p) for p in row.get(PROJECTS_KEY) or []}
        if named & ids or row["entity_id"] in ids or github.repo_url(str(row["full_name"])).lower() in urls:
            out.append(row["entity_id"])
    return out


def link(memory_path: Path, project_id: str, entity_id: str, *, by: str = "user", how: str = HOW_USER,
         session: str | None = None, remove: bool = False, reason: str | None = None) -> list[str]:
    """``entity_id`` (a repository page) is one of ``project_id``'s repositories — or, with ``remove``, is not. The
    person's act (``by: user``) is final both ways: their unlink is remembered and lifts only on their own link again;
    an agent or Cicada's origin rule never re-adds it, and an agent takes back only a link it made. Writes the project's
    ``repositories:`` and the repository page's back-link; returns the paths written (none when nothing changed).
    Raises ``LookupError`` for a page that is not a live project or a repository page, :class:`LinkRefused` in words.
    The caller holds the bank's write admission."""
    memory_path = Path(memory_path)
    with page_lock.page_lock(memory_path):
        project = memory_path / "entities" / f"{project_id}.md"
        repo_page = memory_path / "entities" / f"{entity_id}.md"
        if not project.exists() or not repo_page.exists():
            raise LookupError(project_id if not project.exists() else entity_id)
        rfm = markdown_parser.parse(repo_page, ledger=False).frontmatter or {}
        block = page_repo(rfm)
        if block is None or not is_repository_page(rfm):
            raise LookupError(entity_id)
        from api.services.connectors import github

        url = github.repo_url(str(block["full_name"]))
        parsed = markdown_parser.parse(project)
        fm = parsed.frontmatter
        if str(fm.get("type") or "") != "project" or str(fm.get("status") or "") == "dropped":
            raise LookupError(project_id)
        rows = link_entries(fm)
        gone = removed_urls(fm)
        person = by == "user"
        here = [r for r in rows if _norm(r["url"]) == url.lower()]
        changed = False
        if remove:
            if person:
                if here or url.lower() in [u for u in project_urls(fm)]:
                    rows = [r for r in rows if _norm(r["url"]) != url.lower()]
                    if url.lower() not in gone:
                        fm[REPOS_REMOVED_KEY] = [*(fm.get(REPOS_REMOVED_KEY) or []), url]
                    changed = True
            else:
                own = [r for r in here if r.get("by") == by]
                if not own:
                    raise LinkRefused("You can take back only a link you made; the person decides the rest.")
                rows = [r for r in rows if not any(r is o for o in own)]
                changed = True
        else:
            if url.lower() in gone and not person:
                raise LinkRefused("The person said this repository is not part of that project; it stays out.")
            if url.lower() in gone:
                fm[REPOS_REMOVED_KEY] = [u for u in fm.get(REPOS_REMOVED_KEY) or [] if _norm(u) != url.lower()]
                changed = True
            if not here:
                row = {"entity": entity_id, "url": url, "how": how, "by": by, "day": date.today().isoformat()}
                if session:
                    row["session"] = session
                if reason:
                    row["reason"] = reason
                rows.append(row)
                changed = True
            elif any(r.get("entity") != entity_id for r in here):
                for r in here:
                    r["entity"] = entity_id
                changed = True
        if not changed:
            return []
        if rows:
            fm[REPOS_KEY] = rows
        else:
            fm.pop(REPOS_KEY, None)
        if not fm.get(REPOS_REMOVED_KEY):
            fm.pop(REPOS_REMOVED_KEY, None)
        markdown_parser.write(project, fm, parsed.body)
        bank_index.invalidate(memory_path)
        paths = [f"entities/{project_id}.md", *sync_backlinks(memory_path, [entity_id])]
    return list(dict.fromkeys(paths))


def link_by_origin(memory_path: Path) -> dict:
    """Cicada's own links, after a sync (``tier2``'s ``then``, inside the same admission, its own commit): a
    repository page whose URL hashes (D2a, this install's salt, read and never made) to the remote the ONE project's own
    checkout points at now (``project_birth.page_remotes``) joins that project's ``repositories:`` with ``how:
    origin``. Two projects on one remote link neither (the same repository is not the same project). The back-links
    of every repository page are brought up to date too (a link from before the list included). Returns ``{paths,
    subject, author, words?}``."""
    from api.services import project_birth, project_ownership
    from api.services.connectors import github

    memory_path = Path(memory_path)
    paths: list[str] = []
    made = 0
    salt = _salt()
    with page_lock.page_lock(memory_path):
        if salt:
            sessions = _sessions(memory_path)
            projects = _projects(memory_path)
            # Ruling 56: an automatic link lands only on a project the person started; adopting one links it next sync.
            remotes = {f.stem: project_birth.page_remotes(f.frontmatter or {}, sessions) for f in projects
                       if project_ownership.listed(f.frontmatter, f.path)}
            links = linked_projects(memory_path, projects)
            for row in starred(memory_path):
                url = github.repo_url(str(row["full_name"]))
                wanted = remote_hash(url, salt)
                hits = [pid for pid, rs in remotes.items() if wanted and wanted in rs]
                if len(hits) != 1 or any(p["project"] == hits[0] for p in links.get(url.lower(), [])):
                    continue
                fm = next(f.frontmatter or {} for f in projects if f.stem == hits[0])
                if url.lower() in removed_urls(fm):
                    continue
                try:
                    wrote = link(memory_path, hits[0], row["entity_id"], by=CICADA, how=HOW_ORIGIN)
                except (LookupError, LinkRefused):
                    continue
                if wrote:
                    made += 1
                    paths += wrote
        paths += sync_backlinks(memory_path)
    out = {"paths": list(dict.fromkeys(paths)), "subject": "Repositories linked to their projects", "author": CICADA}
    if made:
        out["words"] = (f"{made} repositor{'y' if made == 1 else 'ies'} linked to {'its' if made == 1 else 'their'} "
                        "project by the checkout you work in.")
    return out


def project_repositories(memory_path: Path, project_id: str) -> list[dict]:
    """A project's repositories, each ``{url, full_name, entity_id?, how, by?, block?}`` — the page's record when a
    repository page exists (``block``, its ``github:``). Derived on read."""
    from api.services.connectors import github

    page = Path(memory_path) / "entities" / f"{project_id}.md"
    if not page.exists():
        return []
    fm = markdown_parser.parse(page, ledger=False).frontmatter or {}
    rows = {_norm(r["url"]): r for r in link_entries(fm)}
    pages = {github.repo_url(str(r["full_name"])).lower(): r for r in starred(memory_path)}
    out = []
    for url in project_urls(fm):
        full = github.parse_repo(url) or url
        entry, found = rows.get(url) or {}, pages.get(url)
        out.append({"url": github.repo_url(found["full_name"]) if found else url,
                    "full_name": str(found["full_name"]) if found else full,
                    "entity_id": found["entity_id"] if found else None,
                    "how": str(entry.get("how") or "linked"), "by": entry.get("by"),
                    "block": found})
    return out


def repositories_line(memory_path: Path, project_id: str) -> str | None:
    """One line for an agent: the GitHub repositories a project lists, each with its page — ``None`` when it lists
    none (``cicada_repo_context``)."""
    rows = project_repositories(memory_path, project_id)
    if not rows:
        return None
    return "GitHub repositories: " + ", ".join(
        r["full_name"] + (f" (page {r['entity_id']})" if r.get("entity_id") else "") for r in rows) + "."


def make_project(memory_path: Path, repo: Repo, *, via: str = "app", by: str = "user") -> tuple[str, list[str]]:
    """The person's "New project from this repository" (ruling 45: their act, from the app or their own shell): a
    project page in their list (``mine: {via}``) named after the repository, which then lists it. A page that already
    answers to the name is started instead, its history kept (ruling 56). Raises ``project_ownership.OwnershipError``
    when the name is held by a page that can't be a project, ``LookupError`` when the repository has no page."""
    from api.services import project_ownership

    entity_id = repository_page(memory_path, repo.full_name)
    if entity_id is None:
        raise LookupError(repo.full_name)
    door = project_ownership.VIA_CLI if via == "cli" else project_ownership.VIA_APP
    target = project_ownership.start_target(Path(memory_path), repo.name)
    if target is not None:
        eid, paths = target, project_ownership.start(Path(memory_path), target, via=door, by=by)
    else:
        eid, paths = project_ownership.create(Path(memory_path), repo.name, repo.description, via=door, by=by,
                                              listed=True)
    return eid, list(dict.fromkeys([*paths, *link(memory_path, eid, entity_id, by=by), f"entities/{eid}.md"]))


def project_candidates(memory_path: Path, full_name: str, *, linked: set[str]) -> list[dict]:
    """The projects a repository card offers to link to: a match first (the origin hash, then the name), then the
    person's own by name (ruling 56: never every page of that type); never one already linked, at most
    :data:`MAX_CANDIDATES`."""
    from api.services import project_ownership

    projects = _projects(memory_path)
    own = {f.stem for f in projects if project_ownership.listed(f.frontmatter, f.path)}
    best = project_match(memory_path, full_name, salt=_salt(), projects=projects, links={})
    out = [best] if best and best["project"] not in linked else []
    rest = sorted(({"project": f.stem, "name": str((f.frontmatter or {}).get("name") or f.stem), "how": "other"}
                   for f in projects if f.stem in own and f.stem not in linked
                   and f.stem != (best or {}).get("project")), key=lambda p: p["name"].lower())
    return (out + rest)[:MAX_CANDIDATES]


def repository_candidates(memory_path: Path, project_id: str, *, linked: set[str]) -> list[dict]:
    """The repositories a project offers to link: the person's own first (one with the project's name before the
    rest), then any other repository page; never one already linked, at most :data:`MAX_CANDIDATES`."""
    from api.services import project_birth

    page = Path(memory_path) / "entities" / f"{project_id}.md"
    fm = markdown_parser.parse(page, ledger=False).frontmatter or {} if page.exists() else {}
    folds = project_birth.name_folds(fm | {"name": fm.get("name") or project_id})
    rows = [r for r in starred(memory_path) if r["entity_id"] not in linked]
    rows.sort(key=lambda r: (project_birth.fold(str(r["full_name"]).split("/", 1)[-1]) not in folds,
                             not r.get("owned"), str(r["full_name"]).lower()))
    return rows[:MAX_CANDIDATES]


def page_repo(fm: dict | None) -> dict | None:
    """The GitHub block of a repository page (or of a project from before projects listed theirs), else ``None``."""
    fm = fm or {}
    block = fm.get(GITHUB_KEY)
    if not isinstance(block, dict) or not block.get("full_name"):
        return None
    if is_repository_page(fm) or str(fm.get("type") or "") == "project":
        return block
    return None


# --- the README preview, outside every bank ------------------------------------------------------------------------


def _readme_root(bank: str) -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / README_DIR / (bank or "default")


def _readme_path(bank: str, entity_id: str) -> Path | None:
    base = _readme_root(bank)
    path = (base / f"{entity_id}.json").resolve()
    return path if path.parent == base.resolve() else None


def read_readme(bank: str, entity_id: str) -> dict | None:
    path = _readme_path(bank, entity_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_readme(bank: str, entity_id: str, data: dict) -> None:
    path = _readme_path(bank, entity_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def forget_readmes() -> None:
    """Disconnect: every README read with the token, in every bank's cache."""
    from api.services.auth import cicada_home

    root = cicada_home() / README_DIR
    for path in root.glob("*/*.json"):
        try:
            path.unlink()
        except OSError:
            pass


def preview_text(markdown: str) -> tuple[str, bool]:
    """A README as words to read: no HTML, no images or badges, a link kept as its words, at most
    :data:`PREVIEW_CHARS`. Returns ``(text, truncated)``. Pure."""
    text = markdown.replace("\r\n", "\n")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = _IMAGE.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _REF_LINE.sub("", text)
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = _BLANKS.sub("\n\n", "\n".join(lines)).strip()
    if len(text) <= PREVIEW_CHARS:
        return text, False
    cut = text[:PREVIEW_CHARS]
    cut = cut[: cut.rfind("\n")] if "\n" in cut[PREVIEW_CHARS // 2:] else cut
    return cut.rstrip() + "\n…", True


def decode_readme(record: dict | None) -> str | None:
    if not isinstance(record, dict) or record.get("encoding") != "base64":
        return None
    try:
        raw = base64.b64decode(str(record.get("content") or ""), validate=False)
    except (ValueError, TypeError):
        return None
    if len(raw) > README_MAX_BYTES:
        raw = raw[:README_MAX_BYTES]
    return raw.decode("utf-8", errors="replace")


def readme_state(cached: dict | None, *, now: datetime | None = None) -> str:
    """``fresh`` (kept less than :data:`README_TTL` ago), ``stale`` or ``missing``."""
    if not cached:
        return "missing"
    at = _stamp(cached.get("fetched_at"))
    now = now or datetime.now(timezone.utc)
    return "fresh" if at and now - datetime.fromisoformat(at) < README_TTL else "stale"


async def ensure_readme(memory_path: Path, entity_id: str, block: dict, *, transport=None,
                        allowed: bool = True) -> dict | None:
    """The README preview for one page: the kept copy while it is fresh, else read once through the API (the
    person's token when connected) and kept. A failed read keeps whatever was kept. Never raises."""
    from api.services.connectors import github, tier2

    bank = Path(memory_path).name
    cached = read_readme(bank, entity_id)
    if readme_state(cached) == "fresh" or not allowed:
        return cached
    full = str(block.get("full_name") or "")
    if github.parse_repo(full) != full:
        return cached
    try:
        record = await github.read_readme(github.client(transport=transport), full)
    except tier2.Refused as exc:
        logger.info(f"github: README not read ({exc.kind})")
        return cached
    except Exception as exc:  # noqa: BLE001 — the class only, never the message
        logger.info(f"github: README not read ({type(exc).__name__})")
        return cached
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if record is None:
        data = {"none": True, "fetched_at": now}
    else:
        markdown = decode_readme(record)
        if markdown is None:
            return cached
        text, truncated = preview_text(markdown)
        data = {"text": text, "truncated": truncated, "path": _text(record.get("path"), 200) or "README",
                "sha": _text(record.get("sha"), 64), "fetched_at": now}
    _write_readme(bank, entity_id, data)
    return data

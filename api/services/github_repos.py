"""Repositories on the graph (G230): the one writer of a repository's page, its README preview, and the list of the
person's own repositories offered as projects.

**What a repository is in the closed set of 10.** A repository Cicada learns of from GitHub — one the person starred,
or one they pasted — is a saved link: a ``media`` page (``media.kind: repository``), born here and never by a model
(Stage 1 never produces ``media``), quiet until the person mentions it (``quiet_pages``), exactly like a bookmark. It
is not a ``tool`` (that page is the thing a conversation says the person uses, made by Sleep from their words) and not
a ``project`` (ruling 36 D4 / 45: only a repository the hook observed, the person's own words, or the person's act make
one). A repository the person OWNS becomes a ``project`` only on their act — "Make it a project" here, or a project
page that already is it (:func:`project_match`) — never by a sync.

**The page** carries the usual media frontmatter plus one ``github:`` block this module alone writes —
``{id, full_name, owner, owner_kind, description, language, topics, private, archived, fork, default_branch,
starred, starred_at, unstarred_on, added, owned}`` — and one trusted ``website`` source: the repository's own GitHub URL,
the person's (they starred or pasted it). Its picture is the media preview rung (``entity_picture`` 4): ``media.
thumbnail`` is the owner's avatar ONLY when an organisation owns the repository (owner 2026-10-28, E) — a personal
account's avatar is never asked — fetched and kept by ``media_preview`` on the ToS rail. A later sync rewrites the
block in place when GitHub's record changed and leaves the page alone when it did not; a repository no longer starred
keeps its page with ``starred: false`` and the day it was seen gone. Nothing here deletes a page or an episode.

**The README preview** is read through the official API (``GET /repos/{full_name}/readme``, the person's token when
connected, none for a public repository), only when the person adds the repository or opens its page, and kept
outside every bank at ``$CICADA_HOME/readmes/<bank>/<entity id>.json`` — like a media preview, a cache of the outside
world: rebuilt, never an error, read again when a week old, gone with Disconnect. The preview is text only: HTML, images and badges are dropped, at
most :data:`PREVIEW_CHARS` kept; the app never loads a picture or a link the README names.

**Matching a project** (:func:`project_match`, derived on read, never written by a sync): a project page whose trusted
``repo`` source is this repository's URL is it (``linked``); one born from a checkout whose origin the hook hashed
(D2a: ``born.repo.remote``) to the hash of this URL with this install's salt is the same repository (``origin``) — the
salt is read, never made, and nothing is stored but the match; a project page with the repository's exact name is a
suggestion (``name``). The person links it in one click (:func:`link_project`).
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

from api.services import bank_index, markdown_parser, page_lock

KIND = "repository"
GITHUB_KEY = "github"
SITE = "github.com"
WEBSITE = "website"
REPO_PREDICATE = "repo"
ADDED_ORIGIN = "github-added"
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
                                "added_by": fact_sources.USER, "added_at": today}]
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


def upsert(memory_path: Path, repo: Repo, idx: dict, *, origin: str, starred: bool | None = None,
           starred_at: str | None = None, added: bool = False, owned: bool | None = None,
           known: dict[int, str] | None = None) -> tuple[str, str, list[str]]:
    """Make or update ``repo``'s page: ``(entity id, "created"|"updated"|"same", paths written)``. The caller holds
    the bank's admission and page lock and saves ``idx``."""
    from api.services import media_ingestor

    memory_path = Path(memory_path)
    known = _pages_by_id(memory_path) if known is None else known
    entity_id = known.get(repo.id)
    if entity_id is None:
        hit = idx.get(media_ingestor.url_hash(repo.url)) or {}
        hit = idx.get(hit.get("alias_of"), hit) if hit.get("alias_of") else hit
        entity_id = str(hit.get("media_entity_id") or "") or None
    paths: list[str] = []
    status = "same"
    page = memory_path / "entities" / f"{entity_id}.md" if entity_id else None
    if page is None or not page.exists():
        entity_id, episode_id = _new_page(memory_path, repo, idx, origin=origin, starred_at=starred_at)
        page = memory_path / "entities" / f"{entity_id}.md"
        paths += [f"episodes/{episode_id}.md", "sources/url_index.json"]
        status = "created"
        known[repo.id] = entity_id
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    if status == "created" or is_repository_page(fm) or str(fm.get("type") or "") == "media":
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        before = dict(media)
        media["kind"] = KIND
        media["media_type"] = KIND
        fm["media"] = media
        changed = before != media
    else:
        changed = False
    changed |= _merge_block(fm, repo, starred=starred, starred_at=starred_at, added=added, owned=owned)
    changed |= _source(fm, repo.url, WEBSITE, date.today().isoformat())
    if changed or status == "created":
        markdown_parser.write(page, fm, parsed.body)
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
    return out


def add(memory_path: Path, repo: Repo) -> tuple[str, str, list[str]]:
    """The person's hand-add (a pasted URL, or a row of the synced list): the repository's page, made or updated.
    A save the person made on purpose: its episode is read by Sleep like any single link they save."""
    from api.services import media_ingestor

    with page_lock.page_lock(memory_path):
        idx = media_ingestor.load_url_index(memory_path)
        entity_id, status, paths = upsert(memory_path, repo, idx, origin=ADDED_ORIGIN, added=True)
        media_ingestor.save_url_index(memory_path, idx)
    bank_index.invalidate(memory_path)
    return entity_id, status, list(dict.fromkeys(paths))


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


def project_match(memory_path: Path, full_name: str, *, salt: str | None = None, projects=None) -> dict | None:
    """``{project, name, how}`` — the project page this repository already is (``linked``: a trusted ``repo``
    source names it; ``origin``: born from a checkout of it, by the salted origin hash), or a suggestion
    (``name``: a project with exactly its name). ``None`` when nothing matches. Derived on read; writes nothing."""
    from api.services import fact_sources, project_birth
    from api.services.connectors import github

    url = github.repo_url(full_name).lower()
    name = full_name.split("/", 1)[1]
    pages = _projects(memory_path) if projects is None else projects
    wanted = remote_hash(github.repo_url(full_name), salt)
    by_name = None
    for f in pages:
        fm = f.frontmatter or {}
        label = str(fm.get("name") or f.stem)
        for s in fm.get("sources") or []:
            if isinstance(s, dict) and str(s.get("ref") or "").rstrip("/").lower() == url \
                    and fact_sources.same_predicate(s.get("predicate"), REPO_PREDICATE) and fact_sources.trusted(s):
                return {"project": f.stem, "name": label, "how": "linked"}
        if any(str(r).rstrip("/").lower() == url for r in fm.get("repos") or [] if isinstance(r, str)):
            return {"project": f.stem, "name": label, "how": "linked"}
        born = fm.get("born") if isinstance(fm.get("born"), dict) else {}
        repo = born.get("repo") if isinstance(born.get("repo"), dict) else {}
        if wanted and repo.get("remote") == wanted:
            return {"project": f.stem, "name": label, "how": "origin"}
        if by_name is None and project_birth.fold(name) in project_birth.name_folds(fm | {"name": label}):
            by_name = {"project": f.stem, "name": label, "how": "name"}
    return by_name


def with_matches(memory_path: Path, rows: list[dict]) -> list[dict]:
    salt = _salt()
    projects = _projects(memory_path)
    return [{**r, "project": project_match(memory_path, r["full_name"], salt=salt, projects=projects)} for r in rows]


def link_project(memory_path: Path, project_id: str, repo: Repo) -> list[str]:
    """The person's link: ``repo`` is this project's repository — a trusted ``repo`` source (which also gives the
    project its organisation's avatar, ``logo_service.repo_owner``) and the GitHub block. The caller holds the bank's
    admission; raises ``LookupError`` for a page that is not a live project."""
    page = Path(memory_path) / "entities" / f"{project_id}.md"
    with page_lock.page_lock(memory_path):
        if not page.exists():
            raise LookupError(project_id)
        parsed = markdown_parser.parse(page)
        fm = parsed.frontmatter
        if str(fm.get("type") or "") != "project":
            raise LookupError(project_id)
        changed = _merge_block(fm, repo, owned=True)
        changed |= _source(fm, repo.url, REPO_PREDICATE, date.today().isoformat())
        if changed:
            markdown_parser.write(page, fm, parsed.body)
    bank_index.invalidate(memory_path)
    return [f"entities/{project_id}.md"] if changed else []


def make_project(memory_path: Path, repo: Repo, *, by: str = "user") -> tuple[str, list[str]]:
    """The person's "Make it a project": a project page in their list (``mine: {via: app}``) named after the
    repository, then linked to it. Raises ``project_ownership.OwnershipError`` when the name is taken (the person
    links that page instead)."""
    from api.services import project_ownership

    eid, paths = project_ownership.create(Path(memory_path), repo.name, repo.description,
                                          via=project_ownership.VIA_APP, by=by, listed=True)
    return eid, list(dict.fromkeys([*paths, *link_project(memory_path, eid, repo), f"entities/{eid}.md"]))


def page_repo(fm: dict | None) -> dict | None:
    """The GitHub block of a repository page or a project linked to one, else ``None``."""
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

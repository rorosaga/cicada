"""G230 — repositories on the graph: the synced lists, the person's hand-add, a repository as a project, and a page's
repository card with its README preview. ``github_repos`` is the writer; this router is its door for every client
(the app, the CLI through ``cli_map``).

Every write is the person's act: demo-gated (``refuse_capture_into_demo``), one admitted transaction around the page
writes and their scoped commit (409 while Sleep holds the pages, G183), any request to GitHub made BEFORE the
admission is taken. The token is never read back, logged or returned; a refusal is GitHub's in words.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.routers.capture import refuse_capture_into_demo
from api.services import git_service, github_repos, markdown_parser, media_preview, write_admission
from api.services.connectors import github, tier2
from api.services.sleep_refusal import SleepWriting

router = APIRouter()
_DEMO_GATE = [Depends(refuse_capture_into_demo)]
BUSY = "Sleep is updating your memory — add the repository again in a moment."
VIAS = frozenset({"app", "cli"})
NOT_A_REPO = "That is not a GitHub repository link. Paste one like https://github.com/owner/name."


class RepoProject(CamelModel):
    project: str
    name: str
    how: str


class RepoRow(CamelModel):
    id: int
    full_name: str
    url: str
    description: Optional[str] = None
    language: Optional[str] = None
    topics: list[str] = []
    owner_kind: str = "User"
    private: bool = False
    archived: bool = False
    fork: bool = False
    starred: bool = False
    starred_at: Optional[str] = None
    unstarred_on: Optional[str] = None
    owned: bool = False
    added: bool = False
    entity_id: Optional[str] = None
    project: Optional[RepoProject] = None


class RepoLists(CamelModel):
    connected: bool
    owned: list[RepoRow] = []
    starred: list[RepoRow] = []


class RepoAddRequest(CamelModel):
    url: str


class RepoAddResponse(CamelModel):
    entity_id: str
    full_name: str
    created: bool


class RepoProjectRequest(CamelModel):
    full_name: str
    #: An existing project page to link; absent, a new project is made (in the person's list).
    project: Optional[str] = None
    #: Which of the person's doors made it (ruling 45's ``mine.via``): ``app`` or ``cli``.
    via: str = "app"


class RepoProjectResponse(CamelModel):
    project: str
    created: bool


class Readme(CamelModel):
    state: str              # fresh | stale | missing | none (the repository has no README)
    text: Optional[str] = None
    truncated: bool = False
    path: Optional[str] = None
    fetched_at: Optional[str] = None


class RepoDetail(RepoRow):
    entity_id: str
    readme: Readme


def _row(block: dict, **extra) -> RepoRow:
    full = str(block.get("full_name") or "")
    return RepoRow(
        id=int(block.get("id") or 0), full_name=full, url=github.repo_url(full),
        description=block.get("description") or None, language=block.get("language") or None,
        topics=[str(t) for t in block.get("topics") or []], owner_kind=str(block.get("owner_kind") or "User"),
        private=bool(block.get("private")), archived=bool(block.get("archived")), fork=bool(block.get("fork")),
        starred=bool(block.get("starred")), starred_at=block.get("starred_at") or None,
        unstarred_on=block.get("unstarred_on") or None, owned=bool(block.get("owned")),
        added=bool(block.get("added")), **extra)


@router.get("/sources/github/repos", response_model=RepoLists)
async def list_repos(settings: Settings = Depends(get_settings)):
    """The repositories the last sync found the person owns — each with the project page it already is, or a
    suggestion — and every repository page (starred or added). Reads the bank only; never asks GitHub."""
    memory_path = settings.memory_path

    def read():
        owned = github_repos.with_matches(memory_path, github_repos.owned(memory_path))
        pages = {r["id"]: r["entity_id"] for r in github_repos.starred(memory_path)}
        return owned, github_repos.starred(memory_path), pages

    owned, starred, pages = await asyncio.to_thread(read)
    return RepoLists(
        connected=github.is_connected(),
        owned=[_row(r, entity_id=pages.get(r.get("id")),
                    project=RepoProject(**r["project"]) if r.get("project") else None) for r in owned],
        starred=[_row(r, entity_id=r["entity_id"]) for r in starred])


async def _record(full_name: str) -> github_repos.Repo:
    """GitHub's record of one repository (the person's token when connected), or the refusal in words."""
    try:
        raw = await github.read_repo(github.client(), full_name)
    except tier2.Refused as exc:
        raise HTTPException(422, exc.words) from exc
    except tier2.base.ConnectorError as exc:
        if "HTTP 404" in str(exc):
            raise HTTPException(404, "GitHub has no repository there that Cicada can read. A private one needs "
                                     "your GitHub connected (Settings → Sources → GitHub).") from exc
        raise HTTPException(502, "GitHub did not answer; try again in a moment.") from exc
    except Exception as exc:  # noqa: BLE001 — the class only, never the message
        logger.info(f"github: repository not read ({type(exc).__name__})")
        raise HTTPException(502, "Cicada could not reach GitHub; try again in a moment.") from exc
    repo = github_repos.Repo.from_api(raw)
    if repo is None:
        raise HTTPException(502, "GitHub's answer was not a repository Cicada can read.")
    return repo


async def _commit(memory_path, paths: list[str], subject: str) -> None:
    if not paths or not (memory_path / ".git").exists():
        return
    message = git_service.build_commit_message(
        f"{subject} {date.today().isoformat()}",
        [f"{p}: updated (trigger: user/github)" for p in paths], authors=["user"])
    await git_service.commit_paths(memory_path, message, paths)


@router.post("/sources/github/repos", response_model=RepoAddResponse, dependencies=_DEMO_GATE)
async def add_repo(request: RepoAddRequest, settings: Settings = Depends(get_settings)):
    """The person adds one repository to the graph — a pasted link, or a row of the synced list: GitHub's record is
    read first (no admission held), then the page is made or updated and committed as one admitted transaction.
    Its README preview is read right after, outside the bank."""
    full = github.parse_repo(request.url)
    if full is None:
        raise HTTPException(422, NOT_A_REPO)
    repo = await _record(full)
    memory_path = settings.memory_path

    async def write():
        entity_id, status, paths = await asyncio.to_thread(github_repos.add, memory_path, repo)
        await _commit(memory_path, paths, "Repository added")
        return entity_id, status

    entity_id, status = await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(BUSY))
    await github_repos.ensure_readme(memory_path, entity_id, repo.block(), allowed=True)
    return RepoAddResponse(entity_id=entity_id, full_name=repo.full_name, created=status == "created")


@router.post("/sources/github/repos/project", response_model=RepoProjectResponse, dependencies=_DEMO_GATE)
async def repo_project(request: RepoProjectRequest, settings: Settings = Depends(get_settings)):
    """The person's "this is my project": link the repository to a project page (``project``), or make one in their
    list named after it. The repository's record comes from the last sync, else from GitHub."""
    from api.services import project_ownership

    full = github.parse_repo(request.full_name)
    if full is None:
        raise HTTPException(422, NOT_A_REPO)
    if request.via not in VIAS:
        raise HTTPException(422, "via is app or cli")
    memory_path = settings.memory_path
    owned = await asyncio.to_thread(github_repos.owned, memory_path)
    block = next((r for r in owned if str(r.get("full_name") or "").lower() == full.lower()), None)
    repo = github_repos.Repo.from_block(block) if block else None
    if repo is None:
        repo = await _record(full)

    async def write():
        if request.project:
            try:
                paths = await asyncio.to_thread(github_repos.link_project, memory_path, request.project, repo)
            except LookupError as exc:
                raise HTTPException(404, f"{request.project!r} is not a project page") from exc
            await _commit(memory_path, paths, "Repository linked to its project")
            return request.project, False
        try:
            eid, paths = await asyncio.to_thread(github_repos.make_project, memory_path, repo, via=request.via)
        except project_ownership.OwnershipError as exc:
            raise HTTPException(409, str(exc)) from exc
        await _commit(memory_path, paths, "Project made from a repository")
        return eid, True

    project, created = await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(BUSY))
    return RepoProjectResponse(project=project, created=created)


@router.get("/entities/{entity_id}/repository", response_model=RepoDetail)
async def get_repository(entity_id: str, settings: Settings = Depends(get_settings)):
    """A repository page's card (or a project's, once linked): GitHub's record as the page keeps it, the project it
    is, and its README preview — kept outside every bank, read through the API when missing or a week old while the
    picture-fetch gate is on (the page's open is the person's view, like its logo). 404 for any other page."""
    memory_path = settings.memory_path
    page = memory_path / "entities" / f"{entity_id}.md"
    if not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    fm = (await asyncio.to_thread(markdown_parser.parse, page)).frontmatter
    block = github_repos.page_repo(fm)
    if block is None:
        raise HTTPException(404, f"{entity_id!r} is not a repository")
    readme = await github_repos.ensure_readme(memory_path, entity_id, block, allowed=media_preview.fetch_allowed())
    match = None
    if not github_repos.is_repository_page(fm):
        match = RepoProject(project=entity_id, name=str(fm.get("name") or entity_id), how="linked")
    elif block.get("owned"):
        found = await asyncio.to_thread(github_repos.project_match, memory_path, str(block["full_name"]),
                                        salt=github_repos._salt())
        match = RepoProject(**found) if found else None
    state = github_repos.readme_state(readme)
    if readme and readme.get("none"):
        state = "none"
    return RepoDetail(**_row(block, project=match).model_dump(exclude={"entity_id"}), entity_id=entity_id,
                      readme=Readme(state=state, text=(readme or {}).get("text"),
                                    truncated=bool((readme or {}).get("truncated")),
                                    path=(readme or {}).get("path"), fetched_at=(readme or {}).get("fetched_at")))

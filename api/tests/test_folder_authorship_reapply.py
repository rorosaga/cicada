"""F2-back R-B6 … R-B8 — a changed authorship rule re-derives the folder's
existing episodes in place, with no re-post from the app: same bytes, same hash,
the stager's own queue rule, one `user` commit."""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, folder_source as fs, git_service, markdown_parser, provenance
from api.services.claims import parse_claims

REFS = "## Retrieval\n\n- [Paper Alpha](https://arxiv.org/abs/2401.00001) — the architecture alpha-project builds on\n"
ALPHA = "media-arxiv-2401-00001"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _body(files):
    return {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                      for f in files], "deleted": []}


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Cicada Test")
    monkeypatch.setattr(git_service, "_sleep", lambda _d: None)
    return memory


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _folder(bank):
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")


def _episode(bank, folder, rel):
    bank_index.invalidate()
    sid = f"folder:{folder['id']}:{rel}"
    for path in (bank / "episodes").glob("ep_*.md"):
        parsed = markdown_parser.parse(path)
        if parsed.frontmatter.get("source_id") == sid:
            return path, parsed
    raise AssertionError(sid)


def _stage(bank, folder, *files):
    fs.sync(bank, folder, list(files), [])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "staged")


# --- the rule, unit by unit (R-B6, R-B7) -------------------------------------


def test_an_agent_file_becomes_the_owners_and_is_queued(bank):
    folder = _folder(bank)
    _stage(bank, folder, _file("archive/sweep.md", "A sweep about alpha-project."))
    path, before = _episode(bank, folder, "archive/sweep.md")
    assert (before.frontmatter["evidence_kind"], before.frontmatter["processed"]) == ("assistant", True)
    fs.update(bank, folder["id"], authorship=[])
    out = fs.reapply_authorship(bank, folder["id"])
    _, after = _episode(bank, folder, "archive/sweep.md")
    fm = after.frontmatter
    assert (fm["authorship"], fm["evidence_kind"], fm["processed"]) == ("user", "user", False)
    assert "processed_by" not in fm
    assert fm["content_hash"] == before.frontmatter["content_hash"]
    assert after.body == before.body and evidence.body_hash(after.body) == evidence.body_hash(before.body)
    assert (out["to_owner"], out["to_agent"], out["paths"]) == (1, 0, [f"episodes/{path.name}"])


def test_an_unread_owner_file_becomes_the_agents_and_is_parked(bank):
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert (fm["authorship"], fm["evidence_kind"], fm["processed"], fm["processed_by"]) == (
        "agent", "assistant", True, "parser")


def test_what_sleep_already_read_is_relabelled_and_never_requeued_or_parked(bank):
    """R-B7 / G104: its claims exist either way; consolidating it twice repeats G104's defect."""
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    path, parsed = _episode(bank, folder, "notes.md")
    markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert (fm["evidence_kind"], fm["processed"], fm["processed_by"]) == ("assistant", True, "sleep")
    fs.update(bank, folder["id"], authorship=[])
    fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert (fm["evidence_kind"], fm["processed"], fm["processed_by"]) == ("user", True, "sleep")


def test_a_deleted_files_episode_follows_the_rule_and_stays_deleted(bank):
    """R-B7: a tombstone keeps its stamp, but the queue rule still holds — an
    agent's words are never queued for Sleep (R-LS10), deleted file or not; no
    paper step runs for a file that is gone."""
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    fs.sync(bank, folder, [], ["notes.md"])
    before = _episode(bank, folder, "notes.md")[1].frontmatter
    assert before["processed"] is False
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    out = fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert fm["evidence_kind"] == "assistant" and fm["source_deleted_at"] == before["source_deleted_at"]
    assert (fm["processed"], fm["processed_by"]) == (True, "parser")
    assert out["to_agent"] == 1 and out["touched"] == {}


def test_a_second_pass_changes_nothing(bank):
    folder = _folder(bank)
    _stage(bank, folder, _file("archive/sweep.md", "A sweep."))
    fs.update(bank, folder["id"], authorship=[])
    fs.reapply_authorship(bank, folder["id"])
    assert fs.reapply_authorship(bank, folder["id"]) == {"paths": [], "touched": {}, "to_owner": 0, "to_agent": 0}


def test_the_reader_reads_the_new_rule_and_every_span_stays_current(bank):
    """R-B8, verified: `/episodes/{id}/text` re-derives each turn's role and an
    asserted focus's kind from the episode's current `evidence_kind`, and the
    span minted before the flip is still `current` — nothing it points at moved."""
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    path, _ = _episode(bank, folder, "notes.md")
    minted = evidence.verify(bank, path.stem, "My notes on alpha-project")
    assert minted.kind == "user"
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    fs.reapply_authorship(bank, folder["id"])
    doc = provenance.episode_document(bank, path.stem, start=minted.start, end=minted.end, hash=minted.hash)
    assert {t.role for t in doc.turns} == {"assistant"}
    assert (doc.focus.kind, doc.focus.stale) == ("assistant", False)


# --- the route (R-B6's one commit, R-B7's papers) ------------------------------


def test_saving_new_rules_re_derives_in_one_user_commit(bank, client):
    folder = _folder(bank)
    assert client.post(f"/sources/folders/{folder['id']}/sync",
                       json=_body([_file("archive/sweep.md", "A sweep.")])).status_code == 200
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "staged")
    path, _ = _episode(bank, folder, "archive/sweep.md")
    r = client.put(f"/sources/folders/{folder['id']}", json={"authorship": []})
    assert r.status_code == 200, r.text
    body = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: user" in body and "trigger: folder/authorship" in body
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        ["sources/folders.json", f"episodes/{path.name}"])
    assert _git(bank, "status", "--porcelain") == ""


def test_the_apps_re_post_after_saving_finds_nothing_to_do(bank, client):
    folder = _folder(bank)
    sweep = _file("archive/sweep.md", "A sweep.")
    client.post(f"/sources/folders/{folder['id']}/sync", json=_body([sweep]))
    client.put(f"/sources/folders/{folder['id']}", json={"authorship": []})
    again = client.post(f"/sources/folders/{folder['id']}/sync", json=_body([sweep])).json()
    assert (again["filesUnchanged"], again["updated"]) == (1, 0)


def test_a_papers_why_moves_with_the_file(bank, client):
    folder = _folder(bank)
    client.post(f"/sources/folders/{folder['id']}/sync", json=_body([_file("refs.md", REFS)]))
    client.put(f"/sources/folders/{folder['id']}", json={"authorship": [{"glob": "refs.md", "authorship": "agent"}]})
    saved = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{ALPHA}.md").body)
             if c.predicate == "saved-because"]
    closed = [c for c in saved if c.valid_to]
    (open_,) = [c for c in saved if not c.valid_to]
    assert [c.observer for c in closed] == ["owner"]
    assert (open_.observer, open_.source_trust, open_.evidence[0].kind) == ("agent", "agent_reflected", "assistant")


def test_while_sleep_runs_the_paper_step_waits(bank, client, monkeypatch):
    from api.services import sleep_cycle

    folder = _folder(bank)
    client.post(f"/sources/folders/{folder['id']}/sync", json=_body([_file("refs.md", REFS)]))
    before = (bank / "entities" / f"{ALPHA}.md").read_text(encoding="utf-8")
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    client.put(f"/sources/folders/{folder['id']}", json={"authorship": [{"glob": "refs.md", "authorship": "agent"}]})
    assert _episode(bank, folder, "refs.md")[1].frontmatter["evidence_kind"] == "assistant"
    assert fs.get_folder(bank, folder["id"])["papers_pending"] is True
    assert (bank / "entities" / f"{ALPHA}.md").read_text(encoding="utf-8") == before

"""G132 phase 1 — the home's pack (ruling 51a): a git bundle of have..HEAD, or the whole history for a first copy, made
read-only on the bank and never carrying a derived or untracked file. Synthetic banks only."""
from __future__ import annotations

import subprocess

from _sync_home import auth, device_token, git, hand_commit, home  # noqa: F401 — the fixture


def _clone(bundle, dest):
    subprocess.run(["git", "clone", "-q", str(bundle), str(dest)], check=True, capture_output=True)
    return dest


def test_a_first_copy_and_a_fast_forward_round_trip(home, tmp_path):  # noqa: F811
    client, master, bank = home
    token = device_token(client, master)
    first = client.get("/sync/pack", headers=auth(token))
    assert first.status_code == 200 and first.headers["content-type"] == "application/x-git-bundle"
    seq = int(first.headers["X-Cicada-Seq"])
    head = first.headers["X-Cicada-Head"]
    (tmp_path / "first.bundle").write_bytes(first.content)
    replica = _clone(tmp_path / "first.bundle", tmp_path / "replica")
    assert git(replica, "rev-parse", "HEAD").strip() == head == git(bank, "rev-parse", "HEAD").strip()

    newer = hand_commit(bank, "entities/page-new.md", "new\n")
    delta = client.get("/sync/pack", params={"have": head}, headers=auth(token))
    assert delta.status_code == 200 and int(delta.headers["X-Cicada-Seq"]) == seq + 1
    (tmp_path / "delta.bundle").write_bytes(delta.content)
    assert len(delta.content) < len(first.content)
    git(replica, "fetch", "-q", str(tmp_path / "delta.bundle"), "HEAD:refs/cicada/home")
    assert git(replica, "rev-parse", "refs/cicada/home").strip() == newer
    # Nothing new since the head: no content.
    assert client.get("/sync/pack", params={"have": newer}, headers=auth(token)).status_code == 204


def test_derived_and_untracked_files_never_travel(home, tmp_path):  # noqa: F811
    client, master, bank = home
    for name in ("vector_index.db", "search_index.db", ".awake", "notes-untracked.md"):
        (bank / name).write_text("never published\n", encoding="utf-8")
    (bank / "episodes" / "ep_2026-09-03_001.md").write_text("---\nid: x\n---\nuncommitted\n", encoding="utf-8")
    before = git(bank, "status", "--porcelain")
    r = client.get("/sync/pack", headers=auth(master))
    assert r.status_code == 200
    (tmp_path / "all.bundle").write_bytes(r.content)
    replica = _clone(tmp_path / "all.bundle", tmp_path / "replica")
    tracked = set(git(replica, "ls-files").split())
    for name in ("vector_index.db", "search_index.db", ".awake", "notes-untracked.md",
                 "episodes/ep_2026-09-03_001.md"):
        assert name not in tracked
    # Read-only on the home: the same status, no ref or index moved.
    assert git(bank, "status", "--porcelain") == before
    assert not (bank / ".git" / "index.lock").exists()


def test_an_unknown_base_answers_404_and_the_replica_asks_again(home):  # noqa: F811
    client, master, _bank = home
    r = client.get("/sync/pack", params={"have": "0" * 40}, headers=auth(master))
    assert r.status_code == 404 and r.json()["code"] == "unknown_base"
    r = client.get("/sync/pack", params={"have": "not-a-sha"}, headers=auth(master))
    assert r.status_code == 404 and r.json()["code"] == "unknown_base"

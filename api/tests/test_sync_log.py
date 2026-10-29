"""G132 phase 1 — the home's log (ruling 51a/e3): a commit's seq is its first-parent position, the same everywhere,
derived with no trailer; the sidecar is disposable; a hand rewrite freezes publishing until "publish from here"; the
log carries no subject, path or title. Synthetic banks only."""
from __future__ import annotations

from _sync_home import auth, device_token, git, hand_commit, home  # noqa: F401 — the fixture
from api.services import sync_log, sync_publish


def _env(tmp_path, monkeypatch):
    from _synthetic_bank import _bank

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "on")
    return _bank(tmp_path)


def test_seq_is_the_first_parent_position_and_only_grows(tmp_path, monkeypatch):
    bank = _env(tmp_path, monkeypatch)
    assert sync_log.update(bank).seq == 1
    shas = [hand_commit(bank, f"entities/page-{i}.md", f"page {i}\n") for i in range(4)]
    head = sync_log.update(bank)
    assert head.seq == 5 and head.sha == shas[-1]
    assert head.seq == int(git(bank, "rev-list", "--first-parent", "--count", "HEAD"))
    _, entries, more = sync_log.since(bank, 0, 10)
    assert [e["seq"] for e in entries] == [1, 2, 3, 4, 5] and not more
    assert [e["sha"] for e in entries[1:]] == shas
    assert all(e["parent"] == p["sha"] for p, e in zip(entries, entries[1:]))


def test_since_and_limit_page_the_log(tmp_path, monkeypatch):
    bank = _env(tmp_path, monkeypatch)
    for i in range(6):
        hand_commit(bank, f"entities/page-{i}.md", f"page {i}\n")
    head, first, more = sync_log.since(bank, 0, 3)
    assert head.seq == 7 and [e["seq"] for e in first] == [1, 2, 3] and more
    _, second, more = sync_log.since(bank, 3, 3)
    assert [e["seq"] for e in second] == [4, 5, 6] and more
    _, last, more = sync_log.since(bank, 6, 3)
    assert [e["seq"] for e in last] == [7] and not more


def test_the_sidecar_rebuilds_the_same_seqs_after_it_is_deleted(tmp_path, monkeypatch):
    bank = _env(tmp_path, monkeypatch)
    for i in range(3):
        hand_commit(bank, f"entities/page-{i}.md", f"page {i}\n")
    _, before, _ = sync_log.since(bank, 0)
    db = sync_publish.bank_dir(bank) / sync_log.DB_FILE
    db.unlink()
    _, after, _ = sync_log.since(bank, 0)
    assert after == before


def test_a_hand_amend_freezes_publishing_until_the_person_publishes_from_here(tmp_path, monkeypatch):
    bank = _env(tmp_path, monkeypatch)
    hand_commit(bank, "entities/page-a.md", "a\n")
    published = sync_log.update(bank)
    git(bank, "commit", "-q", "--amend", "-m", "amended by hand")
    try:
        sync_log.update(bank)
        raise AssertionError("an amended history must freeze")
    except sync_log.HistoryRewritten as exc:
        assert exc.last_seq == published.seq and exc.last_sha == published.sha
        assert exc.body()["code"] == "history_rewritten" and "publish from here" in exc.body()["detail"]
    # Frozen stays frozen: a new commit on top heals nothing on its own.
    hand_commit(bank, "entities/page-b.md", "b\n")
    assert sync_log.state(bank)["state"] == "history_rewritten"
    head = sync_log.publish_from_here(bank)
    assert head.seq == 3 and sync_log.state(bank)["state"] == "publishing"


def test_a_reset_to_an_older_commit_freezes_too(tmp_path, monkeypatch):
    bank = _env(tmp_path, monkeypatch)
    hand_commit(bank, "entities/page-a.md", "a\n")
    sync_log.update(bank)
    git(bank, "reset", "-q", "--hard", "HEAD~1")
    assert sync_log.state(bank)["state"] == "history_rewritten"


def test_the_route_serves_ids_never_subjects_or_paths(home):  # noqa: F811
    client, master, bank = home
    hand_commit(bank, "entities/secret-page.md", "x\n", subject="Subject that names secret-page")
    token = device_token(client, master)
    r = client.get("/sync/log", params={"since": 0}, headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["head"]["seq"] == len(body["entries"]) and not body["more"]
    assert set(body["entries"][0]) == {"seq", "sha", "parent", "at"}
    assert "secret" not in r.text and "Subject" not in r.text
    git(bank, "commit", "-q", "--amend", "-m", "rewritten")
    frozen = client.get("/sync/log", headers=auth(token))
    assert frozen.status_code == 409 and frozen.json()["code"] == "history_rewritten"
    # "Publish from here" is the person's act on the home: the server's own token only.
    assert client.post("/sync/publish/from-here", headers=auth(token)).status_code == 403
    assert client.post("/sync/publish/from-here", headers=auth(master)).status_code == 200
    assert client.get("/sync/log", headers=auth(token)).status_code == 200


def test_a_capture_device_is_refused_and_a_full_one_reads(home):  # noqa: F811
    client, master, _bank = home
    phone = device_token(client, master, "phone", kind="capture")
    for path in ("/sync/log", "/sync/pack", "/sync/status"):
        assert client.get(path, headers=auth(phone)).status_code == 403
    assert client.get("/sync/log", headers=auth(master)).status_code == 200


def test_packed_commits_are_read_by_git_log_with_the_same_seqs(tmp_path, monkeypatch):
    bank = _env(tmp_path, monkeypatch)
    sync_log.update(bank)
    for i in range(3):
        hand_commit(bank, f"entities/page-{i}.md", f"page {i}\n")
    git(bank, "gc", "-q")    # nothing loose: the zlib walk hands over to git log
    assert sync_log._loose_commit(bank, git(bank, "rev-parse", "HEAD").strip()) is None
    head = sync_log.update(bank)
    assert head.seq == int(git(bank, "rev-list", "--first-parent", "--count", "HEAD")) == 4
    newer = hand_commit(bank, "entities/page-x.md", "x\n")
    assert sync_log._loose_commit(bank, newer) is not None and sync_log.update(bank).seq == 5

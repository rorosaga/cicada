"""G133 — a watched folder, backend half (R-F1, R-F2, R-LS8 … R-LS13, R-LS25, R-LS29)."""
from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, entity_extractor, folder_source as fs
from api.services import markdown_parser, source_overview, sync_service

GLOB_TABLE = [
    # (pattern, relpath, matches) — Task 6's FolderGlobTests runs this SAME table.
    ("**/*.md", "README.md", True),
    ("**/*.md", "research/plan.md", True),
    ("**/*.md", "notes.txt", False),
    ("*.md", "research/plan.md", False),
    ("archive/**", "archive/2026-01/sweep.md", True),
    ("archive/**", "research/archive/x.md", False),
    ("**/.git/**", ".git/HEAD", True),
    ("**/.git/**", "sub/.git/config", True),
    ("**/node_modules/**", "web/node_modules/a/b.md", True),
    ("docs/?.md", "docs/a.md", True),
    ("docs/?.md", "docs/ab.md", False),
]


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(relpath=rel, mtime=mtime, sha256=hashlib.sha256(raw).hexdigest(),
                           content_b64=base64.b64encode(raw).decode())


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _folder(bank):
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")


def _episodes(bank):
    bank_index.invalidate()
    return {markdown_parser.parse(p).frontmatter.get("source_id"): markdown_parser.parse(p)
            for p in (bank / "episodes").glob("ep_*.md")}


@pytest.mark.parametrize("pattern, rel, expected", GLOB_TABLE)
def test_globs(pattern, rel, expected):
    assert fs.glob_match(pattern, rel) is expected


@pytest.mark.parametrize("raw", ["/etc/passwd", "../up.md", "a/../b.md", "a//b.md", "", "a\x00b.md"])
def test_unsafe_relpaths_are_refused(raw):
    assert fs.clean_relpath(raw) is None


def test_the_split_threshold_is_four_stage1_chunks():
    assert fs.STAGE1_CHUNK == entity_extractor.CHUNK_SIZE
    assert fs.STAGE1_OVERLAP == entity_extractor.CHUNK_OVERLAP
    assert fs.SPLIT_CHARS == 4 * entity_extractor.CHUNK_SIZE


def test_register_is_an_upsert_with_a_readable_id_and_default_rules(bank):
    a = _folder(bank)
    b = fs.register(bank, label="renamed", path="/Users/example/alpha-project", device="mac-1")
    assert a["id"] == b["id"] and a["id"].startswith("alpha-project-") and b["label"] == "renamed"
    assert b["authorship"] == [{"glob": "archive/**", "authorship": "agent"}]
    assert [f["id"] for f in fs.list_folders(bank)] == [a["id"]]


def test_one_episode_per_file_with_authorship_and_mtime(bank):
    folder = _folder(bank)
    out = fs.sync(bank, folder, [_file("README.md", "# alpha-project\nOur plan."),
                                 _file("archive/2026-01/sweep.md", "An agent's sweep.")], [])
    assert (out["created"], out["files_new"], out["agent_files"]) == (2, 2, 1)
    eps = _episodes(bank)
    mine = eps[f"folder:{folder['id']}:README.md"].frontmatter
    theirs = eps[f"folder:{folder['id']}:archive/2026-01/sweep.md"].frontmatter
    assert (mine["processed"], mine["evidence_kind"], mine["authorship"]) == (False, "user", "user")
    assert (theirs["processed"], theirs["processed_by"], theirs["evidence_kind"]) == (True, "parser", "assistant")
    assert mine["timestamp"].startswith("2025-08-") and mine["origin"] == "folder"
    assert mine["relpath"] == "README.md" and mine["folder_id"] == folder["id"]


def test_resync_of_the_same_bytes_writes_nothing(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "v1")], [])
    before = {p.name: p.stat().st_mtime_ns for p in (bank / "episodes").glob("*.md")}
    out = fs.sync(bank, folder, [_file("README.md", "v1")], [])
    assert out["files_unchanged"] == 1 and out["created"] == out["updated"] == 0
    assert {p.name: p.stat().st_mtime_ns for p in (bank / "episodes").glob("*.md")} == before


def test_an_edit_rewrites_in_place_and_requeues(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "v1")], [])
    ep_id = _episodes(bank)[f"folder:{folder['id']}:README.md"].frontmatter["id"]
    out = fs.sync(bank, folder, [_file("README.md", "v2", mtime=1_756_100_000.0)], [])
    assert out["updated"] == 1
    fm = _episodes(bank)[f"folder:{folder['id']}:README.md"].frontmatter
    assert fm["id"] == ep_id and fm["processed"] is False


def test_a_rename_keeps_identity_and_a_delete_only_stamps(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("a.md", "same bytes"), _file("b.md", "other")], [])
    out = fs.sync(bank, folder, [_file("docs/a.md", "same bytes")], ["a.md", "b.md"])
    assert (out["renamed"], out["tombstoned"], out["created"]) == (1, 1, 0)
    eps = _episodes(bank)
    assert eps[f"folder:{folder['id']}:docs/a.md"].frontmatter["relpath"] == "docs/a.md"
    gone = eps[f"folder:{folder['id']}:b.md"]
    assert gone.frontmatter["source_deleted_at"] and gone.body == "other"
    assert fs.live_file_count(bank, folder["id"]) == 1


def test_a_long_file_splits_on_h2_and_an_edit_touches_one_section(bank):
    folder = _folder(bank)
    pad = "word " * (fs.SPLIT_CHARS // 10)
    text = f"Intro line.\n\n## Retrieval\n{pad}\n\n## Evaluation\n{pad}\n"
    fs.sync(bank, folder, [_file("REFERENCES.md", text)], [])
    base = f"folder:{folder['id']}:REFERENCES.md"
    assert set(_episodes(bank)) == {f"{base}#intro", f"{base}#retrieval", f"{base}#evaluation"}
    edited = text.replace("## Evaluation\n", "## Evaluation\nOne more line.\n")
    out = fs.sync(bank, folder, [_file("REFERENCES.md", edited, mtime=1_756_200_000.0)], [])
    assert (out["updated"], out["created"]) == (1, 0)


def test_a_triple_dash_in_a_path_or_heading_keeps_the_episode_readable(bank):
    """L final review (finding 2): the relpath, the title and a section heading
    ride in the frontmatter, and `markdown_parser.parse` used to split on the
    first two `---` anywhere — a YAML error, an episode `bank_index` skipped, and
    a SECOND episode on the next edit because the stager never saw the first."""
    folder = _folder(bank)
    pad = "word " * (fs.SPLIT_CHARS // 10)
    long_text = f"Intro.\n\n## Plan---draft\n{pad}\n\n## Notes\n{pad}\n"
    fs.sync(bank, folder, [_file("archive/2026-09-01---sweep.md", "v1"),
                           _file("plans/a---b.md", long_text)], [])
    eps = _episodes(bank)
    short = f"folder:{folder['id']}:archive/2026-09-01---sweep.md"
    assert eps[short].frontmatter["relpath"] == "archive/2026-09-01---sweep.md"
    assert eps[short].body == "v1"
    assert f"folder:{folder['id']}:plans/a---b.md#plan-draft" in eps or any(
        k.startswith(f"folder:{folder['id']}:plans/a---b.md#plan") for k in eps)
    count = len(list((bank / "episodes").glob("ep_*.md")))

    out = fs.sync(bank, folder, [_file("archive/2026-09-01---sweep.md", "v2", mtime=1_756_100_000.0),
                                 _file("plans/a---b.md", long_text.replace("## Notes\n", "## Notes\nMore.\n"),
                                       mtime=1_756_100_000.0)], [])
    assert (out["updated"], out["created"]) == (2, 0)
    assert len(list((bank / "episodes").glob("ep_*.md"))) == count
    assert _episodes(bank)[short].body == "v2"


def test_parse_splits_only_on_whole_line_fences(tmp_path):
    p = tmp_path / "ep.md"
    markdown_parser.write(p, {"title": "alpha --- beta", "relpath": "a---b.md"}, "body --- text\n---\nmore")
    parsed = markdown_parser.parse(p)
    assert parsed.frontmatter == {"title": "alpha --- beta", "relpath": "a---b.md"}
    assert parsed.body == "body --- text\n---\nmore"
    (tmp_path / "empty.md").write_text("---\n---\n\nbody\n", encoding="utf-8")
    assert markdown_parser.parse(tmp_path / "empty.md").body == "body"


def test_preview_counts_and_writes_nothing(bank):
    folder = _folder(bank)
    out = fs.sync(bank, folder, [_file("README.md", "x" * 30_000), _file("archive/s.md", "y")], [],
                  preview=True)
    assert out["preview"] is True and out["files_new"] == 2 and out["agent_files"] == 1
    assert out["stage1_passes"] == 3  # ceil(30000 / 11500) for the one owner file
    assert list((bank / "episodes").glob("*.md")) == []


def test_bad_files_are_reported_not_staged(bank):
    folder = _folder(bank)
    bad_sha = fs.IncomingFile("a.md", 1.0, "0" * 64, base64.b64encode(b"x").decode())
    out = fs.sync(bank, folder, [bad_sha, _file(".git/config", "x"), _file("../up.md", "x")], [])
    assert sorted(e["reason"] for e in out["errors"]) == ["checksum mismatch", "excluded", "unsafe path"]
    assert out["created"] == 0


def test_flipping_a_glob_to_user_requeues_the_parser_only_files(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("archive/s.md", "sweep")], [])
    folder = fs.update(bank, folder["id"], authorship=[])
    out = fs.sync(bank, folder, [_file("archive/s.md", "sweep")], [])
    assert out["updated"] == 1
    fm = _episodes(bank)[f"folder:{folder['id']}:archive/s.md"].frontmatter
    assert fm["processed"] is False and fm["evidence_kind"] == "user"


def test_ensure_project_matches_by_name_or_creates_with_paths(bank):
    markdown_parser.write(bank / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project"}, "## Summary\nx")
    assert fs.ensure_project(bank, "Alpha Project", path="/p", device="mac-1") == ("alpha-project", False)
    eid, created = fs.ensure_project(bank, "beta-notes", path="/Users/example/beta", device="mac-1")
    fm = markdown_parser.parse(bank / "entities" / f"{eid}.md").frontmatter
    assert created and fm["type"] == "project"
    assert fm["paths"] == [{"path": "/Users/example/beta", "device": "mac-1"}]


def test_the_channel_row_and_the_sources_card(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "hello")], [])
    from api.services import sync_state
    sync_state.record_sync(bank, fs.channel_id(folder["id"]), count=fs.live_file_count(bank, folder["id"]))
    rows = channel_registry.build_channels(bank, telegram_enabled=False)
    fixed = [r["id"] for r in rows][: len(channel_registry.CHANNEL_IDS)]
    assert fixed == list(channel_registry.CHANNEL_IDS)  # R-LS25: the fixed list never moves
    row = rows[-1]
    assert row["id"] == f"folder:{folder['id']}" and row["label"] == "alpha-project"
    assert row["actions"] == ["sync", "manage"] and row["count"] == 1 and row["count_noun"] == "note"
    bank_index.invalidate()
    card = next(r for r in source_overview.build_overview(bank, channels=rows)
                if r["id"] == f"folder:{folder['id']}")
    assert (card["label"], card["kind"], card["mark"], card["episodes"]) == ("alpha-project", "import", "folder", 1)


# Every channel id the registry can emit with `sync` that the APP routes. The
# Swift twin is `ChannelSyncRoutingTests.registrySyncIds` (a folder id stands
# in for the `folder:` family): a new `sync` row must land in both lists and
# get a handler in `ChannelActions.syncRoute`, or its "Sync now" throws
# "Unknown channel <id>" at the person — the L final review's finding 1.
# round 4 (G142): `calendar-local` — the app's EventKit reader (feat/r4-foundations-app) owns its `syncRoute`.
# round 4 (C9): the Chromium family beyond Chrome — `BrowserInventory` routes each to the app's browser reader.
APP_SYNC_ROUTED = {
    "chrome-bookmarks", "safari-bookmarks", "safari-tabs", "notes",
    "pinterest", "reddit", "x", "folder:*", "wispr-flow", "calendar-local",
    # round 4 (C9): rows that appear once synced — the test gives each a sync.
    "brave-bookmarks", "vivaldi-bookmarks", "comet-bookmarks", "dia-bookmarks",
}
#: Round-4 rows the registry emits only once synced (R-SR15).
ONCE_SYNCED = ("brave-bookmarks", "vivaldi-bookmarks", "comet-bookmarks", "dia-bookmarks")


def test_every_sync_row_the_registry_can_emit_is_one_the_app_routes(bank):
    from api.services import sync_state, wispr_flow
    _folder(bank)
    wispr_flow.save_settings(bank, enabled=True, include_dictation=False, owner_speaker_names=[])
    for channel in ONCE_SYNCED:
        sync_state.record_sync(bank, channel, count=1)
    every_connector = {cid: True for cid in channel_registry.ADAPTERS}
    rows = channel_registry.build_channels(bank, telegram_enabled=True, connectors_connected=every_connector)
    emitted = {("folder:*" if r["id"].startswith("folder:") else r["id"])
               for r in rows if "sync" in r["actions"]}
    assert emitted == APP_SYNC_ROUTED


def test_registering_moves_the_sources_component(bank):
    before = sync_service.components(bank)["sources"]
    _folder(bank)
    assert sync_service.components(bank)["sources"] != before  # R-LS29


@pytest.fixture
def client(bank, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def test_the_routes(client):
    c, bank = client
    r = c.post("/sources/folders", json={"label": "alpha-project", "path": "/Users/example/alpha-project",
                                         "projectName": ""})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert r.json()["device"] and r.json()["channelId"] == f"folder:{fid}"
    body = {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                      for f in [_file("README.md", "hello")]], "deleted": []}
    pre = c.post(f"/sources/folders/{fid}/sync", params={"preview": "true"}, json=body).json()
    assert pre["preview"] is True and pre["filesNew"] == 1
    done = c.post(f"/sources/folders/{fid}/sync", json=body).json()
    assert done["created"] == 1
    assert any(ch["id"] == f"folder:{fid}" for ch in c.get("/sources/channels").json()["channels"])
    assert c.get("/sources/folders").json()["folders"][0]["lastSync"]
    assert c.post("/sources/folders/nope/sync", json=body).status_code == 404
    too_many = {"files": body["files"] * (fs.MAX_BATCH_FILES + 1), "deleted": []}
    assert c.post(f"/sources/folders/{fid}/sync", json=too_many).status_code == 413
    assert c.delete(f"/sources/folders/{fid}").json() == {"removed": True}
    assert list((bank / "episodes").glob("*.md")), "removing a folder never deletes its episodes"


# --- Task 2 review, round 1 ---------------------------------------------------


def test_two_overlapping_syncs_keep_both_episodes(bank):
    """The watcher's batch and a manual Sync overlap in the threadpool: without
    the lock both minted the same ``ep_<date>_NNN`` and one episode was
    overwritten, and the shared ``folders.json.tmp`` raised FileNotFoundError."""
    import threading

    folder = _folder(bank)
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def run(rel):
        try:
            barrier.wait()
            fs.sync(bank, folder, [_file(rel, f"{rel} body")], [])
        except BaseException as e:  # pragma: no cover - the failure being guarded
            errors.append(e)

    threads = [threading.Thread(target=run, args=(rel,)) for rel in ("a.md", "b.md")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    files = sorted((bank / "episodes").glob("ep_*.md"))
    assert len(files) == 2 and len({p.name for p in files}) == 2
    assert set(_episodes(bank)) == {f"folder:{folder['id']}:a.md", f"folder:{folder['id']}:b.md"}


def test_concurrent_registry_saves_never_lose_a_write(bank):
    import threading

    folder = _folder(bank)
    errors: list[BaseException] = []

    def stamp(i):
        try:
            fs.set_flags(bank, folder["id"], **{f"k{i}": i})
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=stamp, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    record = fs.get_folder(bank, folder["id"])
    assert all(record.get(f"k{i}") == i for i in range(8))
    assert not list((bank / "sources").glob("*.tmp"))


def test_a_rename_across_an_authorship_glob_moves_the_queue_state(bank):
    """R-LS10 / R-F2: a rename into ``archive/**`` parks the episode as
    parser-only; a rename back out queues it for Sleep again."""
    folder = _folder(bank)
    sid_user = f"folder:{folder['id']}:notes.md"
    sid_agent = f"folder:{folder['id']}:archive/notes.md"
    fs.sync(bank, folder, [_file("notes.md", "my own words")], [])
    fm = _episodes(bank)[sid_user].frontmatter
    assert (fm["processed"], fm["evidence_kind"]) == (False, "user") and "processed_by" not in fm

    out = fs.sync(bank, folder, [_file("archive/notes.md", "my own words")], ["notes.md"])
    assert out["renamed"] == 1
    fm = _episodes(bank)[sid_agent].frontmatter
    assert (fm["evidence_kind"], fm["processed"], fm["processed_by"]) == ("assistant", True, "parser")
    again = fs.sync(bank, folder, [_file("archive/notes.md", "my own words")], [])
    assert again["files_unchanged"] == 1

    out = fs.sync(bank, folder, [_file("notes.md", "my own words")], ["archive/notes.md"])
    assert out["renamed"] == 1
    fm = _episodes(bank)[sid_user].frontmatter
    assert (fm["evidence_kind"], fm["processed"]) == ("user", False) and "processed_by" not in fm


def test_a_rename_never_unprocesses_what_sleep_consolidated(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("notes.md", "my own words")], [])
    ep = _episodes(bank)[f"folder:{folder['id']}:notes.md"]
    path = bank / "episodes" / f"{ep.frontmatter['id']}.md"
    markdown_parser.write(path, {**ep.frontmatter, "processed": True, "processed_by": "sleep"}, ep.body)
    bank_index.invalidate()
    fs.sync(bank, folder, [_file("archive/notes.md", "my own words")], ["notes.md"])
    fm = _episodes(bank)[f"folder:{folder['id']}:archive/notes.md"].frontmatter
    assert (fm["processed"], fm["processed_by"]) == (True, "sleep")


def test_a_repick_without_rules_keeps_the_rules_set_in_manage(bank):
    folder = _folder(bank)
    fs.update(bank, folder["id"], authorship=[])
    again = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")
    assert again["id"] == folder["id"] and again["authorship"] == []
    custom = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         include=["**/*.md"], exclude=["drafts/**"])
    kept = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")
    assert (kept["include"], kept["exclude"], kept["authorship"]) == (["**/*.md"], ["drafts/**"], [])
    assert custom["id"] == kept["id"]
    fresh = fs.register(bank, label="beta", path="/Users/example/beta-example", device="mac-1")
    assert fresh["authorship"] == [{"glob": "archive/**", "authorship": "agent"}]


@pytest.mark.parametrize("mtime", [1e20, -1e20, float("nan"), float("inf")])
def test_a_bad_mtime_is_one_file_error_not_a_failed_batch(bank, mtime):
    folder = _folder(bank)
    out = fs.sync(bank, folder, [_file("bad.md", "x", mtime=mtime), _file("good.md", "y")], [])
    assert out["errors"] == [{"relpath": "bad.md", "reason": "bad mtime"}]
    assert out["created"] == 1 and out["files_new"] == 1


def test_a_no_change_resync_leaves_the_registry_alone(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "v1")], [])
    reg = fs.registry_path(bank)
    before = (reg.read_bytes(), reg.stat().st_mtime_ns)
    out = fs.sync(bank, folder, [_file("README.md", "v1")], [])
    assert out["files_unchanged"] == 1 and not out["_staged"].paths
    assert (reg.read_bytes(), reg.stat().st_mtime_ns) == before

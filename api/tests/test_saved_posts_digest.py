"""G246 (ruling 81): the graph's change check stays cheap on a cold start with posts drawn as rows (`saved_posts` digest).

The verdict reads a few facts out of every page and episode header. Read from ~19,000 files in a fresh process it cost
seconds, and it is asked before any graph is built. So each file's facts are kept as a small record under the file's own
`(mtime_ns, size)`, in this process and, derived and disposable, in `derived_store` outside every bank. These tests pin that:

* the answer from records equals the old whole-bank computation (an oracle copied here) on a bank with every sign, after
  every kind of change, after a cold start from the stored records, and after a partial change;
* a cold start that finds the stored records reads no header, and a change afterwards reads only the file that moved;
* a stored record of another bank, another version or a damaged file is never read as an answer, and it is rebuilt silently;
* nothing is stored, read or moved while the constant is off, and the route's ETag with it off is byte for byte what it was;
* with it on, the route lists each folder once and its ETag moves exactly when the earned set does.

Synthetic names and words only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_saved_posts import SAVE, TALK, X, Bank, person_claim

from api.services import (bank_index, claims, derived_store, graph_builder, markdown_parser, quiet_pages, saved_posts,
                          sync_service)


@pytest.fixture(autouse=True)
def _reset():
    for fn in (bank_index.invalidate, graph_builder.reset_cache):
        fn()
    saved_posts.STORE_DIGEST = True
    yield
    saved_posts.STORE_DIGEST = True
    bank_index.invalidate()
    graph_builder.reset_cache()


class DigestBank(Bank):
    """`Bank.post` names a save by the hash of the page's name, which differs per process and can name two posts' saves
    alike: a bank with this many posts needs its saves apart."""

    def __init__(self, root: Path):
        super().__init__(root)
        self._saves = 0

    def post(self, pid="media-a-post", *, save=None, page=None, url=X, episodes=(), claim_list=None, save_body="body\n"):
        self._saves += 1
        save_id = f"ep_2026-11-20_{100 + self._saves}"
        self.episode(save_id, {"url": url, "origin": "x-bookmarks", "media_entity_id": pid, **(save or {})}, save_body)
        self.page(pid, {"name": pid.replace("-", " "), "type": "media", "status": "active",
                        "source_episodes": [save_id, *episodes], "media": {"url": url, "media_type": "url"},
                        **(page or {})}, claim_list=claim_list)
        bank_index.invalidate()
        return pid


@pytest.fixture
def bank(tmp_path):
    return DigestBank(tmp_path / "bank")


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


def status(n: int) -> str:
    return f"https://x.com/alex_example/status/{1000000000 + n}"


# ------------------------------------------------------------------------------------------------ the old computation


def oracle(memory_path: Path) -> dict[str, set[str]]:
    """What `saved_posts.state` computed before the digest: every post's signs, read from the cached headers and bodies of
    every page and episode (edges excluded: `_edge_signs` is tested apart)."""
    entities = bank_index.files(memory_path, "entities")
    episodes = bank_index.files(memory_path, "episodes")
    by_episode = {e.stem: e for e in episodes}

    def kind_of(episode_id):
        if not episode_id:
            return None
        return quiet_pages.episode_kind(by_episode[episode_id].frontmatter if episode_id in by_episode else None)

    posts = {e.stem: e for e in entities if saved_posts.is_post(e.frontmatter)}
    saves: dict[str, list] = {}
    for episode in episodes:
        page = str(episode.frontmatter.get(quiet_pages.SAVE_KEY) or "").strip()
        if page:
            saves.setdefault(page, []).append(episode)
    signs: dict[str, set[str]] = {}
    for pid, entry in posts.items():
        fm = entry.frontmatter
        out: set[str] = set()
        if fm.get("human_edited") is True or fm.get("corrections"):
            out.add("edited")
        owned = list(dict.fromkeys(quiet_pages.episode_ids(
            fm.get("source_episodes") if isinstance(fm.get("source_episodes"), list) else [])))
        mine = [by_episode.get(i) for i in owned] + [e for e in saves.get(pid, []) if e.stem not in owned]
        for found in mine:
            if found is not None and found.frontmatter.get(quiet_pages.SAVE_KEY):
                out |= saved_posts.episode_signs(found)
        if quiet_pages.lit_by_episodes(fm, kind_of):
            out.add("conversation")
        elif quiet_pages.lit_by_claims(claims.parse_claims(entry.body()), kind_of):
            out.add("claim")
        signs[pid] = out
    for e in entities:
        for target in saved_posts._tied(e.frontmatter) & posts.keys():
            signs[target].add("project")
        for target in saved_posts._taken_sources(e.frontmatter) & posts.keys():
            signs[target].add("source")
    return signs


def digest_signs(memory_path: Path) -> dict[str, set[str]]:
    return {pid: set(s) for pid, s in saved_posts.state(memory_path).signs.items()}


def agrees(bank: Bank) -> dict[str, set[str]]:
    want = oracle(bank.root)
    assert digest_signs(bank.root) == want
    return want


def rich_bank(bank: Bank) -> dict[str, str]:
    """One bank with every kind of post, work, conversation and tie, and what each is."""
    ids = {}
    ids["row"] = bank.post("media-row", url=status(1))
    ids["note"] = bank.post("media-note", url=status(2), save={"has_note": True})
    ids["why"] = bank.post("media-why", url=status(3), save={"saved_why": {"answer": "to build alpha"}})
    ids["named"] = bank.post("media-named", url=status(4), save={"named": {"why": "title", "at": "2026-11-21"}})
    ids["kept"] = bank.post("media-kept", url=status(5), save={"kept_as_page": {"at": "2026-11-22"}})
    ids["edited"] = bank.post("media-edited", url=status(6), page={"human_edited": True})
    ids["agent"] = bank.post("media-agent", url=status(7), save={"has_note": True, "session_id": "s", "harness": "claude-code"})
    ids["folder"] = bank.post("media-folder", url=status(8), save={"readable_by_folder": {"at": "2026-11-21"}})
    bank.episode(TALK, {"source": "claude-code"}, "user: the post was useful\n")
    ids["talk"] = bank.post("media-talk", url=status(9), episodes=[TALK])
    ids["claim"] = bank.post("media-claim", url=status(10), claim_list=[person_claim(SAVE)])
    ids["external"] = bank.post("media-external", url=status(11), claim_list=[claims.Claim(
        id="c2", text="x", subject="a", observer="external:alex_example",
        evidence=[claims.Evidence(episode=SAVE, start=0, end=4, kind="user")])])
    ids["cited"] = bank.post("media-cited", url=status(12), claim_list=[claims.Claim(
        id="c3", text="x", subject="a", observer="agent",
        evidence=[claims.Evidence(episode=TALK, start=0, end=4, kind="reasoning")])])
    ids["tied"] = bank.post("media-tied", url=status(13))
    ids["sourced"] = bank.post("media-sourced", url=status(14))
    ids["proposed"] = bank.post("media-proposed", url=status(15))
    ids["old"] = bank.post("media-old", url=status(16), save={"has_note": True, "origin": "x-bookmarks"},
                           save_body="# A post\n\n## User note\nThe post's own text.\n")
    ids["work"] = bank.post("media-work", url="https://example.com/an-article")
    bank.episode("ep_2026-11-22_900", {"has_note": True, "media_entity_id": ids["row"], "origin": "web"})
    bank.page("alpha-project", {"name": "Alpha project", "type": "project", "status": "active",
                                "entities_added": [ids["tied"], {"entity": ids["proposed"], "proposed": True}]})
    bank.page("alpha-tool", {"name": "Alpha tool", "type": "tool", "status": "active",
                             "sources": [{"url": "https://example.com", "entity": ids["sourced"]}]})
    for i in range(30):
        bank.episode(f"ep_2026-11-23_{i:03d}", {"source": "claude-code"}, "user: an unrelated chat\n")
    bank_index.invalidate()
    return ids


# ------------------------------------------------------------------------------------------------ the same answer


def test_the_digest_agrees_with_the_whole_bank_computation_on_every_sign(bank):
    ids = rich_bank(bank)
    want = agrees(bank)
    assert want[ids["row"]] == {"note"}                      # the repeat note on an already saved link
    assert want[ids["agent"]] == set() and want[ids["folder"]] == set() and want[ids["old"]] == set()
    assert want[ids["tied"]] == {"project"} and want[ids["sourced"]] == {"source"} and want[ids["proposed"]] == set()
    assert want[ids["claim"]] == {"claim"} and want[ids["talk"]] == {"conversation"} and want[ids["cited"]] == {"claim"}
    assert ids["work"] not in want


def mutations(bank: Bank, ids: dict[str, str]):
    """Each is one change a bank sees; the answer must follow after every one."""
    root = bank.root

    def rewrite(episode_id, **more):
        path = root / "episodes" / f"{episode_id}.md"
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, {**parsed.frontmatter, **more}, parsed.body)

    save_of = lambda pid: next(p.stem for p in (root / "episodes").glob("*.md")   # noqa: E731
                               if f"media_entity_id: {pid}" in p.read_text())
    yield "a why-answer on a save", lambda: rewrite(save_of(ids["row"]), saved_why={"answer": "x"})
    yield "a note is taken back", lambda: rewrite(save_of(ids["note"]), has_note=False)
    yield "a post is kept as a page", lambda: rewrite(save_of(ids["agent"]), kept_as_page={"at": "2026-11-23"})
    yield "a claim is withdrawn", lambda: bank.page(ids["claim"], {"name": "x", "type": "media", "status": "active",
                                                                    "source_episodes": [],
                                                                    "media": {"url": status(10), "media_type": "url"}})
    yield "a conversation is cited", lambda: bank.page(ids["folder"], {
        "name": "x", "type": "media", "status": "active", "source_episodes": [TALK],
        "media": {"url": status(8), "media_type": "url"}})
    yield "a save is deleted", lambda: (root / "episodes" / f"{save_of(ids['why'])}.md").unlink()
    yield "a post page is deleted", lambda: (root / "entities" / f"{ids['named']}.md").unlink()
    yield "a new post", lambda: bank.post("media-new", url=status(99), save={"saved_why": {"answer": "y"}})
    yield "a tie is withdrawn", lambda: bank.page("alpha-project", {"name": "Alpha project", "type": "project",
                                                                     "status": "active"})
    yield "an unrelated capture", lambda: bank.episode("ep_2026-11-24_001", {"source": "claude-code"}, "user: hi\n")
    yield "a page that is no post", lambda: bank.page("beta-tool", {"name": "Beta", "type": "tool", "status": "active"})


def test_the_answer_follows_every_kind_of_change(bank):
    ids = rich_bank(bank)
    agrees(bank)
    for label, change in mutations(bank, ids):
        change()
        bank_index.invalidate()
        try:
            agrees(bank)
        except AssertionError:
            raise AssertionError(f"after {label}") from None


def test_a_cold_start_from_the_stored_records_gives_the_same_answer_and_reads_no_header(bank):
    rich_bank(bank)
    want = agrees(bank)
    saved_posts.persist_now(bank.root)
    assert derived_store.path_of(bank.root, "saved_posts").is_file()
    saved_posts.forget(bank.root, stored=False)       # a fresh process: nothing held
    bank_index.invalidate()
    before = bank_index.parse_count
    assert digest_signs(bank.root) == want
    assert saved_posts.verdict(bank.root).stamp == saved_posts.verdict(bank.root).stamp
    assert bank_index.parse_count == before            # not one header was read


def test_a_change_after_a_cold_start_reads_only_the_file_that_moved(bank):
    ids = rich_bank(bank)
    rich_stamp = saved_posts.verdict(bank.root).stamp
    saved_posts.persist_now(bank.root)
    saved_posts.forget(bank.root, stored=False)
    bank_index.invalidate()
    bank.episode("ep_2026-11-24_001", {"source": "claude-code"}, "user: an unrelated chat\n")
    before = bank_index.parse_count
    assert saved_posts.verdict(bank.root).stamp == rich_stamp          # an unrelated capture: no move
    assert bank_index.parse_count == before + 1                         # its own header, nothing else
    save = next(p.stem for p in (bank.root / "episodes").glob("*.md") if f"media_entity_id: {ids['agent']}" in p.read_text())
    parsed = markdown_parser.parse(bank.root / "episodes" / f"{save}.md")
    markdown_parser.write(bank.root / "episodes" / f"{save}.md", {**parsed.frontmatter, "saved_why": {"answer": "x"}},
                          parsed.body)
    before = bank_index.parse_count
    assert saved_posts.verdict(bank.root).stamp != rich_stamp          # a reason on a save: it moves
    assert bank_index.parse_count == before + 1
    assert digest_signs(bank.root) == oracle(bank.root)


def test_warm_a_second_ask_reads_nothing_and_a_capture_reads_one_file(bank):
    rich_bank(bank)
    saved_posts.verdict(bank.root)
    before = bank_index.parse_count
    saved_posts.verdict(bank.root)
    saved_posts.stamp(bank.root)
    assert bank_index.parse_count == before
    bank.episode("ep_2026-11-24_002", {"source": "claude-code"}, "user: hi\n")
    saved_posts.verdict(bank.root)
    assert bank_index.parse_count == before + 1


def test_an_edge_one_of_his_claims_backs_survives_a_cold_start_without_the_edge_file_parsed(bank, monkeypatch):
    pid = bank.post()
    bank.page("alpha-project", {"name": "Alpha project", "type": "project", "status": "active"},
              claim_list=[claims.Claim(id="c9", text="x", subject="alpha-project", predicate="references", object=pid,
                                       evidence=[claims.Evidence(episode=TALK, start=0, end=4, kind="user")])])
    markdown_parser.write_yaml(bank.root / "graph_edges.yaml", {"edges": [
        {"source": "alpha-project", "target": pid, "label": "references", "claim_id": "c9"},
        {"source": "alpha-project", "target": pid, "label": "about", "claim_id": "c9"},
        {"source": "alpha-project", "target": pid, "label": "references"}]})
    bank_index.invalidate()
    assert saved_posts.verdict(bank.root).signs[pid] == {"edge"}
    saved_posts.persist_now(bank.root)
    saved_posts.forget(bank.root, stored=False)
    bank_index.invalidate()
    loaded = []
    real = markdown_parser.load_yaml_file
    monkeypatch.setattr(markdown_parser, "load_yaml_file", lambda *a, **k: loaded.append(a) or real(*a, **k))
    assert saved_posts.verdict(bank.root).signs[pid] == {"edge"}
    assert loaded == []                                  # the stored rows answered: the file was not parsed again


# ------------------------------------------------------------------------------------------------ derived and disposable


def test_the_records_live_outside_the_bank_and_git_and_the_tree_stays_clean(bank):
    rich_bank(bank)
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(bank.root), *cmd], check=True, capture_output=True)
    saved_posts.verdict(bank.root)
    saved_posts.persist_now(bank.root)
    stored = derived_store.path_of(bank.root, "saved_posts")
    assert stored.is_file() and bank.root not in stored.parents and stored.stat().st_mode & 0o077 == 0
    assert subprocess.run(["git", "-C", str(bank.root), "status", "--porcelain"], capture_output=True,
                          text=True).stdout.strip() == ""
    document = json.loads(stored.read_text())
    assert document["bank"] == str(bank.root.resolve()) and set(document["data"]) <= {"ent", "epi", "edges"}
    assert not any(word in stored.read_text() for word in ("the post was useful", "to build alpha", "own text"))


@pytest.mark.parametrize("damage", ["truncated", "garbage", "another version", "another format", "not a dict", "no rows"])
def test_a_stored_record_that_is_damaged_or_stale_is_ignored_and_rebuilt_silently(bank, damage):
    rich_bank(bank)
    want = agrees(bank)
    saved_posts.persist_now(bank.root)
    path = derived_store.path_of(bank.root, "saved_posts")
    text = path.read_text()
    path.write_text({"truncated": text[: len(text) // 2], "garbage": "\x00\x01 not json",
                     "another version": text.replace(f'"tag":"{saved_posts._tag()}"', '"tag":"0:other"'),
                     "another format": text.replace('"format":1', '"format":99'),
                     "not a dict": "[1, 2, 3]", "no rows": json.dumps(
                         {"format": 1, "tag": saved_posts._tag(), "bank": str(bank.root.resolve()), "data": {"x": 1}}),
                     }[damage])
    saved_posts.forget(bank.root, stored=False)
    bank_index.invalidate()
    before = bank_index.parse_count
    assert digest_signs(bank.root) == want              # rebuilt from the bank, no error
    assert bank_index.parse_count > before


def test_a_second_bank_never_reads_the_first_banks_records(tmp_path):
    first, second = DigestBank(tmp_path / "one" / "bank"), DigestBank(tmp_path / "two" / "bank")
    rich_bank(first)
    saved_posts.verdict(first.root)
    saved_posts.persist_now(first.root)
    shutil.copytree(first.root, second.root, dirs_exist_ok=True)         # the same names, sizes and times (copy2)
    assert derived_store.folder(first.root) != derived_store.folder(second.root)
    assert derived_store.load(second.root, "saved_posts", saved_posts._tag()) is None   # none stored under its key
    # And the very file, copied under the other bank's key, is refused: it names the bank it was made from.
    derived_store.folder(second.root).mkdir(parents=True, exist_ok=True)
    shutil.copy(derived_store.path_of(first.root, "saved_posts"), derived_store.path_of(second.root, "saved_posts"))
    assert derived_store.load(second.root, "saved_posts", saved_posts._tag()) is None
    bank_index.invalidate()
    before = bank_index.parse_count
    assert digest_signs(second.root) == oracle(second.root)
    assert bank_index.parse_count > before                              # it read its own files


def test_two_banks_in_one_process_keep_their_own_answers(tmp_path):
    a, b = DigestBank(tmp_path / "a" / "bank"), DigestBank(tmp_path / "b" / "bank")
    a.post("media-a", url=status(1), save={"saved_why": {"answer": "x"}})
    b.post("media-b", url=status(1))
    assert saved_posts.verdict(a.root).earned == {"media-a"} and saved_posts.verdict(b.root).rows == {"media-b"}
    assert saved_posts.verdict(a.root).stamp != saved_posts.verdict(b.root).stamp


def settle(bank: Bank) -> None:
    """Wait for the background store a change schedules."""
    import time

    for _ in range(400):
        if not saved_posts._PERSISTED.get(str(bank.root), {}).get("busy"):
            return
        time.sleep(0.005)


def test_the_stored_file_is_rewritten_only_when_due(bank, on, monkeypatch):
    writes = []
    monkeypatch.setattr(derived_store, "save", lambda *a, **k: writes.append(a[1]) or True)
    bank.post("media-a", url=status(1))
    saved_posts.verdict(bank.root)
    settle(bank)
    assert writes == ["saved_posts"]                  # the first digest of a bank is stored at once
    bank.post("media-b", url=status(2))
    saved_posts.verdict(bank.root)
    settle(bank)
    assert writes == ["saved_posts"]                  # one file more, inside the interval: not again
    monkeypatch.setattr(saved_posts, "PERSIST_AT_ONCE", 1)
    bank.post("media-c", url=status(3))
    saved_posts.verdict(bank.root)
    settle(bank)
    assert writes == ["saved_posts", "saved_posts"]   # a larger change is stored at once


def test_a_store_that_cannot_be_written_is_no_error(bank, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", "/dev/null/never")       # nothing can be created there
    rich_bank(bank)
    assert digest_signs(bank.root) == oracle(bank.root)
    saved_posts.persist_now(bank.root)
    assert derived_store.load(bank.root, "saved_posts", saved_posts._tag()) is None


def test_with_the_store_switched_off_nothing_is_read_or_written(bank):
    rich_bank(bank)
    saved_posts.verdict(bank.root)
    saved_posts.persist_now(bank.root)
    saved_posts.forget(bank.root, stored=False)
    stored = derived_store.path_of(bank.root, "saved_posts")
    stamp = stored.stat().st_mtime_ns
    saved_posts.STORE_DIGEST = False
    bank_index.invalidate()
    before = bank_index.parse_count
    agrees(bank)
    assert bank_index.parse_count > before                         # read from the bank: the stored file was not used
    bank.post("media-more", url=status(77))
    saved_posts.verdict(bank.root)
    assert stored.stat().st_mtime_ns == stamp                      # and not rewritten


def test_forgetting_a_bank_removes_what_was_stored_for_it(bank, tmp_path):
    rich_bank(bank)
    saved_posts.verdict(bank.root)
    saved_posts.persist_now(bank.root)
    other = DigestBank(tmp_path / "other" / "bank")
    other.post(url=status(5))
    saved_posts.verdict(other.root)
    saved_posts.persist_now(other.root)
    saved_posts.forget(bank.root)
    assert not derived_store.path_of(bank.root, "saved_posts").exists() and str(bank.root) not in saved_posts._DIGESTS
    assert derived_store.path_of(other.root, "saved_posts").is_file()          # another bank's stays


def test_a_new_release_or_an_edited_rule_makes_every_stored_record_again(bank, on, monkeypatch):
    """A stored record outlives a release, and an unmoved file keeps its record indefinitely, so the tag must move with
    whatever a record is made from. The case: a source counts as Cicada's own reading in the next release; the stored
    record still calls its episode a conversation, and the post it names stays earned."""
    reading = "reading-example"
    reading_episode = "ep_2026-11-22_001"
    bank.episode(reading_episode, {"source": reading}, "user: words\n")
    pid = bank.post("media-read", url=status(61), episodes=[reading_episode])
    assert saved_posts.verdict(bank.root).signs[pid] == {"conversation"}
    saved_posts.persist_now(bank.root)
    saved_posts.forget(bank.root, stored=False)                 # a new process
    monkeypatch.setattr(quiet_pages, "CHECK_SOURCES", quiet_pages.CHECK_SOURCES | {reading})
    bank_index.invalidate()
    want = oracle(bank.root)                                    # what the new rule says
    assert want[pid] == set()
    bank_index.invalidate()
    saved_posts.forget(bank.root, stored=False)
    # Control: with the tag unmoved the old store answers, and is wrong. That is what the tag exists to prevent.
    assert saved_posts.verdict(bank.root).signs[pid] == {"conversation"}
    saved_posts.forget(bank.root, stored=False)
    bank_index.invalidate()
    monkeypatch.setattr(saved_posts, "_source_stamp", lambda: "a-later-release")   # editing the constant moves this
    before = bank_index.parse_count
    assert pid not in saved_posts.verdict(bank.root).earned
    assert digest_signs(bank.root) == want
    assert bank_index.parse_count > before                      # read from the bank: the old store was ignored


def test_the_tag_moves_with_the_release_and_with_every_module_a_record_is_made_with(tmp_path, monkeypatch):
    base = saved_posts._tag()
    monkeypatch.setattr(saved_posts, "__version__", "9.9.9")
    assert saved_posts._tag() != base                           # a new release rebuilds once
    monkeypatch.undo()
    files = [tmp_path / "rule_a.py", tmp_path / "rule_b.py"]
    for f in files:
        f.write_text("A = 1\n")
    monkeypatch.setattr(saved_posts, "_source_files", lambda: files)
    saved_posts._source_stamp.cache_clear()
    first = saved_posts._source_stamp()
    files[1].write_text("A = 2\n")                             # an edit of any one of them
    saved_posts._source_stamp.cache_clear()
    assert saved_posts._source_stamp() != first
    saved_posts._source_stamp.cache_clear()


def test_the_modules_a_record_is_made_with_are_all_named_and_found():
    """Every module the record functions reach is in the list, and each is found as a source file in a checkout."""
    named = {"quiet_pages", "save_folders", "promotion", "video_urls", "saved_lists", "episode_time", "project_ownership",
             "fact_sources", "connector_text", "history_index", "claims", "saved_posts"}
    assert named <= set(saved_posts.RECORD_MODULES)
    found = {p.stem for p in saved_posts._source_files()}
    assert found == set(saved_posts.RECORD_MODULES)


# ------------------------------------------------------------------------------------------------ dark


def test_with_the_constant_off_nothing_is_stored_and_no_record_is_made(bank):
    rich_bank(bank)
    assert saved_posts.HIDE_POSTS is False
    saved_posts.hidden_ids(bank.root)
    saved_posts.earned_ids(bank.root)
    saved_posts.stamp(bank.root)
    saved_posts.drawn_as_page(bank.root, "media-row", {"type": "media"})
    saved_posts.filter_related(bank.root, "## Related\n- [[media row]]\n")
    graph_builder.build_graph(bank.root)
    assert saved_posts._DIGESTS.get(str(bank.root)) is None
    saved_posts.verdict(bank.root)       # a caller that asks the rule whatever the constant says (the dry run, keep-as-page)
    settle(bank)
    assert not derived_store.folder(bank.root).exists()


# ------------------------------------------------------------------------------------------------ the route


@pytest.fixture
def client(bank, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank.root))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        config.get_settings.cache_clear()


KEYS = ("entities", "edges", "hubs", "inbox", "logos", "photos")
BASE = "None|None|0.0|None|True|False|"


def expected_etag(bank, *, posts: str | None, include_posts: bool = False) -> str:
    from api.routers.graph import NODE_SHAPE

    extra = f"{BASE}{NODE_SHAPE}"
    if posts is not None:
        extra += f"|posts:{include_posts}:{posts}"
    return sync_service.etag_for(bank.root, *KEYS, extra=extra)


def test_the_route_with_the_constant_off_is_byte_for_byte_what_it_was(bank, client):
    rich_bank(bank)
    assert saved_posts.HIDE_POSTS is False
    assert client.get("/graph").headers["etag"] == expected_etag(bank, posts=None)
    assert not derived_store.path_of(bank.root, "saved_posts").exists() and str(bank.root) not in saved_posts._DIGESTS


def test_the_route_with_it_on_folds_the_earned_stamp_into_the_same_digest(bank, client, on):
    rich_bank(bank)
    etag = client.get("/graph").headers["etag"]
    assert etag == expected_etag(bank, posts=saved_posts.stamp(bank.root))
    assert client.get("/graph?include_posts=true").headers["etag"] == expected_etag(
        bank, posts=saved_posts.stamp(bank.root), include_posts=True)
    assert client.get("/graph", headers={"if-none-match": etag}).status_code == 304


def test_the_route_lists_each_folder_once_with_the_constant_on(bank, client, monkeypatch):
    rich_bank(bank)
    off_etag = client.get("/graph").headers["etag"]
    listed: list[str] = []
    real = bank_index._scan_uncached
    monkeypatch.setattr(bank_index, "_scan_uncached", lambda directory: listed.append(Path(directory).name) or real(directory))
    assert client.get("/graph", headers={"if-none-match": off_etag}).status_code == 304
    off = list(listed)
    listed.clear()
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    on_etag = client.get("/graph").headers["etag"]
    listed.clear()
    assert client.get("/graph", headers={"if-none-match": on_etag}).status_code == 304
    assert listed.count("entities") == off.count("entities")                  # not listed twice, as stamp + ETag did
    assert listed.count("episodes") == 1 and off.count("episodes") == 0       # the one more folder the verdict reads
    assert sorted(n for n in listed if n != "episodes") == sorted(off)


def rewrite_save(bank: Bank, pid: str, **more) -> None:
    path = next(p for p in (bank.root / "episodes").glob("*.md") if f"media_entity_id: {pid}" in p.read_text())
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, **more}, parsed.body)


def test_the_route_moves_when_a_reason_is_stamped_on_a_save_and_not_on_an_unrelated_capture(bank, client, on):
    """The pages folder never moves for these: the posts stamp is what carries them into the ETag."""
    labels = (("a why-answer", {"saved_why": {"answer": "x"}}), ("a note", {"has_note": True}),
              ("named", {"named": {"why": "title", "at": "2026-11-21"}}),
              ("kept as a page", {"kept_as_page": {"at": "2026-11-24"}}))
    posts = {label: bank.post(f"media-{n}", url=status(n)) for n, (label, _more) in enumerate(labels, start=1)}
    first = client.get("/graph").headers["etag"]
    for n in range(3):
        bank.episode(f"ep_2026-11-24_{n:03d}", {"source": "claude-code"}, "user: an unrelated chat\n")
    bank_index.invalidate()
    assert client.get("/graph").headers["etag"] == first                      # an unrelated capture: no move
    seen = {first}
    for label, more in labels:
        rewrite_save(bank, posts[label], **more)
        bank_index.invalidate()
        etag = client.get("/graph").headers["etag"]
        assert etag not in seen, label
        seen.add(etag)
        rewrite_save(bank, posts[label], **{k: None for k in more})            # taken back: the row returns
        bank_index.invalidate()
        assert client.get("/graph").headers["etag"] == first, label
    assert set(posts.values()) == saved_posts.verdict(bank.root).rows


def test_the_route_moves_when_a_claim_citing_a_post_is_written_and_withdrawn(bank, client, on):
    pid = bank.post("media-a", url=status(1))
    first = client.get("/graph").headers["etag"]
    bank.page(pid, {"name": "x", "type": "media", "status": "active", "source_episodes": [SAVE],
                    "media": {"url": status(1), "media_type": "url"}}, claim_list=[person_claim(SAVE)])
    bank_index.invalidate()
    written = client.get("/graph").headers["etag"]
    assert written != first and pid in saved_posts.earned_ids(bank.root)
    bank.page(pid, {"name": "x", "type": "media", "status": "active", "source_episodes": [SAVE],
                    "media": {"url": status(1), "media_type": "url"}})
    bank_index.invalidate()
    withdrawn = client.get("/graph").headers["etag"]
    assert withdrawn != written and pid in saved_posts.verdict(bank.root).rows


def test_the_route_moves_when_a_list_gains_a_save(bank, client, on):
    first = client.get("/graph").headers["etag"]
    bank.post("media-a", url=status(1))
    assert client.get("/graph").headers["etag"] != first


def test_the_route_moves_when_a_save_is_filed_in_or_out_of_a_folder(tmp_path, monkeypatch, on):
    """A folder's list page is a node with a member count made of the saves filed in it. Which saves those are is in the
    saves' own records, so no folder the ETag stats moves: before the digest the ETag answered 304 over a changed count."""
    from _synthetic_bank import _bank
    from fastapi.testclient import TestClient
    from test_list_pages import save

    from api import config, main
    from api.services import list_pages

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    _page, first_save = save(memory, 1, folders=("Alpha",))
    _page, second_save = save(memory, 2, folders=("Alpha",))
    list_pages.sync(memory)
    assert saved_posts.lists_stamp(memory) != ""
    try:
        with TestClient(main.app) as c:
            first = c.get("/graph")
            counts = {n["id"]: n["memberCount"] for n in first.json()["nodes"] if n["id"].startswith("list-")}
            assert sorted(counts.values()) == [2, 2]                         # the whole list and the folder
            assert c.get("/graph", headers={"if-none-match": first.headers["etag"]}).status_code == 304
            path = memory / "episodes" / f"{second_save}.md"
            parsed = markdown_parser.parse(path)
            markdown_parser.write(path, {k: v for k, v in parsed.frontmatter.items() if k != "save_folders"}, parsed.body)
            bank_index.invalidate()
            again = c.get("/graph", headers={"if-none-match": first.headers["etag"]})
            assert again.status_code == 200                                 # the page file never moved
            assert sorted(n["memberCount"] for n in again.json()["nodes"] if n["id"].startswith("list-")) == [1, 2]
            # an unrelated capture leaves it where it is
            memory_episode = memory / "episodes" / "ep_2026-11-24_900.md"
            markdown_parser.write(memory_episode, {"id": "ep_2026-11-24_900", "source": "claude-code",
                                                   "timestamp": "2026-11-24T10:00:00+00:00"}, "user: hi\n")
            bank_index.invalidate()
            assert c.get("/graph", headers={"if-none-match": again.headers["etag"]}).status_code == 304
    finally:
        config.get_settings.cache_clear()


def test_a_bank_that_files_no_save_in_a_folder_keeps_the_etag_it_had(bank, client, on):
    rich_bank(bank)
    assert saved_posts.lists_stamp(bank.root) == ""
    assert client.get("/graph").headers["etag"] == expected_etag(bank, posts=saved_posts.stamp(bank.root))


def test_the_folders_of_a_save_are_read_the_way_the_streams_read_them(bank):
    """The record holds what `source_streams.episodes` counts: a deleted save files nowhere."""
    from api.services import source_streams

    bank.post("media-a", url=status(1), save={"save_folders": {"x-bookmarks": ["Alpha"]}})
    bank.post("media-b", url=status(2), save={"save_folders": {"x-bookmarks": ["Beta"]}, "source_deleted_at": "2026-11-24"})
    bank_index.invalidate()
    before = saved_posts.lists_stamp(bank.root)
    saved_posts.HIDE_POSTS = True
    try:
        filed = saved_posts.lists_stamp(bank.root)
        assert filed != "" and before == ""
        assert {n for n, _c in source_streams.episodes(bank.root).folder_names.values()} == {"Alpha"}
        bank.post("media-c", url=status(3), save={"save_folders": {"x-bookmarks": ["Gamma"]}})
        assert saved_posts.lists_stamp(bank.root) != filed
    finally:
        saved_posts.HIDE_POSTS = False


def test_a_bank_deleted_or_renamed_takes_its_stored_records_and_another_banks_stay(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_bank_trash_export import _client

    from api import config
    from api.services import bank_registry

    client, root = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    bank_registry.create_bank(root, "Other")
    held = {}
    for name in ("scratch", "other"):
        path = bank_registry.bank_dir(root, name)
        DigestBank(path).post(f"media-{name}", url=status(1))
        saved_posts.verdict(path)
        saved_posts.persist_now(path)
        held[name] = derived_store.path_of(path, "saved_posts")
        assert held[name].is_file()
    assert client.post("/banks/other/rename", json={"newName": "Moved"}).status_code == 200
    assert not held["other"].exists() and held["scratch"].is_file()          # the renamed bank's old key is gone
    assert client.delete("/banks/scratch").status_code == 200
    assert not held["scratch"].exists() and not held["scratch"].parent.exists()
    config.get_settings.cache_clear()
    assert isinstance(client, TestClient)

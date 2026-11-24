"""Old bulk material is read on the engine's lightest model (ruling 80, owner 2026-11-24, G246).

The owner: "current model for new saves and the 453 list saves; the smallest model for old bookmarks." These tests hold the
table (which saves), the lightest model (never another provider, sign-in, key or billing), the batch (one model's), the
spending line, the option, and the record (which model read what). Synthetic banks, placeholder titles, example.com links.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from drain_harness import git, install, is_processed, seed_bank

from api.config import Settings, get_settings
from api.services import (anthropic_models, bank_index, bookmark_sync, history_index, light_reads, markdown_parser,
                          media_ingestor, price_supplement, saved_order, sleep_cycle, sleep_drain, sleep_run_prefs,
                          sleep_spend)
from api.services.connections import byok
from api.services.connections import registry as registry_module

TODAY = date.today().isoformat()
RELEASED = {history_index.TURN_KEY: TODAY}


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()


# ---- which saves are old bulk material: the one table -------------------------------------------------------------------


@pytest.mark.parametrize("fm, kind", [
    ({"origin": "chrome-bookmark", "source": "bookmark"}, "browser"),
    ({"origin": "brave-bookmark", "source": "youtube"}, "browser"),
    ({"origin": "safari-bookmark", "source": "bookmark"}, "browser"),
    ({"source": "bookmark"}, "browser"),                                     # a bookmarks file imported before the stamp
    ({"origin": "instagram-saved", "source": "instagram", "arrived_by": "file"}, "file"),
    ({"origin": "youtube-playlist", "source": "youtube", "arrived_by": "file"}, "file"),
    ({"origin": "x-bookmarks", "source": "url", "arrived_by": "file"}, "file"),
    ({"source": "url", "arrived_by": "file"}, "file"),
])
def test_old_bookmarks_and_saves_out_of_a_file_are_old_bulk_when_released_from_the_pile(fm, kind):
    assert light_reads.why({**fm, **RELEASED}) == kind and light_reads.is_old_bulk({**fm, **RELEASED})


@pytest.mark.parametrize("fm", [
    {"origin": "chrome-bookmark", "source": "bookmark"},
    {"origin": "instagram-saved", "source": "instagram", "arrived_by": "file"},
])
def test_a_save_that_was_never_in_the_pile_is_read_on_his_model_whatever_it_is(fm):
    assert light_reads.why(fm) is None and light_reads.why(None) is None and light_reads.why({}) is None


@pytest.mark.parametrize("fm", [
    # a list his agent read in his browser, or a connector he connected: no file door, whatever the origin
    {"origin": "x-bookmarks", "source": "url", "folder": "Bookmarks"},
    {"origin": "x-likes", "source": "url", "folder": "Likes"},
    {"origin": "instagram-saved", "source": "instagram", "folder": "Saved"},
    {"origin": "linkedin-saved", "source": "linkedin"},
    {"origin": "youtube-playlist", "source": "youtube"},
    {"origin": "reddit-saved", "source": "url", "folder": "r/alpha_sub"},
    {"origin": "github-starred", "source": "url"},
    {"origin": "substack-saved", "source": "url"},
    {"origin": "pinterest-saved", "source": "url"},
    {"origin": "tab-group", "source": "tab-group"},
    {"origin": "saved-link", "source": "url"},
    {"origin": "telegram", "source": "url"},
])
def test_everything_else_released_from_the_pile_reads_on_the_model_he_chose(fm):
    assert light_reads.why({**fm, **RELEASED}) is None


def test_the_browser_origins_are_the_ones_bookmark_sync_stamps_and_the_file_door_is_the_ingestors():
    assert light_reads.browser_origins() == frozenset(bookmark_sync.CHANNEL_BY_ORIGIN)
    assert {"chrome-bookmark", "safari-bookmark", "brave-bookmark"} <= light_reads.browser_origins()
    assert light_reads.FILE_DOOR == media_ingestor.FILE_DOOR == "file"


def test_a_file_the_person_gives_stamps_every_save_it_holds_and_a_sync_or_a_feed_does_not(tmp_path):
    html = (b"<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><DT><A HREF=\"https://example.com/a\">A</A>"
            b"<DT><A HREF=\"https://example.com/b\">B</A></DL>")
    items, _label, _bookmarks = media_ingestor.parse_upload(html, "bookmarks.html")
    assert items and all(i.arrived_by == "file" for i in items)
    feed = (b"<rss version='2.0'><channel><title>T</title><item><title>P</title><link>https://example.com/p</link>"
            b"<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>")
    rss, _l, _b = media_ingestor.parse_upload(feed, "feed.xml")
    assert rss and all(i.arrived_by is None for i in rss)
    synced = bookmark_sync._tag_origin(media_ingestor.RawItem(url="https://example.com/c") and
                                       [media_ingestor.RawItem(url="https://example.com/c")], "chrome-bookmark")
    assert synced[0].arrived_by is None
    # The stamp reaches the episode, and only when there is one.
    memory = _bank(tmp_path)
    for n, by in enumerate(("file", None)):
        item = media_ingestor.RawItem(url=f"https://example.com/w{n}", title="A title", arrived_by=by)
        meta = media_ingestor.MediaMeta(title="A title", description="words", site="example.com", media_type="url")
        res = media_ingestor.write_prepared(media_ingestor.PreparedItem(item, meta), memory, {})
        fm = markdown_parser.parse(memory / "episodes" / f"{res.episode_id}.md").frontmatter
        assert fm.get("arrived_by") == by


# ---- the lightest model of the engine he chose --------------------------------------------------------------------------


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _same_way_in(found, chosen_settings):
    """Another provider, sign-in, key or billing path is never reached: same engine, same key, same provider."""
    from api.services import engine_select

    assert engine_select.engine_label(found.settings) == engine_select.engine_label(chosen_settings)
    assert found.settings.llm_mode == chosen_settings.llm_mode
    if engine_select.engine_label(chosen_settings) == "litellm":
        assert byok.provider_for_model(found.model) == byok.provider_for_model(chosen_settings.litellm_model)
        from api.services import telemetry

        assert telemetry.connection_for_model(found.model) == telemetry.connection_for_model(chosen_settings.litellm_model)


@pytest.mark.parametrize("chosen", ["sonnet", "opus", "fable", "claude-sonnet-5-5"])
def test_the_claude_plans_small_model_for_a_larger_choice(chosen):
    s = _s(llm_mode="agent", agent_model=chosen)
    found = light_reads.lighter(s)
    assert found is not None and found.model == "haiku" and found.settings.agent_model == "haiku"
    assert found.settings.kept_main_models == {"agent_model": chosen}, "the same-name second look keeps the person's"
    assert found.settings.agent_disambiguation_model == s.agent_disambiguation_model
    _same_way_in(found, s)
    assert s.agent_model == chosen, "the person's settings are never changed"


@pytest.mark.parametrize("chosen", ["haiku", "claude-haiku-5-5", "claude-haiku-4-5"])
def test_a_choice_that_is_already_the_small_model_has_no_lighter_one(chosen):
    assert light_reads.lighter(_s(llm_mode="agent", agent_model=chosen)) is None


@pytest.mark.parametrize("settings", [
    _s(llm_mode="codex", codex_model="a-model"), _s(llm_mode="codex"), _s(llm_mode="cursor", cli_engine_model="auto"),
    _s(llm_mode="opencode", cli_engine_model="a/model"), _s(llm_mode="grok", cli_engine_model="grok-x"),
    _s(llm_mode="local"),
])
def test_an_engine_with_no_lighter_model_cicada_knows_reads_on_the_chosen_one(settings):
    assert light_reads.lighter(settings) is None


@pytest.mark.parametrize("chosen", ["anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5", "claude-opus-5-5",
                                    "anthropic/claude-sonnet-4-6"])
def test_a_claude_key_reads_old_saves_on_its_own_newest_priced_small_model(chosen):
    s = _s(llm_mode="byok", litellm_model=chosen)
    found = light_reads.lighter(s)
    assert found is not None and found.model == "anthropic/claude-haiku-5-5"
    assert found.settings.litellm_model == found.model and found.settings.kept_main_models == {"litellm_model": chosen}
    _same_way_in(found, s)
    # Priced, and cheaper than what he chose, on a read of the measured size.
    assert price_supplement.claude_cost(found.model, input_tokens=1, output_tokens=1) is not None
    assert light_reads._reference_cost(found.model) < light_reads._reference_cost(chosen)


def test_a_claude_key_skips_a_small_model_with_no_price_and_never_guesses_one(monkeypatch):
    monkeypatch.setattr(anthropic_models, "active", lambda line: ["claude-haiku-9-9", "claude-haiku-5-5"])
    assert light_reads.lighter(_s(llm_mode="byok", litellm_model="anthropic/claude-opus-5-5")).model == \
        "anthropic/claude-haiku-5-5"
    monkeypatch.setattr(anthropic_models, "active", lambda line: ["claude-haiku-9-9"])
    assert light_reads.lighter(_s(llm_mode="byok", litellm_model="anthropic/claude-opus-5-5")) is None


@pytest.mark.parametrize("chosen", ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-9-9"])
def test_a_claude_key_with_nothing_lighter_or_no_price_for_its_choice_keeps_it(chosen):
    assert light_reads.lighter(_s(llm_mode="byok", litellm_model=chosen)) is None


def test_an_older_small_model_on_a_claude_key_moves_to_the_newer_cheaper_one_of_the_same_key():
    s = _s(llm_mode="byok", litellm_model="anthropic/claude-haiku-4-5")
    found = light_reads.lighter(s)
    assert found.model == "anthropic/claude-haiku-5-5"
    _same_way_in(found, s)


@pytest.mark.parametrize("chosen, light", [
    ("gpt-5.4", "gpt-5.4-nano"), ("gpt-5.4-mini", "gpt-5.4-nano"), ("openai/gpt-5.4", "gpt-5.4-nano"),
    ("gemini/gemini-flash-latest", "gemini/gemini-flash-lite-latest"),
])
def test_another_key_reads_old_saves_on_its_own_providers_lightest_priced_model(chosen, light):
    s = _s(llm_mode="byok", litellm_model=chosen)
    found = light_reads.lighter(s)
    assert found is not None and found.model == light
    _same_way_in(found, s)


@pytest.mark.parametrize("chosen", [
    "gpt-5.4-nano", "gemini/gemini-flash-lite-latest",
    "openrouter/openai/gpt-5.4", "openrouter/anthropic/claude-sonnet-5-5",      # a router is its own billing path
    "groq/openai/gpt-oss-120b", "mistral/mistral-small-latest", "xai/grok-4.20-0309-non-reasoning",
    "deepseek/deepseek-chat", "azure/gpt-5.4",                                 # not that provider's own id
    "",
])
def test_a_provider_with_no_lighter_priced_model_known_reads_on_the_chosen_one(chosen):
    assert light_reads.lighter(_s(llm_mode="byok", litellm_model=chosen)) is None


def test_every_lightest_key_model_has_a_price_and_structured_output():
    import litellm

    from api.services import pricing

    price_supplement.apply(litellm)
    for provider, model in light_reads.LIGHTEST_KEY.items():
        assert byok.provider_for_model(model) == provider
        assert pricing.estimate_cost(model, 1000, 1000) is not None
        assert litellm.model_cost[model].get("supports_response_schema")


def test_a_chosen_model_with_no_price_gets_no_lighter_one_and_still_stops_a_metered_run(monkeypatch):
    s = _s(llm_mode="byok", litellm_model="gpt-5.4")
    monkeypatch.setattr(light_reads, "_reference_cost", lambda m: None if m == "gpt-5.4" else 0.001)
    assert light_reads.lighter(s) is None
    guard = sleep_spend.guard_for(_s(llm_mode="byok", litellm_model="anthropic/claude-sonnet-9-9"), 5.0)
    assert guard.is_reached() and guard.sentence == sleep_spend.NO_PRICE_SENTENCE


def test_a_later_stage_override_follows_the_batchs_one_model():
    s = _s(llm_mode="byok", litellm_model="anthropic/claude-sonnet-5-5", consolidation_model="anthropic/claude-opus-5-5")
    found = light_reads.lighter(s)
    assert found.settings.effective_consolidation_model == found.model
    assert light_reads.lighter(_s(llm_mode="byok", litellm_model="anthropic/claude-sonnet-5-5")) \
        .settings.effective_consolidation_model == "anthropic/claude-haiku-5-5"


def test_the_same_name_second_look_still_reads_with_the_model_he_chose():
    from api.services import same_name_tend

    s = _s(llm_mode="agent", agent_model="sonnet")
    found = light_reads.lighter(s)
    assert found.settings.agent_model == "haiku"
    assert same_name_tend.main_tier(found.settings).agent_disambiguation_model == "sonnet"
    assert same_name_tend.main_tier(s).agent_disambiguation_model == "sonnet"
    key = light_reads.lighter(_s(llm_mode="byok", litellm_model="anthropic/claude-opus-5-5"))
    assert same_name_tend.main_tier(key.settings).litellm_disambiguation_model == "anthropic/claude-opus-5-5"


# ---- the order and the batches ----------------------------------------------------------------------------------------


def _save(memory, eid, *, origin="chrome-bookmark", day="2026-11-20", released=True, **fm):
    base = {"id": eid, "timestamp": f"{day}T10:00:00+00:00", "processed": False, "source": "bookmark", "origin": origin,
            "url": f"https://example.com/{eid}", "media_entity_id": f"media-{eid}", "title": f"Title {eid}",
            "saved_at": day, **(RELEASED if released else {})}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", base, "# A title\n\n## Description\nwords")


def test_old_bulk_material_is_read_after_every_other_save_only_when_the_option_is_on(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                          {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                           "source": "mcp", "session_id": "ses_a"}, "user: hello")
    _save(memory, "ep_2026-11-18_001", day="2026-11-18")                                   # old bookmark, released
    _save(memory, "ep_2026-11-19_001", day="2026-11-19", origin="x-likes", source="url", folder="Likes")   # agent list
    _save(memory, "ep_2026-11-15_001", day="2026-11-15", released=False)                    # a bookmark made singly
    _save(memory, "ep_2026-11-17_001", day="2026-11-17", read_asked={"why": "said-the-link", "at": "2026-11-24T10:00:00+00:00"})
    _save(memory, "ep_2026-11-16_001", day="2026-11-16", origin="instagram-saved", source="instagram", arrived_by="file")
    bank_index.invalidate()
    ids = ["ep_2026-11-01_001", "ep_2026-11-15_001", "ep_2026-11-16_001", "ep_2026-11-17_001", "ep_2026-11-18_001",
           "ep_2026-11-19_001"]
    today, bg = saved_order.order(memory, ids)
    assert today == ["ep_2026-11-01_001", "ep_2026-11-17_001", "ep_2026-11-19_001", "ep_2026-11-18_001",
                     "ep_2026-11-15_001", "ep_2026-11-16_001"], "off: as it was, grouped by origin, newest origin first"
    ordered, background = saved_order.order(memory, ids, old_bulk_last=True)
    assert ordered == ["ep_2026-11-01_001",                                  # conversations first, as before
                       "ep_2026-11-17_001",                                  # a save he talked about
                       "ep_2026-11-19_001", "ep_2026-11-15_001",             # a list his agent read, a save made singly
                       "ep_2026-11-18_001", "ep_2026-11-16_001"]             # old bookmarks, then a file's saves
    assert sorted(ordered) == sorted(ids) and background == bg == frozenset(
        {"ep_2026-11-19_001", "ep_2026-11-15_001", "ep_2026-11-18_001", "ep_2026-11-16_001"})
    assert light_reads.old_bulk_ids(memory, background) == {"ep_2026-11-18_001", "ep_2026-11-16_001"}


def test_a_batch_never_holds_two_models_and_a_retry_does_not_mix_them():
    ids = ["n1", "n2", "n3", "n4", "n5", "o1", "o2"]
    light = frozenset({"o1", "o2"})
    waiting, settled = set(ids), set()
    batches = []
    while True:
        batch, more = sleep_drain.next_batch_retrying(ids, waiting, settled, 4, {}, light=light)
        if not batch:
            break
        batches.append(batch)
        settled |= set(batch)
        assert more == len([i for i in ids if i not in settled])
    assert batches == [["n1", "n2", "n3", "n4"], ["n5"], ["o1", "o2"]]
    assert sleep_drain.batches_left(ids, 4, None, light=light) == 3 and sleep_drain.batches_left(ids, 4, None) == 2
    # A light save that failed once is tried first in the next batch, with its own kind and no other.
    batch, more = sleep_drain.next_batch_retrying(ids, waiting, {"n1", "n2", "n3", "n4"}, 4, {"o2": 1}, light=light)
    assert batch == ["o2"] and more == 2, "its retry alone, then the rest as before"
    batch, more = sleep_drain.next_batch_retrying(ids, waiting, {"n1", "n2", "n3", "n4"}, 4, {"n5": 1}, light=light)
    assert batch == ["n5"] and more == 2, "the retry of one on his model ends where the lighter model begins"
    # No lighter model in play: as it always was.
    assert sleep_drain.next_batch_retrying(ids, waiting, set(), 4, {"o2": 1}) == (["o2", "n1", "n2", "n3"], 3)


# ---- a night: which model read what, the option, the line -------------------------------------------------------------


def _wrap_extract(monkeypatch):
    """What Stage 1 was handed: the ids of each batch and the model its engine copy names."""
    from api.services import entity_extractor

    seen: list[tuple[list[str], str]] = []
    real = entity_extractor.extract

    async def spy(episodes, settings_, *a, **kw):
        model = {"byok": settings_.litellm_model, "codex": settings_.codex_model}.get(settings_.llm_mode, settings_.agent_model)
        seen.append(([e["id"] for e in episodes], model))
        return await real(episodes, settings_, *a, **kw)

    monkeypatch.setattr("api.services.entity_extractor.extract", spy)
    return seen


def _night(tmp_path, monkeypatch, *, cfg_kw=None, option=None, cap=2, label="claude-cli"):
    install_rig = install(monkeypatch, engine_label=label)
    seen = _wrap_extract(monkeypatch)

    def extra(memory):
        for i in (1, 2):
            eid = f"ep_2026-11-0{i}_001"
            markdown_parser.write(memory / "episodes" / f"{eid}.md",
                                  {"id": eid, "timestamp": f"2026-11-0{i}T10:00:00+00:00", "processed": False,
                                   "source": "mcp", "session_id": f"ses_{eid}"}, "user: a conversation")
        _save(memory, "ep_2026-11-20_001", day="2026-11-20", origin="x-likes", source="url", folder="Likes")   # his agent's list
        _save(memory, "ep_2026-11-21_001", day="2026-11-21", released=False)                    # a bookmark made singly
        for n in range(3):
            _save(memory, f"ep_2026-11-1{n}_001", day=f"2026-11-1{n}")                          # old bookmarks, released
        _save(memory, "ep_2026-11-05_001", day="2026-11-05", origin="instagram-saved", source="instagram",
              arrived_by="file")                                                                 # a save out of a file

    memory = seed_bank(tmp_path, [], extra=extra)
    if option is not None:
        sleep_run_prefs.write(registry_module.get_registry(Settings()), light_old_saves=option)
    cfg = Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=cap, link_enrich_enabled=False,
                   **(cfg_kw or {"llm_mode": "agent", "agent_model": "sonnet"}))
    asyncio.run(sleep_cycle.run(cfg, "sleep_light", user_triggered=True, drain=True))
    return memory, seen, install_rig


def test_old_saves_are_read_on_the_lighter_model_in_batches_of_their_own_after_every_other_save(tmp_path, monkeypatch):
    memory, seen, _rig = _night(tmp_path, monkeypatch)
    seen = [(sorted(ids), m) for ids, m in seen]
    assert seen == [(["ep_2026-11-01_001", "ep_2026-11-02_001"], "sonnet"),
                    (["ep_2026-11-20_001", "ep_2026-11-21_001"], "sonnet"),      # his agent's list and his own save
                    (["ep_2026-11-11_001", "ep_2026-11-12_001"], "haiku"),       # old bookmarks, newest first
                    (["ep_2026-11-05_001", "ep_2026-11-10_001"], "haiku")]       # then older and the file's
    assert all(is_processed(memory, i) for ids, _m in seen for i in ids)
    assert git(memory, "status", "--porcelain").strip() == ""


def test_the_option_off_reads_everything_on_the_model_he_chose_in_todays_order(tmp_path, monkeypatch):
    memory, seen, _rig = _night(tmp_path, monkeypatch, option=False)
    assert {m for _ids, m in seen} == {"sonnet"}
    read = [i for ids, _m in seen for i in ids]
    assert read[:2] == ["ep_2026-11-01_001", "ep_2026-11-02_001"] and sorted(read) == sorted(set(read)) and len(read) == 8
    # The option is read back the way the other options are, and defaults on.
    assert sleep_run_prefs.load(registry_module.get_registry(Settings())).light_old_saves is False


def test_an_engine_with_no_lighter_model_reads_everything_on_the_chosen_one_and_nothing_fails(tmp_path, monkeypatch):
    from api.services import codex_engine

    async def signed_in(**_kw):
        return True, "signed in", None

    monkeypatch.setattr(codex_engine, "preflight", signed_in)
    memory, seen, _rig = _night(tmp_path, monkeypatch, cfg_kw={"llm_mode": "codex", "codex_model": "a-model"}, label="codex-cli")
    read = [i for ids, _m in seen for i in ids]
    assert len(read) == 8 and all(is_processed(memory, i) for i in read)
    assert {m for _ids, m in seen} == {"a-model"}, "the ChatGPT plan has no lighter model Cicada knows: the one he chose"
    assert sleep_cycle.get_sleep_state().drain.light_model is None and sleep_cycle.get_sleep_state().drain.stop is None


def test_a_save_he_talks_about_during_the_night_leaves_the_lighter_class(tmp_path, monkeypatch):
    rig = install(monkeypatch, engine_label="claude-cli")
    seen = _wrap_extract(monkeypatch)

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "mcp", "session_id": "ses_a"}, "user: hello")
        for n in range(3):
            _save(memory, f"ep_2026-11-1{n}_001", day=f"2026-11-1{n}")

    memory = seed_bank(tmp_path, [], extra=extra)
    ran = {"done": False}
    real = sleep_cycle._promote_talked_saves

    def mention(ds, memory_path, ids):
        if not ran["done"]:
            ran["done"] = True
            _save(memory, "ep_2026-11-10_001", day="2026-11-10", read_asked={"why": "said-the-link", "at": "2026-11-24T10:00:00+00:00"})
            bank_index.invalidate()
        return real(ds, memory_path, ids)

    monkeypatch.setattr(sleep_cycle, "_promote_talked_saves", mention)
    cfg = Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=1, link_enrich_enabled=False,
                   llm_mode="agent", agent_model="sonnet")
    asyncio.run(sleep_cycle.run(cfg, "sleep_talk", user_triggered=True, drain=True))
    assert seen == [(["ep_2026-11-01_001"], "sonnet"), (["ep_2026-11-10_001"], "sonnet"),
                    (["ep_2026-11-12_001"], "haiku"), (["ep_2026-11-11_001"], "haiku")]
    assert rig.extract_batches, "the run read"


# ---- the spending line and the plan reserve ------------------------------------------------------------------------------


def test_a_run_on_a_key_needs_a_price_for_both_models_before_it_starts():
    chosen = _s(llm_mode="byok", litellm_model="anthropic/claude-sonnet-5-5")
    found = light_reads.lighter(chosen)
    ok = sleep_spend.guard_for(chosen, 5.0, also=(found.model,))
    assert not ok.is_reached()
    unpriced = sleep_spend.guard_for(chosen, 5.0, also=("anthropic/claude-haiku-9-9",))
    assert unpriced.is_reached() and unpriced.sentence == sleep_spend.NO_PRICE_SENTENCE


def test_each_model_adds_at_its_own_price_and_the_line_holds_across_both():
    dear = light_reads._reference_cost("anthropic/claude-sonnet-5-5")
    cheap = light_reads._reference_cost("anthropic/claude-haiku-5-5")
    assert cheap < dear / 2, "the lighter read is the saving"
    guard = sleep_spend.SpendGuard(dear * 2 + cheap * 2.5)
    for cost in (dear, dear, cheap, cheap):
        guard.observe(cost)
    assert not guard.is_reached()
    guard.observe(cheap)
    assert guard.is_reached(), "the figure is the sum of what each call cost, at its own model's price"


def test_a_line_reached_with_only_old_saves_left_ends_the_night_and_puts_them_back(tmp_path, monkeypatch):
    rig = install(monkeypatch, engine_label="litellm")
    seen = _wrap_extract(monkeypatch)

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "mcp", "session_id": "ses_a"}, "user: hello")
        for n in range(4):
            _save(memory, f"ep_2026-11-1{n}_001", day=f"2026-11-1{n}")

    memory = seed_bank(tmp_path, [], extra=extra)

    def spend_the_line(ep):
        guard = sleep_cycle.get_sleep_state().drain.spend
        if guard is not None and ep["id"] == "ep_2026-11-13_001":
            guard.observe(guard.limit_usd + 1)         # the first light batch's first read crosses the line

    rig.after_read = spend_the_line
    cfg = Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=1, link_enrich_enabled=False, llm_mode="byok",
                   litellm_model="anthropic/claude-sonnet-5-5")
    asyncio.run(sleep_cycle.run(cfg, "sleep_line", user_triggered=False, drain=True))
    state = sleep_cycle.get_sleep_state()
    assert state.drain.stop is None and state.drain.light_model == "anthropic/claude-haiku-5-5"
    assert [m for _ids, m in seen] == ["anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-5-5"]
    filed = markdown_parser.parse(memory / "episodes" / "ep_2026-11-13_001.md").frontmatter
    assert filed["processed"] is True and filed.get("processed_by") != "index", "the one the line fell on was read"
    for n in range(3):
        fm = markdown_parser.parse(memory / "episodes" / f"ep_2026-11-1{n}_001.md").frontmatter
        assert (fm["processed"], fm["processed_by"]) == (True, "index"), "the rest back in the pile"


def test_a_plan_window_reached_with_only_old_saves_left_ends_the_night_on_the_plan_too(tmp_path, monkeypatch):
    import time

    from api.services import sleep_paused
    from api.services.agent_stream import RateLimitSignal

    rig = install(monkeypatch, engine_label="claude-cli")
    seen = _wrap_extract(monkeypatch)
    sleep_run_prefs.write(registry_module.get_registry(Settings()), reserve_pct=10)

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "mcp", "session_id": "ses_a"}, "user: hello")
        for n in range(4):
            _save(memory, f"ep_2026-11-1{n}_001", day=f"2026-11-1{n}")

    memory = seed_bank(tmp_path, [], extra=extra)
    full = RateLimitSignal(status="allowed", limit_type="five_hour", utilization=0.99, resets_at=int(time.time()) + 3600)
    rig.after_read = lambda ep: sleep_cycle.get_sleep_state().drain.guard.observe_signals([full]) \
        if ep["id"] == "ep_2026-11-12_001" else None
    cfg = Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=2, link_enrich_enabled=False,
                   llm_mode="agent", agent_model="sonnet")
    asyncio.run(sleep_cycle.run(cfg, "sleep_plan", user_triggered=False, drain=True))
    ds = sleep_cycle.get_sleep_state().drain
    assert [m for _ids, m in seen] == ["sonnet", "haiku"] and ds.stop is None, "a finished night, not a pause"
    assert sleep_paused.get_paused(memory) is None
    assert ds.returned_saves and "ep_2026-11-12_001" not in ds.returned_saves
    assert {i for i in ds.returned_saves} <= {f"ep_2026-11-1{n}_001" for n in range(4)}, "only old saves go back to the pile"
    for eid in ds.returned_saves:
        fm = markdown_parser.parse(memory / "episodes" / f"{eid}.md").frontmatter
        assert (fm["processed"], fm["processed_by"]) == (True, "index")


# ---- the record: which model read what --------------------------------------------------------------------------------


def test_the_run_detail_says_which_batches_read_on_the_lighter_model(tmp_path, monkeypatch):
    from api import main
    from api.services import telemetry

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    memory, seen, _rig = _night(tmp_path, monkeypatch)
    cfg = Settings(CICADA_MEMORY_PATH=memory, _env_file=None)
    main.app.dependency_overrides[get_settings] = lambda: cfg
    try:
        client = TestClient(main.app)
        rows = [e for e in telemetry.read_events() if e.kind == "sleep_run"]
        assert len(rows) == 4
        lighter = [bool((e.refs or {}).get("lighter")) for e in sorted(rows, key=lambda e: int((e.refs or {}).get("batch") or 0))]
        assert lighter == [False, False, True, True]
        drain_id = sleep_cycle.get_sleep_state().drain.drain_id
        body = client.get(f"/sleep/runs/{drain_id}").json()
        assert [b["lighter"] for b in body["batches"]] == [False, False, True, True]
        assert [b["filed"] for b in body["batches"]] == [2, 2, 2, 2]
    finally:
        main.app.dependency_overrides.pop(get_settings, None)


def test_the_commit_of_a_lighter_batch_names_the_model_that_wrote_it(tmp_path, monkeypatch):
    from api.services import agent_engine

    install_rig = install(monkeypatch, engine_label="claude-cli")
    asked: list[str] = []

    async def fake_extract(episodes, settings_, *a, **kw):
        asked.append(settings_.agent_model)
        agent_engine.record_model_used("claude-haiku-5-5" if settings_.agent_model == "haiku" else "claude-sonnet-5-5")
        return [{"episode_id": e["id"], "episode_timestamp": e["timestamp"], "origin": "mcp",
                 "entities": [{"name": e["id"], "type": "concept", "confidence": 0.7, "source_episode": e["id"]}],
                 "relationships": []} for e in episodes]

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "mcp", "session_id": "ses_a"}, "user: hello")
        _save(memory, "ep_2026-11-10_001", day="2026-11-10")

    memory = seed_bank(tmp_path, [], extra=extra)
    cfg = Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=1, link_enrich_enabled=False,
                   llm_mode="agent", agent_model="sonnet")
    asyncio.run(sleep_cycle.run(cfg, "sleep_trailers", user_triggered=True, drain=True))
    assert asked == ["sonnet", "haiku"]
    log = git(memory, "log", "--format=%B%x00", "--grep=Sleep cycle").split("\x00")
    authors = [[l for l in m.splitlines() if l.startswith("Cicada-Author:")] for m in log if "Sleep cycle" in m]
    flat = sorted(a for group in authors for a in group)
    assert flat == ["Cicada-Author: claude-haiku-5-5", "Cicada-Author: claude-sonnet-5-5"]
    assert install_rig is not None


# ---- the option: the backend route and the command --------------------------------------------------------------------


def test_the_option_is_on_by_default_and_is_read_and_set_through_the_run_options_route(tmp_path, monkeypatch):
    from api import main

    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    client = TestClient(main.app)
    assert client.get("/sleep/run-options").json()["lightOldSaves"] is True
    assert client.put("/sleep/run-options", json={"lightOldSaves": False}).json()["lightOldSaves"] is False
    assert client.get("/sleep/run-options").json()["lightOldSaves"] is False
    assert client.put("/sleep/run-options", json={"batchSize": 10}).json()["lightOldSaves"] is False, "a merge leaves it"
    assert client.put("/sleep/run-options", json={"lightOldSaves": True}).json()["lightOldSaves"] is True
    assert client.put("/sleep/run-options", json={"lightOldSaves": None}).status_code == 422


@pytest.mark.parametrize("stored, reads", [({}, True), ({"light_old_saves": False}, False), ({"light_old_saves": True}, True),
                                           ({"light_old_saves": "no"}, False)])
def test_a_hand_edited_option_never_turns_it_on_by_accident(stored, reads):
    class Reg:
        def prefs(self):
            return {sleep_run_prefs.PREF_KEY: stored}

    assert sleep_run_prefs.load(Reg()).light_old_saves is reads


def test_the_command_sets_and_shows_the_option_through_the_same_options_route():
    import json

    from api import cli_app
    from api.services import cli_map

    row = next(r for r in cli_map.ROWS if r.command == ("sleep", "options"))
    assert "light_old_saves" in {a.prop for a in row.args}
    calls: list = []

    def fake_call(boot, method, path, body=None):
        calls.append((method, path, body))
        return {"batchSize": 25, "continueAfterReset": False, "reservePct": None, "spendLimitUsd": 5.0,
                "lightOldSaves": bool((body or {}).get("lightOldSaves", True))}

    args = type("A", (), {"batch_size": None, "continue_after_reset": None, "reserve": None, "spend_limit": None,
                          "light_old_saves": "off"})()
    boot = type("B", (), {"client": None})()
    from unittest import mock

    with mock.patch.object(cli_app, "call", fake_call), mock.patch.object(cli_app, "require_person", lambda *_: None), \
            mock.patch.object(cli_app, "_warn", lambda b: []):
        result = cli_app.cmd_sleep_options(boot, args)
    assert calls == [("PUT", "/sleep/run-options", {"lightOldSaves": False})]
    assert "old saves on the lightest model: off" in result.text and json.dumps(result.data)

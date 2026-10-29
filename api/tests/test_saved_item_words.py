"""A saved item's fetched text is the page's words, never the person's (2026-10-29).

A bookmark, a saved link, a saved-list post, a feed item, a tab group: its body is the page's title, site and
description, with the person's own reason or note in its own section. Before `authorship`, a save had no turn marker,
so R4's default read the whole save as the person's writing — a four-paragraph description was four exchanges "in the
person's own words" (promotion), and a span in it was labelled `user`.
"""
from __future__ import annotations

from api.services import authorship, evidence, history_index, inbox_tend, markdown_parser, promotion

EP = "ep_2026-10-01_001"
SAVE = """# alpha-tool: a tool for things

**Source:** article
**URL:** https://example.com/alpha
**Site:** example.com
**Folder:** Reading
**Saved:** 2026-10-01

## Description
alpha-tool does the first thing.

alpha-tool does the second thing.

alpha-tool does the third thing.

alpha-tool does the fourth thing.

## Why it was saved
to try alpha-tool on alpha-project

## Note
assistant: the agent filed alpha-tool"""
SAVE_FM = {"id": EP, "source": "article", "url": "https://example.com/alpha", "media_entity_id": "media-alpha",
           "origin": "chrome-bookmark"}
TOOL = {"name": "alpha-tool", "type": "tool"}


def _bank(tmp_path, fm=None, body=SAVE):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {**SAVE_FM, **(fm or {})}, body)
    return memory


# ---------- whose words, from the record ----------

def test_a_save_is_known_by_its_record_never_by_a_line():
    assert authorship.of(SAVE_FM) == evidence.SAVE_KIND
    assert authorship.of({"url": "https://example.com"}) == evidence.SAVE_KIND
    for door in ("chrome-bookmark", "x-bookmarks", "youtube-playlist", "rss", "chrome-tab-group", "youtube-history"):
        assert authorship.of({"origin": door}) == evidence.SAVE_KIND, door
    assert authorship.of({"source": "watch-history-month"}) == evidence.SAVE_KIND
    # The person's own channels stay theirs: a note, a shared file, a Notes note, a chat export, a Telegram text.
    for own in ("note", "phone", "device-file", "apple-notes", "claude-export", "telegram"):
        assert authorship.of({"origin": own, "source": own}) is None, own
    # An agent's saved note is the agent's (ruling 50, `test_agent_saved_words`).
    assert authorship.of({"origin": "mcp", "source": "mcp"}) == evidence.AGENT_KIND
    # A declared kind always wins (a folder's own files, a reminder, a relayed turn).
    assert authorship.of({**SAVE_FM, "evidence_kind": "assistant"}) == "assistant"
    assert authorship.of({"evidence_kind": "user", "origin": "reminders-local"}) == "user"
    assert authorship.of(None) is None


def test_one_list_of_the_persons_sections_and_of_the_saving_doors():
    assert history_index.PERSON_SECTIONS is evidence.PERSON_SECTIONS
    assert inbox_tend.saved_origin is authorship.saved_origin


# ---------- spans and turns ----------

def test_only_the_reason_is_the_persons_in_a_save():
    ov = authorship.of(SAVE_FM)
    kind = lambda quote: evidence.verify(None, EP, quote, text=SAVE, kind_override=ov).kind  # noqa: E731
    assert kind("alpha-tool: a tool for things") == "page"          # the title Cicada fetched
    assert kind("Reading") == "page"                                  # the header lines
    assert kind("alpha-tool does the third thing") == "page"         # the fetched description
    assert kind("to try alpha-tool on alpha-project") == "user"      # the person's own reason
    assert kind("the agent filed alpha-tool") == "assistant"         # an agent's note keeps its marker
    # Without the record's word the old reading holds — every marker-less writer but a save is the person's.
    assert evidence.verify(None, EP, "alpha-tool does the third thing", text=SAVE).kind == "user"


def test_a_save_on_disk_is_read_through_its_own_record(tmp_path):
    memory = _bank(tmp_path)
    assert evidence.verify(memory, EP, "alpha-tool does the third thing").kind == "page"
    assert evidence.verify(memory, EP, "to try alpha-tool").kind == "user"


def test_the_reader_turns_agree_with_the_span_kind_in_a_save():
    ov = evidence.SAVE_KIND
    spans = evidence.turns(SAVE, override=ov)
    # `## Note` opens the person's block, and the agent's own marker inside it wins.
    assert [t.role for t in spans] == ["page", "page", "user", "user", "assistant"]
    reason = spans[2]
    assert reason.marker is None and SAVE[reason.content_start:reason.end] == "to try alpha-tool on alpha-project"
    for t in spans:
        for off in range(t.start, t.end):
            assert evidence.kind_for(EP, SAVE, off, ov) == t.role, (t, off)


def test_every_person_section_heading_counts_and_nothing_else():
    for heading in evidence.PERSON_SECTIONS:
        body = f"# T\n\n## Description\nfetched words\n\n{heading}\nmy own words\n"
        roles = {body[t.content_start:t.end].strip(): t.role for t in evidence.turns(body, override=evidence.SAVE_KIND)}
        assert roles["my own words"] == "user" and roles["fetched words"] == "page", heading
    # A repeat save's note episode: the person's note under `## Note` is theirs, an agent's keeps its marker.
    note = "# Note on A clip\n\n**URL:** https://example.com/a\n\n## Note\n"
    assert evidence.speaker_kind(note + "save this", len(note) + 1, saved=True) == "user"
    assert evidence.speaker_kind(note + "assistant: filed it", len(note) + 12, saved=True) == "assistant"
    assert evidence.speaker_kind(note, 3, saved=True) == "page"
    # A watched day or a tab group has no section of the person's: all of it is the page's.
    day = "# Watched on 2026-10-01\n\n- a video title — https://youtu.be/x\n"
    assert {t.role for t in evidence.turns(day, override=evidence.SAVE_KIND)} == {"page"}


def test_search_hits_in_a_save_read_its_kind(tmp_path):
    assert evidence.speaker_kind(SAVE, SAVE.find("third thing"), saved=True) == "page"
    assert evidence.speaker_kind(SAVE, SAVE.find("to try"), saved=True) == "user"
    assert evidence.speaker_kind(SAVE, SAVE.find("third thing")) == "user"   # unchanged without the flag


# ---------- promotion ----------

def test_a_fetched_description_is_no_exchange_of_the_persons():
    """Four paragraphs naming the tool were four exchanges "in the person's own words": a page from one bookmark."""
    bookmark = SAVE.split("## Note")[0]   # a browser bookmark: no agent line, so no marker at all
    old = promotion.measure(TOOL, promotion.exchanges(bookmark))
    assert old[0] > promotion.MIN_EXCHANGES and old[1]
    count, named = promotion.measure(TOOL, promotion.exchanges(bookmark, override=authorship.of(SAVE_FM)))
    assert count <= promotion.MIN_EXCHANGES
    assert named   # the person's reason names it — their own words still count
    no_reason = SAVE.split("## Why it was saved")[0]
    assert promotion.measure(TOOL, promotion.exchanges(no_reason, override=evidence.SAVE_KIND)) == (1, False)


def test_a_relationship_cited_in_the_description_is_not_the_persons():
    rel = {"source": "alpha-tool", "target": "beta-company", "evidence_quote": "alpha-tool does the first thing"}
    evidence.attach_relationship_evidence(rel, EP, SAVE, kind_override=authorship.of(SAVE_FM))
    assert rel["evidence"][0]["kind"] == "page" and not promotion.person_said(rel)
    rel = {"source": "alpha-tool", "target": "alpha-project", "evidence_quote": "to try alpha-tool on alpha-project"}
    evidence.attach_relationship_evidence(rel, EP, SAVE, kind_override=authorship.of(SAVE_FM))
    assert promotion.person_said(rel)


def test_sleeps_episode_dict_carries_the_records_answer(tmp_path):
    from api.services import sleep_cycle

    memory = _bank(tmp_path, {"processed": False, "timestamp": "2026-10-01T10:00:00+00:00"})
    [ep] = sleep_cycle._get_unprocessed_episodes(memory)
    assert authorship.of_episode(ep) == evidence.SAVE_KIND
    assert ep["evidence_kind"] is None   # the declared field is untouched: no agent name is read off a save
    assert inbox_tend.person_turns(ep) == ["to try alpha-tool on alpha-project"]


def test_the_contacts_card_rule_never_reads_a_save():
    """The card rule wanted a MARKED person turn already; a save's reason is never one (unchanged)."""
    assert all(t.marker is None for t in evidence.turns(SAVE.split("## Note")[0], override=evidence.SAVE_KIND))

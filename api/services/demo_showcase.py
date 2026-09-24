"""G117, round 4 (T-Demo) — the demo that shows everything.

The owner (2026-09-24): "showing the demo is a nice addition so people can see everything in the app, even memories
with pictures, videos, showcasing everything." `demo_bank` built the G117 roster and the G141 scenario; this module
adds, on top of both, one of every thing a fresh viewer should meet: people and a company with pictures (the C11
upload rung), a saved video, an article with a preview image, a paper with its arXiv details, a calendar day, an open
Chrome tab group, beliefs an agent wrote and the app signs "Claude Code · Opus 5.5 · high effort" (round 4 C1–C4), and
the four inbox kinds DS-2 found missing (R-DI21: removal, divergence, normalization — the informational conflict is
`demo_bank`'s inbox-004, `uses` being multi-valued) plus a served merge suggestion.

The rails `demo_bank` states hold here too:
* **R7 — deterministic.** No `random`, no LLM, no network, no real clock: every date is an offset from the pinned
  `today`, so two runs write the same bytes.
* **Synthetic.** People are `*-example`; every URL is on example.com except the four in :data:`PUBLIC_URLS`, each a
  public-domain or CC0 item with its licence written beside it (the brief: "record the licence in the generator").
* **Production shapes.** Each piece is written in the shape its live writer writes, and committed the way that writer
  commits — under its own author and trigger — so `/contributors`, the Feed and the entity card read the demo exactly
  as they read a real bank, and no file is left for the next `git add -A` writer (the G85 smear).
* **The Projects wire does not move.** Nothing here names the scenario's projects or their people, so
  `projects-demo.json` stays the demo's wire (`test_projects_app_fixture.py` holds it with the showcase on).

`demo_bank.populate` calls :func:`write` last and hands it its own `_run_commit`, so this module never imports
`demo_bank`.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from api.services import (calendar_local, decay_policy, demo_pictures, entity_body, entity_picture, episode_ids,
                          episode_scrub, episode_staging, git_service, markdown_parser, media_ingestor, owner_identity,
                          paper_metadata, papers, sync_state)
from api.services.agentic_write import write_claim

Commit = Callable[[Path, str, list[str]], None]

# --- The four public items (verified 2026-09-24: HTTP 200, and the licence read from the provider's own metadata) --

VIDEO_URL = "https://www.youtube.com/watch?v=4czjS9h4Fpg"
VIDEO_THUMBNAIL = "https://i.ytimg.com/vi/4czjS9h4Fpg/hqdefault.jpg"
ARTICLE_THUMBNAIL = ("https://upload.wikimedia.org/wikipedia/commons/thumb/5/54/"
                     "Claude_Monet%2C_Impression%2C_soleil_levant.jpg/"
                     "960px-Claude_Monet%2C_Impression%2C_soleil_levant.jpg")
PAPER_ARXIV_ID = "2303.04137"
PAPER_URL = f"https://arxiv.org/abs/{PAPER_ARXIV_ID}"

#: Every URL the demo holds that is not on example.com, and why it may be here.
PUBLIC_URLS: dict[str, str] = {
    VIDEO_URL: ("'Perseverance Rover's Descent and Touchdown on Mars (Official NASA Video)', on NASA's own YouTube "
                "channel (oEmbed author_name: NASA). NASA media is generally not subject to copyright in the US "
                "(nasa.gov/nasa-brand-center/images-and-media). It plays only in YouTube's own player (Track V)."),
    VIDEO_THUMBNAIL: "YouTube's own thumbnail for that video, from its oEmbed thumbnail_url.",
    ARTICLE_THUMBNAIL: ("Claude Monet, 'Impression, soleil levant' (1872), a 960 px rendition on Wikimedia Commons; "
                        "Commons lists it as public domain (LicenseShortName: Public domain)."),
    PAPER_URL: ("The arXiv abstract page of Chi et al., 'Diffusion Policy' (arXiv:2303.04137). arXiv metadata, the "
                "abstract included, is CC0. Never fetched: papers.never_scraped and the demo's Sleep tail both skip "
                "it."),
}

# --- Ids other tests and the app read ------------------------------------------------------------------------------

#: The person the guided tour opens in the demo (the app's `DemoShowcase.person`; `api/tests/fixtures/demo_showcase.json`).
PERSON = "leo-example"
SESSION = "ses_demo_leo_01"
MODEL, EFFORT = "claude-opus-5-5", "high"
VIDEO_ID = "media-perseverance-descent"
ARTICLE_ID = "media-local-first-software"
BOOKMARK_ID = "media-gripper-teardown"
PAPER_ID = papers.PaperKey(arxiv_id=PAPER_ARXIV_ID).entity_id           # media-arxiv-2303-04137
TOOL_CLI = "tool-example-a-cli"                                          # inbox-006's subject, so its card is served

# (entity id, gradient top, gradient bottom, figure) — pastel, ART_DIRECTION's palette family; never a face.
_AVATARS = (
    (PERSON, (214, 226, 234), (169, 192, 210), (94, 127, 163)),
    ("paula-example", (238, 223, 204), (214, 191, 166), (197, 141, 122)),
    ("maria-example", (225, 232, 216), (191, 208, 185), (127, 162, 138)),
    ("nina-example", (232, 222, 240), (201, 186, 222), (140, 118, 170)),
)
_MARKS = (("acme-example", (245, 236, 214), (226, 205, 160), (176, 132, 60)),)

_LEO_SUMMARY = "A robotics engineer Bob works with on motion planning."

# (speaker, "HH:MM:SS", words) — a Stop-hook capture: the person's turns and the agent's kept replies (G105).
_LEO_TURNS = (
    ("user", "10:00:00", "Leo Example leads motion planning now, and he wants to try Diffusion Policy on the gripper."),
    ("assistant", "10:00:40", "Noted: Leo leads motion planning and wants to try Diffusion Policy. Both are on his page."),
    ("user", "10:05:00", "He also sent me the Perseverance landing video; he watches it before every demo."),
    ("assistant", "10:05:30", "Saved the video and linked it to Leo."),
)
# (predicate, object, object kind, text, quote, "HH:MM:SS" the write landed) — each joins the reply after its question.
_LEO_CLAIMS = (
    ("works-on", "motion planning", "literal", "Leo Example works on motion planning",
     "Leo Example leads motion planning now", "10:00:20"),
    ("interested-in", PAPER_ID, "node", "Leo Example wants to try Diffusion Policy",
     "he wants to try Diffusion Policy on the gripper", "10:00:25"),
    ("recommended", VIDEO_ID, "node", "Leo Example recommended the Perseverance landing video",
     "He also sent me the Perseverance landing video", "10:05:10"),
)

# (id suffix, title, "HH:MM" start, minutes, calendar, location, attendees, notes)
_CALENDARS = ({"id": "demo-work", "title": "Work", "account": "example.com"},
              {"id": "demo-home", "title": "Personal", "account": "example.com"})
_EVENTS = (
    ("standup", "Standup", "09:30", 15, "demo-work", None, ["Leo Example", "Maria Example"], None),
    ("lunch-leo", "Lunch with Leo Example", "12:30", 60, "demo-work", "Canteen", ["Leo Example"], None),
    ("paper-reading", "Paper reading: Diffusion Policy", "15:00", 60, "demo-work", None, ["Nina Example"],
     "Read sections 3 and 4 first."),
    ("dentist", "Dentist", "17:30", 30, "demo-home", "Example Street 12", [], None),
)

#: Round 4 Sources part 2's tab-group snapshot (`tab_groups.sync`, landing in parallel on feat/r4-sources2): one
#: episode per open group, keyed `tab-group:<browser>:<profile>:<identity>`, `source: tab-group`, origin
#: `chrome-tab-group`, the colour in `tab_group_color`. Written here in that shape directly — swap to
#: `tab_groups.body_for` once it is on dev (r4-research2/tab-groups.md §4).
_TAB_GROUP = {"identity": "saved:demo-robot-learning", "title": "Robot learning", "color": "blue",
              "tabs": (("Diffusion Policy reading notes", "https://example.com/notes/diffusion-policy"),
                       ("Teleoperation tips", "https://example.com/guides/teleoperation"),
                       ("Motion planning cheat sheet", "https://example.com/notes/motion-planning"))}

# (entity id, title, url, media type, site, channel, thumbnail, provider, origin, folder, day offset, "HH:MM",
#  description)
_MEDIA = (
    (VIDEO_ID, "Perseverance Rover's Descent and Touchdown on Mars", VIDEO_URL, "youtube", "youtube.com", "NASA",
     VIDEO_THUMBNAIL, "youtube", "chrome-bookmark", "Robotics", 0, "08:40",
     "NASA's footage of the Perseverance rover's descent and touchdown on Mars on 18 February 2021, from the "
     "cameras on the rover and its descent stage."),
    (ARTICLE_ID, "Why local-first software matters", "https://example.com/articles/local-first-software", "url",
     "example.com", None, ARTICLE_THUMBNAIL, None, "safari-bookmark", "Reading List", 0, "08:10",
     "Your notes should live on your own machine first, sync second, and never be held by a server."),
    (BOOKMARK_ID, "A gripper teardown", "https://example.com/blog/gripper-teardown", "url", "example.com", None,
     None, None, "safari-bookmark", "Favorites", -20, "14:00", ""),
)

# The paper's arXiv details as the export API returned them on 2026-09-24 (CC0 metadata; `parse_arxiv_atom`'s shape).
_PAPER_META = {
    "title": "Diffusion Policy: Visuomotor Policy Learning via Action Diffusion",
    "abstract": (
        "This paper introduces Diffusion Policy, a new way of generating robot behavior by representing a robot's "
        "visuomotor policy as a conditional denoising diffusion process. We benchmark Diffusion Policy across 12 "
        "different tasks from 4 different robot manipulation benchmarks and find that it consistently outperforms "
        "existing state-of-the-art robot learning methods with an average improvement of 46.9%. Diffusion Policy "
        "learns the gradient of the action-distribution score function and iteratively optimizes with respect to "
        "this gradient field during inference via a series of stochastic Langevin dynamics steps. We find that the "
        "diffusion formulation yields powerful advantages when used for robot policies, including gracefully "
        "handling multimodal action distributions, being suitable for high-dimensional action spaces, and "
        "exhibiting impressive training stability. To fully unlock the potential of diffusion models for visuomotor "
        "policy learning on physical robots, this paper presents a set of key technical contributions including the "
        "incorporation of receding horizon control, visual conditioning, and the time-series diffusion transformer. "
        "We hope this work will help motivate a new generation of policy learning techniques that are able to "
        "leverage the powerful generative modeling capabilities of diffusion models. Code, data, and training "
        "details is publicly available diffusion-policy.cs.columbia.edu"),
    "authors": ["Cheng Chi", "Zhenjia Xu", "Siyuan Feng", "Eric Cousineau", "Yilun Du", "Benjamin Burchfiel",
                "Russ Tedrake", "Shuran Song"],
    "published": "2023-03-07", "updated": "2024-03-14", "primary_category": "cs.RO", "doi": None,
    "journal_ref": None,
}


def write(bank_dir: Path, today: date, *, commit: Commit) -> None:
    """Everything above, in the order each piece's live writer would have run, each committed as that writer commits.
    Called last by `demo_bank.populate`, after the scenario, so no id or byte the scenario tests pin moves."""
    bank_dir = Path(bank_dir)
    day = str(today)
    media_paths = _write_media(bank_dir, today)
    commit(bank_dir, git_service.build_commit_message(
        f"Sources ingest {day}",
        ["sources/url_index.json: updated (trigger: user/media_save)",
         f"{len(_MEDIA) + 1} media item(s) saved (trigger: user/media_save)"],
        authors=["user"]), ["sources/url_index.json", *media_paths])
    # `bookmark_sync._commit_removals`: a removal is a PROPOSAL (no one chose anything yet), so it lands alone as
    # `cicada` — never inside the person's save.
    removal = _write_removal(bank_dir, today)
    commit(bank_dir, git_service.build_commit_message(
        f"Bookmark removal sync {day}", [f"{removal}: created (trigger: sync/bookmark_removal)"],
        authors=["cicada"]), [removal])
    paper = papers.page_path(bank_dir, PAPER_ID).relative_to(bank_dir).as_posix()
    paper_metadata.apply(bank_dir, PAPER_ID, _PAPER_META, source="arxiv", today=day)
    commit(bank_dir, _scoped("Paper details", "papers/metadata", "cicada", [paper]), [paper])
    # `sync_state.json` rides the calendar's commit: the live route leaves it for the next `git add -A` writer, and
    # the demo must leave nothing behind (the G85 smear).
    calendar = [*_write_calendar(bank_dir, today), sync_state.SYNC_STATE_FILENAME]
    commit(bank_dir, _scoped("Calendar sync", "capture/calendar", "user", calendar), calendar)
    tabs = _write_tab_group(bank_dir, today)
    commit(bank_dir, _scoped("Tab groups sync", "capture/tab-groups", "user", tabs), tabs)
    grace = _write_owner_statement(bank_dir, today)
    commit(bank_dir, git_service.build_commit_message(
        f"Memory update {day}", [f"{grace}: updated (trigger: user/companion_app)"], authors=["user"]), [grace])
    sleep_paths = _write_sleep_findings(bank_dir, today)
    commit(bank_dir, git_service.build_commit_message(
        f"Sleep cycle {day}", [f"{p}: updated (source: n/a, trigger: sleep/extraction)" for p in sleep_paths],
        authors=["gpt-5.4-mini"], engine="litellm"), sleep_paths)
    leo = _write_leo_beliefs(bank_dir, today)
    commit(bank_dir, git_service.build_commit_message(
        f"Agent write {day}", [f"{leo}: updated (source: n/a, trigger: mcp/claude-code)"],
        authors=["claude-code"], sessions=[SESSION]), [leo])
    for write_ in _write_pictures(bank_dir, today):
        lines = [f"{write_.page}: updated (trigger: {entity_picture.TRIGGER})"]
        lines += [f"{p}: added (trigger: {entity_picture.TRIGGER})" for p in write_.added]
        commit(bank_dir, git_service.build_commit_message(f"{write_.subject} {day}", lines, authors=["user"]),
               [write_.page, *write_.added])


# --- Saved things: a video, an article, a bookmark, a paper (the Feed; R-DL18's guide too) -------------------------


def _write_media(bank_dir: Path, today: date) -> list[str]:
    """Each item in `media_ingestor`'s own shapes — the episode `write_media_episode` writes, the page
    `write_media_entity` writes, the `url_index.json` row `ingest_one` adds — with `today` in place of its clock
    (R-PJB7), and `enrichment_attempted` set so no Sleep pass ever fetches a demo link. Returns the paths to commit."""
    idx = media_ingestor.load_url_index(bank_dir)
    paths: list[str] = []
    for (eid, title, url, media_type, site, channel, thumb, provider, origin, folder, offset, hhmm,
         description) in _MEDIA:
        day = str(today + timedelta(days=offset))
        at = f"{day}T{hhmm}:00+00:00"
        ep = _media_episode(bank_dir, eid, title, url, media_type, site, channel, origin, folder, day, at, description,
                            processed=offset < 0)
        media = {"url": url, "media_type": media_type, "site": site, "channel": channel, "thumbnail": thumb,
                 "saved_at": at, "url_hash": media_ingestor.url_hash(url)}
        if provider:
            media["provider"] = provider
        fm = {"name": title, "type": "media", "status": "active", "confidence": 0.7, "created": day,
              "last_referenced": day,
              **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
              "source_episodes": [ep], "tags": sorted({media_type, folder.lower().replace(" ", "-")}), "related": [],
              "version": 1, "folder": folder, "origin": origin, "enrichment_attempted": True, "media": media}
        body = "\n".join(["## Summary", f"Saved {media_type} — {title}."]
                         + (["", "## Description", description] if description else []))
        markdown_parser.write(bank_dir / "entities" / f"{eid}.md", fm, body)
        idx[media_ingestor.url_hash(url)] = {"media_entity_id": eid, "episode_id": ep, "url": url, "title": title,
                                             "media_type": media_type, "thumbnail": thumb, "saved_at": at}
        paths += [f"entities/{eid}.md", f"episodes/{ep}.md"]
    paths += _write_paper_page(bank_dir, today, idx)
    _index_saved_pages(bank_dir, idx)
    media_ingestor.save_url_index(bank_dir, idx)
    return paths


def _media_episode(bank_dir: Path, eid: str, title: str, url: str, media_type: str, site: str, channel: str | None,
                   origin: str, folder: str, day: str, at: str, description: str, *, processed: bool) -> str:
    episodes = bank_dir / "episodes"
    ep = episode_ids.next_episode_id(episodes, day)
    lines = [f"# {title}", "", f"**Source:** {media_type}", f"**URL:** {url}", f"**Site:** {site}"]
    if channel:
        lines.append(f"**Channel:** {channel}")
    lines += [f"**Folder:** {folder}", f"**Saved:** {day}"]
    if description:
        lines += ["", "## Description", description]
    body = episode_scrub.scrub_body("\n".join(lines), writer="demo", bank=bank_dir.name)
    fm = {"id": ep, "timestamp": at, "source": media_type, "title": title, "processed": processed,
          "content_hash": hashlib.sha256(media_ingestor.normalize_url(url).encode()).hexdigest()[:12],
          "url": url, "media_entity_id": eid, "folder": folder, "origin": origin}
    if processed:
        fm["processed_by"] = "sleep"
    markdown_parser.write(episodes / f"{ep}.md", fm, body)
    return ep


def _write_paper_page(bank_dir: Path, today: date, idx: dict) -> list[str]:
    """`papers.ensure_page`'s placeholder page (its shape, the pinned day) and both index rows through
    `papers.index_aliases`; `write` then fills it through `paper_metadata.apply`, as a fetched response would."""
    day = str(today)
    at = f"{day}T09:20:00+00:00"
    key = papers.PaperKey(arxiv_id=PAPER_ARXIV_ID)
    ep = _media_episode(bank_dir, PAPER_ID, f"arXiv {PAPER_ARXIV_ID}", PAPER_URL, "url", "arxiv.org", None,
                        "chrome-bookmark", "Papers", day, at, "", processed=False)
    fm = {"name": f"arXiv {PAPER_ARXIV_ID}", "type": "media", "status": "active", "confidence": 0.8, "created": day,
          "last_referenced": day,
          **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
          "source_episodes": [ep], "tags": [papers.KIND], "related": [], "version": 1, "origin": "chrome-bookmark",
          "folder": "Papers", "enrichment_attempted": True,
          "media": {"url": key.canonical_url, "media_type": "url", "kind": papers.KIND, "site": "arxiv.org",
                    "channel": None, "thumbnail": None, "saved_at": at,
                    "url_hash": media_ingestor.url_hash(key.canonical_url)},
          "paper": {"arxiv_id": key.arxiv_id, "doi": None, "title": None, "authors": [], "published": None,
                    "updated": None, "primary_category": None, "journal_ref": None, "venue": None, "sections": [],
                    "title_from": "placeholder"},
          "sources": [{"ref": key.abs_url, "kind": "url", "added_by": "cicada", "added_at": day}]}
    markdown_parser.write(papers.page_path(bank_dir, PAPER_ID), fm, f"## Summary\nSaved paper — arXiv {PAPER_ARXIV_ID}.")
    papers.index_aliases(idx, key, PAPER_ID, title=_PAPER_META["title"], episode_id=ep)
    idx[media_ingestor.url_hash(key.abs_url)]["saved_at"] = at      # its clock, pinned (R-PJB7)
    return [f"entities/{PAPER_ID}.md", f"episodes/{ep}.md"]


def _index_saved_pages(bank_dir: Path, idx: dict) -> None:
    """R-DL18 — a saved page `demo_bank` wrote without a Feed row (the scenario's cluster guide) gets the row
    `ingest_one` would have added, from the page's own `media:` block, so the Feed shows every saved thing."""
    for path in sorted((bank_dir / "entities").glob("media-*.md")):
        fm = markdown_parser.parse(path).frontmatter
        media = fm.get("media") if isinstance(fm.get("media"), dict) else None
        if not media or not media.get("url"):
            continue
        h = media_ingestor.url_hash(media["url"])
        idx.setdefault(h, {"media_entity_id": path.stem, "episode_id": "", "url": media["url"],
                           "title": fm.get("name") or path.stem, "media_type": media.get("media_type") or "url",
                           "thumbnail": media.get("thumbnail"), "saved_at": media.get("saved_at") or ""})


def _write_removal(bank_dir: Path, today: date) -> str:
    """A bookmark the person deleted in Safari, asked about in `bookmark_sync`'s own removal shape (G129 slice 2)."""
    from api.services.inbox_service import next_inbox_num

    inbox = bank_dir / "inbox"
    item = f"inbox-{next_inbox_num(inbox):03d}"
    markdown_parser.write(inbox / f"{item}.md", {
        "kind": "removal", "required_input": "choice", "status": "pending", "priority": 0.4,
        "entity_id": BOOKMARK_ID, "entity_name": "A gripper teardown", "title": "Still keep A gripper teardown?",
        "created_date": str(today), "question": "It was removed from Safari.",
        "options": [{"key": "keep", "label": "Keep"}, {"key": "remove", "label": "Remove"}],
        "allow_other": False, "allow_defer": True, "channel": "safari-bookmarks", "browser": "Safari",
        "url": "https://example.com/blog/gripper-teardown", "synced_at": f"{today}T07:30:00+00:00", "hint": None,
        "trigger": "sync/bookmark_removal"}, "A gripper teardown was removed from Safari.")
    return f"inbox/{item}.md"


# --- A calendar day and an open tab group (capture) ------------------------------------------------------------------


def _write_calendar(bank_dir: Path, today: date) -> list[str]:
    """Four events today, in `calendar_local.sync`'s episode shape (its `body_for`, its source ids, its extra keys),
    staged through the G20 stager with the pinned day — `sync` itself stamps the real clock. The channel's last sync
    is pinned too, so Sources says "Last synced" for it."""
    calendars = {c["id"]: c for c in _CALENDARS}
    drafts = []
    for suffix, title, hhmm, minutes, cal, location, attendees, notes in _EVENTS:
        hour, minute = (int(x) for x in hhmm.split(":"))
        start = f"{today}T{hour:02d}:{minute:02d}:00+00:00"
        end_minutes = hour * 60 + minute + minutes
        end = f"{today}T{end_minutes // 60:02d}:{end_minutes % 60:02d}:00+00:00"
        event = {"id": suffix, "title": title, "start": start, "end": end, "calendar_id": cal, "location": location,
                 "attendees": attendees, "notes": notes}
        body, _ = calendar_local.body_for(event, calendars[cal])
        drafts.append(episode_staging.EpisodeDraft(
            title=title, source_id=calendar_local.SOURCE_PREFIX + suffix, source=calendar_local.ORIGIN,
            origin=calendar_local.ORIGIN, body=body, timestamp=f"{today}T07:00:00+00:00", original_date=str(today),
            extra={"event_start": start, "event_end": end, "calendar_id": cal}, writer="demo"))
    result = episode_staging.stage(drafts, bank_dir / "episodes", bank=bank_dir.name)
    sync_state.record_sync(bank_dir, calendar_local.CHANNEL_ID, count=len(_EVENTS), at=f"{today}T07:00:00+00:00")
    return list(result.paths)


def _write_tab_group(bank_dir: Path, today: date) -> list[str]:
    group = _TAB_GROUP
    lines = [f"# Tab group: {group['title']}", "", "**Browser:** Chrome", f"**Colour:** {group['color']}",
             f"**Open tabs:** {len(group['tabs'])}", ""]
    lines += [f"- {name} — {url}" for name, url in group["tabs"]]
    draft = episode_staging.EpisodeDraft(
        title=f"Tab group: {group['title']}", source_id=f"tab-group:chrome:Default:{group['identity']}",
        source="tab-group", origin="chrome-tab-group", body="\n".join(lines), timestamp=f"{today}T08:00:00+00:00",
        original_date=str(today), extra={"browser": "chrome", "profile": "Default", "tab_group_color": group["color"]},
        writer="demo")
    return list(episode_staging.stage([draft], bank_dir / "episodes", bank=bank_dir.name).paths)


# --- Beliefs: the person's own, Sleep's, and an agent's signed ones ---------------------------------------------------


def _write_owner_statement(bank_dir: Path, today: date) -> str:
    """The person's word on where Grace works — a human claim (`origin: manual_edit`). The different reading below is
    another observer's, so it lands in its own slot (`claim_reconciler.K` includes the observer) and both stay open;
    `write_claim` hands back no nudges, so the divergence card that asks between them is written by
    `_write_sleep_findings` in `inbox_generator.write_claim_nudges`' shape."""
    write_claim(bank_dir, "grace-example", "works-at", "Acme Example", observer=owner_identity.DEFAULT_OBSERVER,
                object_kind="literal", text="Grace Example works at Acme Example", today=today)
    return "entities/grace-example.md"


def _write_sleep_findings(bank_dir: Path, today: date) -> list[str]:
    """What one Sleep night found: Grace somewhere else (a divergence), Nina's employer under a folded predicate (a
    normalization audit), a CLI page beside Tool Example A (so inbox-006's merge card is served — G98 hides a merge
    whose subject has no page), Leo's page summary, and the capture episode Leo's beliefs cite. The two items are
    `inbox_generator.write_claim_nudges`' shape with the pinned day."""
    from api.services.inbox_service import next_inbox_num

    day = str(today)
    agent = write_claim(bank_dir, "grace-example", "works-at", "Initech Example", observer="agent",
                        object_kind="literal", text="Grace Example works at Initech Example", today=today)
    owner = next(c for c in _claims(bank_dir, "grace-example")
                 if c.predicate == "works-at" and c.object == "Acme Example")
    nina = write_claim(bank_dir, "nina-example", "works-at", "Hooli Example", observer="agent", object_kind="literal",
                       text="Nina Example works at Hooli Example", today=today)
    _write_page(bank_dir, TOOL_CLI, "tool", "Tool Example A (CLI)", "The command-line side of Tool Example A.", day)
    leo = bank_dir / "entities" / f"{PERSON}.md"
    parsed = markdown_parser.parse(leo)
    markdown_parser.write(leo, parsed.frontmatter, entity_body.compose_body_v2(
        summary=_LEO_SUMMARY, key_facts=[], history_entries=[], related=[], links=[], open_questions=[]))
    capture = _write_capture(bank_dir, today)
    inbox = bank_dir / "inbox"
    divergence = f"inbox-{next_inbox_num(inbox):03d}"
    markdown_parser.write(inbox / f"{divergence}.md", {
        "kind": "divergence", "required_input": "choice", "status": "pending", "priority": 0.5,
        "entity_id": "grace-example", "entity_name": "Grace Example",
        "title": "I'm reading something different about Grace Example", "created_date": day,
        "options": ["Keep my statement (Acme Example)", "Update to Initech Example", "Both true — different context"],
        "predicate": None, "question": None, "allow_other": False, "allow_defer": False,
        "claim_id": agent["claim_id"], "existing_claim_id": owner.id, "source_episode": capture,
        "trigger": "sleep/conflict_resolution", "raw_predicate": None, "canonical_predicate": None},
        "You said Grace Example works-at 'Acme Example'; I'm now reading 'Initech Example'. Keep your statement?")
    normalization = f"inbox-{next_inbox_num(inbox):03d}"
    markdown_parser.write(inbox / f"{normalization}.md", {
        "kind": "normalization", "required_input": "choice", "status": "pending", "priority": 0.3,
        "entity_id": "nina-example", "entity_name": "Nina Example", "title": "Confirm a predicate fold for Nina Example",
        "created_date": day, "options": ["Correct fold", "Wrong fold — keep separate"], "predicate": None,
        "question": None, "allow_other": False, "allow_defer": False, "claim_id": nina["claim_id"],
        "existing_claim_id": None, "source_episode": capture, "trigger": "sleep/conflict_resolution",
        "raw_predicate": "is employed by", "canonical_predicate": "works-at"},
        "Predicate 'is employed by' was auto-folded to canonical 'works-at'. Confirm this fold is correct.")
    return ["entities/grace-example.md", "entities/nina-example.md", f"entities/{TOOL_CLI}.md", f"entities/{PERSON}.md",
            f"episodes/{capture}.md", f"inbox/{divergence}.md", f"inbox/{normalization}.md"]


def _write_capture(bank_dir: Path, today: date) -> str:
    """The conversation Leo's beliefs came from, as the Stop hook writes it (`transcript_capture`): the person's turns
    and the agent's kept replies, one episode for the session, and the per-turn sidecar with each reply's model and
    effort (round 4 C1) — through `episode_staging.render`, the sidecar's one writer (R-CS7)."""
    day = str(today)
    draft = episode_staging.EpisodeDraft(turns=[
        episode_staging.Turn(text=text, speaker=speaker, ts=f"{day}T{hms}+00:00",
                             model=MODEL if speaker == "assistant" else None,
                             effort=EFFORT if speaker == "assistant" else None)
        for speaker, hms, text in _LEO_TURNS])
    body, stamps, _ = episode_staging.render(draft)
    episodes = bank_dir / "episodes"
    ep = episode_ids.next_episode_id(episodes, day)
    fm = {"id": ep, "timestamp": f"{day}T10:00:00+00:00", "source": "claude-code", "origin": "claude-code",
          "title": "Leo and motion planning", "processed": False,
          "content_hash": hashlib.sha256(body.encode()).hexdigest()[:12], "session_id": SESSION,
          "harness": "claude-code", "capture_kind": "transcript", "captured_at": f"{day}T10:05:31+00:00"}
    episode_staging.set_turn_stamps(fm, stamps)
    markdown_parser.write(episodes / f"{ep}.md", fm, body)
    return ep


def _write_leo_beliefs(bank_dir: Path, today: date) -> str:
    """Three claims an agent wrote over MCP during that session — `mcp_tools.write_claim`'s call: observer `agent`,
    the harness as author, the session, the second it landed as `recorded_ts` (C2) — so `turn_authorship` joins each
    to the reply that answered its question and the card signs it "Claude Code · Opus 5.5 · high effort"."""
    capture = next(p.stem for p in sorted((bank_dir / "episodes").glob("*.md"))
                   if markdown_parser.parse(p).frontmatter.get("session_id") == SESSION)
    for predicate, obj, kind, text, quote, hms in _LEO_CLAIMS:
        write_claim(bank_dir, PERSON, predicate, obj, observer="agent", object_kind=kind, text=text,
                    source_episode=capture, session_id=SESSION, authored_by="claude-code",
                    evidence=[{"episode": capture, "quote": quote}], today=today,
                    recorded_ts=f"{today}T{hms}Z")
    return f"entities/{PERSON}.md"


# --- Pictures (the C11 upload rung) -------------------------------------------------------------------------------


def _write_pictures(bank_dir: Path, today: date) -> list[entity_picture.PictureWrite]:
    """Soft pastel avatars and one company mark, drawn in code (`demo_pictures` — never a real photo, never a face),
    stored exactly as `POST /entities/{id}/picture` stores an upload: validated, `assets/pictures/<id>.png`, the
    page's `picture:` key. Each is committed alone as the person's, like the route's."""
    writes = []
    for eid, top, bottom, ink in _AVATARS:
        data = demo_pictures.avatar(top, bottom, ink)
        writes.append(entity_picture.write_upload(bank_dir, eid, data, entity_picture.validate_upload(data),
                                                  today=today))
    for eid, top, bottom, ink in _MARKS:
        data = demo_pictures.mark(top, bottom, ink)
        writes.append(entity_picture.write_upload(bank_dir, eid, data, entity_picture.validate_upload(data),
                                                  today=today))
    return writes


# --- Helpers -----------------------------------------------------------------------------------------------------------


def _scoped(subject: str, trigger: str, author: str, paths: list[str]) -> str:
    """`folder_source._commit_message`'s shape — an UNDATED subject and one `updated` line per path — for the three
    writers that commit through `folder_source.commit_paths_for` (paper details, the calendar, tab groups), so the
    demo's history reads exactly as a live bank's does."""
    return git_service.build_commit_message(subject, [f"{p}: updated (trigger: {trigger})" for p in paths],
                                            authors=[author])


def _claims(bank_dir: Path, entity_id: str):
    from api.services.claims import parse_claims

    return parse_claims(markdown_parser.parse(bank_dir / "entities" / f"{entity_id}.md").body)


def _write_page(bank_dir: Path, eid: str, kind: str, name: str, summary: str, day: str) -> None:
    fm = {"name": name, "type": kind, "status": "active", "confidence": 0.6, "created": day, "last_referenced": day,
          **decay_policy.frontmatter_fields(decay_policy.default_class_for(kind)), "source_episodes": [], "tags": [],
          "related": [], "version": 1, "layout_version": 2}
    markdown_parser.write(bank_dir / "entities" / f"{eid}.md", fm, entity_body.compose_body_v2(
        summary=summary, key_facts=[], history_entries=[], related=[], links=[], open_questions=[]))

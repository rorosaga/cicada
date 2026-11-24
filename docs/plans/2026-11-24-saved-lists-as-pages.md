# Saved posts are rows, a list has a small page, a work keeps its page (ruling 81, G246)

**Status (2026-11-24, docs only).** The direction is the owner's and is recorded as ruling 81 in `docs/goals/TODO.md` (backlog row
G246 in `docs/goals/memory-evolution.md`; one line per track in `docs/goals/feature-status.md`). **Nothing in this plan is built, and
nothing the person sees has changed.** Every track ships dark behind one constant (`saved_posts.HIDE_POSTS = False`); the coordinator
flips it in a later one-line pull request only after reading a dry run on the real memory. The questions in section 7 stand at their
stated defaults. Where this text and ruling 81 differ, the ruling wins. Corrections made when this plan was filed (the code was
spot-checked at dev head `22d8aedfd`; the lines named below held):

- The backlog row is **G246** (this plan's draft said G247, which does not exist). Section 5's draft ruling is not repeated here: the
  ruling as recorded is the one in `TODO.md`, so there is one text, not two.
- **Ruling 68 is not amended.** Ruling 68 is about a file, recording, memo or photo the person added; it says nothing about a saved
  post, and a post is not one of those. What this plan changes is the quiet-page rule of 2026-10-20 ("a page only an import made is
  dimmed until mentioned", `quiet_pages`) for a saved post and for a list's page, which ruling 68's pages also use. They keep that rule.
- The ruling goes after ruling 80 in `TODO.md` (the file lists 78, 79, 80 in order), not above it as section 5 said.
- The area docs (`storage.md`, `features.md`, `app.md`, `api.md`, `mcp.md`) and `CLAUDE.md` are **not** edited by the docs track:
  nothing they describe is false while the switch is off, and the open branches edit several of them. The track that builds each part
  edits the area doc it makes wrong, in its own pull request, as `CLAUDE.md` already requires.
- Figures taken from the owner's memory are given as "about half of all pages" and nothing finer; the plan's exact counts were removed.

Planner output, 2026-11-24, revised after two critics. Code read only at dev head `7ccc6d4d9`; every
`file:line` below was opened that day unless it says "from the reading notes" (two notes files, not kept in the repository) or "to confirm".

Placeholders only (`<post>`, `<list>`, `alpha-list`). Nothing run or built when it was written. No bank, `~/.cicada`, `~/Library` or
`~/.claude/projects` read.

The owner's words that settle the direction (2026-11-24, verbatim): "ok yes, but maye a small entity page that has all the saved posts would
be good, no? i want to somehow see saved things somewhere evn if i havent refer to them yet. What would you recommend?" and, to the
coordinator, "ok go ahead with your recommendations". The recommendation he accepted: pages stay for works one refers back to; a short post
is a save without a page of its own, listed under its source; it gets a page when he talks about it or gives a reason; and one small page per
list so he can see what he saved without having referred to it. In the same message: "i just bookmarked an x post and nothing happened with the
notch or anything. same with the rest of sources". That report is now a gate on this work (section 6, Track D), not a side note.

---

## 0. What the reading changed in the intended shape (read this first)

The coordinator's shape (decide "post or work" on read, no migration, existing post pages stop being drawn and counted and show as rows under their
list, new posts may stop being written as files later) is right. These things in it were wrong or missing; each is fixed below.

1. **"From origin and kind" is not enough; the rule must key on the saved link.** `origin` is only the first door (`source_streams.py:22-24` from the reading notes;
   `_on_site` `:436`), so a post bookmarked in Chrome first has a browser origin, and `media_kinds.kind_of` has no post kind: an X status comes out
   `link`, an Instagram post `picture` (`media_kinds.py:50-68`). Five of the nine list origins are works. `saved_lists.canonical(key, url)`
   (`saved_lists.py:713-780`) already says "is this link a post of that site". The rule: the page's own saved link is a post of X, Instagram,
   LinkedIn, Reddit, Pinterest or TikTok, it is not a video the video rail knows, and the page is not a declared book, paper, repository, file, list.
2. **The decision is door-independent; the row's identity is not.** `canonical` is called only by the saved-list recorder and the in-site save
   (`mcp_tools.py:2031`, `site_saves.py:82`). A bookmark, a paste, a notch save and Telegram go through `media_ingestor.normalize_url`
   (`media_ingestor.py:214-252`), which keeps the host and strips tracking only, so a `twitter.com` status and an `x.com` status are two `url_hash`
   keys, two episodes, two pages today. `is_post` answers the same for both; the plan no longer claims one row. The dry run counts the doubles.
3. **Two corrections to the first reading.** A LinkedIn article does match the post pattern (`_LI_POST` accepts `urn:li:article`, `saved_lists.py:694-695`, a rare shape
   its own comment says it measured), so the rule excludes it. A Reddit link post is already a work: its page is the outbound link, the permalink an `alias_of` row
   (`media_ingestor.py:1350` from the reading notes), and the rule reads the page's own link, never an alias.
5. **"Earned" is not `quiet`, and it cannot read `has_note` naively.** `quiet_pages.episode_kind` calls every episode that carries `media_entity_id` an
   import (`quiet_pages.py:64-80`). Every X-connector and Pinterest save written before #858 carries `has_note: true` though its text is the author's
   (`connector_text.old_shape`, `connector_text.py:52-58`; `REPAIR = False`, `:36`); and `has_note` is also set for an agent's note on a save
   (`media_ingestor.py:2256`, `:2514`; ruling 50). The rule treats an old-shape connector episode, and a note on an episode that carries an agent's
   `session_id`, as no words of his.
6. **A folder's reason must not earn every post in the folder a page** (`history_index.PERSON_KEYS` includes `readable_by_folder`, `:99`).
7. **The graph cache and its ETag do not see an earned sign** (`graph_builder.py:154-171`, `routers/graph.py:66`): a reason is stamped on an episode,
   which moves neither. Section 4.1 adds a stamp that moves only when the earned set moves, never on an unrelated capture. **Hiding must also correct
   `degree`** (counted from raw links before nodes exist, `graph_builder.py:176-177`) and every other reader of "a page" (4.1: hubs, Related, meaning).
9. **A mention of an already-read post leaves no trace in the bank.** `saved_mentions._saves` skips an episode whose `history_index.kind` is None
   unless woken (`saved_mentions.py:~70-95`); `wake_mentioned` wakes only `saves.wakeable` (`:153-180`), and the stamp `read_asked` is popped when an
   index writer re-stages the episode (`episode_staging.py:458-463`). After #875 reads every save, "he talked about it" would be a queue row outside
   the bank. A stamp that survives restaging is needed (Track M), and **nothing is hidden before it ships** (the flip, item 12).
10. **A list page must not be a hub, a members list, or quiet.** The owner removed list hubs on 2026-10-19 (`docs/architecture/storage.md:77-105`); a
    `media:` block makes any page an import and so quiet (`quiet_pages.py:106-118`), so it needs an explicit exemption.
11. **New posts as non-files (Step B) is the expensive half and not worth doing first** (4.4).
12. **The release is gated by one flip.** Every track below ships with `saved_posts.HIDE_POSTS = False` (the `connector_text.REPAIR` pattern:
    "the coordinator sets it to True after reading a dry run", `connector_text.py:33-36`). Nothing a person sees changes until Track F flips it, and Track F
    waits for: list pages, every door landing on a list, the mention stamp, the diagnosis of the notch report, and the dry-run counts. This is what makes
    "hide first, show later" impossible, and it lets the tracks merge in any order.
13. **Lists of works get no page by default.** His 2026-10-19 decision is that a playlist is "a property of the video"
    (`docs/architecture/storage.md:77-105`); his 2026-11-24 words are about saved posts. List pages are for the lists of posts (X, Instagram, LinkedIn,
    Reddit, Pinterest, TikTok and their folders). YouTube and Substack lists wait for his answer (question 4).

---

## 1. What the person sees

Words below are the ones to use on screen and in the docs. No internal term is needed to understand any line.

### 1.1 Where a saved post lives

A post he saves (a bookmarked or liked X post, a saved Instagram, LinkedIn, Reddit, Pinterest or TikTok post, from the site's own list, from a
click inside the site, from a link he pastes, from the notch, or from his browser's bookmarks) is kept the way it is kept today: its words, its
author, the day it was posted, the day he saved it, its link, and every list and folder it is on. It is found by words and by meaning in search,
recall and Ask exactly as before. It shows as a **row under its site's list**, newest first, in Sources and in the Feed. **A post saved any way
other than the site's own list lands on a list too**: a stream called "Saved another way" under that site holds it (Track 3), so there is no door
whose posts show nowhere. It no longer shows as a page of its own in the graph or the page lists, because nobody has referred to it. Opening a
row shows the post's text and its link, as today.

The test is the link, not the door. A post he bookmarked in Chrome is the same post as the one on the site's list. An article, a video (a TikTok
video, a YouTube video), a paper, a book, a repository, a track, a recording he added, or the page behind an ordinary web bookmark keeps its page,
exactly as now. A long X thread and a Reddit thread are rows too until he talks about them: length cannot be measured without reading.

### 1.2 Seeing everything he saved in one place, before he has referred to any of it

**Sources, then the site, then the list** (Bookmarks, Likes, Reposts, Saved, "Saved another way", a folder): every item, newest first, five at a
time and "All N" for the rest; **the Feed**: every save from every source. Both unchanged except the new stream. **New: the list's own page**, opened
from the list's header on Sources, from Clusters (a "Lists" group under Media), from the graph, and from find.

### 1.3 What a list's page shows, and how it changes

The page says, in one line, what the list is ("Posts you bookmarked on X.") and carries the site's real mark. Under it: how many he has saved
there, the day of the newest, and, on the Mac that reads it, when it was last read. For a folder he gave a reason to, the reason ("why this folder",
his words) shows here and only here. Then the five newest items as the cards Sources uses (title, two lines of the post's words, the author, the
day posted, the lists it is on, how deep it was read) and "All N", which opens the whole list in place of the column (Esc comes back). Nothing on the
page is a copy: the count, the newest day and the cards are read from his saves each time it opens, so it cannot be out of date.

Over time it changes without being rewritten: the count grows, the newest day moves, the cards change. The page file is written once, when the
first item of that list arrives, and again only if the list's name changes or he removes it. An optional later step (question 1) lets Sleep add one
sentence about what he tends to save there. A folder or a playlist on a site that has them (an X bookmark folder, an Instagram collection, a
Pinterest board) gets its own small page the same way. A folder of his browser's own bookmarks does not. A list or folder with nothing in it is
not drawn and not counted (derived on read; a renamed folder leaves no orphan node). If he turns a list off, its page stays and keeps showing what
he saved; if he removes the source from Cicada, the page goes with it, undoable.

### 1.4 When he talks about a post or gives a reason

The post gets its own page, the ordinary kind (not dimmed, asked about like any page), and keeps it. This happens when: his own words name it in a
conversation (its link or its whole title); he writes or answers why he saved it (the question that appears when he saves, a note, the "why" he
types for a bookmark); a conversation or his own claim cites it; he edits its page, links it from another page, attaches it to a project, or
presses "Keep as a page" on its row (Track K). **When:** a why-answer, a note or "Keep as a page" shows at the next refresh of the graph; a
conversation naming it shows after the next Sleep that reads that conversation (the stamp is written after each batch, `sleep_cycle.py:4073`), not
at once. The card on the list says "has a page" and opens it.

Not on that list, on purpose: Sleep reading the post (it reads every save and leaves facts on pages he already has, marked as the author's, with
the post as the citation); an agent opening or summarising it on its own; **an agent's note on a save** (an episode carrying a harness's
`session_id`; his own why-answer on it still counts); the post being in a folder with a reason (that shows on the folder's page). An agent's page
edit made through a trusted harness does count: it applies at once and sets `human_edited` (`page_edits.py:695`), and no code can tell an edit he
asked for from one he did not, so the plan states it rather than guess.

### 1.5 The graph and Clusters, before and after

- **Graph, before:** every post he ever saved is a dimmed dot, joined by faint lines to the things it named. **After:** those dots and lines are
  gone; each non-empty list is one dot (sized by how much it holds once the polish step is done); a post he talked about stays, **joined to its list
  from the first release** (a read-time edge, Track 2a), and keeps the lines to the things it names. A list with no earned post is a lone dot, on
  purpose: a fake edge would be worse than none.
- **Clusters, before:** Media holds every saved link and post (about half of all pages, by another session's count on the owner's memory; one
  list read adds hundreds). **After:** Media holds the works, the lists and the posts he talked about; a "Lists" group and a "Posts" chip appear
  in the Media menu; Home's page count drops by the posts hidden.
- **Unchanged and said so:** the status page, the bank switcher and the CLI keep counting files (`entity_count`, `routers/status.py:72`,
  `cli_app.py:~1515`; the hub stats line, `hub_builder.py:262`), so two numbers exist; one dated line in the app says which is which (Track K).

### 1.6 The thousands of post pages he already has

No repair pass, nothing deleted, nothing rewritten, no commit. The files and their git history stay; each is judged on read by its link and its signs
of use, so the same page is a row today and a page again the moment he talks about it, or presses "Keep as a page".

**He will see:** the old posts he never touched leave the graph and Clusters; each non-empty list gets a page; Home's page count falls; the lines
between a post and the things it named vanish (the facts and citations on those things stay); a target page's `## Related` list no longer shows the
hidden posts (filtered on read, section 4.1 part 7). **One dated line says so** ("N saved posts now sit under their lists. Open one to keep it as
a page.", Sources header and under Home's count, Track K) so thousands of dots do not just disappear. **He will not see change:** Sources and the
Feed, search, recall and Ask, the posts' text and links, anything he talked about or gave a reason for, his files and git history. How many pages
disappear is not knowable from code: Track 1 ships a counts-only dry run (by origin and door, never a title or a link) that the coordinator reads on
his real memory and **reports to him in words before Track F**.

---

## 2. Which saves are works and which are posts

### 2.1 The rule, keyed on what the code knows

One pure function of a page's own record, in a new `api/services/saved_posts.py` (it imports `saved_lists.canonical`; it does not edit
`saved_lists.py`, which `feat/saves-words-on-screen` edits):

```
is_post(fm)  is true when every line holds
  type == "media"
  media.kind is not declared as book, paper, repository, file or list      (media_kinds.kind_of already returns these first, :57-61)
  media.url is a post of a site in POST_SITES, by post_site(url) (in saved_posts.py: canonical(key, url) for each key)
        POST_SITES = x, instagram, linkedin, reddit, pinterest, tiktok       (the platforms whose list kind is "posts"; not Spotify, Goodreads)
  the link is not a LinkedIn article (urn:li:article)
  video_urls.resolve(url) is None                                              (a TikTok /video/ link is a video: video_urls.py:49,210-211;
                                                                                video_state.is_video_page, video_state.py:127-134, G162)
  the page is not a feed item                                                  (episode_time.is_feed_item, used at media_kinds.py:62)
```

`post_site` reads the page's own link only, never an alias, never the origin, never the door. The same link through any door gives the same answer.
It cannot tell an Instagram reel from a photo post: `canonical` itself treats `/p/`, `/reel/` and `/tv/` as one post under three spellings
(`saved_lists.py:742`), and an Instagram page's media type is `instagram`, so its kind is `picture` (`media_kinds.py:36`); a reel is therefore a
row by default (question 5). A TikTok `/photo/` post is a post, a `/video/` link a work (a test pins it).

A post is **drawn as a page** when `is_post` is false or it is **earned**; **drawn as a row** when `is_post` and not earned. Earned is derived on
read, never stored on the page, and is one function that the graph node's `quiet`, the inbox's quiet test and the hubs all call (`quiet_pages.is_quiet`
returns False for an earned post, so a post he talked about is no longer dimmed and may be asked about like any page; one predicate, not two).

| Sign | Where it is recorded today | Retained? |
|---|---|---|
| A conversation or his own claim cites the page | `quiet_pages.is_quiet` (`quiet_pages.py:121-136`); `external:` claims skipped (`:130-131`) | while the claim stands |
| His own words on one of its saves: a note, a why-answer, an earlier why-answer | `saved_posts.EARNED_KEYS` = `history_index.PERSON_KEYS` minus `FOLDER_READ_KEY` (derived from the one definition, `history_index.py:99`; it differs on purpose: a folder reason is his words about the list, so it reads as his to Sleep and the activity clock and as no earn to the graph). A note counts only when the episode has no agent `session_id`; an old-shape connector episode counts as none | yes |
| His words named the save | a new key `named: {why, at}` that no re-stage pops (Track M), and `read_asked` where present (`history_index.py:91`, stamped by `wake`, `:228`) | yes: `named` survives; `read_asked` does not (below) |
| He edited or pinned the page | page frontmatter `human_edited` (`page_edits.py:695`), `corrections` (`:71`); `aliases_removed`, `sources_removed` to confirm | yes |
| He pressed "Keep as a page" | a new episode key `kept_as_page: {at}` (Track K) | yes |
| A project lists it, or a source link the person took points at it, or a non-machine edge reaches it | pre-pass over `graph_edges.yaml` rows and entities' `sources[].entity` (`graph_builder.py:~309`, a proposal excluded, `fact_sources.is_proposed`). Edges whose label only Cicada's readers write (`about`, `describes`, link recon) do not count; an edge counts only when a claim whose observer is the person backs it | while that claim or link stands |

Not earned, on purpose: an agent's read or watch of it (`CHECK_SOURCES`, `quiet_pages.py:51`); Sleep's reading and `external:` claims; a folder's reason;
a repost, like or second list; an agent's note on a save; a merge in doubt.

**Retained, not append-only (corrected after the critique).** Three signs are not strictly monotone in code, and the plan says so. (a) `read_asked`
is popped when an index writer re-stages the episode (`episode_staging.py:458-463`, "these are a bare save again"): `named` is a separate key that this
line never touches. (b) Sign 6 is rebuilt from claims, so a retracted claim removes it: it is the person's own act to retract. (c) The old-shape test
reads a body, only for episodes with a connector origin (`saved_reading.CONNECTOR_TEXT_ORIGINS`, `:35`), `has_note` and none of `_THEIRS_KEYS`
(`connector_text.py:44`), memoised per file stamp. How many that is cannot be known from code (every connector save before #858, possibly thousands, not
"a few hundred"); the dry run gives the number and the cold path is measured (section 4.1 part 3). Tests: each sign alone earns; a restage keeps
`named`; a restage drops `read_asked` and the post stays earned; retracting the only claim returns the post to a row.

### 2.2 Every origin

"Result" is for the page the origin writes. The link decides, so every row of the table says the same thing about the same link. A post goes to
the site's list it belongs to by label (Track 3 adds "Saved another way" for any door with no label).

| Origin (writer) | Usually holds | Result |
|---|---|---|
| `x-bookmarks` (list read, X connector), `x-likes`, `x-reposts` | X statuses | post, row until earned |
| `instagram-saved` (saved and "Liked posts") | `/p/`, `/reel/`, `/tv/` | post (a reel cannot be told from a link, question 5) |
| `linkedin-saved` | `feed/update/urn:li:activity|share|ugcPost`, `/posts/` | post; `urn:li:article` is a work |
| `reddit-saved` "Saved posts", "Saved comments", "Upvoted" | permalinks; link posts point outside Reddit | permalink: post (a thread too); outbound link: work |
| `reddit-saved` "Joined communities" | a community link | work (a record) |
| `pinterest`, `pinterest-saved` | `/pin/<id>` | post |
| `tiktok-saved` (`tiktok-history` makes no page) | `/@user/video/<id>`, `/@user/photo/<id>` | `/video/`: work (video rail); `/photo/`: post |
| `youtube-playlist`, `spotify-saved`, `substack-saved` | videos, tracks, articles | work |
| `github-*`, `goodreads`, `book*`, `apple-books`, `file`, arXiv and DOI papers | `media.kind` repository, book, file, paper | work |
| `chrome-bookmark`, `safari-bookmark`, `brave-`, `vivaldi-`, `comet-`, `dia-bookmark`, `safari-tab` | any link | by link: an X, Instagram, LinkedIn, Reddit, Pinterest or TikTok-photo post is a post and a row under that site's "Saved another way" **and** under the browser's bookmarks; every other link is a **work** (section 2.3) |
| `saved-link` (paste, notch, site click, agent `cicada_save_url`) and `telegram` | any link | by link; the same two lists. Today such a post lands on no list (below) |
| `rss` | feed items | unchanged (kind `feed`) |
| nil origin | any link | by link |
| `list` (new) | the list | neither: a work-like page, never a row |

**Why Track 3 exists (the owner's own report).** A post saved through a door other than the site's list read lands on no list today. `saved_lists`'
in-site save writes the site's own origin and label (`site_saves.py:82`), so that door is fine. But a click-less paste, a notch save or an agent
save carries `origin="saved-link"` (`routers/sources.py:170`, `mcp_tools.py:624`), and `source_streams._classify` puts a save with no label in a stream
only when `s.origin == origin` (`source_streams.py:~452-462`); no X stream has origin `saved-link`, and the "Saves you make" stream has
`counts="none"` (`:368-369`). `_on_site` (`:436`) pulls the page into the X source group but gives it no stream, and `_on_site` refuses browser origins
on purpose (`:428-436`), so a Chrome bookmark of a status is under the browser only. `channel_items` files it under `files` by origin
(`channel_items.py:850`). Hiding such a post first would leave it nowhere: it must have a list before it is hidden.

### 2.3 The browser-bookmark question, in plain words

**A web page he bookmarks keeps its page** (a bookmark is a deliberate save, and the page is where the fetched description, the read stamp and the
link card live, `link_enrichment.py:357-363`). **A post he bookmarks in his browser (an X status) is a row**, the same as the same post saved on
the site, because the same post must give one answer wherever he saved it (ruling 67); one `saved_posts.ROW_ORIGINS` line changes it either way.
Asked once, plainly, as question 2, default as stated. He can always press "Keep as a page" on the row.

---

## 3. The invariants

Each is a test or a measured gate (section 6).

1. **One predicate.** Every reader calls `saved_posts` (`is_post`, `drawn_as_page`, `hidden_ids`); no other module re-derives it. A test greps for the
   import and the absence of a copy in: the graph builder and its route's stamp, `/graph/meaning`, the hub builder, the `## Related` read filter,
   `channel_items` (the row's `page` field), `page_blocks`, the CLI graph, `quiet_pages`. The app holds no rule: it follows the server's nodes.
2. **Derived on read, nothing stored per post, no repair pass.** A graph build on a git bank leaves the tree clean (a test). Two exceptions, both
   one new key on an episode written when he acts: `named` (Track M) and `kept_as_page` (Track K). Neither is a pass over the old bank.
3. **Nothing lost.** A row is still stored (file, episode, `url_index`), searchable (the `med` index and vectors untouched), found by recall, Ask and
   the hook (`saved_lookup`, `hook_recall` unchanged; the ruling 62 cases in `test_lean_pass.py` pass for a post drawn as a row), openable to its text
   and link, carrying who posted it and when, and every list and folder (`id_utils.page_lists`, `save_folders`). Step A keeps the file.
4. **One answer across doors; not one row** (corrected). `is_post` is a pure function of the page's own link, so the same status through a bookmark,
   the list, Telegram and a site click gives one answer. It does not give one `url_index` row: only the list recorder and the in-site save dedup
   through `canonical`. A book, paper, repository, video or recording is never a row, whatever list it came through (a test over every origin of
   2.2). A test pins that an `x.com` and a `twitter.com` link of one status are both posts. Routing the bookmark and paste doors through `canonical`
   aliases would be a separate fix to ruling 67, not in this plan; the dry run reports how many post links exist twice so it can be judged.
5. **A post that earned a page keeps it unless the person undoes the cause** (corrected, section 2.1).
6. **No model job without a bound.** Tracks 1 to F start no model job. The optional list sentence (Track N) reads at most 40 rows, one call a list, at
   most 5 lists a run, only when 25 new items arrived since the last one, hash-gated, on a plan engine through `providers.resolve_llm_fn`
   (so `sensitive_hold` applies), never a metered key by default (rulings 4, 31), a plan limit a pause, modelled on `in_short` (`PER_RUN = 10`, from the reading notes).
7. **No API field renamed or removed.** Additions: the `/graph` parameter `include_posts` (default false; for any client, not in the app), a node-shape
   suffix, two `media_kind` values (`post`, `list`), a `page` field on list rows and stream rows, a `list` block, `hiddenPosts` on the graph response.
   `/graph` returns fewer nodes by default once flipped (its one behavioural change, said in `api.md`); the CLI `graph` command (`cli_app.py:449`)
   gets the new default and says so. `entity_count` stays a file count.
8. **The remote connector and agents see the same truth.** `page_blocks.build` is the one function the app's card and `cicada_recall_detail` read
   (`page_blocks.py:1-30`); the list block is added there. A post drawn as a row is still returned by `cicada_recall_detail(<its id>)` and found by
   `cicada_recall`. No new tool, no third door. The remote reply of a list page without the `sources` scope carries no item words
   (`test_remote_scopes_read.py`). An agent reading a target page's Related text sees the post's name; it opens by id.
9. **Ruling 80's reading works for a post with no page** (Step B only): section 4.3.
10. **A list page is not a hub.** No tag, no `member of` edge, not a member of the Media hub (the hub builder excludes `media.kind: list`), no line per
    post. A browser folder never gets a page.
11. **Portable.** The page stores no per-Mac number (last read is read live, `saved_lists.last`, from the reading notes); every name comes from the tables
    (`saved_lists.PLATFORMS`), none from a person.
12. **A list page is never quiet, never decays, never a project, never merged, and the inbox never asks about it.** Being quiet is what suppresses
    inbox questions today, so exempting the page from quiet would make it askable; the inbox gets its own exclusion and a test pins "no question
    names a list page". `entity_merge` refuses a merge or split of one; agent writes (`cicada_edit_page`, `cicada_write_claim`, `cicada_link_entity`)
    on a `list` page are refused with one sentence under the G199 contract (the guards' homes not read: Track 2b finds each precondition).
13. **Write rails.** The list writer runs only on the home (replica mode refuses writers), never into a demo bank (`demo_guard`), inside
    `write_admission` then the page lock, one commit per batch under `cicada`, never over Sleep (`media_pages.RETRY_S`, `media_pages.py:65`).
14. **Nothing is hidden until it can be found.** With `HIDE_POSTS = False` the product is today's. The flip (Track F) is refused by a test that
    saves an X status through every door (list read, in-site save, bookmark, paste, notch, agent, Telegram) and checks it is a row on a list page that
    counts it and shows it.
15. **No dead link.** Every wikilink on a page opens a page: a target page's Related lines for a hidden post are filtered on read, and a test opens
    every wikilink of a page whose edges include hidden posts.

---

## 4. The two steps

### 4.1 Step A: the rule on read for existing and new posts, and the list pages (do now)

New posts are still written as a page file by capture (no model at capture time). The change is in what is drawn, counted and listed. Parts:

1. `saved_posts.py` (predicate, `HIDE_POSTS`, the earned set, `hidden_ids`, `hidden_names`, `EARNED_KEYS`) with `post_site` inside it.
2. `media_kinds.py`: `KINDS` gains `post` and `list` (`:15`); `kind_of` returns them; **`origin_of` returns the list block's source, not the word `list`**,
   so the app's mark table has a mark (`media_kinds.py:37-47`); the app's `ClustersModel.mediaKindOrder` (`:48`) and `Copy.Lists.mediaKind` mirror them.
3. **Graph and ETag.** `graph_builder._build_full` (`:147`): a pre-pass (before the degree loop, `:176`) asks `saved_posts.hidden_ids` for the set of drawn-as-row
   posts, computed from cached frontmatter only plus `raw_links` (already loaded) and entities' `sources`/project fields, so a post processed before its
   linker is still known (the source-link and project signs are no longer discovered in the node loop, `:309`). A hidden post is skipped before
   `entity_ids.add` (`:~212`), `degree` skips edges with a hidden end, and the dangling-edge filter (`:437`) and the hub filter (`:382`) already drop what
   points at a missing node. The cache becomes two slots keyed by `include_posts` (today one `_CACHE` slot, `:104`, `:504`). `routers/graph.py` adds the
   earned stamp and `include_posts` to the ETag's `extra` (`:66`) and bumps `NODE_SHAPE` (`:51`). **The stamp** is a hash of the sorted earned ids from
   `bank_index.derived_over(memory_path, ("entities", "episodes"), "saved_posts.earned", ...)` (`bank_index.py:308`): incremental over cached headers, so
   a capture re-runs a pass over cached frontmatter (tens of ms) and the result moves only when a sign appears or goes. The graph ETag is stat-only today
   (`sync_service.etag_for`, `:389-405`; `bank_index.dir_fingerprint`, "No parse", `:425`), so the first 304 after a restart now pays a cold parse of
   both folders (about 2.4 s per 5,900 files, `bank_index.py:329`) plus the old-shape body reads; the graph build already pays that parse through
   `quiet_pages.episode_lookup` (`graph_builder.py:229`). Measured on `benchmarks/scale/hot_routes.py`: cold ETag and cold build, warm ETag, with the
   budget "no more than a tenth warm, no worse than a cold build cold". If it misses, the stamp falls back to the stat stamps of the episodes of post
   pages (`bank_index.stamps`, no parse).
4. **`/graph/meaning`** (`routers/graph.py:88`, `meaning_neighbors.py:60-76`) reads every `vec_entities` row, so hidden posts would take the five
   neighbour slots of drawn pages: it drops `hidden_ids` before `nearest_pairs`, and its signature (`:40-50`) includes the hidden-set stamp.
5. **Hubs, one rule.** `hub_builder._load_active_entities` (`:84-112`, frontmatter only) takes `saved_posts.hidden_ids` through the same function (so an
   earned post is a member and a row is not, like the graph) and excludes `media.kind: list`. Hubs are files Sleep rewrites (Stage 5.6), so the Media
   hub node's `member_count` and `degree` (`graph_builder.py:370-376`) read the old file until the first Sleep after the flip; said in the docs and
   in the dry run. `_index.md` totals, `cicada_open_hub('media')` and `edge_count` follow the file and the same night.
6. `quiet_pages`: the list exemption and the earned exemption (section 2.1), with the episode-flags memo `earned_flags` (`quiet_pages.py:~85`) the
   graph and the inbox share.
7. **No dead links.** Every `## Related` block lists inbound `about` edges by name, including a post's (`conflict_resolver.py:1403-1453`,
   `_edges_by_entity` mirrors them, `:1378-1400`; `related_edges` drops no `about`, `:1483`; `entity_body._related_bullets`, `entity_body.py:633`,
   `render_related`, `:860`), and the app resolves a `[[name]]` only through graph nodes (`MarkdownBody.swift:~261-270`, `PageLinkIndex.swift:40-60`; the
   `sanitizeID` fallback does not add the `media-` prefix), so a hidden post's link would open nothing. The fix is on read, not on write: the entity
   route that serves a page body (`routers/entities.py:108` and `_card_read`, `:173-266`) drops a `## Related` bullet whose name maps only to hidden
   posts (`saved_posts.hidden_names`). Nothing is rewritten; an earned post's line shows again at once. Test: every wikilink opens.
8. List pages: new `api/services/list_pages.py`, one writer (4.2). App: Clusters shows the new kinds; Home's count follows the graph
   (`GettingStartedCard.swift:395`); `QuickIndex.entityDocs` lets a `list` page in (`QuickIndex.swift:141`); the list header on Sources gains a quiet
   "Page" link; a card for a list page.

### 4.2 The list page, exactly

- **Type.** `type: media`, `media: {kind: list}`, a `list:` block `{stream, folder, source}` where `stream` is the frozen stream id (`"<source>.<stream>"`,
  `source_streams.py:80` from the reading notes) and `folder` the folded folder name or null. No new entity type (closed at ten, `entity_types`). `concept` is wrong
  (Stage 1 resolves concepts by name; a conversation about "my bookmarks" would write claims onto it). `directory` means a folder he works in. A hub
  is the thing he removed.
- **Id and name.** `list-<stream with dots as dashes>[--<folder slug>]` (two folders that slug alike get a short hash). It must not start with `media-`:
  `inject_media_edges`, `link_enrichment`, `link_recon`, `reading_walls` and `source_proposals` glob `media-*.md` (`media_ingestor.py:3074`,
  `link_enrichment.py:357`). Name: the source's name, the list's label and, for a folder, the folder ("X: Bookmarks", "X: Bookmarks, <folder>").
- **Stored:** identity, one fixed first sentence from the stream's spec, the day it was born, `status: active`, empty `tags`. **Derived on read:** the
  rows, count, newest day, depth words, last read, and for a folder the reason (`save_folders`, `GET /sources/save-folders`).
- **Which lists (corrected).** Only lists of posts: every stream with `counts == "members"` whose source is X, Instagram, LinkedIn, Reddit, Pinterest
  or TikTok and which holds at least one member (`source_streams._saved_groups`), including the new "Saved another way" stream, plus one page per
  site folder (`Episodes.folder_names`, `source_streams.py:390-402,514-580`). Not YouTube, Substack, Spotify, history streams, directories, books,
  feeds, any browser folder (question 4). About a dozen stream pages and tens of folder pages against thousands of media pages.
- **The writer** (`list_pages.sync`, a copy of `media_pages`'s shape, `media_pages.py:304-474`): no model, file and git work alone; triggered after a
  list read lands (`cicada_record_saved_list` commits), at start-up (`main.py`) and after a Sleep run (`sleep_cycle.py:2416` from the reading notes). Idempotent. A
  page that exists in any status holds its key, so a page he archives or drops is never recreated (memory is in the page itself). Retired, undoably,
  when the source is forgotten (`media_pages.py:66,200`). An empty list is never written and never drawn.
- **The block.** `page_blocks.KINDS` gains `list` (`page_blocks.py:40`, `SHAPE` bump): `{stream, folder, count, newest, why, recent: up to 5
  {title, author, posted, saved, url}}`; `why` is the folder's reason, read at the time (the field the folder card needs). The app draws its own
  cards from the items route; the five compact rows are for agents and the CLI (about 8 ms warm for the largest list, `docs/architecture/app.md:2810`).
- **The card** (`EntityDetailCard.pageBlock`, `EntityDetailCard.swift:499-519`; a new branch beside `isFile` and `isBook`): head with the source's real
  mark (DR-52), one line of what the list is, "N saved, newest <day>, last read <when>" (DR-38), the folder's reason, five cards
  (`SourceStreamCards(key: SourceListKey.make(channel, stream:, folder:), cap: 5)`, `SourceStreamItems.swift:141`) and "All N" (DR-81). An empty list
  draws nothing. DR-37, 38, 52, 74, 78, 81, 60/61, 71. No picture, no glyph.
- **Graph.** The node exists once the page does and is non-empty. It carries `member_count` (`schemas.py:2571`); sizing is polish (`nodeMemberCount` is
  defined and called nowhere, `graph.js:434`). **Edges (moved into Track 2a):** a read-time edge from a list to each earned post that is a member (the
  `source_links` mechanism, `graph_builder.py:309`; membership from `source_streams.members().streams_of` and `folder_matches`, read only, never
  persisted, never one per hidden post) and from a folder page to its list's page. G109: every custom force stays alpha-scaled.

### 4.3 Where Sleep's reading lands, with and without a page

With the file kept (Step A) nothing moves: facts land on pages he already has as claims observed `external:<author, else site>`, evidence spans in the
save's own episode (`authorship.is_saved`, `authorship.py:64-72`), at most twelve open ones a page, exact-name joins (#862); the post's page keeps its
`about` edges (written to pages the save names in full, at most five, `media_ingestor.py:3034-3103`) but they are not drawn while it is a row. **The
one-sentence "what it is about" on the save's own page (ruling 80 section 1.2) is not in code** (no writer found; the only `describes` writers are a page
read and a video watch, `page_read.py:20`), and this plan does not add it.

With no page (Step B): facts and citations are unchanged (they cite the episode); the citation opens the Reader at the span (`ProvenanceRouter.swift:89-100`);
the `about` edge does not exist, which matches "one node in place of hundreds"; a name met only in saves stays held (`pending_store`).

### 4.4 Step B: new short posts are not written as a page file (later; not done now)

What must then live on the save's own record (from the first reading; lines are its own unless shown above): lists beyond the first (`collections:` lives only
on the page, `add_collection`, `media_ingestor.py:2651`, empty id returns False `:2663`), a later author (`give_channel`, `:2680`), item rows for lists
(`channel_items._collect` is page-driven, `_feed_episode_rows` `:579-593`) and counts (`source_streams._count`, `saved_media` `:427`); about sixteen
path builders that name `entities/{id}.md` unguarded (`mcp_tools.py:661,666,1766,1771,2060,2066,2070,2275,2280`, `routers/sources.py:200,736`,
`telegram_capture.py:480`, `reading_service.py:123`); the agent doors that refuse a save with no page (`watch_record.resolve` `:77-86`, the page read
`mcp_tools.py:1535`, `explore_candidates` `:131`, `source_proposals._save_of`, `page_links._saved_page`); an earn writer modelled on `media_pages.sync`; the
find's dedup (`QuickIndex.mediaDocs`, `:162-175`); and the defects of the existing pageless seam (feed items) that a copy inherits:
`quiet_pages.episode_kind` classes an episode with no `media_entity_id` a conversation (`:64-80`), a second list is dropped, `saved_mentions.wake_lit`
needs a page, `reading_service.ask` returns `mediaEntityId: ""`, a tombstoned pageless row is not filtered by the Feed.

**Migration-free path.** Flip `is_pageless` (`media_ingestor.py:2538`) for a post with no reason at write only; a reader `saved_rows` merges files and
pageless episodes by `url_hash`; the earn writer builds the page from the episode. **Recommendation: not now.** What he sees is entirely delivered by
Step A; Step B changes what is on disk (one fewer small file per save, no measured pain) and touches about sixteen writers, a dozen readers, three
agent doors and the find; #875 is about to change how saves are queued; the dry run will say what share of posts ever earns a page. **Revisit when:** a
measured cost (graph build, git size, page walk in Sleep) names the files, or the first real nights of reading are judged.

---

## 5. The ruling text

Recorded as **ruling 81** in `docs/goals/TODO.md` (after ruling 80), with the backlog row **G246** in `docs/goals/memory-evolution.md` and one line
per track in `docs/goals/feature-status.md`. The draft that stood here was replaced by that text, made true to what is decided: the direction is
the owner's two sentences; the rule for which saves are posts, the list pages, "Keep as a page" and the dark release are the coordinator's
recommendations that he told to go ahead; nothing is built. The area docs and `CLAUDE.md` are edited by the tracks that change what they
describe (section 6), not by the docs track. `CLAUDE.md` was within a few characters of its size limit when this was filed, so a rail line
there must be paid for by cutting as much from the same rail.

---

## 6. Tracks (one pull request each to `dev`, each from its own worktree)

### The order, and what each touches

Three branches are open and stacked: `feat/saves-wait-for-sleep` (#875) with `feat/saves-words-on-screen` and `feat/grouped-save-read`. Checked against
`git diff --name-only origin/dev...<branch>` (corrected: the first plan checked one branch only): **all three edit `api/services/mcp_tools.py` and
`source_streams.py`; `saves-words-on-screen` also edits `saved_lists.py`, `mcp/server.py`, `channel_items.py`, `source_overview.py`, `media_ingestor.py`,
`schemas.py` and the app's `SourcePageStreams.swift`; #875 and `grouped-save-read` edit `saved_mentions.py`, `history_index.py`, `episode_staging.py`,
`sleep_cycle.py`, `TODO.md`, `storage.md`.** Tracks marked "after the stack" wait for all three to merge. Everything ships behind `HIDE_POSTS = False`
(section 0 item 12), so merge order inside "ships dark" is free.

| Track | Suggested branch | Files touched | Depends on |
|---|---|---|---|
| 0 docs | `docs/ruling-81` | `TODO.md`, `memory-evolution.md`, `feature-status.md`, new `docs/plans/2026-11-24-saved-lists-as-pages.md`; no area doc, no `CLAUDE.md`, no `DESIGN_RULES.md` (the list's card in 4.2 applies DR-37, 38, 52, 74, 78 and 81 and departs from none, so §9 gets no line; Track 2a cites them again) | nothing (rebases over the stack's doc edits) |
| D diagnosis | `diag/notch-saves` (a report first) | none first; then whatever the cause needs (`SaveWhy/*.swift`, `SiteSave.swift`) | nothing; **gates Track F** |
| 1 rule | `feat/posts-are-rows` | new `saved_posts.py` (with `post_site`), `media_kinds.py`, `quiet_pages.py`, `graph_builder.py`, `routers/graph.py`, `meaning_neighbors.py`, `hub_builder.py`, `routers/entities.py` (Related filter only), new `api/scripts/saved_posts_dry_run.py`, `schemas.py` (a field), app: `Models/Entity.swift` (both kinds, `MediaBlock.isList`), `Theme/Copy+Lists.swift`, `ClustersModel.swift`, `MediaKindChips.swift` | nothing; none of the three branches' files except `schemas.py` (a different region, to confirm) |
| 2a lists | `feat/list-pages` | new `list_pages.py`, `page_blocks.py`, `routers/entities.py` (`_build_media_block` only), `main.py`, `entity_merge.py`, `graph_builder.py` (the read-time edges), `quiet_pages.py` (list exemption), `hub_builder.py` (list exclusion), app: `EntityDetailCard.swift`, new `Views/Graph/ListPageCard.swift`, `Search/QuickIndex.swift`, `Theme/Copy+Lists.swift` | Track 1 merged (the `list` kind, hub and quiet changes) |
| 2b lists, the stack's files | `feat/list-pages-sources` | `source_streams.py` (a `page` field on a stream row, near `_stream`, `:733`), `mcp_tools.py` and `mcp/server.py` (recall words the block; the agent guards), `sleep_cycle.py` (one line next to the `media_pages` call), app `Views/Sources/SourceStreamItems.swift`, `Models/SourcePageStreams.swift` | Track 2a, **after the stack** |
| 3 doors | `feat/saved-another-way` | `source_streams.py` (the stream and its membership by `post_site`, browser origins and `saved-link` included), `channel_items.py`, `source_overview.py` (counts), `Models/SourcePageStreams.swift` (the label) | Track 1, **after the stack** |
| M mention | `feat/named-stamp` | `saved_mentions.py`, `history_index.py`, `episode_staging.py` (the `named` key that no restage pops) | **after #875 and `grouped-save-read`** |
| K keep | `feat/keep-as-page` | one route in `routers/sources.py` (stamps `kept_as_page`, committed as the person), `saved_posts.py`, app: the row's action, the dated line, Home's count note | Track 1, after the stack for `routers/sources.py` |
| F flip | `flip/hide-posts` | one line in `saved_posts.py`; the release PR | 1, 2a, 2b, 3, M, K, D, the dry run read and reported to the owner, his answers |
| N, P, S later | `feat/list-notice`, `fix/pageless-seam`, `feat/pageless-posts` | as section 4.4 | on request or the revisit trigger |

### Track 0: `docs/ruling-81`. Docs only. First.
Done: ruling 81, the G246 row, the feature-status lines and this plan, checked by `api/tests/test_claude_md_size.py` and
`api/tests/test_crucial_tier.py` and a read against rulings 62, 67, 68, 80 for contradictions. It shares `TODO.md` with the three open
branches: a rebase, not a dependency.

### Track D: `diag/notch-saves`. A diagnosis, before and alongside everything. Owner: the coordinator, on the scratch app.
**The report:** he bookmarked an X post and neither the notch nor anything else answered, and "the rest of sources" behaved the same. The plan cannot
answer it from code; it names the gates the code has, in order, and the one question that tells which door he used (section 7, question 0):
1. **X's own bookmark button** (the in-site save, ruling 77): `SiteSaveWatcher` reads nothing unless Accessibility is already granted
   (`SiteSave.swift:835`, `trusted`), a site is connected or is the offered candidate (`watched()`, `:~845-850`), and `isWanted` holds; an unknown layout
   or direction asks nothing (`app.md:1596-1650`). With Accessibility off or X neither connected nor offered, **nothing happens, by design**.
2. **Chrome's star or the bookmark's ⌘D** (G191 v4/v5): the question needs the browser's bookmark source on, the bubble shape known, and the file diff
   (`BookmarkBubble.swift`, `SaveWhyPolicy.swift`); a bookmark at launch or Sync never asks.
3. **The backend refused or held it:** a save while Sleep holds the pages is held (`SiteSaveOutbox`, up to a day) and asked about only within five
   minutes; a stale one is stored and never asked late (`app.md:1596-1650`).
4. **It landed and showed nowhere** (a bookmark or paste of a status sits under the browser or `files` and under no X list, 2.2, Track 3), or **"the rest
   of sources" too**, which points at a common cause: a backend that is down, an old build, or the live install on a moving checkout. His own machine
   cannot be read from here.
The track: reproduce each door with a status on the scratch app (`verify-cicada`, features `saved-links-and-reading.md`, `sources.md`), read the
`site-save` log lines (an outcome word, what settled it, milliseconds; never a link), fix what is a defect, report what is a missing permission.
**Track 3's verification and the "ask why" earn path use a typed note or a conversation mention, never the notch**, so they are testable when the
notch is not.

### Track 1: `feat/posts-are-rows`. The rule, the graph, Clusters, hubs, meaning, Related, the dry run. Ships dark.
- New tests: `test_saved_posts.py` (every origin of 2.2 as a parametrised case, including a TikTok `/video/` and `/photo/`; each link shape per site;
  an `x.com` and a `twitter.com` link are both posts; alias and door independence; LinkedIn article is a work; a Reddit link post is a work; declared
  kinds are never rows; each earned sign alone earns; Sleep's `external:` claim, an agent read, an agent note and a folder reason do not; an old-shape
  connector episode is not words of his; a restage keeps `named` and drops `read_asked`; retracting the only claim returns a row), `test_graph_builder.py`
  (with `HIDE_POSTS` on and off: a row is absent, its target's `degree` falls, an earned post is present with its edges and not quiet, the cache key
  and ETag move when a save gains a why-answer with no page change and do **not** move on an unrelated capture, `include_posts` has its own cache slot,
  a clean git tree after a build), `test_hub_pages.py` (a row is no hub member, an earned post is, a list page is not), a meaning-neighbours test (a hidden
  post takes no slot), an entity-route test (no Related bullet for a hidden post; every wikilink opens), `test_lean_pass.py` (ruling 62 cases unchanged
  for a row), the inbox test (an earned post may be asked about; a row never), app `ClustersModelTests`, a crucial-tier line for invariants 4 and 15.
- Verified by: the dry run on a scratch bank, then by the coordinator only on the real memory: counts by origin and door (posts, works, earned by sign,
  hidden, posts saved through a door that lands on no list, post links that exist twice, Related lines that would be filtered, old-shape episodes, degree
  changes), never a title or a link; timing of `/graph`, its ETag cold and warm, and `/graph/meaning` before and after on `benchmarks/scale/hot_routes.py`.

### Track 2a: `feat/list-pages`. One writer, one block, one card, the find exception, the read-time edges.
- New tests: `test_list_pages.py` (born at the first item and not before; id never starts with `media-`; empty tags; not a member of any stream or hub; not
  counted by `is_files_media` (`source_overview.py:330`); never quiet; never merged; no inbox question names it; idempotent; archived stays archived;
  retired on forget, undoably; an empty or renamed folder is not drawn; demo bank and replica refuse; Sleep holding retries; the same bank on two
  machines gives the same pages; **every earned post is joined to its list and every folder page to its list's page**), `test_page_blocks.py` (block
  shape, same dict for the card and `recall_detail`), `test_remote_scopes_read.py` (no item words without `sources`), app `ListPageCardTests`,
  `QuickIndexLatencyTests` (the exception, no latency change).
### Track 2b: `feat/list-pages-sources`. After the stack.
The Sources header link, the `page` field on stream rows, the recall words, the guards on agent writes to a list page (one `list_pages.is_list(fm)` check at
each precondition: `entity_merge`, `page_edits`, `cicada_write_claim`, `cicada_link_entity`), the post-Sleep trigger. Tests: the `page` field; an agent write
to a list page is refused with its sentence on both doors; the 8 ms row read re-measured with `stream=` and `folder=`.

### Track 3: `feat/saved-another-way`. After the stack. **The owner's report, made structural.**
Add, for each of X, Instagram, LinkedIn, Reddit, Pinterest and TikTok, one stream "Saved another way" (`counts: members`): its members are the site's
posts by `saved_posts.post_site` from **any** origin (a browser bookmark, `saved-link`, Telegram, nil origin) that sit on no other stream of that
source. It is the one place `_on_site`'s refusal of browser origins (`source_streams.py:428-436`) is lifted, and only for a post link. The same post
still shows under its browser's bookmarks. Tests: **save an X status through each of seven doors (list read, in-site save, Chrome bookmark, Safari
bookmark, paste, agent `cicada_save_url`, Telegram) and check the status is a row on a list that the list page counts and shows**; a status with a list
label is on that list and not also on "Saved another way"; a non-post link never is. Verified by the scratch app with a typed note, not the notch.

### Track M: `feat/named-stamp`. After #875 and `grouped-save-read`.
When his words name a save that is already read, stamp `named: {why, at}` and nothing else (no flip, no queue; the one change to #875's "for one already
read, only the ask"); when they name a waiting one, `wake` as today. `episode_staging.py:458-463` is left popping `read_asked`, never `named`. Tests: a
post read on the first night, then named in a conversation, becomes a page (the missing test of the first plan); a mention of a waiting post is
unchanged; the stamp never changes `processed` or `kind`; `test_depth_on_mention_g245.py` still passes; the page appears after the batch commit.

### Track K: `feat/keep-as-page`. After Track 1.
A one-click "Keep as a page" on every row with no page (Sources row, Feed detail) stamps `kept_as_page` under the episode lock and commits as the person;
it is also the way back for a work wrongly drawn as a row. The dated line (1.6) and `hiddenPosts` from the graph response. Tests: route and stamp; the
post reappears at the next graph; no stamp on a demo bank.

### Track F: `flip/hide-posts`. The release.
One line (`HIDE_POSTS = True`), plus the docs sentence and the dry-run numbers in the PR body. **Refused unless:** the door test of invariant 14 passes,
the mention test passes, Track D's report is in, the coordinator has read the dry run on the real memory and told the owner in words how many pages
will leave the graph and what became of every door, and the owner has answered or let stand each default in section 7.

### Tracks N, P, S. Later.
N `feat/list-notice` (optional, question 1): a tail step beside `in_short`; a list qualifies after 25 new items; one call reads at most 40 items (title,
author, first 160 characters), at most 5 lists a run, a plan engine through `providers.resolve_llm_fn`; at most two sentences about what the list holds,
never about him; dated, observer `agent`, committed alone. P `fix/pageless-seam`: the defects of 4.4. S `feat/pageless-posts`: section 4.4's list.

### How each is checked in the real thing
`verify-cicada`, a second copy of the app on a scratch home, never the live install; a worktree checkout via `--checkout`. Fixture: about 130 saves
through the production writers (`saves_fixture.capture_saves`, `benchmarks/consolidation/saves_fixture.py`): 40 X posts (3 with a reason, 2 named in a
conversation, 1 outbound-link repost, one status in both `twitter.com` and `x.com` spelling), 12 Instagram, 10 LinkedIn (1 article), 6 Reddit (2 outbound),
6 Pinterest, 6 TikTok (3 `/video/`), 8 YouTube videos, 3 papers, 4 books, 12 Chrome bookmarks (3 of X statuses), 3 pasted statuses, 2 X folders (one with
a reason). Screenshots at dev head and on the branch, light and dark: Sources X Bookmarks and "Saved another way"; the list's page; Graph; Clusters Media;
Home's count and the dated line; find; a target's Related list; the post's page reappearing after a reason. The coordinator reads the fixture's counts
against the expected table first. A real-memory read is the dry run only.

---

## 7. Open questions for the owner (each changes what is built; each has a default if he does not answer)

0. **(Diagnostic, one sentence.)** When you bookmarked the X post, did you press X's own bookmark button or Chrome's star, and is Accessibility
   switched on for Cicada (Settings, Permissions)? It decides which gate in Track D applies. **No answer:** the coordinator reproduces both.
1. **Should Sleep write one short sentence on each list's page about what you tend to save there?** It costs a small model call per list now and then
   and says something about your habits from strangers' posts. **Recommendation: not yet.** **No answer:** not built.
2. **A web page you bookmark in your browser keeps its own page (a bookmark is deliberate). A post you bookmark in your browser, such as an X status, sits as a
   row with the rest of your saved posts, because it is the same post wherever you saved it, and you can press "Keep as a page" on it. Is that right?**
   **No answer:** exactly that. One line makes every browser bookmark a row, or every bookmarked post a page.
3. **Does a reason you gave a whole folder make every post in it a page?** **Recommendation: no**; it shows on the folder's page ("why this folder").
   **No answer:** no.
4. **Should your YouTube playlists, Watch later and Substack saved list get a page each, too?** Their items are works that already keep pages, and on
   2026-10-19 you chose that a playlist is a property of the video, so a list page would add dots that join nothing. **Recommendation: no.** **No answer:** none.
5. **Is a saved reel or TikTok video a post or a work?** TikTok videos are treated as videos (they have pages) because Cicada's video queue already
   treats them so; Instagram reels cannot be told from photo posts by link, so they are rows. **No answer:** as stated.

Not asked, decided here: new posts as non-files (Step B) later (4.4); per-folder pages follow the recommendation he accepted; works keep pages (his
option (a)); a long X or Reddit thread is a row until he talks about it.

---

## 8. Not verified, and out of scope

- **How many of the media pages are posts by this rule, and how many are earned:** not knowable from code. Track 1's dry run is the measurement; it
  also gives the number of list pages, degree changes, double-spelled links, door counts and Related lines filtered.
- Not read: whether any test pins `media_kinds.KINDS` against the app's lists; whether `entity_merge` already guards by kind; where each agent-write
  precondition lives (Track 2b); the frontmatter key names for "he edited the page" beyond `human_edited` and `corrections`; the `video_urls.resolve`
  answer for a TikTok `/photo/` link (a test pins it); `SiteSaveWatcher.watched()`'s exact lines (`SiteSave.swift:~845`).
- Whether a Reddit, Pinterest or TikTok save stores the canonical form of its link in `media.url` (it does for X, Instagram, LinkedIn per `canonical`'s
  aliases and `write_prepared`; Track 3's test runs the six sites through the real writers).
- `GET /sources` on a row with no page and how the Reader draws a pageless save: not run (Step B only).
- The cause of the owner's notch report: **not known**, not diagnosed here; Track D owns it and gates Track F. Out of scope: watch history, follows,
  records, feed items, the daily pace of reading (#875), the Sources redesign, and routing the bookmark and paste doors through `canonical` (a separate
  fix to ruling 67, counted by the dry run).

---

## 9. What changed after critique

Two critics attacked the first revision (an owner-view critic and an engineering critic). Each blocker and serious flaw, and what was done:

| Flaw | Done |
|---|---|
| Owner blocker: a post saved through another door lands on no list; the missing notch called a side note | Evidence confirmed (`source_streams.py:~452-462`, `:368-369`, `:428-436`, `channel_items.py:850`). Added Track 3 ("Saved another way"), invariant 14 (a seven-door test refuses the flip), the `HIDE_POSTS` flip (section 0 item 12) so nothing hides before it, and Track D, the diagnosis, as a gate. Keeping posts drawn for their first days: not adopted, the flip does it better. Engineering: the notch report had no track, so Track D, question 0, and Track 3's verification avoids the notch |
| Owner blocker: a mention of an already-read post earns nothing, and the first release ships before the fix | Evidence confirmed (`saved_mentions.py`, `episode_staging.py:458-463`). Track M (the `named` key), made a hard dependency of Track F; test added; the first-night case written into section 2.1 |
| Owner serious: a hidden post's `[[link]]` in a target's Related list opens nothing | Confirmed (`conflict_resolver.py:1403-1453`, `MarkdownBody.swift:~261-270`). Fixed on read (4.1 part 7, invariant 15), not on write, so an earned post's line returns at once and nothing is rewritten |
| Owner serious: pages for YouTube lists, playlists and Substack reverse his 2026-10-19 decision and float | List pages are for lists of posts only (section 0 item 13, 4.2); question 4 |
| Owner serious: Instagram reels and TikTok videos are works | Partly. TikTok `/video/` is a video on the video rail (`video_urls.resolve`), so a work. Instagram reels cannot be told from photo posts by link (`canonical` aliases `/p/`, `/reel/`, `/tv/`), so rows; question 5. The critic's remark that `media_kinds` already says `video` for them is wrong for both: a TikTok page keeps `url`/`bookmark` as its media type (`media_ingestor.py:259-264`) and an Instagram page is `picture`. Long X and Reddit threads: stated plainly as rows Engineering: a TikTok video contradicted the video rail; fixed by `video_urls.resolve(url) is None` in the rule |
| Owner serious: the graph is worse for posts he talks about until Track 3 adds the edge | Moved to Track 2a (the mechanism exists, `graph_builder.py:309`). The test "no list node has degree 0" is **considered and kept out**: a list with no earned post has nothing honest to join to; the test pins that every earned post is joined and every folder page joins its list |
| Owner minor: the old bank changes with no sentence in the app, no way back | Dated line, `hiddenPosts`, "Keep as a page" (Track K); counts reported to him before the flip |
| Owner minor: the page appears only after Sleep reads the conversation; agent notes counted | Said in 1.4; agent note and agent `session_id` excluded; an agent's page edit stated to count and why |
| Owner minor: a bookmark is deliberate, yet a bookmarked post is a row | Said plainly in 2.3 and question 2 with a default; "Keep as a page" is the way back. Not changed to by-door, because it would give one post two answers (ruling 67) |
| Engineering serious: "one `url_index` row across doors" is false | Confirmed (`canonical` callers `mcp_tools.py:2031`, `site_saves.py:82`; `normalize_url` keeps the host). Invariant 4 and section 0 item 2 rewritten; the dry run counts doubles; routing other doors through `canonical` named a separate fix |
| Engineering serious: hubs are persisted; two parts disagree about a page | One rule: the hub builder calls the same function and excludes lists; the Media hub's count is stale until the first Sleep after the flip, said in the docs (4.1 part 5). Other readers that treated hidden posts as pages are listed and decided: meaning neighbours (4.1 part 4), Related (part 7), counts (1.5, invariant 7) |
| Engineering serious: "every sign is append-only" is false | Rewritten as "retained" with the three exceptions; `named` survives restaging; node `quiet` follows earned (one predicate in `quiet_pages`); sign 6 restricted to the person's claims |
| Engineering serious: tracks 1 and 2 share files; the first plan checked one branch | Rechecked against all three; the table in section 6 gives files and dependencies; `post_site` moved into `saved_posts.py`; stack-file work moved to 2b and 3 after the stack; shared Swift files owned by Track 1 |
| Engineering serious: the ETag needs a parse; the cache has one slot; source-link signs found in the loop | Section 4.1 part 3: `derived_over` stamp that moves only on a sign, cold path measured, two cache slots, a pre-pass; "a few hundred" vs "thousands" resolved to "unknown until the dry run" |
| Engineering minor: a forked "words of his"; list-page claims unsupported; the CLAUDE.md budget | `EARNED_KEYS` derived from `PERSON_KEYS`; `why` in the list block; `origin_of` for `list`, an inbox exclusion test, agent write guards, no orphan folder pages (derived); `wc -m` = 59,986 and the trim budgeted in Track 0 |

**Considered and kept.** (1) "No list node has degree 0": kept out, see above. (2) "Keep a post drawn as a page for its first days": the flip is stronger and
has no clock. (3) "Hubs ignore `is_post`": not taken, an earned post would be drawn but absent from its hub while works have `member of`. (4) Browser-bookmarked
posts as pages by default: kept as rows for the one-answer reason, put to him in plain words. (5) The Related fix on write: kept to read time, so
earning changes the answer with nothing stale or rewritten.

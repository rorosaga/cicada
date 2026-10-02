# Reading the web: how Cicada reads a page, and which pages it reads

**Commit as:** `docs/specs/2026-09-29-reading-the-web-design.md`
**Base:** `dev @ 2155940`, 2026-09-29. **Status:** design only, **revision 2** (folds in a review of revision 1 against the
code; the changes are marked in §14 and §16). No code, no bank write, no dependency added.
**Backlog home:** new rows, numbers assigned when filed (the owner asked for them in the same session). Proposed titles
are in §12. This spec extends G102 (site recon), G61 phase 2 (the escalation ladder), G133 (papers, `never_scraped`),
G140 (`cicada_record_watch`) and G105/G149 (capture and recall that never depend on a model choosing a tool). It
duplicates none of them.
**Sibling specs, same day.** The **video queue** spec (thumbnails, transcript vs watch) and the **Sleep page v5** spec
(progress, engine menu) are written beside this one. §7.4 and §8.4 name the two seams. Where they differ, the sibling
wins for its own surface and this spec wins for the reader, the chat links and the browser modes.

**Privacy.** Every number about the owner's data below is an aggregate count. No URL, host, title, conversation or
episode is quoted. Examples use `example.com` and placeholders. The counts were taken from the owner's own export files
and active bank on 2026-09-29 by a throwaway script in the scratchpad, not committed.

**Legend.** **[measured]** = run by the author of this spec on 2026-09-29. **[reported]** = the research pass's own
run or a vendor's statement, not re-run here. **[assumed]** = stated so a later measurement can disprove it.

> **The owner's request (Rodrigo, 2026-09-29, verbatim, in two parts).**
> "The other thing i'm wondering then is wether we should implement a low level fast scraper for websites, and that way
> the agents dont have to use something like browser harness, tho i think if using something like browser harness in
> the background or browser use from chatgpt or claude directly is really good because that way stuff like linkedin,
> twitter or whatever can be seen from the logged in sessions of the user themselves. So in parallel maybe research
> about extremely fast scrapers we can implement because we eithe rneed the agent's freedom to look at the page itself
> and even interact if needed, or the scraper that just gives what's on the site. maybe this can be different modes we
> can offer, and by default we set one..."
>
> "Design for all the video stuff, an improved design for the consolidation (sleep) page, and also wether we have some
> sort of computer use/browser harness (from the browser use skill), turned on so that our consolidation can run using
> this."
>
> "Also in backlog document for futurue, that i think we can use a classifier model to navigate quicker and cheaper,
> through websites using a model like jev. thing is that its not in the plans people normally have. but we can build it
> still and have it in settings as an option and a "needs openrouter" or smth like that, if the user wants to turn it
> on."

The session also asked, in the owner's words paraphrased, what to do about links inside imported chats: they are never
fetched today, and the two big exports likely hold thousands. §6 answers that with measured counts.

---

## 1. What this spec decides, in ten lines

1. **Two axes, not one list of modes.** *Automatic reading* is what Cicada may do on its own, even at 3 a.m.:
   **Off · Reader (default) · Reader + local browser engine (later, optional)**. *Reading with an agent* is what the
   person's own agent may do on pages they pick: **Off (default) · With my browser**. The two axes exist because ruling 4
   forbids a scheduled cycle from spending plan quota, and a signed-in browser is a plan-quota action. One flat list
   would hide that.
2. **The Reader is a ladder on the same bytes, not a headless browser.** An honest User-Agent, `Accept: text/markdown`,
   robots.txt honoured, metadata first, then readable text, then a distinct `needs_js` status (§4).
3. **A login wall is never fetched by the backend.** X, LinkedIn, Instagram, Facebook, TikTok and Reddit are read only
   by an agent in the person's own browser, and only after the person's explicit "Ask an agent" on that link, or per site
   the person turned on after a page from it could not be read (§5, §8). Cicada asks; what the agent does in its browser
   is up to it and the person.
4. **Chat links.** Read the links **the person shared** (594 unique across the two exports, measured, 536 of them readable).
   Do **not** read what an assistant cited (1,389 unique) or consulted (3,031 more), except an assistant link that came up
   in two or more conversations (at most about 23, measured). Never read a link that is a login, an unsubscribe, a
   magic link or a signed URL (§6).
5. **Import stays network-free and mints no page.** Parsers keep a `links` sidecar on the episode, offsets taken from the
   stager's own scrubbed text. Reading is a queue, with its own lane (which the two existing lanes must be told to
   leave alone) and a user-triggered catch-up job whose progress is counted from files, never from a running tally
   (§6.6). **Nothing unattended runs until the person chooses it** (R-RW12).
6. **Agents read through the queue, not through a spawn.** New MCP tools `cicada_reading_queue` and `cicada_record_read`,
   the `cicada_record_watch` pattern, with its own contract item. A Cicada-spawned browse call is a later, spike-gated
   slice with its own pinned argv. Measured: `--chrome` bypasses the engine's locks (§8.2).
7. **Consolidation itself never gets a browser.** Stages 1 to 5 stay a text-in, text-out engine (§8.1). "Is a browser
   harness turned on?" has an answer, and it is in §8.3: installed here, connected to nothing.
8. **Five fetch-layer rulings for the owner to approve** (R-RW1 to R-RW3, R-RW10, R-RW11, §9): the descriptive
   User-Agent, `Accept: text/markdown`, metadata-first, robots.txt, and a backoff rule that lets the fixes reach pages
   already stamped `blocked`.
9. **The classifier navigator (Jev) is a backlog row and a Settings placeholder**, behind a `Navigator` interface, off,
   "Needs OpenRouter", benchmarked against two open baselines before anything is built (§10).
10. **Ten slices, five of them backend-only,** each shippable alone (§13).

---

## 2. Goals and non-goals

**Goals.**
- Make a saved or shared link readable at a quality worth extracting entities from (G102's point: the output is
  relations, not a nicer card).
- Turn the ~1,460 imported conversations' links into part of the graph, at a bounded and visible cost.
- Let the person choose between a reader that "just gives what's on the site" and an agent that can look and interact,
  with one safe default.
- Reach pages behind a login only through the person's own logged-in browser, with the person present and told what
  they are accepting.
- Keep the app honest about what happened to each link: read by the reader, by an agent, metadata only, or not read.

**Non-goals.**
- **No stealth.** No TLS or JA3 impersonation (`curl_cffi`), no fingerprint randomisation, no CAPTCHA solving, no
  proxies, no "smart mode" that escalates to unblocking (Scrapling, spider). A block is never retried with different
  headers (the standing ToS rail).
- **No hosted reader by default.** Jina Reader, Firecrawl and unblocker services send every URL to a third party. Not
  offered in this spec. If ever offered, it is opt-in, off, and labelled with who receives the URL.
- **Cicada never authenticates, never reads a cookie or a browser profile, and never runs a signed-in browser itself.**
- **No crawling.** One URL per read. A navigator (§10) may hop, one page at a time, and only later.
- **No transcript or video download** (Track V's rail: a stream is never derived). Video is the sibling spec.
- **No app-side price or token figure** outside the Sleep page's Details and engine menu (DR-59, ruling 12).

---

## 3. What exists, and what was measured

### 3.1 The fetch path today

| Fact | Where | Status |
|---|---|---|
| One reference transport: `default_fetch`. Fresh httpx client, no cookies, `trust_env=False`, 4 s (`FETCH_TIMEOUT_S`), ≤ 5 redirects, 512 KB streamed, `net_guard` on every hop. 401/403/407/451 or a redirect to a login page is `blocked`, never retried. An interstitial title is `interstitial`. | `link_enrichment.py:630-689` | read |
| Extraction is BeautifulSoup `html.parser`: drop script/style/nav/footer, headings plus the text of `main`/`article`/`body`, cut at 2,000 characters. Under 100 characters is `failed:empty_body`, commented "JS-rendered / empty — out of scope". | `_extract_visible_text`, `MIN_EXCERPT_CHARS` | read |
| User-Agent is `Mozilla/5.0 (CicadaBot)`. Two other modules (`logo_service`, `reddit` connector) and `paper_metadata` each carry their own. | `media_ingestor.py:36` | read |
| **There are two page transports.** `default_fetch` (4 s, 512 KB, `trust_env=False`, guard hook) serves the backfill and Stage 5.57; `media_ingestor._enrich_opengraph` (5 s, 1.5 MB, a caller-injected client, a manual redirect walk) serves save-time `enrich()` and already parses `og:*`, `twitter:*` and the meta description. | `link_enrichment.py`, `media_ingestor.py:395-445` | read |
| **`robots.txt` is not read anywhere.** "robots-lite" appears only in `default_fetch`'s docstring. | `link_enrichment.py:631` | read |
| The excluded set is YouTube/video, `instagram.com`, `linkedin.com`, papers and arXiv. **X is not excluded.** Only `classify_page`'s login-host and redirect heuristics apply to it. The brief that started this spec said otherwise. | `_excluded_media`, `link_enrichment.py:252` | read |
| The Sleep-tail backfill is oldest-first, capped at `link_enrich_backfill_per_cycle` = 20 a night, with a 30-day retry backoff on a failed fetch. | `config.py:219`, `_in_fetch_backoff` | read |
| No `lxml`, `trafilatura` or `selectolax` in `api/pyproject.toml`; `beautifulsoup4` only. | `pyproject.toml` | read |
| **The importers drop link structure.** `parse_anthropic_conversations` keeps `text` (or the first text block) and ignores `content[].citations`. `parse_chatgpt_json` keeps only string `parts` and ignores `metadata.content_references` and `search_result_groups`. Inline URLs in the prose survive as text; structured citations do not survive at all. | `routers/conversations.py:255-320, 449-520` | read |

### 3.2 Fetch versus extract (from the research pass)

**[reported]** Fetching 12 real pages took 53 to 827 ms each. Every extractor took 1 to 30 ms. **Choose on quality,
footprint and rail fit, not on parse speed.** One run per page, Python 3.12, macOS arm64, so treat as an order of
magnitude.

### 3.3 Three findings that change the plan

1. **Cicada's User-Agent is refused by Wikipedia under httpx.** **[measured]** 2026-09-29, `httpx.get` with the
   exact UA: **403, 141 bytes**. With `CicadaBot/1.0 (+https://github.com/rorosaga/cicada; personal-memory reader)`:
   **200, 706 KB**. `curl` with the old UA got 200, so the trigger is the header set as a whole, not the UA string
   alone. Wikimedia's policy asks for an identifiable agent with a contact. A saved Wikipedia link is `blocked` today.
2. **`Accept: text/markdown` already returns markdown from Cloudflare-fronted sites.** **[measured]** a request to a
   Cloudflare-hosted blog returned `200 text/markdown; charset=utf-8`. It is an honest, standard header. It only helps
   sites that opt in.
3. **Metadata from the bytes a *backfill* fetch returns is a free tier the backfill never reads.** Save-time
   `_enrich_opengraph` already reads `og:*`, `twitter:*` and the meta description (that is where the 52 % figure below
   comes from); the backfill's `default_fetch` path does not, and neither reads `ld+json` or a `__NEXT_DATA__` head.
   **[reported]** Notion, Substack and X shells carry `og:description`, `ld+json` or a `__NEXT_DATA__` blob while their
   body text is near empty. Through the backfill they become `failed:empty_body` or a navigation-flavoured excerpt.

**[measured]** In this bank, 740 of 1,423 saved media pages (52 %) already carry a substantive `## Description`
(≥ 120 characters with a sentence end), so the zero-LLM reuse tier covers about half of what is saved. The other half
is what the reader has to improve.

### 3.4 The chat-link census

**[measured]** on the owner's two current exports (a ChatGPT export of 1,118 conversations and a Claude export of 365;
aggregate counts only). A "link" is a normalised URL (`host + path`, no `www.`, no trailing slash) so tracking
parameters do not inflate it.

| | ChatGPT (1,118) | Claude (365) |
|---|---|---|
| Conversations with a link in message text | 224 (20 %) | 96 (26 %) |
| Unique links **the person** wrote | 453 | 155 |
| Unique links **the assistant** wrote in prose | 438 | 86 |
| Structured citations: unique **cited** URLs | 547 (`content_references`) | 844 (`citations[].details.url`) |
| Unique URLs the assistant only **consulted** (search results, never cited) | 3,130 total, 3,031 not cited | not in the export as a list |
| URLs inside tool results (web search and fetch output) | not present | 35,456 occurrences, noise |

Across both exports:

| Class | Unique URLs | Note |
|---|---|---|
| **Person-shared** | **594** | 474 appear in one conversation, 61 in two, 42 in three, 9 in four, 8 in five or more. |
| Assistant prose, not also the person's | 387 | Includes localhost, `example.com` and placeholder hosts; a third or so is noise. |
| Structured-cited (ChatGPT 547 + Claude 844, deduplicated) | **1,389** | 1,366 of 1,389 appear in a single conversation. 23 appear in two or more. 23 are also person-shared (the two 23s were counted separately and may overlap). Adding the consulted-only ChatGPT results (3,031) brings the assistant-side structured total to 4,420 before de-duplicating against prose and the person's own links. |
| **Union of everything** | 4,553 | "Thousands" was right, and almost all of it is not the person's own. |

Host classes of the 594 person-shared links, by count of unique URLs: GitHub 103, video 12, login-walled social 20,
`arXiv` 6, local or example hosts 13, the AI vendors' own share and attachment hosts 7, everything else 433 across
267 distinct hosts (the five biggest hosts hold 30 %). **Outside the readable set: 58** (video 12 + walled 20 + arXiv 6 +
local 13 + vendor hosts 7), leaving **536** (GitHub 103 + 433) as the number every count in this design uses (§6.1).

Two more numbers that shape the design:
- Only **21 of the 594** are already saved as media pages here, so saved-link dedupe matters little. Repeats **inside
  the chats** matter more (120 of the 594 came up in two or more conversations).
- The Claude export's 35,456 tool-result URLs are search-engine noise. They are never links the person meant.

**What was not measured.** The share of the 594 that are readable (not a login, not JS-only, not dead) is unknown until
S3 reads them. The whole design assumes it is high enough to be worth the run; the S3 acceptance test reports it.

---

## 4. The Reader: a ladder on the same bytes

**The fetch stays inside today's rail** (4 s, ≤ 512 KB, ≤ 5 redirects, no cookies, no auth, `net_guard`, no header
retry). The ladder is what is done with what came back.

**There are two page transports, not one, and the ladder covers both.** `link_enrichment.default_fetch` (4 s, 512 KB,
`trust_env=False`, guard hook; the backfill and Stage 5.57) and `media_ingestor._enrich_opengraph` (5 s, 1.5 MB, a
caller-injected client with a manual redirect walk; the save-time `enrich()`). R-RW1 and R-RW2 apply to **both**. The
metadata parse R1 is **extracted from `_enrich_opengraph`** (which already reads `og:*`, `twitter:*` and the meta
description at save time, and is where the 52 % substantive-description figure comes from) into one shared function,
`page_meta.parse(html)`, that both transports call. R1 adds `ld+json` and the `__NEXT_DATA__` head to it; it does not
duplicate a second parser.

| Rung | What | Zero-LLM | New dependency |
|---|---|---|---|
| **R0** | Identity: `User-Agent: CicadaBot/1.0 (+https://github.com/rorosaga/cicada; personal-memory reader)`, one constant in `media_ingestor`, and `Accept: text/markdown, text/html;q=0.9`, on both transports. **Robots.txt first (R-RW10):** once per host per run, same caps. A `text/markdown` response skips extraction. | yes | none |
| **R1** | **Metadata from the same HTML** through `page_meta.parse`: `og:*`, `twitter:*`, `<meta name=description>`, `ld+json` (`headline`, `description`, `author`, `datePublished`), the `<title>`. Also the head of a `__NEXT_DATA__` blob when it holds a plain description. | yes | `selectolax` (Lexbor), a few MB, MIT |
| **R2** | **Main content to markdown:** trafilatura fed the bytes our own guarded fetch returned (never its own `fetch_url`). Falls back to today's bs4 extractor. Cap unchanged: 2,000 characters for the summarizer. | yes | see D-RW1 |
| **R3** | **Classify what is left.** A short body plus a JS-framework marker (`__NEXT_DATA__`, an empty `#root` or `#app`, a `<noscript>` demanding JS) is **`needs_js`**, distinct from `blocked`, `interstitial` and a real 4xx. | yes | none |
| **R4** | **Optional local browser engine** for `needs_js` only. A sidecar over CDP: Obscura (Apache-2.0) or Lightpanda (AGPL-3.0). Off by default, never bundled, non-stealth, **robots.txt honoured on the main navigation (R-RW10)**. Slice S9, decision D-RW2. | yes | user-installed |

R5 and above are not the reader. They are the agent (§8).

### 4.1 Data model and wire

`FetchResult` gains fields; the existing two stay (`status`, `text`):

```
FetchResult(status, text, meta, tier, content_type)
  status: ok | blocked | interstitial | needs_js | failed:<reason>
  tier:   markdown | metadata | main | excerpt          # what produced `text`, best rung that answered
  meta:   {title, description, site, author, published, image}   # R1, every field optional
```

A media page's frontmatter gains one small block, written only when a read happened (R15's rule: a page that was
never read stays byte-identical):

```yaml
read:
  by: reader            # reader | local-browser | agent   (who)
  tier: metadata        # markdown | metadata | main | excerpt | agent
  at: '2026-09-29'      # aware-UTC day, the machine zone
  v: 1                  # reader_version at the time of the read
```

and, **beside `fetch_status` and `fetch_attempted_at`, one more key on every fetch outcome including failures**:
`fetch_reader_v: 1`. A `read:` block exists only for a successful read, so a `blocked` or `failed:*` page has no `read.v`;
`fetch_reader_v` is what §4.4's version rule reads. A page stamped before this key exists reads as version 0.

- `fetch_status` and `fetch_attempted_at` stay as they are. `needs_js` is a new value (its retry rule is §4.4).
- **No page text is stored.** The gist is the `describes` claim (≤ 400 characters, G140's clip) and the `## Description`
  section, as today ("spans, not copies"). The excerpt is held in memory and dropped.
- A `describes` claim written from a read carries evidence `kind: page`, observer `external:reader`
  (deterministic) or the summarizer's label, as today.
- The Feed detail column's "Saved from" block gains **one line, "Read"**, over the `read` field on `MediaSourceItem`
  (§7.5), in exactly the known facts: *Read by Cicada's reader · Sep 29*, *Read by Claude Code · Sep 29*, *Only its
  description was read*, or *Not read yet*. The same four words serve the video queue's "seen by an agent / transcript
  only / both / neither" (sibling spec). It never says "in your browser": Cicada cannot know which tool an agent used.

### 4.2 Statuses the app names

| Server status | App says |
|---|---|
| `ok`, tier `markdown`/`main` | Read |
| `ok`, tier `metadata` | Only its description was read |
| `blocked` | This site turned the reader away. Cicada looks again in a month. |
| `blocked`, reason `robots` | This site asks not to be read by tools like Cicada's reader. Cicada looks again in a month. |
| `interstitial`, `login_wall` | This page asks you to sign in or accept something first. |
| `needs_js` | This page only fills in with JavaScript. It waits for an agent or a browser engine. |
| `failed:*` | Couldn't load it. Cicada tries again in 30 days. |
| never read | Not read yet |

### 4.3 The reading lanes, in the ledger

The existing `link_enrich` report (`$CICADA_HOME/link_enrich/<bank>.json`) is not a row log. `write_progress_marker`
writes **one JSON object of run counts, overwritten each run** with `write_text`, and nothing load-bearing reads it. So
there are no rows to append to. Two honest options, and this spec takes the first:

1. **Extend the aggregate.** The report gains counters, by tier (`markdown`, `metadata`, `main`, `excerpt`), by status
   (`ok`, `blocked`, `needs_js`, `failed`, `robots`) and by `host_class` (a closed enum: `public`, `github`, `docs`,
   `news`, `social_walled`, `other`, never a host name), plus the `reader_version`. Counts only, still a file for humans
   and agents, still overwritten each run.
2. **A per-read ledger kind** is a separate decision, taken only if a later slice needs one. It would be a new telemetry
   kind filed beside `read` in `reads-*.jsonl` (so `sync_service.components["telemetry"]` does not tick the app's
   consumption domain), ids and enums only, with its own ETag consequences. Not built here.

### 4.4 Backoff and re-eligibility: the rule S1 must implement

The first draft's page-state copy contradicted the code. `_in_fetch_backoff` treats **every non-`ok`** `fetch_status`,
`blocked` included, as retryable after `link_enrich_fetch_retry_days` (30), and it has no case for `needs_js`. The rule,
per status (R-RW11):

| Status | Retried by the clock? | Otherwise |
|---|---|---|
| `blocked` (including reason `robots`) | Yes, after 30 days, same headers | Eligible once on a `fetch_reader_v` bump (below). The copy says "looks again in a month", not "doesn't try again". |
| `failed:*` | Yes, after 30 days | `failed:empty_body` is eligible once on a version bump. |
| `interstitial` | Yes, after 30 days | none |
| **`needs_js`** | **No.** `_in_fetch_backoff` gains a case: `needs_js` is skipped by the clock and by `scan_backfill`'s count of what the backfill still owes. | Eligible again only when a rung that could help exists: the local engine is installed and on (R4), or an agent read arrives (`cicada_record_read`). |
| `ok` | not applicable | none |

**The version rule.** R-RW1's headline fix (Wikipedia 403 to 200) does not reach a page already stamped `blocked` or
`failed:empty_body` under the old UA: it sits in backoff for up to 30 days. So `reader_version` is **consumed**: a
page whose `fetch_status` is `blocked` or `failed:empty_body` and whose `fetch_reader_v` is lower than the current
reader version is **eligible once**, and the retry stamps the current version whatever it finds. A bump is a code change
that says the ladder changed materially; it is never applied to a page a second time. `test_reader_backoff.py` covers
`_in_fetch_backoff` for every row above.

### 4.5 A metadata-tier result costs no model call

`backfill` sends every `ok` fetch result to `summarize_fn` today, so a `tier: metadata` result would still cost an LLM
call. S1 changes the loop: when the result is `tier: metadata` and its description is substantive (the same test as the
52 % measure: ≥ 120 characters with a sentence end), the description is **written directly as the `## Description` and
the `describes` claim, and `summarize_fn` is not called**. A thin metadata result still goes to the summarizer with the
metadata as context. This is where the "about half of pages need no call" saving in §6.4 and §11 is actually realised.

---

## 5. The rail, restated for reading (nothing here loosens it)

The standing rail (CLAUDE.md "Reaching the outside world"): a fetched page is 4 s, ≤ 512 KB, no cookies, never behind
auth; consent walls and login pages are retired without a byte fetched; **a block is never retried with different
headers**; no scraping behind authentication, ever.

**What this spec adds, each a dated ruling in TODO on approval (R-RW1 to R-RW12, §9):**

1. **A fixed, honest identity is not "different headers".** A descriptive User-Agent and an `Accept` header apply to
   every request the same way. The rail forbids trying a *second* identity after a block. It does not forbid having a
   truthful first one. Wikimedia asks for exactly this.
2. **The login-walled host list is one closed set the reader and the chat-link scanner both use:** `x.com`,
   `twitter.com`, `t.co`, `linkedin.com`, `instagram.com`, `facebook.com`, `fb.com`, `tiktok.com`, `reddit.com` and
   `old.reddit.com`, plus the AI vendors' own share hosts. It also fixes the X gap in §3.1. Reddit already has a
   connector; X has one; the export archive is the sanctioned path for both.
3. **Side-effect and secret-bearing URLs are never fetched.** A GET can unsubscribe, confirm, log out or redeem.
   Denied: a query key in `token`, `key`, `sig`, `signature`, `auth`, `code`, `session`, `otp`, `magic`, `reset`,
   `verify`, `confirm`, `invite`, `unsubscribe`; a path segment `unsubscribe`, `verify`, `confirm`, `reset`, `invite`,
   `logout`, `oauth`, `callback`, `delete`; any AWS-style signed URL (`X-Amz-Signature`); a private-workspace host
   (Google Docs and Drive, Notion workspaces, Figma, Slack, Dropbox, OneDrive, Airtable shares); any port but 80/443.
   Such a link is kept in the episode sidecar and never read, and its query string never enters a media page.
4. **Cicada's own process never holds a session.** No cookie, no profile, no `~/Library` browser read by the backend.
   The only browser-shaped thing Cicada may ever run itself is the optional local engine (R4), with a fresh context,
   no storage, `net_guard` on every subrequest, robots.txt honoured (R-RW10) and no stealth build. This item is about the
   backend's process: the person's own browser is a separate matter, governed by item 5.
5. **Reading with an agent is a person-driven action, never scheduled** (ruling 4 already excludes scheduled plan use),
   and **Cicada only asks**. A walled page reaches an agent only after the person's explicit "Ask an agent" on that link,
   or per site the person turned on after a page from it could not be read, one entry per site per call (§8.4). The read happens in a harness the person already installed and
   approved, and **what the agent does in its own browser is not something Cicada can enforce**, so no Cicada text
   promises it (no "read-only", no "never posts"). The page's words are **data, not instructions** (§8.5).
6. **The person is told, before first use, what they accept** (§8.6): a platform's terms may forbid automated access
   even when signed in, the person is responsible for compliance, and their account may be restricted.
7. **The Reader honours `robots.txt`** (R-RW10), once per host per run, under the same caps. The first revision of this
   spec leaned on a "robots-lite" politeness that does not exist in the code (§3.1).

### 5.1 What the platforms say (research pass; not legal advice)

- **LinkedIn**'s User Agreement §8.2 forbids "software, devices, scripts, robots or any other means (such as crawlers,
  browser plugins and add-ons…) to scrape or copy the Services" and bots or "other unauthorized automated methods".
  Its Help page on prohibited software names extensions that "scrape, modify the appearance of, or automate activity".
  Enforcement is account restriction.
- **X**'s terms: "crawling or scraping the Services in any form, for any purpose without our prior written consent is
  expressly prohibited" (since September 2023).
- **No carve-out** for an assistive, person-initiated, low-rate read exists in either. What differs in practice is
  initiator, volume and use: a person asking their agent to read the one profile they are looking at, once, into
  private memory, produces the traffic a person does. The signals platforms act on are bulk, scheduled, unattended,
  regular and broker-style.
- **Case law, as context only.** *hiQ v. LinkedIn* (public-page scraping likely not a CFAA violation; breach of the
  User Agreement found; ended in a 2022 consent judgment). *Meta v. Bright Data* (2024: terms bind users while
  logged in, so contract risk concentrates exactly on signed-in sessions). This is the reason "with my sessions" is
  the mode with an acknowledgement and a deny-list, not the default.
- **Sanctioned paths for the person's own data come first:** X's account archive and Cicada's existing X connector;
  LinkedIn's Member Data Portability API (EU/EEA/Swiss only). The UI points there before offering the browser.

---

## 6. Links inside imported chats

### 6.1 Which links are worth reading

| Class | Definition | Default | Why |
|---|---|---|---|
| **U · the person's own** | A URL in a `user` turn of a conversation (the person pasted or typed it) | **Read** | The person chose to bring it into a conversation about something they were working on. Measured: 594 unique, of which **536** are in the readable set below. |
| **C2 · cited twice** | An assistant-cited or assistant-written URL that appears in **two or more conversations** (a link that is also class U is simply class U) | **Read** | Coming back to it is the signal that it mattered. Measured: 23 cited in two or more conversations, some of which are also class U, so **at most about 23 extra pages**. Defined across every episode's sidecar in the bank at queue time, not per import. |
| **C1 · cited once** | Cited or linked by the assistant in one conversation only | **Metadata from the export, no fetch** | Measured: 1,366 of 1,389. ChatGPT's own citation records carry `title` and `snippet` (788 items with a title and a URL) and Claude's carry the URL. Keep them in the sidecar and show them in the Reader. Read one only on the person's click. |
| **X · consulted** | Search results the model saw but did not cite (3,031 URLs) | **Never** | The person never saw them as sources. |
| **T · tool-result noise** | URLs inside web-search or fetch output (35,456 occurrences in one export) | **Never** | Same reason. Also a privacy exposure of pages the person never chose. |
| **A · inside an upload** | A URL inside `attachment [<name>]` text | **Never** | It is a document's link, not the person's share. `attachment` is already `page`, not the person's words. |
| **W · walled** | §5 item 2's hosts | **Never by the backend.** An agent may be asked, one link at a time, by the person's explicit "Ask an agent", or per site the person turned on after a page from it could not be read (§8.4). | ToS. |
| **V · video** | YouTube, Vimeo, TikTok, Loom | **Not a page read.** Handed to the video queue. | Sibling spec; Track V. |
| **P · paper** | arXiv, DOI | **Not a page read.** `papers.py` builds the page from the arXiv or Crossref API. | `never_scraped`, G133. |
| **H · vendor host** | The AI vendors' own share and attachment hosts | **Never** | A share page is not the person's source; measured 7 of the 594. |
| **S · side-effect or secret** | §5 item 3 | **Never** | A GET may act. |
| **L · local** | localhost, private ranges, `example.*`, `.local` | **Never** | `net_guard` already refuses most. Drop them at extraction so they never count. |

**The readable set** is what is left of a count after the class filter: not W, V, P, H, S, L, X, T or A, and not C1
unless the person clicks. Every count shown to the person (the intake row, Settings, the job's total, the queue) is over
the readable set, labelled as what "can be read". Measured on the 594 person-shared links: video 12 + walled 20 + arXiv
6 + local or example 13 + vendor hosts 7 = 58 are outside it, leaving **536** (GitHub 103, everything else 433). The
denylist's own share (class S) is not measured, so 536 is an upper bound.

The assistant-only class costs nothing to keep as metadata and a lot to read, and the design keeps the cheap half.

### 6.2 What import does, and does not, do

**Import stays network-free, LLM-free and page-free** (Awake principle). The change is in the two parsers and the stager,
and **offsets are taken where the evidence text is made, not at parse time**:

- **Where the offsets come from.** `episode_staging.render` builds the evidence text: each turn is scrubbed and then
  prefixed `<speaker>: `, and `_stamps` derives each turn's offset from those same scrubbed lines. An offset computed on
  the parser's raw messages would point at the wrong characters. So link extraction is a sibling of `render`,
  `render_with_links(messages, cited)`, which returns the body, the stamps and the links from **one pass over the same
  scrubbed lines**. A Markdown link `[text](url)` is one link, not two; trailing punctuation is stripped;
  `episode_scrub` runs on the URL (a token in a query never lands in the bank); classes L, T, A, S and H are dropped.
- **What the parsers add.** They read the structured citations they drop today: ChatGPT
  `metadata.content_references[].url`/`items[].url` (with `title` and a `snippet` clipped to 200 characters) and Claude
  `content[].citations[].details.url`. Nothing from `search_result_groups` and nothing from a tool result. These are the
  `cited` entries and carry no offset, because the URL is not in the prose. They travel on the parsed episode.
- **How they reach the draft.** `EpisodeDraft` gains a `links` field; `draft_from_export` copies a fixed set of keys today,
  so it is named in S2's scope and carries the parser's `cited` entries into the draft. `render_with_links` fills the
  offset-bearing `user` and `assistant` entries. **`cited` entries (no offset) and offset-bearing entries are kept in
  separate lists until the stager merges them**, so a refresh that re-derives offsets never drops a `cited` one.
- **The sidecar** is frontmatter on the episode, outside `content_hash` (the `turns:` precedent), capped at 60 entries
  head-stable:

```yaml
links:
  - {url: 'https://example.com/a', role: user, offset: 1204}        # offset into the evidence text; a span, not a copy
  - {url: 'https://example.com/b', role: assistant, offset: 3310}
  - {url: 'https://example.com/c', role: cited, title: 'A title', snippet: 'First 200 characters…'}
```

- `role` is one of `user | assistant | cited`. `offset` exists for the first two and is absent for `cited`.
  `evidence.span_status` sees drift through the episode's hash as it does for any span.
- **Keeping it current needs a new branch.** When a re-import's body is unchanged, `_stage_locked` takes its
  `same_body and same_meta` branch and skips without touching the file, and only `update_in_place` (body changed) calls
  `_apply_common`. So "the stager keeps the sidecar current" and "a re-import that only adds citations" are **a new
  same-body refresh path** (a `_relink`, in the family of `_restamp`) that rewrites only the `links` sidecar: it never
  flips `processed`, never touches `content_hash`, and takes no new episode id. S2 names it and tests it.

### 6.3 From a link to a page: a new writer, named changes

The existing writer does not fit "a page for a link found in a conversation" as first drafted. In the code today,
`ingest_one` always calls `enrich()` (a network fetch), `write_media_entity` hard-codes `source_episodes` to the media
page's own freshly minted episode, `ingest_batch` returns only `(created, dup_count)`, and the duplicate branch never
touches `source_episodes`. So there is no `defer_enrich` and no way to name a conversation. **S3 makes these changes, all
in the media writer, none in the reader:**

| Change | Where | Why |
|---|---|---|
| `RawItem.source_episodes: list[str]` and `RawItem.defer_enrich: bool` | `RawItem` | The conversation id has no field today; `defer_enrich` skips `enrich()` and uses the URL-derived fallback title. |
| `write_media_entity` writes `source_episodes` from the item, not only its own episode | `write_media_entity` | So `inject_media_edges` joins the page to the conversation's entities. |
| `ingest_one(..., defer_enrich)` threads the flag through | `ingest_one` | 536 saves must not become 536 fetches. |
| A new `ingest_batch_results(...)` returning `list[IngestResult]` (the tuple-returning `ingest_batch` stays for its callers) | `ingest_batch` | The caller needs each page's `media_entity_id` to add the `saved-because` claim and to attach the conversation to an existing page. |
| `attach_episode(idx, existing, episode_id)` for the duplicate path | new, media writer | The duplicate branch never touches `source_episodes`; a link already saved gains the conversation in the same commit. |
| Set `RawItem.added` to the message's own time (validated by `saved_at.validate`) | the chat-link caller | The index `saved_at` is always the **ingest** time. The person's date is `RawItem.added`, which becomes `content_saved_at`, and the Feed's recency sort already prefers it. |
| A born-processed media episode, or none (S3's plan decides, D-RW6) | `write_media_episode` gains a `processed` argument | `ingest_one` writes a `processed: False` media episode for every page today, so 536 pages would add about 536 unprocessed episodes to Sleep's queue. |

- **Origin.** Chat-link pages reuse the origin ids the chat importers already stamp, **`chatgpt-export` and
  `claude-export`**, not new `chat-chatgpt`/`chat-claude` ids. Unlisted ids would render as their own raw-id card in
  `source_overview` (`_ORIGIN_TO_ID.get(origin, f"origin:{origin}")`, the defect class G124 R-S4 fixed), and would need new
  entries in `OriginIconography.logoName(for:)` and `SourceDisplayName`. The export card's conversation count is
  unchanged, the pages appear under the channel's "What came in" list (G161), and `test_source_overview_chat_pages.py`
  holds it. The Feed's kind filter treats them as `link`.
- **When a page is minted.** **At read time, not at import.** The chat lane (§6.4) and the catch-up job each mint a page
  immediately before reading it, from a sidecar link, so import mints nothing, the Feed grows as pages are read, and a
  bank whose owner never chose reading has none of these pages.
- **Author and trigger.** The mint is offline and model-free, so it commits alone as **`Cicada-Author: cicada`, trigger
  `capture/chat-links`** (a new trigger, added to CLAUDE.md's list in S3), not as `user`: `_commit_media` defaults to
  `user` / `user/media_save`, which would claim the person saved these. Appending a conversation to an already-saved page
  is in the same commit.
- **The person's own sentence becomes the why.** For class U, the sentence containing the URL, if it has words beyond the
  URL and is ≤ 240 characters, becomes a `saved-because` claim with a `user` evidence span into the conversation (the
  G133 mechanism, zero LLM). A bare URL writes none.

A link already saved (`url_index.json`, keyed by `url_hash` over `normalize_url`) does **not** get a second page. Measured
overlap is 21 of 594, so this is the rare path.

**Not minted:** W, V, P, H and C1 links stay in the sidecar (V and P are handed to their own paths). A page for a
login-walled link with no title and no readable text would be a node with nothing on it.

### 6.4 Caps, order, cost, and a lane that actually is separate

**The chat lane is not separate unless the existing two lanes are told to leave it alone.** A minted chat page has no
`describes` claim and no `enrichment_attempted`. `link_enrichment._candidates` (Stage 5.57's in-cycle pass,
`link_enrich_max_per_cycle` = 20, most recent first) and `scan_backfill` (the Sleep-tail lane, 20 a night, oldest-first by
`saved_at`) select on exactly that, and **neither filters on origin**. Left alone, they would fetch chat pages uncapped by
`link_enrich_chat_per_cycle` and starve the person's own saves. So S3 changes both:

- `_candidates` and `scan_backfill` **exclude** pages whose origin is in `CHAT_LINK_ORIGINS` (`chatgpt-export`,
  `claude-export`).
- The chat lane has **its own scan and sort**: `scan_chat_lane`, repeats first (the number of conversations in
  `source_episodes`, descending), then message date descending.
- `test_chat_lane_caps.py` exercises **both existing entry points**, not only the new one.

| Knob | Default | Reason |
|---|---|---|
| `link_enrich_backfill_per_cycle` (saved links, unchanged) | 20 a night | Existing. |
| **`link_enrich_chat_per_cycle` (new lane)** | **10 a night, only when `reading.chat_links` is `nightly`** | A separate lane so a big import cannot starve the person's own saves, and the reverse. |
| Catch-up job (§6.6), user-triggered | the whole readable set, 2 concurrent, ≥ 3 s between requests to one host | 536 links at 10 a night would take about 54 nights. The person can choose to run it now. |
| Per-import ceiling on links queued | 1,500 | A safety stop. A conversation's sidecar is capped at 60. |
| Order within the chat lane | conversations-in-which-it-appears (desc), then message date (desc) | The links that came up twice are the likeliest to matter. The saved lane keeps oldest-first (G102 R2). |
| Per-host spacing | ≥ 3 s, and a host answering 403 or 429 is skipped for the rest of the run | The rung-1 numbers of G61 S4, same rail. Robots.txt applies (R-RW10). |

**Cost of the catch-up over the measured readable set.** Every figure here is an estimate, not a measurement.
- **Network [assumed from §3.2]:** fetch-bound, hundreds of distinct hosts, a few hundred milliseconds a page. Order of ten
  minutes with the spacing above.
- **Model calls:** about half of pages already carry an OG description that reuses at zero LLM (52 % measured on the
  saved pages; assumed similar). The rest need one summarizer call each, so **roughly 250 calls**, then G102's recon in
  batches of 8 (`link_recon_batch_size`), about 70 more. The app shows **"about 300 model calls"**, never a price or a
  token count (DR-59). A short excerpt of each summarized page goes to the chosen engine, and the intake and Settings
  copy say so in one neutral sentence: "Some pages are then summarized by the engine you chose for Sleep; a short excerpt
  of each goes to it. Where that engine runs is shown in Settings → Engines." (§7.1; no provider is named on this page.)
- **Whose quota.** The catch-up is a user trigger, so it runs on `preview.manual` (the same rule as Consolidate and the
  G125 R10 amendments); a scheduled night never spends plan quota (ruling 4). The intake card says so.

### 6.5 The consent moment

A read of pages the person did not explicitly save is new outbound traffic, so import shows it. The intake preview card
(the one every door shares) gains one row **only when the file holds readable class U links**. **No radio that enables
unattended reading is pre-selected.**

```
┌──────────────────────────────────────────────────────────────────┐
│  Import                                                          │
│                                                                  │
│  1,118 conversations · 224 new · 0 grown · 894 already here      │
│                                                                  │
│  Into  [ My memory                                   ▾ ]         │
│                                                                  │
│  Links in this file                                              │
│  536 links in your messages can be read. Cicada reads pages     │
│  with its own reader; a short excerpt of each goes to your      │
│  engine to be summarized.                                        │
│   (•) Read them when I say                                       │
│   ( ) A few each night                                           │
│   ( ) Don't read links from chats                                │
│                                                                  │
│  Links an assistant added are read only if they came up in      │
│  two or more conversations.                                      │
│                                                                  │
│                                   [ Cancel ]  [ Import ]         │
└──────────────────────────────────────────────────────────────────┘
```

Copy is DR-59 (sentence case, plain verbs, no "!"). Import stays one primary, `Import`. The engine sentence is the
neutral sentence of §7.1 (the engine you chose for Sleep summarizes; Settings → Engines shows where it runs). The choice writes `reading.chat_links` on the bank:
`manual` (the default), `nightly`, or `off`.

- **Counts are honest about what they count.** The card's number is from `POST /intake/sniff` (which stages nothing and
  already counts episodes), computed over the **uploaded file only** and over the readable set: `links: {yours,
  cited_twice_in_file, others}`, all labelled "in this file". Class C2 is defined across the whole bank (§6.1), so a
  per-import count undercounts it and the card never promises a total for it; the bank-wide figure appears in Settings and
  the queue (§7.1, §7.4).
- **Doors that show no card.** `/conversations/upload`, `/banks/{name}/import`, any API import that skips the preview, and
  S2b's live conversations never show this row. They leave `reading.chat_links` at `manual` until the person chooses
  (R-RW12), so a click-through, a script or a Stop hook can never enrol the bank in nightly fetching.

### 6.6 The catch-up job and a progress bar that cannot lie

`POST /reading/jobs` `{scope: chat_links | saved | selection, urls?}` answers **202** with `{job}`. **It does not run on
`intake_jobs`.** That module is staging-specific: its `Job` carries `staged/created/updated/skipped`, its `run` calls
`episode_staging.stage`, and it has no generic work function and no single-flight concept ("one stage runs at a time" is
`STAGE_LOCK`'s job, which a page read does not take). The reading job needs **its own process-local registry**
(`reading_jobs`, the same prune and `KEEP_SECONDS` shape as `intake_jobs`, sharing no code with staging) with an explicit
**single-flight guard**. `GET /reading/jobs/{id}` returns:

```
{state: running|done|cancelled|failed, total, read, metadata_only, blocked, needs_js, failed, waiting, phase}
```

**Every count is derived from files at request time**, not kept as a running tally: `total` is the readable-set queue at
job start, each other count is the number of pages in scope whose `read`/`fetch_status` now says so. A restart loses the
job object, not the truth: the counts recompute, and the app shows "Paused. 212 of 536 read." with Resume. **409** while
Sleep runs, while another reading job runs, and in a demo bank (`refuse_capture_into_demo`, §7.3). Cancel stops after the
request in flight; nothing is undone. `test_reading_job.py` covers both 409s.

**Reading is not consolidating.** A page read writes a `describes` claim and a `## Description`; the graph edges
(`about` claims from G102's recon) arrive in the same run's recon step, and the entity promotion of what those pages
mention happens in the next Sleep. The progress line therefore names two things and never merges them (§7.4, and the Sleep
page v5 spec's progress bar, which is the owner's separate ask for consolidation itself).

### 6.7 Live conversations too

The same extractor applies to a Stop-hook episode (Claude Code, Codex), so a link the person pastes in tomorrow's
session enters the same queue, at `manual` until the person chooses. Not in S2's first cut (imports only), listed in §13
as S2b.

---

## 7. App surfaces

All against `docs/design/DESIGN_RULES.md` (Direction D). Ids applied: DR-31/32 (the Reader, its states in words),
DR-33 (Settings panel), DR-40/41 (four button kinds; one `PrimaryActionButton` per surface), DR-44 (`Tag`),
DR-45 (text tabs), DR-47 (`SectionLabel`), DR-48 (rows, hover fill only), DR-50 (`EmptyStateView`), DR-52 (real marks,
never altered), DR-53 (icons), DR-54 (name a source like a person would), DR-59 (copy). No new colour, no new
component: every block below is composed from `SettingsRow`, `SourceRow`, `Tag`, `NeutralButton`, `TextButton` and
`SettingsSheet`.

### 7.1 Settings → Reading the web (new section `reading`, Customize group, after Integrations)

`SettingsSection` gains one case (raw value `reading`; no existing raw value moves, so a saved selection restores). The
page has a `PageTitle`, and five `SectionLabel` blocks. The Memory page's link-backfill row keeps its place and gains a
"Reading the web ›" link (`SettingsInlineLink`), so nothing that exists is removed.

```
Reading the web
How Cicada reads the pages you save and share.

AUTOMATIC READING
  (•) Reader                                          Recommended
      Reads public pages with Cicada's own reader. It asks each page's
      own site for the page and follows the site's robots.txt.
      <engine note>
  ( ) Off
      Cicada keeps links but reads no pages.
  ( ) Reader and a browser engine on this Mac          Not installed
      Also reads pages that only fill in with JavaScript.       [ Set up… ]

LINKS FROM CHATS
  [ Read them when I say ▾ ]      (Read them when I say · A few each night · Don't read)
  Links an assistant added are read only if they came up in two or more
  conversations.
  [ Read the queue now… ]      536 can be read · 212 read

WITH AN AGENT
  Let an agent read pages for you                            [ Off      ⏵ ]
  When Cicada's reader can't open a page (a sign-in, a consent page, a
  refusal), its site is listed below. You decide which sites your own
  agent may read with your browser. Cicada never signs in for you.
  An agent has recorded reads · last Sep 29             (only once one has)
                                         [ Copy for an agent ]

HOW YOUR AGENT READS                                  (owner 2026-09-30)
  (•) Let my agent choose
  ( ) Its own browser or computer tools
  ( ) browser-harness   [Skill]  Uses your own Chrome, including sites where you're signed in.   Install
  ( ) macos-harness     [Skill]  Can control any app on your Mac.                                 Open in graph

SITES THAT NEED YOUR BROWSER
  [icon] LinkedIn        41 saved pages are waiting              [ off ]
  [icon] paperfold.io    6 pages are queued for your agent       [ on  ]
         Your agent wasn't signed in to this site. Sign in in your browser, then try again.   [ Try again ]
  Site icons come from an icon service, which is told the site's name. Cicada doesn't ask these sites for their icons.

SMARTER NAVIGATION                                          Not available yet
  A small model that picks which link to follow. Needs an OpenRouter key.
```

- **Rows follow DR-48**: hover `bgHover`, no lift. A radio is the DR-42 anatomy without the Recommended row logic.
  `Reader and a browser engine` is drawn only once S9 ships; until then the row is absent, not disabled (a dead option
  teaches nothing).
- **Recommended** is the DR-42 word in `accentText`, on Reader only.
- **The `<engine note>` is one neutral sentence, and it names no provider.** The Reader asks the page's own site for the
  page, but for roughly half the pages (the ones with no usable description, §11) a **short excerpt is then sent to the
  engine that summarizes it**. The note says so without choosing or naming an engine: "Some pages are then summarized by the
  engine you chose for Sleep; a short excerpt of each goes to it. Where that engine runs is shown in Settings → Engines."
  (owner, 2026-09-30: providers "are literally just providers, so dont assume or make the choice for the user" — the earlier
  draft's case analysis by engine, "silent for Ollama" and "your <plan>", is deleted, and `LeavesMacNote` stays on the
  Engines and Who-reads pages where a provider name shows the person's own choice). The first draft of this spec said
  "nothing sent anywhere but the page's own site", which is false whenever a hosted engine summarizes, and it is removed. A
  future navigator row gains its own OpenRouter sentence (§10).
- **The chat-links control writes `reading.chat_links`**: `manual` (the default and the state of any bank nobody has
  asked), `nightly`, `off` (§6.5). The count is over the **readable set** (§6.1 after the class filter), never over the
  raw 594.
- **The page names no agent product (2026-09-30).** The earlier "Browsers on this Mac" block (per-agent-product rows,
  `browser-harness --doctor`, a bundle-id scan) is dropped: detecting and listing the person's tools made a choice for
  them. Kept: one honest fact, "An agent has recorded reads · last Sep 29", from the ledger, once one has. Which tool reads
  is the person's own selection (**How your agent reads**: "Let my agent choose", the agent's own tools, or a catalog skill,
  each skill a `type: skill` page in the graph, tagged Skill in the row), never something Cicada detects.
  - The app never scans a browser's `Extensions/` or `NativeMessagingHosts/` folders: those live inside a browser profile,
    which the standing rail reads only after the person turned that browser on (`cicada.browserWatch.enabled.<channel>`),
    and a profile read is a Full Disk Access flow this spec does not want. It never reads `~/.claude.json` (the `agent_live` rule).
  - There is **no per-browser "Connected"** state. A `cicada_record_read` call proves neither which tool nor that a browser
    was involved.
  - **Sites that need your browser** lists every site Cicada's own reader could not read (a sign-in, a consent page, a
    refusal, or a host the backend never requests), with measured counts and a per-site switch (§7.2). Each site wears its
    favicon, fetched from the icon service only.
- **Smarter navigation is a deliberate exception to "absent, not disabled".** It is drawn as a labelled, switch-less
  "Not available yet · Needs OpenRouter" row **because the owner asked for it to exist in Settings** with that label
  (2026-09-29). It has no control until S8's benchmark says the feature is worth building; if S8 says no, the row goes.
- **No price, no token count** anywhere on this page (DR-59).

### 7.2 Settings → With an agent: the first-use sheet

Turning "Let an agent read pages for you" on opens a `SettingsSheet` (never a popover), and nothing changes until its
button is pressed.

```
┌──────────────────────────────────────────────────────────┐
│  Let an agent read pages for you                         │
│                                                          │
│  You choose each page with "Ask an agent". Cicada then   │
│  offers that page to your own agent, which can read it   │
│  in your browser, signed in as you, and tell Cicada      │
│  what it saw.                                            │
│                                                          │
│  Cicada only asks. What your agent does in your browser  │
│  is up to it and you.                                    │
│                                                          │
│  Some sites, LinkedIn and X among them, forbid           │
│  automated access even when you are signed in. You are   │
│  responsible for following a site's terms, and the site  │
│  may restrict your account.                              │
│                                                          │
│  If the site offers a download of your own data,         │
│  that is safer.  X: your account archive.                │
│                                                          │
│  Cicada asks your agent not to type credentials, and     │
│  not to post, message or change anything. It can't see   │
│  or enforce what happens in your browser.                │
│                                                          │
│  [ ] I understand                                        │
│                                                          │
│                          [ Not now ]  [ Turn on ]        │
└──────────────────────────────────────────────────────────┘
```

`Turn on` is disabled until the box is ticked (DR-41: 45 % and a `.help` saying why). **There is no site picker on the
sheet** (owner, 2026-09-30: "limiting the amount of sites makes no sense to me, because we will never know which sites this
will happen"). A site is *surfaced* on Settings → Reading the web ("Sites that need your browser") when Cicada's own reader
could not read one of its pages, and its switch there writes `reading.agent_sites` (`{site: day}`, empty by default); the
queue (§8.4) derives the site's waiting pages from it. Flipping a site while the master is off raises this sheet, and "Turn
on" sends the acknowledgement, the master switch and that site in one call; with a current acknowledgement the sheet is
skipped. Per-page "Ask an agent" (§7.3) is always available while the master is on: it is the person's own consent for that
page. `t.co` is never offered; Reddit surfaces like any site. The acknowledgement is stored per install with its date and
version (`reading.agent_ack: {date, v: 2}`); a change of the wording re-asks, and until they do the switch reads off.
**Adult, pirated, financial and health hosts are refused outright**, matching the structural denials of §5.3, and are not
listed. The sheet says Cicada *asks* the agent not to type credentials, post, message or change anything, and that it can't
see or enforce what happens: an **instruction and an honest limit, not a promise** (R-RW8).

### 7.3 The conversation Reader: "Links in this conversation"

A conversation's Reader column (DR-31) gains one section, `SectionLabel` "Links in this conversation (14)", after
"Noted from this conversation". Each row (DR-48) is a mark, the page's title or its host, a `Tag` for the class, a state
in words and, on hover, one action.

```
Links in this conversation (14)
  [github]  example.com/team/repo           [You shared]  Read · Sep 29
  [ ]       example.com/docs/setup          [You shared]  Not read yet      Read now
  [ ]       example.org/paper-blog          [Cited by ChatGPT]  Title only  Read now
  [ ]       linkedin.com/in/…               [You shared]  Needs your browser   Ask an agent
  [▶]       video, in your video queue      [You shared]  Waiting            Open
```

- `You shared`, `Cited by ChatGPT`, `Written by Claude` are the three roles (§6.2). A `Tag` never filters (DR-44).
- **Read now** calls `POST /reading/read` with one URL: user-triggered, ungated like `sync_now`, 409 while Sleep runs and
  in a demo bank. **`POST /reading/read`, `POST /reading/jobs` and `POST /reading/asks` sit outside the `/capture/` and
  `/sources/` prefixes**, so they carry the `refuse_capture_into_demo` dependency explicitly and join the gated list in
  `test_demo_capture_routes.py`; otherwise the demo-bank rail (which polices only those prefixes) would let a "Read now"
  fetch into a demo whose pages are deliberately `enrichment_attempted`.
- **Ask an agent** calls `POST /reading/asks` (§8.4) and copies a sentence for the person to give their own agent (the
  `Copy setup prompt` pattern): "Read this page in my browser and tell Cicada with cicada_record_read: example.com/…".
  Cicada spawns nothing here. It is offered whenever agent reading is on; where Cicada's reader could not open the page it
  also offers "Let an agent read <site>" (§7.2), the site's own switch.
- **Data:** `GET /episodes/{id}/links` is not a Store domain and has no `VersionVector` mapping, like `/citations`. It
  ETags over `episodes` + `entities` + `sources` (the sidecar is on the episode, the page state on the entity, the saved-link
  join in `sources/url_index.json`) with the shape tag in `extra`, and a `ProvenanceCache`-style in-memory cache revalidates
  it. Ids and urls only for the page state; the title and snippet come from the sidecar. A page with no read state says
  "Not read yet". An episode from before S2 has no sidecar and the section is absent, not empty.
- **Empty:** the section is omitted when there are no links (DR-50 applies only to a whole empty page).

### 7.4 Sleep page and the video queue: the seams, as data contracts

The Sleep page v5 owns the room, the engine menu, consolidation progress **and the layout and wording of Details**. Today's
Details › What's waiting is a set of per-origin study rows built from unprocessed episodes (`StudyListCard`), not the
key-value rows this spec's first draft drew. So this spec supplies **data**, not a mock, and defers placement wholly to the
Sleep v5 spec:

- **`GET /reading/queue`** (S3): counts only, `{waiting, readable, read, metadata_only, needs_js, blocked, failed, agent_read}`,
  every count over the readable set. It ETags over `episodes` + `entities` + `sources` with the shape tag in `extra`; the
  body is cached in-process keyed by that ETag, so a 304 costs nothing and a rebuild walks the sidecars and media pages
  once per change. **It does not ride `/status`**, whose ETag inputs would change. The app keeps it in a small
  `ReadingQueueCache` (not a Store domain, no `VersionVector` mapping, in memory, emptied on a bank switch), revalidated
  when the Sleep page appears and on `entities`/`episodes` sync events.
- Two facts for Sleep v5 to place: "Pages waiting to be read" (the `waiting` count, a link to Settings → Reading the web)
  and, while a job runs, one progress line.

```
Reading pages · 212 of 536 read · 31 only a description · 9 sign-in pages · 6 couldn't load      [ Cancel ]
```
(Illustrative only: the sentence and the count nouns are this spec's; the row grammar is Sleep v5's.)

- **Two queues, one vocabulary, no shared store.** The video spec (R-VU3) keeps its queue at
  `$CICADA_HOME/video_queue/<bank>.json` and reads it through `GET /videos/state` and `cicada_video_queue`, and its run
  control lives in the Feed's Videos view (R-VU4). This spec does **not** fold videos into a reading queue. A class V
  link is handed to that queue and nothing else. What the two share is the words on the Feed's detail column ("Read by
  Cicada's reader", "Read by an agent", "Only its description was read", "Not read"; the video spec's seen / transcript /
  both / neither). Page reading has no per-item request store: what is waiting is derived from the sidecars and media pages
  (§6.6).
- The reading job's progress bar and the consolidation progress bar are **different bars with different nouns**
  ("read" versus "consolidated"), because a page is read once and consolidated later, and a bar that merged them would be
  wrong for hours after each import.

### 7.5 Feed: chat-shared links, and the "Read" line

Chat-shared pages are ordinary media pages with the export's origin (`chatgpt-export` or `claude-export`, §6.3) and the
message's date. The Feed detail's "Saved from" block reads "ChatGPT · shared by you · in *<conversation title>* · Aug 3"
(DR-54), with the conversation opening the Reader. **D-RW4 decides whether they sit in the Feed's main list or under an
origin filter.**

**The "Read" line needs a field.** `GET /sources` builds its rows from `url_index.json` plus each page's frontmatter, and
`MediaSourceItem` (`api/models/schemas.py`) has no `read` or `fetch_status`. S3 adds one **additive, defaulted** field,
`read: {by, tier, at, status}` (absent for a page never read, so an older client and every older ETag body decode
unchanged), and the Swift decode reads it leniently. The line's words are exactly the known facts and no more:
*Read by Cicada's reader · Sep 29*, *Read by Claude Code · Sep 29*, *Only its description was read*, *Not read yet*.
It does **not** say "in your browser": Cicada cannot know that (§8.4).

---

## 8. Reading with an agent, and the browser question

### 8.1 Does consolidation get a browser? No, and that is the design

Sleep's engines are locked text-in, text-out on purpose: the Claude engine's argv is `-p --output-format stream-json
--verbose --safe-mode --strict-mcp-config --tools "" --setting-sources "" --no-session-persistence`, and the Codex
engine's is `exec --ephemeral --ignore-user-config … -s read-only … --disable plugins apps shell_tool …` in Cicada's own
home. The first invariant in `agent_engine.py`: the spawned engine can never write back into memory. A browser tool is a
tool. So **consolidation stays a pure text engine**, and what an engine "reads" is text Cicada handed it.

What can use a browser is a **separate call class**: a page read, a G61 source check. It is not a flag on the extraction
argv (§8.2).

### 8.2 Measured: `--chrome` overrides the locks

**[reported by the research pass, claude 2.1.284]** Adding `--chrome` to the full pinned argv exposes **22
`mcp__claude-in-chrome__*` tools** to the model (`navigate`, `computer`, `javascript_tool`, `read_page`,
`get_page_text`, `form_input`, `file_upload`, `read_network_requests`, `tabs_*` and more) although `--safe-mode`,
`--strict-mcp-config`, `--tools ""` and `--setting-sources ""` are all present. `--allowedTools` is a permission rule,
not an inventory filter, and did not narrow the list. Without `--chrome`, or with `--no-chrome`, the model sees none.

**Consequences, all cheap:**
- A browse step is its own constant, `BROWSE_FLAGS`, in its own module, with its own approval and ledger kind. It is never
  `PINNED_FLAGS + ("--chrome",)`.
- A test asserts no non-browse engine argv contains `--chrome`; consider `--no-chrome` on the ordinary argv as insurance.
- The extension needs a **direct Anthropic plan** (Pro, Max, Team, Enterprise) signed in with `/login`. An API key,
  `setup-token`, Bedrock or Vertex keep it off. So it can only ever be the plan-CLI engine, never `byok`.

**Unverified, and the reason S7 is spike-gated:** whether `claude -p --chrome` can finish without an interactive
per-site approval ("Claude in Chrome wants to…"). If it blocks for a click, it works for a person-initiated read and is
useless unattended, which is fine because unattended is out of scope anyway. Also unverified: whether Cicada's isolated
Codex home (`~/.cicada/codex`, `--ignore-user-config`) can load a browser MCP through `-c mcp_servers.<name>…`, and
whether the Codex Chrome plugin's native host, registered against the person's main `~/.codex`, is reachable from it
(doubtful). The Codex/ChatGPT desktop stack is fully set up on this Mac, but it belongs to the person's home, not to
Cicada's.

### 8.3 Is a browser harness turned on? What is on this Mac today

**[reported, the research pass's local checks on 2026-09-29].** Nothing is wired to Cicada.

| Item | State |
|---|---|
| `browser-harness` skill and CLI (0.1.13; `browser-harness-mcp` present) | Installed. **Not attached** to any Chrome: its own doctor reports zero active connections, because Chrome's `chrome://inspect/#remote-debugging` approval has not been given. Not registered as an MCP server in Claude or Codex. Cloud auth off. |
| Claude in Chrome extension | Installed and onboarded, **off by default** (`claudeInChromeDefaultEnabled: false`); absent from `claude mcp list`; appears only with `--chrome`. |
| `macos-harness` / `cua-driver` | Installed. Native-app control, not a web reader. |
| Codex/ChatGPT Chrome and computer-use plugins | Enabled in the person's own Codex home. Not reachable from Cicada's isolated home (unverified). |
| `browser-use` marketplace plugin | Cloned, not installed. |

So the honest answer to "is it turned on so consolidation can use it" is: **the tools exist, nothing is connected, and
consolidation would not use them if it were.** What turns on is the agent reading axis (§7.1), which lets *the person's
agent* do the reading. §7.1's "Browsers on this Mac" block is how the app says this in plain words.

### 8.4 The two ways an agent reads

> **2026-09-30, owner, at review:** "limiting the amount of sites makes no sense to me, because we will never know which
> sites this will happen" — and, of the engine copy, "ollama and the rest are literally just providers, so dont assume or
> make the choice for the user." The pre-picked five-site allow list is replaced by sites *surfaced from the reader's own
> failures* and switched on per site; copy is provider-neutral. Recorded in TODO ruling 14.

**Route A, the queue (S4, the default and the first to ship).** The person's own agent, in its own harness, pulls work
and pushes back what it saw. Cicada spawns nothing, so `--chrome` never arises, the harness can be anything (portability),
and the per-site approval belongs to that harness's own extension. **Cicada does not know which tool the agent read with**
(a browser, a plain fetch, its own search) and never infers it; nothing in the app or the primer claims otherwise.

- **`cicada_reading_queue(limit≤20, reason?)`** (`read` scope remotely). Empty unless the person has turned on agent
  reading. Rows are of two kinds, and a row is never a class S link:
  - **Public rows** (`needs_js`, blocked or a `robots` refusal on a non-walled host): up to 20 a call.
  - **Ask rows and site rows.** An *ask row* is a link the person explicitly sent with "Ask an agent" (§7.3). A *site row* is
    a saved page Cicada's own reader could not read that belongs to a site the person turned on (§7.2), derived at read, never
    stored. **At most one row per site per call**, so an agent works a site steadily rather than in a burst. A walled page
    that is neither asked nor on an allowed site is never listed, whatever its class in §6.1. A site's pages are surfaced
    from the reader's own failures wherever they happen (save time, the in-cycle pass, the backfill), and a page that
    already holds words is never listed. Grants are machine-wide (`reading.json`); a `needs_login` pause is per bank (the
    ask store is), and turning the site on again lifts it. The ask is stored machine-wide beside the video queue's precedent
    (`$CICADA_HOME/reading_asks/<bank>.json`, never in a bank; `{url_hash, host_class, at}`; expires after 7 days) and is
    written only by `POST /reading/asks`, which the app's button calls.
  - Each row: `{url, why, role, conversation_title?}`. **A remote connection without `sources` sees no conversation title
    and, for a `role: user` row, no URL** (the URL is the person's own words); it sees the host class and is told the person's
    own words exist. Such a connection can read only rows whose URL is not the person's.
  - **Amended 2026-09-30 (TODO ruling 14, owner: "limiting the amount of sites makes no sense to me, because we will never
    know which sites this will happen").** The per-host allow list is gone: sites are surfaced from the reader's failures and
    switched on per site; an agent may also record an outcome for a wall page of an allowed site with no per-page ask, and a
    site row from a channel that is the person's own words (Telegram, an agent's save, a chat export) needs `sources`.
  - **Amended 2026-09-29 (TODO ruling 14, at the owner's "build it now").** An *ask* row's URL is visible to any connection
    holding `read`: the person's explicit "Ask an agent" is the consent to hand that URL to an agent, and the default scopes
    would otherwise leave the ChatGPT and Claude apps unable to read any ask. The rule above still holds for a row harvested
    from a conversation (S3, not built): its URL and the conversation title need `sources`.
- **`cicada_record_read(url, summary, excerpts=[{quote}], kind?)`** (`record` scope). Caps as `cicada_record_watch`: one
  summary line ≤ 1,500 characters, at most 12 excerpts of 240, folded so no line can pose as a turn. What it writes, and
  how it differs from `record_watch`:
  - **A read episode** in the `attachment [<host>]:` grammar. Each summary line and each excerpt is rendered as a quoted
    (`> `) line under an `attachment [<host>]:` marker. `evidence._marker` already reads that family as kind **`page`**, and
    the episode carries **no `evidence_kind`** (an `evidence_kind: assistant` override would turn every span into
    `assistant`, because `evidence.kind_for` returns a declared `assistant`/`user` before it reads a marker). It is
    `processed: true, processed_by: agent`, so Sleep never extracts from it raw. **This deliberately differs from
    `watch_record`, whose episode is `processed: False`** and whose spans are `media` from timed `video [m:ss]:` lines.
  - **One `describes` claim** on the media page, observer the agent's harness label, with a `page` span for the summary and
    one per excerpt.
  - **Saving the page.** Like `record_watch`, it saves an unsaved http(s) link through the media writer first. Unlike
    `record_watch`, it does so **only for a URL that is in the queue** (a sidecar link or a saved link), so an agent cannot
    fabricate pages. `read.by: agent` and the harness label are stamped.
  - **What a `page` span means here.** It means "text an agent reported from the page", not "text Cicada checked". The
    backend never holds the page (§8.5).
- **The contract** gains a **new contract item 9**, not a bridge line. The bridge mechanism (`skill_catalog.bridge_lines`)
  is an installed-skill gate capped at `MAX_BRIDGE_LINES = 3`, and `BRIDGE_TEXT` already has three keys, so a fourth line
  would be silently dropped. Item 9 is emitted only while `reading.agent` is on and `cicada_record_read` exists in the
  tool schema. `reading.agent` is **folded into the primer's cache key** next to the bridge fingerprint (the key is
  `CONTRACT_VERSION:variant:stamp:tz:fingerprint(bridges)` today, so a toggle would otherwise serve a stale primer).
  `CONTRACT_VERSION` +1; the remote primer never passes `bridges`, so it takes its own path and `REMOTE_CONTRACT_VERSION`
  is bumped separately. The R12 test covers every argument the item names, and a **token-budget assertion** (every primer,
  local and remote, ≤ `MAX_TOKENS` = 1,800) joins `test_handshake_read_r12.py`.
- **Declared by acting.** Cicada records that a harness has called `cicada_record_read` (a ledger fact, last 30 days) and
  shows it once, plainly, in §7.1 as "An agent has recorded reads · last Sep 29". It does not light a per-browser
  "Connected": a call proves neither which tool nor that a browser was involved. Cicada never infers browse ability from an
  `initialize` capability.

**Route B, a spawned browse call (S7, spike-gated).** From "Read with my browser" on a chosen item, the backend spawns one
`claude -p --chrome` or a Codex call with a browser MCP, in `BROWSE_FLAGS`, foreground and person-present, one page at a
time, with a fixed floor between navigations and a per-run page cap. It is a plan-quota action, so it is manual only by
construction (ruling 4). It reports through the same `cicada_record_read` write path, so provenance is identical.
**Not built until the three spikes in §13 (S6) come back.**

### 8.5 Page content is untrusted, and what Cicada can and cannot check

Both vendors document prompt injection in browsing. A read's words enter memory as `page` evidence, never as the person's,
and never trigger a write beyond the sanctioned `cicada_record_read`.

- **The Reader (R0 to R3).** No prompt exists at R0 to R3, so there is nothing to inject. A summarizer gets the excerpt in
  a data fence with a closed output, and its output is `locate`d in the in-memory excerpt before it is written; a claim it
  cannot locate is dropped. The excerpt is then discarded, so the check is real for the Reader.
- **An agent's read (Route A and B).** The backend never has the page: it was read in the person's browser or by the
  agent's own tool, and "no page text is stored". The only text a `locate` could run against is the agent-written read
  episode, which would make the check circular. So **Cicada does not check an agent's excerpts against the page, and says
  so**: the spans are `page` kind by grammar, the app labels them "From the page, as Claude Code read it" (never "From the
  page" alone), and a fabricated quote cannot be filtered. Provenance never blocks memory (the standing rule), and the
  read episode is `processed: true`, so Sleep never treats it as a source to extract from raw. The claim's observer is the
  agent, never the person.

### 8.6 Who is responsible, said once

Anthropic's help text says the person is responsible for browser actions taken by Claude, including third-party terms on
automated access. OpenAI's page copy names LinkedIn among example sites while the site's own terms still apply. Cicada
says the same thing in the person's words (the §7.2 sheet), because hiding it would be the risk, and says nothing about
what an agent will or will not do inside a browser, because Cicada cannot enforce it.

### 8.7 Modes, by name (the owner's word), and how they map

| The owner's word | Where it lives | Default |
|---|---|---|
| "A scraper that just gives what's on the site" | **Reader** (§4) | **On** |
| "Even interact if needed" | **Agent reading**, Route A (or B later) | Off |
| "Logged-in sessions of the user themselves" | Agent reading, "With my browser" | Off, behind §7.2 |
| A public page that needs JavaScript | Reader + local engine (R4) or Agent reading | Off |

The research pass proposed four flat modes including "Agent browser (public)", a fresh isolated browser driven by a model.
This spec **drops it as a separate mode**: for a public JS page R4 is cheaper (no model), and for a public page that needs
interaction the person's own agent does it through the queue. If the owner rules against R4 (D-RW2), "agent, public" comes
back as the fallback for JS pages.

---

## 9. Rulings proposed (each a dated TODO ruling on approval)

| Id | Ruling | Effect |
|---|---|---|
| **R-RW1** | One descriptive User-Agent, `CicadaBot/1.0 (+<repo url>; personal-memory reader)`, one constant in `media_ingestor`, used by every reader of someone else's page, **on both page transports** (`default_fetch` and `_enrich_opengraph`). A fixed truthful identity is not "different headers". | Fixes the Wikipedia 403. `logo_service` and `paper_metadata` keep theirs until touched. |
| **R-RW2** | `Accept: text/markdown, text/html;q=0.9` on every page fetch, both transports; the `content_type` gate allows `text/markdown`. | Skips extraction on sites that opt in. |
| **R-RW3** | Metadata from the fetched bytes is a first-class tier, ahead of body text, through one shared parser. A metadata-tier result is written as the description without a summarizer call. | Turns many `failed:empty_body` pages into a description, and saves calls. |
| **R-RW4** | The login-walled host list (§5.2) is one closed set used by the reader and the chat-link scanner, including X. | Closes the X gap. |
| **R-RW5** | Side-effect and secret-bearing URLs are never fetched (§5.3). | A GET never unsubscribes or redeems anything. |
| **R-RW6** | Chat links: class U is read, C2 (cited in two or more conversations) is read, C1 is metadata only, X, T, A, S, H, L never (§6.1). Defaults per R-RW12. | The census-backed default. |
| **R-RW7** | Import is network-free and mints no page; reading is a queue with its own lane, excluded from the two existing lanes, and a user-triggered catch-up; progress is counted from files (§6). | Bounded and honest. |
| **R-RW8** | Agent reading is person-driven and never scheduled. Cicada only *asks* an agent to read: a walled page is surfaced only after the person's per-link "Ask an agent", or per site the person turned on after a page from it could not be read, one entry per site per call; a public JS page may be listed in batches while agent reading is on. Cicada does not control, and does not promise anything about, what the agent does in its own browser. The backend never holds a session. The standing rail "no scraping behind authentication" governs Cicada's own fetcher and is unchanged. | The dated ruling that keeps the person-driven mode from eroding the rail, without promising what Cicada cannot enforce. |
| **R-RW9** | `--chrome` never appears in any argv but `BROWSE_FLAGS`; a test enforces it. | Locks stay locks. |
| **R-RW10** | **Robots.txt is honoured by the Reader.** Fetched once per host per run under the same 4 s and 512 KB caps and `net_guard`, no cookie; 4xx allows, a disallow is `blocked` with reason `robots`, a 5xx or a timeout disallows for the run without stamping the page. Applies to a user-triggered "Read now" too. | Makes the politeness claim true. It did not exist before this revision. |
| **R-RW11** | **Backoff by status.** `blocked` and `failed:*` retry after `link_enrich_fetch_retry_days` (30); `needs_js` is never retried by the clock; a `fetch_reader_v` bump makes `blocked` and `failed:empty_body` pages eligible once. | Lets R-RW1's fix reach pages already stamped. |
| **R-RW12** | **Nothing unattended without a choice.** `reading.chat_links` is `manual` until the person picks `nightly` or `off`; no radio that enables unattended reading is pre-selected; imports that show no card and live conversations stay `manual`. | Consent, matching the onboarding rule that nothing is read before a tick. |

An R4 rail amendment (a per-fetch budget above 4 s, a user-installed local renderer counting as the same rail) is
written only if D-RW2 says yes, and only in S9's own PR.

---

## 10. The navigator (future): a classifier that picks the next link

**Facts.** **Jev** is TypeSafe AI's "System One" decision model. Confirmed today from OpenRouter's docs: model id
`typesafe/jev-1.13` (alias `~typesafe/jev-latest`), `POST https://openrouter.ai/api/alpha/decisions` or
`…/api/v1/systemone`, 32K context, input tokens billed and **output free**, three question primitives (Choice, Noul
yes/no, Score) returning probabilities not prose, weights closed. **[reported]** launched 2026-09-15, about $0.042 per
million input tokens, 70 to 500 ms end to end. Those two figures and the "40 to 200× cheaper and faster" claim are
TypeSafe's own or a critic's summary of it, and one critique found the gain holds mainly against the slowest baselines
and that typed decomposition helped every model tested, which is not Jev's doing. Not in the plans people normally have,
as the owner said.

**What it does here.** Ranking candidate links from a page (anchor text, path, heading) against a goal, and answering
stop conditions ("does this page already hold the answer?", "is this a wall or junk?"). The precedent is Mind2Web's
MindAct: a fine-tuned DeBERTa ranks elements (about 85 to 89 % recall in the top 50), a larger model chooses among the
survivors. Where Cicada would use it: G61's "find the page that holds this fact" from a source's home page in one or two
hops, and G102's site recon across a site's `about` and `docs`. Never a crawler.

**Fit with the rails.**
- It sees only page text already fetched under the rail. It adds no scraping. A Noul "is this a wall?" can retire a page;
  it can never trigger a retry.
- The page text and the goal leave the Mac for TypeSafe via OpenRouter: `LeavesMacNote` gains a sentence, the toggle is
  off by default, no gate treats it as implicit, and a person's name is never sent (G159's rule).
- It must be swappable: one interface, `Navigator` (`rank(goal, candidates) → scores`, `stop(goal, page) → p`), with
  `heuristic` (the default, zero cost, no OpenRouter), `embedder` (the on-device EmbeddingGemma cosine against anchor text,
  already shipped), `jev` (OpenRouter) and `local-classifier` (a fine-tuned MiniLM or DeBERTa, open, CPU, no data leaves).

**Settings.** A row "Smarter navigation" under Reading the web, drawn as **Off · Needs OpenRouter** and, until
built, a switch-less "Not available yet" (§7.1: a deliberate exception to "absent, not disabled", because the owner asked
for the row). On enabling, the row says where reads leave the Mac and to whom.

**Do first, and it is the whole gate.** Before any of it: a small navigation set (real "find the team page from the home
page" tasks over public sites), and three baselines measured against each other: the heuristic, the on-device embedder,
and a MindAct-style MiniLM. Jev is built only if it beats the embedder by a margin worth an OpenRouter key. Cheapest
baseline first, because that is the one most people can use without a key.

---

## 11. Cost, in one table

| Path | Time per page | Model use | Whose quota | Estimate basis |
|---|---|---|---|---|
| Reader R0 to R3 | fetch 53 to 827 ms, extract 1 to 30 ms | none | none | reported, one run |
| Summarize a page the reader read | one call | one mini-model call, about half of pages need it (a substantive metadata-tier result needs none, §4.5); **a short excerpt of the page is sent to that engine, including a hosted one** | the engine's, on `preview.manual` for a triggered run; `settings.litellm_model` on the tail as today | 52 % substantive-description share measured on saved pages |
| Chat-link catch-up (536 readable) | about ten minutes of fetch | about 250 summarize calls plus about 70 recon calls | manual engine | assumed |
| Local engine R4 | reported 51 to 84 ms page loads (Obscura's own claim) | none | none | reported, vendor |
| Agent read, Route A or B | seconds per step, about 30 to 120 s a page including model round trips | reported 3 to 12k tokens per navigation, about 27 to 114k a session (Playwright-MCP-style reviews) | the person's Claude or ChatGPT plan | reported, not measured on Cicada |
| Navigator (Jev) | 70 to 500 ms (reported) | none, it is a classifier | OpenRouter key, input tokens only | reported |

A plan-quota action never runs on a schedule. The app shows a count of reads and of model calls, never a price or a token
count (DR-59).

---

## 12. Backlog rows to file (numbers assigned when filed)

**Filed 2026-09-29:** rows 1 and 7 are **G164**, row 2 is **G165**, rows 3 and 4 are **G166**, row 5 is **G167**, row 6 is **G168**; the G61, G102 and G133 notes are on those rows.


Each carries its evidence and cites this spec; none re-opens a settled ruling.

1. **The Reader ladder** 💸 (no spend in the ladder itself): R0 to R3, robots.txt, `needs_js`, both transports, the
   backoff and `fetch_reader_v` rule, the extractor bench. APPLY.
2. **Links inside imported chats** 💸: sidecar (offsets from `render`), roles, classes, the chat-link writer and its named
   signature changes, the chat lane and the two existing lanes' exclusion, the reading-job registry, the intake row and
   the consent defaults (R-RW12). APPLY.
3. **Reading with an agent**: the queue and per-link asks, `cicada_record_read` (`attachment` grammar, `page` spans),
   contract item 9 and its cache key, the sheet and a per-site permission list built from failures. APPLY (Route A), DECIDE (sessions).
4. **A spawned browse call class**: `BROWSE_FLAGS`, three spikes. RESEARCH.
5. **A local browser engine (Obscura or Lightpanda)**: sidecar and rail amendment. DECIDE.
6. **A classifier navigator behind `Navigator`** (Jev via OpenRouter, embedder, local classifier), benchmark first. Carries
   the owner's 2026-09-29 request for a Settings option labelled "Needs OpenRouter".
   RESEARCH.
7. **Settings → Reading the web** and the "Browsers on this Mac" detection. APPLY.
8. A note on **G61**: the reader and the agent queue are its rung 1 and rung 2; S4's `default_fetch` reuse becomes the
   ladder, so G61 S4 and RW-1 share one implementation. A note on **G102**: the metadata tier is the "cheap slice"
   extended to unread pages. A note on **G133**: `never_scraped` and the video and paper hand-offs.

---

## 13. Phasing: shippable slices and acceptance tests

Each slice is its own PR to `dev`, cites the DR ids and R-RW ids it applies, and leaves the suite green.

| Slice | What | Backend-only? | Depends on |
|---|---|---|---|
| **S0** | This spec, the R-RW rulings and the backlog rows, in `docs/goals/`. No code. | docs | owner approval |
| **S1** | **Reader ladder.** R-RW1 to R-RW3, R-RW10, R-RW11: UA constant and `Accept` on **both** page transports (`default_fetch`, `media_ingestor._enrich_opengraph`), robots.txt, one shared metadata parser (`page_meta.parse`, extracted from `_enrich_opengraph`, R1 on `selectolax`), R2 extractor (D-RW1), R3 `needs_js`, the `read:` block, `fetch_reader_v`, the backoff rule (§4.4), a metadata-tier result written without a summarizer call (§4.5), the aggregate report counters (§4.3). Includes a **bench harness** over replayed fetch results. | yes | S0, D-RW1 |
| **S2** | **Chat-link extraction.** Two parsers keep structured citations; `episode_staging.render_with_links` (offsets from the same scrubbed lines as the turn stamps); `EpisodeDraft.links`; the same-body sidecar refresh branch; `draft_from_export` carries the parser's `cited` entries; `POST /intake/sniff` returns in-file link counts. No network, no pages. | yes | S0 |
| **S2b** | The same extractor on Stop-hook episodes (`reading.chat_links` stays `manual` until chosen). | yes | S2 |
| **S3** | **Chat links become pages and get read.** The chat-link writer (§6.3: `RawItem` fields, `defer_enrich`, `ingest_batch_results`, `attach_episode`, its own commit), the chat lane and the exclusion of chat pages from the two existing lanes (§6.4), the reading-job registry, `POST /reading/read`, `POST /reading/jobs`, `GET /reading/jobs/{id}`, `GET /reading/queue`, `GET /episodes/{id}/links`, the intake row, `MediaSourceItem.read`, the Reader's "Links in this conversation". | backend + app | S1, S2, D-RW3, D-RW4 |
| **S4** | **Agent reading, Route A.** `cicada_reading_queue`, `cicada_record_read`, `POST /reading/asks`, contract item 9 gated on the setting, cache-key fingerprint, remote contract +1, R12, ledger kind `read_agent`. | yes | S1 |
| **S5** | **Settings → Reading the web**: the section, the two axes, the sheet (no site picker), the surfaced-sites list with its per-site switches and favicons, "How your agent reads", the Feed's "Read" line, `GET /reading/settings`. | app + a small `GET /reading/settings` | S1, S4 |
| **S6** | **Spikes, no data at stake** (two days): does `claude -p --chrome` finish a public-page read with no interactive prompt, and at what cost; can `~/.cicada/codex` load Playwright MCP through `-c mcp_servers…`; can the Codex Chrome plugin's native host be reached from an isolated `CODEX_HOME`. Output: a ruling. | research | none |
| **S7** | **Spawned browse call class**, `BROWSE_FLAGS`, "Read with my browser", the R-RW9 test. Only if S6 says yes. | backend + app | S4, S6 |
| **S8** | **Navigator benchmark**: task set, three baselines, a written result. No product code. | research | none |
| **S9** | **Local browser engine**, only if D-RW2 says yes: sidecar over CDP, rail amendment, `reader_js` mode. | backend + app | S1, D-RW2 |

**Acceptance tests (names and what they prove).**

- **S1**
  - `test_reader_identity.py`: every page fetch, on **both** transports, carries the one UA and the `Accept` header; a
    `text/markdown` reply is used without extraction; `test_wikipedia_class_fixture` replays a recorded
    403-under-old-UA / 200-under-new pair.
  - `test_reader_robots.py`: robots.txt is fetched once per host per run under the same caps; a disallow means the page is
    not requested and reads `blocked` with reason `robots`; a 4xx robots reply allows; a 5xx or a timeout disallows for the
    run without stamping the page; the robots request carries no cookie and `net_guard` applies to it.
  - `test_reader_metadata.py`: fixtures for an OG-only page, an `ld+json` page and a `__NEXT_DATA__` shell each return `ok`
    with tier `metadata` and never `failed:empty_body`; `page_meta.parse` is the one parser both transports call (a test
    imports both call sites and asserts identity).
  - `test_reader_metadata_no_llm.py`: a `tier: metadata` result with a substantive description is written by the backfill
    without calling `summarize_fn`; a thin one still goes to the summarizer.
  - `test_reader_needs_js.py`: a shell with an empty root and a framework marker is `needs_js`; a real 403 stays `blocked`;
    an interstitial stays `interstitial`.
  - `test_reader_backoff.py`: `_in_fetch_backoff` covers the rule of §4.4. `blocked` and `failed:*` retry after
    `link_enrich_fetch_retry_days`; `needs_js` is never retried by the clock; a page stamped `blocked` or
    `failed:empty_body` under an older `fetch_reader_v` is eligible once after a version bump and then stamped current.
  - `test_reader_rail.py`: no cookie is sent, a 403 is never retried with other headers, `net_guard` still refuses a private
    redirect, the byte and time caps hold.
  - **Bench gate (D-RW1's evidence):** over at least 100 saved pages' replayed bytes, the chosen extractor must beat
    today's bs4 on the share of excerpts that do **not** open with navigation text, and must not lose on the share that
    reach 100 characters. Reported, never asserted as a fixed number.
- **S2**
  - `test_chat_links_extract.py`: user versus assistant versus cited roles; Markdown links count once; trailing
    punctuation stripped; classes L, T, A, S, H dropped; a URL with a `token=` never survives scrub; an attachment's links
    are never recorded; **every recorded `offset` slices the stager's rendered evidence text to the URL** (the rendering
    after scrub and speaker prefix), asserted against `episode_staging.render`'s own output.
  - `test_chat_links_parsers.py`: a ChatGPT fixture with `content_references` and `search_result_groups` records the
    former and never the latter; a Claude fixture with `citations[].details.url` records it; a `tool_result` URL is
    never recorded; `draft_from_export` carries `cited` entries into the draft.
  - `test_chat_links_sidecar.py`: the sidecar is outside `content_hash`; a re-import whose body is unchanged but whose
    citations changed takes the new same-body refresh branch (rewrites only the sidecar, never flips `processed`, never
    touches `content_hash`); capped head-stable at 60; `cited` entries survive a refresh that only re-derives offsets.
  - `test_sniff_link_counts.py`: sniff returns "in this file" counts over the readable set and stages nothing.
  - Import makes **no network call** (the suite's fetch stub asserts zero) and mints **no page**.
- **S3**
  - `test_chat_link_pages.py`: class U mints a media page with the chat origin, `content_saved_at` equal to the message
    date, `source_episodes` naming the conversation (and no media episode of its own, or a born-processed one, per the S3
    plan's decision in §6.3), no fetch at mint; `inject_media_edges` joins the page to the conversation's entities; a link
    already in `url_index.json` mints nothing and gains the conversation through `attach_episode` in the same commit; a bare
    URL writes no `saved-because`; the mint commits as `cicada` with trigger `capture/chat-links`, not as `user`.
  - `test_chat_lane_caps.py`: **through both existing entry points** (`_candidates` and `scan_backfill`) a chat-origin page
    is never selected, and through the new chat scan at most `link_enrich_chat_per_cycle` are; repeats first, not
    oldest-first; a saved-link lane and a chat lane never starve each other.
  - `test_reading_job.py`: progress counts equal file-derived counts after a simulated restart; 409 while Sleep runs; a
    second `POST /reading/jobs` while one runs is 409 (the registry's own single-flight guard, not `STAGE_LOCK`); 409 in a
    demo bank; cancel leaves every read page intact; every count sums to total.
  - `test_demo_capture_routes.py` (extended): `POST /reading/read`, `POST /reading/jobs` and `POST /reading/asks` carry
    `refuse_capture_into_demo` and are in the gated list.
  - `test_reading_queue_etag.py`: `GET /reading/queue` and `GET /episodes/{id}/links` return an ETag over the components of
    §7.3 and answer 304 unchanged.
  - `test_source_overview_chat_pages.py`: chat-link pages carry an origin the Sources overview and `OriginIconography`
    already know; no raw `origin:<id>` card appears; the export card's conversation count is unchanged.
  - `test_reading_walled_never_fetched.py`: X, LinkedIn, Instagram, Facebook, TikTok and Reddit are never requested by the
    backend under any mode.
  - Swift: `LinksInConversationTests` (role tags, state words, an absent section for a pre-S2 episode);
    `IntakeLinksRowTests` (no radio pre-selects unattended reading); `ReadingProgressTests` (no price, no token count,
    `CountLiteralLintTests`); `FeedReadLineTests` (`MediaSourceItem.read` decodes when absent).
  - **Measured on the owner's exports before merge:** the share of the readable set that reads `ok`, `metadata`, `blocked`,
    `needs_js`, `failed`. This is the number §3.4 says is missing.
- **S4**
  - `test_record_read.py`: caps and folding as `record_watch`; the read episode renders every excerpt as an
    `attachment [<host>]:` quoted line, carries no `evidence_kind`, is `processed: true, processed_by: agent`, and every span
    into it is kind `page`; saves an unsaved link through the media writer only for a queued URL; `read.by: agent`; refused
    in a demo bank and while Sleep runs.
  - `test_reading_queue_tool.py`: returns nothing when agent reading is off; never returns a class S link; returns a walled
    link only when the person's ask exists for that exact URL, or its site is allowed and the page is a wall page the reader could not read, at most one such row per site per call;
    public `needs_js` and blocked rows in batches of up to 20.
  - `test_handshake_read_r12.py`: every argument the primer names exists in the schema; contract item 9 appears only when
    the setting is on and the tool exists; toggling the setting changes the cache key; every primer, remote included,
    stays within `MAX_TOKENS` (1,800).
  - `test_remote_scopes_read.py`: `read` and `record` scopes gate the two tools; a connector without `sources` is shown no
    conversation title and no URL for a `role: user` row, only its host class.
- **S5**
  - `SettingsReadingSectionTests` (the section is searchable through `SettingsIndex`, lands and washes its row);
    `AgentReadingSheetTests` (Turn on disabled until acknowledged; no site picker; the sheet asks the agent not to type
    credentials and says Cicada can't enforce it); `ReaderEngineNoteTests` (the one neutral sentence, no provider named);
    `ProviderNeutralCopyLintTests`; `ReadingSitesTests` (the surfaced list from the pinned fixture, a switch while the master is
    off, a rollback with the server's sentence); a lint that no string on the page carries a price or a token count.
- **S7 (if it ships)**
  - `test_browse_argv_isolation.py`: no engine argv but `BROWSE_FLAGS` contains `--chrome`; `--no-chrome` on the rest.
  - `test_browse_manual_only.py`: refused on any scheduled path; refused for `byok`; refused in a demo bank; a deny-listed
    host is refused without a per-host opt-in.

---

## 14. Open questions for the owner (only real decisions)

**D-RW1. The extractor and the fetch-layer rulings.** Approve R-RW1 to R-RW3, R-RW10 and R-RW11 as written? And the
extractor: **trafilatura** (Apache-2.0, best published quality, about 65 MB of dependencies including `lxml`; the
maintainer's own benchmark has it at F 0.924 against readability-lxml's 0.826, and I have not re-run that), or
**`rs-trafilatura`** (about 21 MB, MIT or Apache, reports a higher score on its own sets but is a 0.1.x package with about
two dozen commits). *Recommendation:* trafilatura, pinned, with today's bs4 extractor as the fallback, and let S1's bench on
your own saved pages overrule the published numbers.

**D-RW2. A local browser engine for JavaScript-only pages: yes, no, or later?** If yes, **Obscura** (Apache-2.0, Rust,
39 MB, created April 2026, v0.2.3, so pin a source) or **Lightpanda** (AGPL-3.0, 84 to 88 MB, more mature, beta Web API
coverage). Cicada is MIT; running Lightpanda as a separate downloaded process over CDP, never bundled or modified, is the
conventional reading, but that is a legal call I cannot make. Either needs a rail amendment (a fetch budget above 4 s, a
ruling that a user-installed renderer is the same rail). *Recommendation:* **later.** Ship S1 first, measure how many saved
and chat pages are `needs_js`, and decide on that number. Obscura if yes.

**D-RW3. Chat links: what happens when nobody answered the question?** The card (§6.5) offers **Read them when I say**
(the default, nothing fetched until you press Read), **A few each night**, and **Don't read links from chats**. The
unattended option is never pre-selected, and any import that shows no card (the two deprecated shims, a re-import through
the API, a live conversation captured by the Stop hook) behaves as **Read them when I say** until you choose. This is
stricter than the first draft of this spec, which pre-selected "a few each night". *Recommendation:* as drawn. The price is
that a person who clicks straight through gets no reading until they open Settings or press Read now.

**D-RW4. Where do chat-shared links sit in the Feed?** In the main list dated by the day they were shared (the Feed grows
by up to about 536 pages, roughly 40 % over the current saved count), or behind an origin filter "From chats" that is off
until chosen. *Recommendation:* in the main list, with the vendor's mark and the message date. A link you shared is memory,
and the origin line already says where it came from. Reconsider if the Feed's relevance sort suffers. Note that pages are
minted only when read (§6.3), so the Feed grows as you read, not at import.

**D-RW5. Ship "With my browser" (signed-in sessions) at all?** It is the only way LinkedIn, X and Instagram get read, and
their terms forbid automated access even when you are signed in; your account is the one at risk. *Recommendation:* yes, last
(S4 gives Route A, which needs no Cicada code that touches a session), behind §7.2's acknowledgement, a per-site permission
list built from the reader's own failures that starts empty, an explicit "Ask an agent" on each link, and no promise about what your agent does in its browser. If
you would rather Cicada never offer it, Route A still works for public pages and you point your own agent at the rest
yourself.

**D-RW6. A new `processed_by` value for deterministic writers.** A chat-link page's own episode (if it has one) is written
by no model and no person. `processed_by` today is `sleep`, `agent` or `user`. *Recommendation:* add `cicada`, matching the
`Cicada-Author` label, and audit every reader of `processed_by` first (a grep gate, like `is_event`). The alternative is to
write no media episode for a chat-link page at all, which needs S3's plan to prove nothing reads that episode (the
`describes` claim's evidence path).

**D-RW7. Robots.txt for the Reader** (R-RW10, new in this revision). Cicada's reader has never read `robots.txt`; earlier
drafts of this spec assumed it did. *Recommendation:* honour it, at the cost of some pages reading `blocked` with reason
`robots` that read fine today. The alternative is to say plainly that the Reader ignores robots.txt, which the descriptive
User-Agent makes an odd position to hold.

*Critiques not adopted.* None was shown wrong. Two were adopted in a different shape than proposed: the chat-link default
is `manual` (not `off`), and the "Smarter navigation" row is kept as a deliberate exception (§7.1) because the owner asked
for it.

---

## 15. Risks

| Risk | Signal | Mitigation |
|---|---|---|
| **The readable set turns out mostly unreadable** (dead links, JS-only, walled) | S3's measured status split | The design already treats it as data, not a promise. R3's `needs_js` and the agent queue absorb the JS share; if reads are under a third, stop after S3 and keep the sidecar. |
| **A chat link is a capability link** (a shared document, an unlisted page) | Class S denylist misses a pattern | The denylist is a closed set and a test. A private-workspace host is never fetched. The URL was already in the conversation, so storing it in a media page adds no new exposure beyond the bank; the query string is scrubbed. |
| **A GET has a side effect** | An unsubscribe or confirm link read | R-RW5. Also: the reader sends no cookies, so a personalised action link mostly cannot act. That is a mitigation, not a guarantee. |
| **A polite fetch of hundreds of small sites reads as a crawler** | A host answering 429 | ≥ 3 s per host, one attempt per link, a 403 or 429 skips the host for the run, **robots.txt honoured (R-RW10, new: the reader did not read it before)**, an honest UA with a contact URL. |
| **The descriptive UA gets Cicada blocked more, not less** | `blocked` rate before and after in S1's replay | R-RW1 is measured, not assumed: the replay compares old and new UA over the same URLs. Revert is one constant. |
| **A model summarizer is injected by page text** | A read that produced an instruction-shaped claim | Data fence, closed output, the summarizer's output located in the in-memory excerpt before it is written (Reader path only), `processed: true` episodes (§8.5). An agent's excerpts (Route A) are unverified and labelled so. |
| **`--chrome` overrides the locks** | Any argv test failing | R-RW9 and `test_browse_argv_isolation.py`. |
| **Route A depends on agents doing it** | The `cicada_record_read` rate over 30 days | Measured before S7 is built. G61's threshold logic applies: low participation means Route B, or leave it. |
| **The agent queue becomes a bulk-read surface** (an agent told to "work the queue" reads every walled link) | Queue rows per call | Walled links appear only after the person's per-link ask, or on a site the person turned on, one entry per site per call; public rows are batches of 20 and never walled. |
| **The person's account is restricted by a platform** | A report | The acknowledgement says it; the site permissions start empty and each site is switched on by the person after a page from it could not be read. Cicada does not control what the agent does in its browser and says so. Not fully mitigable, which is why it is D-RW5. |
| **Vendor claims about Jev do not hold** | S8's benchmark | Nothing ships before it, and the heuristic and the on-device embedder are the default paths. |
| **The Sleep-page v5 spec draws the Details rows differently** | A plan-time diff | §7.4 supplies data contracts and one progress line; the Sleep spec owns placement and wording. |
| **The sidecar grows episodes** | Episode size | Capped at 60 entries and 200-character snippets; `cited` only. |
| **Import time grows** | S2's timing over the two exports | Extraction shares `render`'s scrubbed lines; measured in S2, budget of a few percent of parse time. |
| **Old `blocked` pages never see the UA fix** | Wikipedia-class pages still `blocked` after S1 | `fetch_reader_v` (§4.4): a version bump makes `blocked` and `failed:empty_body` pages eligible once. |

---

## 16. What this spec did not verify

- The research pass's timings (53 to 827 ms fetch, 1 to 30 ms extract) and its quality table are its own single runs and
  the maintainer's benchmark. S1's bench replaces them with numbers on Cicada's own pages.
- Whether `claude -p --chrome` finishes without a click, whether an isolated Codex home can load a browser MCP, and the
  cost of a browse call on Cicada work (S6).
- The share of chat links that are readable (S3).
- Jev's price and latency (vendor and a critic); its model id, endpoint, context length, free output and closed weights are
  confirmed from OpenRouter's own page.
- The legal reading of Lightpanda's AGPL against Cicada's MIT, and the platform terms as they apply to a particular
  person's account (D-RW2, D-RW5).
- **Code claims in this revision.** Revision 2 folds in a review of this spec against the code. Spot-checked directly
  against `dev @ 2155940`: no robots.txt handling in `link_enrichment.py`, no `defer_enrich` anywhere in `api/services`,
  the export origin ids `chatgpt-export` and `claude-export` in `routers/intake.py`, `_in_fetch_backoff` treating every
  non-`ok` status as retryable, `ingest_batch` returning a bare `(int, int)`, `MAX_BRIDGE_LINES = 3`. The remaining code
  claims (`episode_staging` internals, `evidence.kind_for`, `intake_jobs`, the two-transport split, the Sources overview
  mapping, `_commit_media`'s defaults) are taken from the review and must be re-read by each slice's plan.

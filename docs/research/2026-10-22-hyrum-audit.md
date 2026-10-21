# Hyrum's Law audit (2026-10-22): the MCP surface and the Settings panel

Two audits under the Hyrum's Law method, in one place. **Mode A** covers the MCP tool surface, which every
connected agent reads. **Mode B** covers the app's Settings panel, which the owner finds overwhelming. PR #398
applies four presentation-only changes from Mode B. Everything else here is a proposal.

**Classes.** *Contract* is promised, documented or tested. *De facto* is not promised, but a consumer was found.
*Incidental* means no consumer was found.

**How it was observed.** Every run used the verify-cicada skill on scratch state: a scratch HOME, `CICADA_HOME`,
bank and port, the owner page named "Verify Person", and the plan account masked. Nothing from a real bank was read.
Every example below is synthetic (`alpha-project`, `bob-example`).

- Mode A ran one backend at VERSION 0.5.0. It seeded two conversations through `/capture/turn`, ran one Sleep on the
  plan at haiku, then made about 120 stdio calls across all 46 tools, deliberately bad ones included. A driver kept
  one server process for many calls, so per-process state showed. Remote primers were rendered offline.
- Mode B read every control's source for its stored key or route. It drove two copies of the app, each on its own
  scratch backend: `dev` at `0fa3f239` (before) and this branch (after). Every pane was shot in both, and each moved
  control was driven once. `cv app containment` found nothing open under the real Application Support, and nothing
  changed under either run's bank id.

---

## Ranked across both

Ranked by harm. Harm already done to an agent's work or to the person's record comes first. Harm a careless change
would do to consumers nobody can search comes next. Cosmetic cost is last. "A" ids point into Mode A, "B" rows into
the Mode B table.

| # | Item | Harm basis | Status |
|---|---|---|---|
| 1 | **A3. The tool schema is advertised, never enforced** | Done now. Invalid data is already written: an `observer` outside the pattern is recorded, and an empty episode is saved and counted | Proposal |
| 2 | **A5. An episode id's date is the UTC day, read as the person's day** | Done now, to the record. Sleep dated a fix "the 21st" for words said on the local 22nd. Three readers take the day from the id | Proposal, needs the owner's intent first |
| 3 | **A2. A refusal comes back as an answer (`isError: false`); a crash carries the raw Python message** | Done now, to every agent. Telling "not found" from a real answer means parsing English | Proposal |
| 4 | **A4. Tool and argument names** | Careless-change harm, highest. Names sit in user allowlists, installed skills and other harnesses' configs, none searchable. The lean-MCP rename is planned | Proposal (freeze, then unlisted aliases) |
| 5 | **A1. The recall reply's `cicada-hints` fence and block layout** | Careless-change harm. Six tests, the CLI, a verify feature file and the benchmarks read it | Proposal (document; fix two misleading keys) |
| 6 | **B1. Merging the 15 Settings sections** | Careless-change harm. `cicada.settingsSection` raw values, deep links and search sections would move | Proposal |
| 7 | **A11. The legacy observer value (the owner's first name) is in the public schema** | Done now. A hardcoded owner name ships to every client and writes a trust-protected claim | Proposal |
| 8 | **A7. The handshake misleads** | Done now, to agents. Any client named like "claude" is told to run `claude --resume`. Two HTTP routes are named that no MCP agent can call | Proposal |
| 9 | **B-paths. Settings copy names `~/.cicada/…` whatever `CICADA_HOME` is** | Done now, to the person and to agents that read the screen. Observed on a scratch home: Privacy says `~/.cicada/secrets.env` while Plans & keys, on the same app, names the real path | Proposal |
| 10 | **A8. SKILL.md has drifted from the tools** | Done now, to agents. It forbids page edits that the primer now teaches | Proposal (docs only) |
| 11 | **B4. "Where your memory lives" moved General → Devices** | Careless-change harm, now spent. Every consumer in the repo was migrated in #398. People's own notes that quote "Settings → General → A server" were not searchable | **Done** |
| 12 | **A6. `cicada_recall_detail` returns raw internals** | Low. Only the golden fixture and one benchmark parser read them | Proposal |
| 13 | **A9. Untrusted text is marked on one door and not the other** | Safety. Saved-link titles a third party wrote reach a stdio agent unmarked | Proposal |
| 14 | **B6, B7, B2. Repeated headers and order** | Cosmetic. Incidental, no consumer | **Done** |
| 15 | **A10. JSON-RPC gaps (no `ping`, no `-32700`)** | Client-compatibility risk, no harm seen | Proposal |
| 16 | **A12, A13, remaining B proposals** | Cosmetic, or a cost to context budget | Proposal |

---

## Mode A: the MCP surface

### Findings

**A1. The recall reply: the `cicada-hints` fence and the block layout.** Contract, with de facto parts.
`cicada_recall` opens with a fenced block, info string `cicada-hints`, holding `suggested_entities`, `relevant_hub`,
`hub_members_preview`, `next_tool` and `note`. A process's first recall also carries `state` (`engine`, `pending`,
`projects`, `as_of`, its own `next_tool`); later calls in the process omit it. Each hit follows as
`### <name> (<type>, confidence: <raw float>, status: <s>)`, then `Related: …`, then the page body. The heading uses
the display name (`Bob-example`), not the id.

- Consumers: `api/tests/fixtures/mcp_stdio_golden.json` (`recall`, `recall_again`, byte for byte), and
  `test_mcp_recall_legs.py:65`, `test_cli_reads.py:15,56`, `test_cli_unit2.py:421`, `test_mcp_handshake.py:77,87`.
  The CLI's `--json` `data` carries the payload (`mcp.md:1253`). The verify skill's `recall-and-search.md:25` tells
  verifiers to read `suggested_entities`. The benchmarks feed this text to a model as context
  (`benchmarks/retrieval.py:57-59`, `run_table1.py`, `run_table3.py`), so a layout change moves their numbers.
- Misleading now: `next_tool` appears twice with different values (`mcp_tools.py:1933,1957`). `state.pending` is the
  `_state.md` cursor, stale by design; it said 0 while `cicada_pending` listed 5. One confidence shows three ways:
  `0.8928571428571429` in the heading, `0.89` on the hub, `conf 0.60` in `cicada_get_perspective`.
- **PROPOSAL.** Keep the fence and its keys. Say in `mcp.md` what is stable (keys, info string) and what is not (key
  order, the prose `note`, confidence precision). Rename `state.next_tool` to `state.refresh_with`, or drop it.
  Rename `state.pending` to `pending_as_of`, or drop it, since the handshake carries the number. Round confidence to
  two places. *Migration:* the golden fixture and the three CLI tests change in the same PR. Agents mostly read
  `suggested_entities`, which stays. A renamed key gets a release note naming the old one.

**A2. Errors are prose on the success channel.** De facto, and already misleading.
Refusals and not-found answer `isError: false`, in at least eight wordings (`Entity 'x' not found.`,
`No subject 'x' found in memory.`, `No project 'x'.`, a lowercase `no project 'x'.` in `cicada_backlog`,
`Could not write claim: …`, `Nothing changed — …`, `Error: …`, and others). `mcp_tools.py` has 26 `Error:` returns and
about 59 other refusal sentences. `isError: true` comes only from an uncaught exception, and on stdio it carries the
raw message (`Error: 'int' object has no attribute 'lower'` for `query=123`). The remote runtime answers with the
class name only (`api/remote/runtime.py:333`) and sets `is_error` for denied, busy, demo and capped too
(`api/remote/app.py:300`). Transport detail leaks: `Could not resolve inbox-999 (HTTP 404: …)` (`mcp_tools.py:4044`).
The structured code already exists and is dropped: bodies return `Reply(str)` with `code` (`not_found`,
`empty_graph`, `out_of_range`, `demo_bank`, …) and `data`, the CLI exposes it as `{ok, code}`, and
`mcp/server.py:1201-1214` sends only the text.

- Consumers: the golden fixture pins five of these with `isError` absent. The CLI envelope reads `Reply.code`.
- **PROPOSAL (contract change).** Keep every sentence. Set `isError: true` when `Reply.code` is a refusal code. Add
  `structuredContent: {code, data}`, which a 2024-11-05 client ignores. On stdio, replace exception text with the
  remote shape. *Migration:* re-record the golden fixture for the flag only. The release note says `isError` now also
  means "refused". An agent that retried on `isError` will stop retrying a not-found, which is the intent.

**A3. The schema is advertised but never enforced.** The contract is broken; the leniency is de facto.
Every argument is read with `arguments.get(key, default)` (`mcp/server.py:1332-1506`). Nothing checks `required`,
`enum`, `pattern` or type.

- Wrong data is written. `cicada_write_claim` with `observer: "martian"` answered `Recorded: … observer=martian`
  though the pattern forbids it. `cicada_save_episode` with no `content`, a required field, saved an empty episode
  (rev `e3b0c44298fc`, sha256 of "") that then counted in `cicada_timeline`.
- Silently ignored or wrong. `start: "abc"` reads from line 1. `top_k: "lots"`, `limit: "ten"` and
  `entity_ids: "alpha"` are dropped. `since: "last tuesday"` falls back to 7 days without saying so.
  `cicada_project` with `tz: "Mars/Olympus"` fell back to UTC and called the person's today "tomorrow".
- Asymmetric. A missing `query` on `cicada_recall` searches `''`; `cicada_recall_detail` answers `entity_id is
  required.`
- Consumers: none found in the repo relying on leniency. Other agents almost certainly send stringified ints today.
- **PROPOSAL (contract change).** Validate once in `handle_tool` against `TOOLS[name].inputSchema` and answer
  `isError: true` with `Invalid arguments: <field> …`. Fix the two data-integrity cases first: an observer outside
  the pattern, and empty `content`. *Migration:* accept a digit string for an integer for one release, with a warning
  in the reply, then reject. Check whether the remote listener's SDK already validates, so both doors refuse the
  same inputs.

**A4. Tool and argument names.** Contract.
46 stdio tools and 28 remote (27 shared plus `cicada_capture_turns`). Names are spelled out in the primer (23
tools), the remote primer, `SKILL.md` and its byte copy in `plugins/cicada/skills/cicada/` (pinned by
`test_claude_code_plugin.py:89-91`), `skills/cicada-librarian/SKILL.md`, every tool description, `cli_map.py`,
`api/remote/catalog.py`, `tool_client.py:26`, `test_write_admission_sites.py:518`, the benchmark prompt
(`run_retrieval_eval.py:68`), and users' own permission allowlists (`mcp__cicada__cicada_recall`). `mcp.md:1249` plans
the lean-MCP grouping "with the old names kept as aliases".

- Sibling drift an agent trips on today. One inbox id is `id` in `cicada_resolve_inbox` and `item_id` in
  `cicada_record_check`; `resolve_inbox(item_id=…)` answers `Error: id is required`. One page id goes by
  `entity_id`, `subject`, `project` or `hub`. A backlog item prints as `AP1` but `cicada_add_backlog_note` wants
  `alpha-project/AP1`, and its error example names another project's prefix (`backlog.py:297`). `save_url` writes
  ids bare while `write_claim` and `record_watch` backtick them, and the tests' regexes differ to match
  (`test_video_save_defects.py:43`, `test_watch_record.py:59`). `cicada_resolve_inbox`'s description gives example
  keys `a`/`b`/`both`/`neither`; real decay questions use `archive`/`keep`. The remote `cicada_resolve_inbox` has no
  `quote` or `answer` by design (R-R22), so a stdio-trained agent's `quote` is dropped silently (see A3).
- **PROPOSAL (contract change).** Freeze names and arguments, and say so in `mcp.md`. For the lean slice, keep old
  names callable but *unlisted* (a dispatch alias table), not listed twice. *Migration:* one deprecation line in each
  aliased reply, an R12-style test over the aliases, and a removal date in TODO.md. Additive now: accept `item_id`
  on `cicada_resolve_inbox`, fix the example keys, and backtick ids in `save_url` (golden re-record and the regex at
  `test_video_save_defects.py:43`).

**A5. Identifier shapes.** Entity ids are Contract (passed back); claim and episode internals are de facto.

- Entity ids are `sanitize_id(name)` (`id_utils.py:21`): lowercased, with only `/\:*?"<>|.` and spaces replaced.
  `&`, `(`, `)`, `'`, `,`, `#`, `%`, `!` and accented letters survive (observed
  `rust-&-systems-programming-a-primer`). Media ids are `media-<title slug>` with a hash suffix only on truncation or
  collision (`media_ingestor.py:2029-2057`). Lookup tolerates legacy stems by case-insensitive and sanitized matches
  (`mcp_tools.py:3630`); `entity_id: "Bob-Example"` resolves.
- Claim ids come in at least eight shapes: Sleep `clm_<date>_<8hex>`, agent `clm_<entity>_<predicate>_<8hex>`,
  progress `clm_<entity>_happened_<8hex>_<date>`, retraction, link reconciliation, seeder, inbox and connections
  import each their own. No consumer parses the inner shape.
- Episode ids are `ep_YYYY-MM-DD_NNN` by the **UTC** day (`episode_ids.py:49`). Everything a reader sees uses the
  local day. One conversation saved at 00:27 local is `ep_2026-10-21_001 · 2026-10-21` in `cicada_ask` and
  `today (2026-10-22)` in `cicada_project`. Readers that take the day from the id: `ask_sources.py:49`,
  `benchmarks/hard_questions.py:95`, `skill_alias_repair.py:77`.
- **PROPOSAL.** Document entity ids as opaque, case-insensitive on lookup, possibly holding `&()',#%` and non-ASCII,
  URL-encoded in paths; changing the slug rule would orphan wikilinks and history. Document claim ids as opaque.
  For episode ids, first confirm intent against the "read on time" rule (owner 2026-10-16): Sleep's dating may be
  wrong around midnight for every owner outside UTC. Then have the three readers use the episode's `timestamp` in the
  person's zone. *Migration:* none for the id itself; the readers change behind it.

**A6. `cicada_recall_detail` returns the raw page.** De facto (golden), else incidental.
The full frontmatter comes back, plumbing included (`section_provenance`, `layout_version`, `decayed_through`,
`learned_on`, `decay_rate`), with the raw claims fence and every internal field (`origin`, `authored_by`,
`source_trust`, `premises`, offsets and hashes). Paging is by line, and a part boundary can fall inside the claims
fence (reasoned, not reproduced). Consumers: the golden `recall_detail`; `benchmarks/system/engine.py:47` parses the
fence.
**PROPOSAL.** Strip the five plumbing keys (`decay_class` stays), render claims through the one wire builder (G118),
never split a fence across parts. *Migration:* re-record the golden and update the benchmark parser in the same PR.

**A7. The handshake.** Contract (R12, at most 1,800 tokens); content partly misleading.
The generic primer is 4,819 characters, inside the cap. R12 holds: all 23 tools it names exist, with every argument.
Misleading: it names `POST /conversations/{id}/resume` and `GET /episodes/{id}/span…`, which no MCP agent can call
(`handshake.py:353,356`). The variant is picked by substring on `clientInfo.name` (`handshake.py:420`), so a desktop
client named with "claude" is told to `claude --resume`. "Bank `<dir name>`" shows the folder name. The Now block is
the stale `_state.md` view. `protocolVersion` is always `2024-11-05`.
**PROPOSAL.** Drop the two routes (resume is the person's step in the app). Match variants on exact names, with a
desktop variant that has no `--resume`. Keep `serverInfo.name`. *Migration:* the handshake tests change with it.

**A8. Teaching material drifted.** De facto: agents follow it.
`SKILL.md` (and its plugin copy) shows a bank layout with `leann/` and `sources/` that no longer exists. It says to
route corrections through the inbox or `cicada_save_episode`, which predates `cicada_edit_page`, so an agent gets
opposite advice from the primer. Its "tools missing → `./install.sh`" predates the plugin door. Hub pages tell an
agent to read `memory/entities/<id>.md` directly (`hub_builder.py:199`), a path a remote or client agent lacks.
**PROPOSAL.** Fix the text. Hub copy changes on the next Sleep rebuild; no migration.

**A9. Untrusted-content marking differs by door.** Incidental, and a safety gap.
The remote runtime fences whole read replies. On stdio only video and skills replies carry `REFERENCE_HEADER`
(`mcp_tools.py:227,1117,1129,5523`); recall, recall_detail, sources, ask and open_hub do not, though they carry
third-party titles and summaries.
**PROPOSAL.** One rule for both doors: the header above any block from a fetched page or provider. Additive text;
the golden changes.

**A10. JSON-RPC conformance.** Incidental.
No `ping` (`-32601`). Malformed JSON gets no answer, so a client waiting on that id hangs (the server stays up).
`tools/call` with no `name` reports a blank tool. Only 3 of 46 stdio tools carry annotations; the remote table
annotates all.
**PROPOSAL.** Answer `ping` with `{}`, a parse error with `-32700` and `id: null`, a missing name with `-32602`, and
annotate stdio reads from the remote `READ_TOOLS`. All additive.

**A11. The legacy observer value in the public schema.** Contract (accepted), unintended in exposure.
`cicada_write_claim`'s `observer.pattern` lists the legacy observer value, the owner's first name
(`mcp/server.py:48-51`). The comment calls it "accepted and unadvertised", but the pattern advertises it. Passing it
writes `observer=owner`, a trust-protected claim.
**PROPOSAL.** Keep accepting it server-side; drop it from the advertised pattern. *Migration:* none; only old local
installs send it. This is CLAUDE.md's "a hardcoded owner name is a bug".

**A12. Small things.** Incidental.
`Skills on this Mac ():` prints an empty list in parentheses. Backlog lists say `by An agent`, capitalised
mid-sentence. A claim citing a missing episode says `quote not found in ep_…` instead of "no such episode".
`resolve_inbox(skip=true)` on a missing id answers `Skipped …`. `cicada_explore_start` with a bad `scope` answers
the trust refusal first. Gate messages name the setting two ways. `get_perspective(history=true)` prints the same
header with or without history.

**A13. Tool-list weight.** Incidental (order), Contract (names).
`tools/list` is 77.6 KB, about 19k tokens by a chars/4 estimate, loaded by every stdio client. The longest
descriptions are `cicada_record_check` (1,525 characters) and `cicada_edit_page` (1,260). 19 of 46 tools are
stdio-only workflows. Where a client caps the tool count (not checked here), array order decides what vanishes.
**PROPOSAL.** Declare the order unstable. The lean slice (A4) is the real fix.

### Hyrum table (Mode A)

| Observable behavior | Class | Consumers found | Action |
|---|---|---|---|
| `cicada-hints` fence, keys, once-per-process `state` | Contract | golden; test_mcp_recall_legs:65; test_cli_reads:15,56; test_cli_unit2:421; test_mcp_handshake:77,87; verify feature file | Keep, document; fix `next_tool` twice and stale `pending` (A1) |
| Recall block layout, raw-float confidence | De facto | golden; benchmarks/retrieval.py:57 | Keep layout; round; note benchmark impact (A1) |
| Refusals as `isError: false` prose; raw exception text | De facto | golden (5 keys); CLI `Reply.code` | `isError` + `structuredContent`; sanitize (A2) |
| Schema not enforced | Contract broken | none relying | Validate at dispatch; fix observer and empty-episode writes now (A3) |
| Tool and argument names | Contract | primer, SKILL.md and copy, librarian skill, cli_map, remote catalog, tool_client, benchmark prompt, user allowlists | Freeze; unlisted aliases with a dated removal (A4) |
| `id`/`item_id`, four names for a page id, `AP1` vs `alpha-project/AP1` | Incidental inconsistency | test regexes only | Accept `item_id`; document (A4) |
| Bare vs backticked ids | De facto | test_video_save_defects:43, test_watch_record:59 | Backticks everywhere (A4) |
| Entity id charset | Contract (passed back) | lookup tolerance, mcp_tools:3642 | Keep; document as opaque (A5) |
| Claim id shapes | Incidental | opaque regexes | Document as opaque (A5) |
| Episode id date is the UTC day | De facto | ask_sources:49, hard_questions:95, skill_alias_repair:77 | Confirm intent; readers use timestamp + zone (A5) |
| recall_detail internals, raw claims fence | De facto (golden) | golden; benchmarks/system/engine.py:47 | Strip; one claim renderer (A6) |
| Primer HTTP routes, substring variant, stale Now | Contract (R12) / incidental | handshake tests, hook note, CLI | Drop routes; exact-name variants (A7) |
| SKILL.md layout and "never edit" advice | De facto (teaching) | agents | Fix the text (A8) |
| Reference header on stdio only for video and skills | Incidental | none | One rule, both doors (A9) |
| No ping, no -32700, sparse annotations | Incidental | none | Add (A10) |
| Legacy observer value in the advertised pattern | Contract (accepted) | old installs | Accept, stop advertising (A11) |

### Inconsistencies an agent trips on today

1. One reply is JSON plus markdown (recall), its sibling plain prose (`cicada_ask`), another raw YAML plus JSONL
   (recall_detail). Only recall and the CLI's `data` are machine-readable.
2. "Nothing there" is an answer (`isError: false`) while the same misuse can be an exception (`isError: true`),
   depending on whether Python raised.
3. The inbox id is `id` in one tool and `item_id` in its sibling; the page id goes under four names.
4. The day of a conversation differs by one between `cicada_ask` (from the id) and `cicada_project` or
   `cicada_timeline` (local) around midnight.
5. `state.pending` and "Sleep queue" say 0 while `cicada_pending` lists work.
6. The primer names two HTTP routes that are not tools, and SKILL.md forbids the page edits the primer teaches.
7. The schema gives `observer` a pattern, and the server records any string.

### Not searched

- Other people's agents and harness configs (Cursor, Codex, Gemini CLI, opencode, any third-party MCP client).
- Installed copies of the plugin and of `SKILL.md` in users' homes, and users' permission allowlists. A
  plugin-registered server may be namespaced differently by Claude Code; worth confirming before the plugin is the
  only door.
- Connector users on claude.ai, ChatGPT and other apps, and those apps' caching of tool lists. The remote listener
  was not started; its subset was read from `api/remote/catalog.py` and `api/remote/tools.py`.
- The Swift app parses no MCP text (none found under `app/CicadaApp/Sources`).
- Any real bank or its logs. The count of legacy-stem pages is known only from a code comment.
- Paging across a claims fence, and ids holding `#` or `%` in API paths. Reasoned about, not reproduced.

### Follow-ups

- Decide the error contract (A2) before the lean-MCP slice, so renamed tools ship with it instead of migrating twice.
- After the rename lands, put the alias removal date in TODO.md, and test it.
- Ask the owner whether episode-id days are meant to be UTC (A5). It is a memory-correctness question first.
- A1, A2, A4, A6 and A9 all re-record `api/tests/fixtures/mcp_stdio_golden.json`. Group them in one themed PR, as
  the fixture's header asks.
- Git identity: with no `user.name`, bank commits fall back to the account's full name and `user@hostname`, so a
  handed-over bank carries both. Outside the MCP surface, on the portability line.
- The verify skill's own defects found during this audit were fixed in PR #397.

---

## Mode B: the Settings panel

**What the panel is.** 15 sidebar sections in three groups. *Cicada:* General, You, Privacy & data, Search & files,
Memory, Sleep. *Customize:* Integrations, Reading the web, Agents, From anywhere, Devices, Skills. *Engines & keys:*
Engines, Plans & keys, Advanced. About 70 controls, counted from `SettingsIndex.staticIDs` plus per-agent,
per-browser and per-site rows. In the verify window (panel 880 pt wide), Agents is 5 screens tall, Integrations 4,
Plans & keys 3, and General, Privacy, Sleep, Reading, Skills and Engines 2 each (counted from the before
screenshots).

**Ground rules.** Controls over the person's data, privacy, consent and trust are never cut. Rulings that name a
control bind: 4/4b/4c (*Scheduled runs may use my plan*), 15 (*Keep going on extra usage*, opt-in), 31 (plan-first
engines, Auto by default), 12 (no prices in Settings), G182 (*Install updates automatically*), the three network
gates, G176 (weather), G135 (connector), G198 (page editors), G179 (Messages ticks), G191 (bookmark removal), and the
skill-install consent.

### Settings table

Ranked by impact, biggest simplification first. "Who uses it" is a judgment from the control's job. No usage numbers
exist, and the telemetry ledger was not read.

| # | Setting | Who uses it | Verdict | Default or inferred value | Migration note |
|---|---|---|---|---|---|
| B1 | The sidebar: 15 sections | Everyone, every visit | **Merge** (proposal) to about 10. Memory joins Search & files; Plans & keys joins Engines; From anywhere joins Devices | Unchanged | Changes `cicada.settingsSection` raw values, `SettingsIndex` sections, `router.openSettings(.remote / .plansAndKeys / .memory)` deep links and docs. `SettingsSection.restored(from:)` already falls back for a retired raw value; map each to its new home, as `legacyAgentsMode` did. Needs the owner's word |
| B2 | Sleep → *The scenery* | Rare, once. Decoration | **Move** (done: after Engine). Further proposal: move it to the study room on the Sleep page | Local weather | Order only. Its Source row carries the G176 weather consent, so it stays visible, never folded |
| B3 | Sleep → *Mascot* | Nobody yet: one choice | **Infer** (proposal): hide the card until a second mascot exists | `bookworm` | `cicada.mascot` keeps its value. `MascotSettingsTests` pins search landing on this row, so hiding it changes that contract |
| B4 | General → *Where your memory lives* | Someone setting up a home server (G181) | **Move to Devices** (done) | This Mac | Same view and files (`api_base.next`, `device_token`), same `memoryHome` id. Search entry, token sheet, api.md, headless.md and a `runtime_layout.py` comment now name Devices |
| B5 | Agents (install, grid, walkthrough, auto recall, page editors, links) | Once per agent | **Move to advanced** (proposal): fold a connected agent's walkthrough to one line; connected state first | Unchanged | `ConnectView` has its own probes, so its own change. The install card already hides in a release build (G182). The G198 trust list stays open |
| B6 | Engines → *Ask* (header Ask over a row Ask, no control) | Read-only | **Merge** into the Engine card (done) | Ask follows the engine | DR-37, DR-38. Row id `engineAsk` unchanged. `Copy.askGroup` deleted, no other caller |
| B7 | Sleep → *Runs* (header Runs over a row Runs) | Everyone who schedules | **Keep**; header **cut** (done) | Manual | DR-38. `sleepRuns`, the route and its values unchanged. `Copy.runsGroup` deleted |
| B8 | Sleep → *Engine* (header Engine over a row Engine) | Everyone who schedules | **Keep**; proposal: drop the header, as B7 did | Whatever Engines resolves | DR-38. Found in this run's after shots. It is the one link to Engines and what the plan switch acts on (ruling 4), so the row stays |
| B9 | Memory → *Fetch link previews* (manual) | Rare. Maintenance | **Infer** (proposal): Sleep's tail runs it behind the connector gate | Not run unless clicked | UX principle 1. It changes backend fetch timing, so it needs its own backlog row and the ToS rail's limits |
| B10 | Plans & keys → seven key cards open, each with its path | Few. Ruling 31 makes plans the default | **Move to advanced** (proposal): fold unconnected key cards under "Use an API key instead" | Unchanged | Credentials are trust; one click away, connected ones stay open |
| B-paths | Privacy → API keys, Advanced → API token, Devices → token help | Anyone who follows the path | **Fix** (proposal): name the resolved `CICADA_HOME`, as Plans & keys already does | n/a | Observed: on a scratch home, Privacy said `~/.cicada/secrets.env` while Plans & keys named the real file. Static strings in `Copy+Settings.swift:285,340` and `Copy+Devices.swift:23,25,97`. Agents read these off the screen, so the copy and the token sheet change together |
| B-env | Engines banner "…in Cicada's environment (api/.env) sets the engine" | Anyone with an engine pinned | **Fix** (proposal): say where the value came from, or name only the variable | n/a | `Copy+HomeSleep.swift:15` always says `api/.env`. In the verify run the pin came from the process environment, and no `api/.env` existed |
| B-model | Search & files → "set up for the larger version on another Mac" | A new memory | **Fix** (proposal) | n/a | Shown on a fresh scratch bank that was never on another Mac. `EmbeddingsWire.swift:335-337` infers "built elsewhere" from `needsDownload && !available && needsToken` |
| B11 | General → *Command-line tool* | Agent users with a shell (G180) | **Move** (proposal) to Agents | Not installed | Writes `~/.local/bin/cicada` only on click. mcp.md names General, so a move updates it |
| B12 | General → *Setup* and *Getting to know Cicada* | New people, once | **Merge** (proposal) into one "Getting started" group | Unchanged | Two cards, one job |
| B13 | Memory → *How things fade* | Shows a choice only after decay answers | **Keep**; proposal: hide the explainer while there is no suggestion | Unchanged | Suggestions apply only on Apply (G147) |
| B14 | General → *Text size* | People who need larger text | **Keep** | 100 % | Accessibility; its doc comment says removal needs the owner's word |
| B15 | General → Appearance, Open at login, Show in menu bar, Keep memory working | Everyone, once | **Keep** | Dark / off / on / offered | `cicada.colorScheme`, `cicada.loginItem.requested`, `cicada.menuBar.visible`, the LaunchAgent |
| B16 | General → Version, *Install updates automatically* | Testers; update consent | **Keep** | On (G182) | Consent, stays visible |
| B17 | Sleep → *Scheduled runs may use my plan* | Everyone who schedules | **Keep** | On (ruling 4c) | Binding |
| B18 | Engines → cards, model, *Keep going on extra usage*, *Use my Claude plan when I start a cycle* | Everyone, once | **Keep** | Auto (31); extra usage off (15) | Binding |
| B19 | Privacy & data → location, banks, export, delete, gates, usage ledger, Remove all keys, access from other apps, agent conversations | Rare; the person's right | **Keep** | As set | Data, privacy, trust. Gates are read-only displays of the backend's environment |
| B20 | You → name, handle, email, owner page | Everyone, once | **Keep** | As set | The person's own data (G117) |
| B21 | Search & files → folders, understanding, Advanced | Once | **Keep**; Advanced already folded (DR-39) | Words only until the click | Each download is the person's click |
| B22 | Integrations → exports, browsers, tab groups, YouTube history, Calendar, Contacts, Messages, Ask why I saved it | Once per source | **Keep** | Off until turned on | Every row is a read consent (G179, G191) |
| B23 | Reading the web → the switch, how it reads, how it watches, sites, never-explore | Few | **Keep**; proposal: fold "how it reads / watches" while the switch is off | Off | Consent (G166, ruling 25) |
| B24 | From anywhere | Few | **Keep** | Off (G135) | Trust |
| B25 | Devices → this app, your devices, Add, Revoke | Few | **Keep** | As set | Trust (ruling 28) |
| B26 | Skills | Few | **Keep** | As set | Install only on consent, pinned |
| B27 | Advanced | Debugging | **Keep**; already the advanced section | Read-only | Names env switches, never values (R-O22) |

### Proposed layout

About ten sections in three groups. *Cicada:* General (Look, Startup, When Cicada is closed, Getting started, Version
and updates), You, Privacy & data, Search & memory (folders, understanding, how things fade, link previews; search
version and rebuild folded), Sleep (Runs, Scheduled runs, Engine, then the study room). *Customize:* Integrations,
Reading the web, Agents (connected agents first, each walkthrough folded once connected, the trust list open, the
command-line tool), Devices & access (where your memory lives, this app, your devices, from anywhere), Skills.
*Engines & keys:* Engines (choice, model, plan switches, Ask, then sign-ins with unconnected keys folded), Advanced.

Behind a fold: a connected agent's walkthrough, the search version, unconnected API key cards, and Reading's method
pickers while its switch is off.

### Kept on purpose

Every data, privacy, consent and trust control, visible and one click from the sidebar: *Scheduled runs may use my
plan* (ruling 4), *Keep going on extra usage* (ruling 15), the engine choice (ruling 31), the network gates and the
usage ledger, the weather disclosure (G176), the connector (G135), devices and tokens (ruling 28), page editors
(G198), every browser, Calendar, Contacts and Messages read consent (G179), bookmark removal (G191, asked in words
when it happens), *Install updates automatically* (G182), skill installs, bank export and delete, *Remove all keys*,
and You.

### What PR #398 changed (presentation only)

1. *Where your memory lives* moved from General to the top of Devices (B4). DR-38: one decision in one place.
2. Sleep reads Runs, Scheduled runs, Engine, then *The scenery* and *Mascot* (B2). The Runs card lost its repeated
   header (B7, DR-38).
3. Engines' *Ask* line joined the Engine card (B6, DR-37, DR-38).

No stored key, default, route or backend read changed. `cicada.settingsSection` raw values are untouched, so a saved
section still restores.

### Hyrum check: rows moved between pages

| Observable behavior | Class | Consumers found | Action |
|---|---|---|---|
| `memoryHome`'s Settings section (General → Devices) | Contract (search landing) | `SettingsIndex.staticEntries`, `SettingsRowLintTests`, the token sheet's copy, api.md, headless.md, a `runtime_layout.py` comment, a `HeadlessAppTests` MARK | All updated in #398. No deep link opened General at that row. Verified: searching "server" lands on Devices › Memory on |
| Files the server choice writes (`api_base.next`, `api_base`, `device_token`) | Contract (hooks, MCP, CLI read them) | `ServerConnection`, hooks, CLI | Unchanged. Verified: picking *A server* without *Check and use* wrote neither file |
| Sleep's card order and the Runs header | Incidental | `SettingsSleepView` only | Changed |
| Engines' Ask card header (`Copy.askGroup`) | Incidental | none outside `EnginesView` | Removed. Verified: searching "ask" lands on Engines › Ask |
| `Copy.runsGroup` | Incidental | none outside `SettingsSleepView` | Removed |

Not searched: other people's scripts, notes or agent instructions that quote "Settings → General → A server". An
installed older app keeps its own copy until it updates.

### Migration

- #398: none. Every value is stored where it was, under the same key, with the same default.
- B1 (merging sections): map each retired raw value onto its new section in `SettingsSection.restored`, the R-O11
  pattern for `cicada.agentsMode`, and keep the old search keywords on the merged entries.
- B3 (hiding Mascot): `cicada.mascot` keeps working, and the card returns when `MascotRegistry.all` grows.
- B9 (link previews by Sleep): it changes when the backend fetches, so it needs its own backlog row, the connector
  gate and the ToS rail's limits.
- B-paths: the copy, the token sheet and any doc that quotes `~/.cicada/device_token` change in one PR.

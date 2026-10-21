# Settings audit (2026-10-22)

The owner finds the Settings panel overwhelming. This audit lists every control the panel shows, asks of each who
changes it and whether a default or an inference would serve, and gives a verdict. It follows the Hyrum's Law skill's
Mode B (settings audit), with a Mode A check for every row this PR moved.

**What was looked at.** Every control's source, read for its stored key or route, and every pane of the app built
from `dev` at `0fa3f239` (before this change), driven as a separate verify copy on a scratch backend and bank. That
copy turned out to share the app's on-disk caches with an installed Cicada, so it was stopped and its screenshots
are not published. Before and after screenshots are to be retaken once the verify copy is fully separated.

**What the panel is today.** 15 sidebar sections in three groups (Cicada: General, You, Privacy & data, Search & files,
Memory, Sleep. Customize: Integrations, Reading the web, Agents, From anywhere, Devices, Skills. Engines & keys:
Engines, Plans & keys, Advanced). Measured at the default panel size (880 × 620 pt), Agents is 8 screens tall,
Integrations 4, Reading the web, Plans & keys and General 2 to 3. About 70 controls, counted from the `SettingsRow`
ids in `SettingsIndex.staticIDs` plus the per-agent, per-browser and per-site rows.

**Ground rules.** Controls over the person's data, privacy, consent and trust are never cut. The rails and rulings
that name a Settings control are binding: ruling 4/4b/4c (*Scheduled runs may use my plan*), ruling 15 (*Keep going
on extra usage*, opt-in), ruling 31 (plan-first engines, Auto by default), ruling 12 (no prices in Settings), G182
(*Install updates automatically*), the three network gates, the G176 weather gate, the G135 connector, the G198 page
editors trust list, the G179 Messages ticks, the G191 bookmark-removal consent, and the skill-install consent.

## Settings audit: Cicada's Settings panel

Ranked by impact, the biggest simplification first. "Who uses it" is a judgment from the control's job, not a
measurement. No usage numbers exist, and the telemetry ledger is not read for this.

| # | Setting | Who uses it | Verdict | Default or inferred value | Migration note |
|---|---|---|---|---|---|
| 1 | The sidebar itself: 15 sections | Everyone, on every visit | **Merge** (proposal) | About 10 sections. Memory joins Search & files. Plans & keys joins Engines. From anywhere joins Devices | Changes `cicada.settingsSection` raw values, `SettingsIndex` sections, `router.openSettings(.remote / .plansAndKeys / .memory)` deep links and docs. `SettingsSection.restored(from:)` already falls back for a retired raw value. Map each retired one to its new home, as `legacyAgentsMode` did. Needs the owner's word |
| 2 | Sleep → *The scenery* (Source, Time, Weather, Preview) | Rare, and once. It is decoration | **Move** (done: now after Engine). Further proposal: move it to the study room on the Sleep page | Local weather, unchanged | Done in this PR: order only. The Source row carries the G176 weather consent (what is sent, and to whom), so it stays visible and is never folded away |
| 3 | Sleep → *Mascot* | Nobody yet. It offers one choice (Bookworm) | **Infer** (proposal): hide the card until a second mascot exists | `bookworm`, unchanged | `cicada.mascot` keeps its value. `MascotSettingsTests` pins that searching "mascot" lands on this row, so hiding it means changing that search contract. Left as a proposal |
| 4 | General → *Where your memory lives* (This Mac / A server, address, device token) | Only someone setting up a home server (G181) | **Move to Devices** (done) | This Mac, unchanged | Same view (`MemoryHomeSetting`), same files (`$CICADA_HOME/api_base.next`, `device_token`). The search entry `memoryHome` now names Devices. The Devices page's own subtitle already said "where it lives". The token sheet's "Settings → General → A server" now reads Devices, as do api.md, headless.md and `runtime_layout.py`'s comment |
| 5 | Agents page (8 screens: one-time install, agent grid + connect walkthrough, auto recall, page editors, cloud and reading links) | Once per agent, then rarely | **Move to advanced** (proposal): once an agent is connected, fold its walkthrough to one line, and show the grid's connected state first | Unchanged | Presentation only, but `ConnectView` is 485 lines with its own probes, so it gets its own change. The one-time install card already hides in a release build (G182). The page editors trust list (G198) stays open and visible |
| 6 | Engines → *Ask* (a card titled Ask under a header Ask, one line, no control) | Read-only | **Merge** into the Engine card (done) | Ask follows the engine | DR-37 (a single line never gets a card) and DR-38 (no repeated label). Row id `engineAsk` unchanged. `Copy.askGroup` deleted, no other caller |
| 7 | Sleep → *Runs* (a header "Runs" over a row titled "Runs") | Everyone who schedules Sleep | **Keep** the control. The duplicate header is **cut** (done) | Manual, unchanged | DR-38. Row id `sleepRuns`, the schedule route and its values are unchanged. `Copy.runsGroup` deleted, no other caller |
| 8 | Memory → *Fetch link previews* (a manual "Fetch now") | Rare. It is maintenance | **Infer** (proposal): let Sleep's tail run it, behind the connector gate | Not run unless clicked, unchanged | UX principle 1, "never require memory maintenance". Moving it into Sleep changes backend behaviour and network timing, so it stays a proposal |
| 9 | Plans & keys → OpenAI and Anthropic API key cards, open by default, each with its file path | Few. Ruling 31 makes plans the default | **Move to advanced** (proposal): fold unconnected key cards under "Use an API key instead" | Unchanged | Credentials are a trust control, so they stay one click away and the connected ones stay open |
| 10 | General → *Command-line tool* | Agent users with a shell (G180) | **Move** (proposal) to Agents, beside the other agent wiring | Not installed, unchanged | Writes `~/.local/bin/cicada` only on click. mcp.md names General as its home, so a move updates that doc |
| 11 | Sleep → *Engine* (read-only preview of both engine lines, with a link to Engines) | Everyone who schedules | **Keep** | Whatever Engines resolves | It repeats Engines' answer, but it is what the plan switch beside it acts on (ruling 4). Its link is the one way between the two pages |
| 12 | General → *Setup* (Run setup again, Show checklist) and *Getting to know Cicada* (Guided tour, Demo memory) | New people, once | **Merge** (proposal): one "Getting started" group | Unchanged | Two cards with one job. Low impact |
| 13 | Memory → *How things fade* (an explainer until a suggestion exists) | Shows a choice only after decay answers | **Keep**. Proposal: hide the explainer while there is no suggestion | Multipliers unchanged | Suggestions apply only on Apply (G147) |
| 14 | General → *Text size* | People who need larger text | **Keep** | 100 % | Accessibility. Its doc comment says removing it needs the owner's word |
| 15 | General → *Appearance*, *Open at login*, *Show in menu bar*, *Keep memory working* | Everyone, once | **Keep** | Dark / off / on / offered | `cicada.colorScheme`, `cicada.loginItem.requested`, `cicada.menuBar.visible`, the LaunchAgent |
| 16 | General → *Version* and *Install updates automatically* | Testers; the update consent | **Keep** | On (G182) | The update switch is consent and stays visible |
| 17 | Sleep → *Scheduled runs may use my plan* | Everyone who schedules | **Keep** | On (ruling 4c) | Binding ruling 4/4b/4c |
| 18 | Engines → the engine cards, model, *Keep going on extra usage*, *Use my Claude plan when I start a cycle* | Everyone, once | **Keep** | Auto (ruling 31). Extra usage off (ruling 15) | Binding rulings |
| 19 | Privacy & data → memory location, banks, export, delete, the three network gates, usage ledger, *Remove all keys*, access from other apps, agent conversations | Rare, but it is the person's right | **Keep** | As set | Data, privacy and trust. The gates are read-only displays of the backend's environment |
| 20 | You → name, handle, email, owner page | Everyone, once | **Keep** | As set | The person's own data (G117) |
| 21 | Search & files → folders, *Understand what you mean*, *Understand images*, Advanced (search version, rebuild) | Once | **Keep**. Advanced is already folded (DR-39) | Words-only until the click | Each download is the person's click (network rail) |
| 22 | Integrations → chat exports, browsers, tab groups, YouTube history, Calendar, Contacts, Messages, *Ask why I saved it* | Once per source | **Keep** | Off until turned on | Every row is a read consent (the app reads `~/Library` only after the person turns a source on; G179 ticks; G191) |
| 23 | Reading the web → *Let an agent read pages*, how it reads, how it watches, YouTube lists, sites, never-explore | Few | **Keep**. Proposal: fold "how it reads / watches" while the switch is off | Off | Consent (G166, ruling 25) |
| 24 | From anywhere → the connector switch, reach, connectors, sign-in requests | Few | **Keep** | Off (G135) | Trust |
| 25 | Devices → this app's connection, devices, Add, Revoke | Few | **Keep** | As set | Trust (ruling 28) |
| 26 | Skills → Cicada's own skills, installed skills, install | Few | **Keep** | As set | Install only on consent, pinned |
| 27 | Advanced → backend status, MCP command, API token location, environment overrides, settings file | Debugging | **Keep**. It is already the advanced section | Read-only | Names env switches, never values (R-O22) |

**Proposed layout.** About ten sections in three groups. *Cicada:* General (Look, Startup, When Cicada is closed,
Getting started, Version and updates), You, Privacy & data, Search & memory (folders, understanding, how things fade,
link previews; search version and rebuild folded), Sleep (Runs, Scheduled runs, Engine, then the study room).
*Customize:* Integrations, Reading the web, Agents (connected agents first, each walkthrough folded once connected,
the trust list open, the command-line tool), Devices & access (where your memory lives, this app, your devices, from
anywhere), Skills. *Engines & keys:* Engines (choice, model, plan switches, Ask, then sign-ins with unconnected API
keys folded), Advanced. What moves behind a fold: the per-agent connect walkthrough once connected, the search
version, unconnected API key cards, and Reading's method pickers while its switch is off.

**Kept on purpose.** Every data, privacy, consent and trust control, visible and one click from the sidebar:
*Scheduled runs may use my plan* (ruling 4), *Keep going on extra usage* (ruling 15), the engine choice (ruling 31),
the network gates and usage ledger, the weather disclosure (G176), the connector (G135), devices and tokens (ruling
28), page editors (G198), every browser, Calendar, Contacts and Messages read consent (G179), bookmark removal (G191,
asked in words at the moment it happens), *Install updates automatically* (G182), skill installs, bank export and
delete, *Remove all keys*, and You.

## What this PR changed (presentation only)

1. *Where your memory lives* moved from General to the top of Devices. Same view, same files, same `memoryHome` row
   id. Its search entry now names Devices. The token sheet's instruction, api.md, headless.md and one backend comment
   name Devices. DR-38 (one decision in one place).
2. Sleep reads Runs, Scheduled runs, Engine, then the study room's *The scenery* and *Mascot*. What Sleep does comes
   before how its room looks. The Runs card lost the "Runs" header that repeated its one row's title (DR-38).
3. Engines' *Ask* line joined the Engine card instead of filling a card of its own under a repeated header (DR-37,
   DR-38).

No stored key, default, route or backend read changed. `cicada.settingsSection` raw values are untouched, so a saved
section still restores.

## Hyrum check: rows moved between pages

| Observable behavior | Class | Consumers found | Action |
|---|---|---|---|
| `memoryHome`'s Settings section (General → Devices) | Contract (search landing) | `SettingsIndex.staticEntries`, `SettingsRowLintTests` (row on a page), the token sheet's copy, api.md, headless.md, `api/services/runtime_layout.py` comment, `HeadlessAppTests` MARK | All updated in this PR. No `openSettings(.general, row: .memoryHome)` deep link exists |
| The files the server choice writes (`api_base.next`, `api_base`, `device_token`) | Contract (hooks, MCP, CLI read them) | `ServerConnection`, hooks, CLI | Unchanged |
| The Sleep page's card order and the Runs header | Incidental | `SettingsSleepView` only. No test pins the order | Changed |
| Engines' Ask card header (`Copy.askGroup`) | Incidental | No reader outside `EnginesView` | Removed |
| `Copy.runsGroup` | Incidental | No reader outside `SettingsSleepView` | Removed |

Not searched: other people's scripts or agent instructions that quote "Settings → General → A server". The repo,
its docs, skills and plugin were searched. An installed older app keeps its own copy until it updates.

## Migration notes

- This PR: none needed. Every value is stored where it was, under the same key, with the same default.
- Proposal 1 (merging sections): map each retired raw value onto its new section in `SettingsSection.restored`, the
  pattern R-O11 used for `cicada.agentsMode`, and keep the old search keywords on the merged entries.
- Proposal 3 (hiding Mascot): `cicada.mascot` keeps working, and the card returns when `MascotRegistry.all` grows.
- Proposal 8 (link previews by Sleep): it changes when the backend fetches, so it needs its own row in the backlog,
  the connector gate, and the ToS rail's limits.

---
name: verify-cicada
description: Run Cicada end to end on scratch state, isolated from the person's live install, and prove a behavior across its surfaces. A backend on a scratch HOME, CICADA_HOME, bank and port; the MCP server over stdio; a Sleep cycle on the Claude plan with haiku; the `cicada` CLI; and a second, separately identified copy of the macOS app on a scratch home, driven with macos-harness. Use it to verify a change in the real app, API, MCP or CLI (this checkout or another with `--checkout`), to reproduce a bug before fixing it, or to capture screenshots and transcripts as evidence.
---

# verify-cicada

Every helper lives in `bin/` beside this file. `cv` is the dispatcher. Each run has one directory holding scratch
state and a `run.json` record (ports, pids, env), and one evidence directory that survives cleanup.

Shell state does not persist between an agent's Bash calls. Start every call with the absolute `cv` path and the run:

```sh
CV="$(git rev-parse --show-toplevel)/.claude/skills/verify-cicada/bin/cv"
$CV launch --run-id my-check --evidence ~/cicada-verify-evidence/my-check      # prints the run dir
```

```sh
CV="$(git rev-parse --show-toplevel)/.claude/skills/verify-cicada/bin/cv"
export CICADA_VERIFY_RUN=<the run dir launch printed>       # or --run <dir> on the verb
$CV doctor
```

Every verb but `launch`, `residue`, `deny` and `selftest` refuses without the run, and refuses a directory `launch`
did not create under the run root (`$CICADA_VERIFY_ROOT`, else `$TMPDIR/cicada-verify`). Run ids are letters, digits,
`.` and `-`, so the app's bundle id is the run id itself. Evidence defaults to `$CICADA_VERIFY_EVIDENCE`, else
`~/cicada-verify-evidence/<id>`, never inside the run dir; every `--save` and evidence name stays inside it.

## What isolation means here

Never drive, query, POST to or kill the person's own install: their app (`~/Applications/Cicada.app`, bundle id
`com.rorosaga.cicada`), their backend on 127.0.0.1:8000, their `~/.cicada`, `~/cicada/memory` or a checkout's
`memory/`, their `~/Library/Application Support/Cicada`, or anything `com.cicada.*` in launchd. Never call the
`mcp__cicada__*` tools of your own session: they are wired to the person's bank. `cv` refuses ports 8000 and 8765 and
kills only pids it recorded whose command line still carries the marker it recorded.

| Surface | How a run is kept apart | What still touches the real account |
|---|---|---|
| Backend | `HOME`, `CICADA_HOME`, `CICADA_MEMORY_PATH`, `CICADA_PORT`, `CICADA_REMOTE_PORT` all scratch; `LITELLM_MODE=PRODUCTION` so no `.env` is walked into; commits as `Verify Run <verify@example.invalid>`; the owner named `Verify Person` (`--no-owner` skips that); a clean env (only `PATH`, `TMPDIR`, locale and `USER` pass through; never `CLAUDE_CODE_OAUTH_TOKEN`, see below); refuses a checkout with an `api/.env` | nothing |
| Network | `CICADA_ALLOW_CONNECTOR_FETCH=off`, `CICADA_ALLOW_LOGO_FETCH=off`, `CICADA_ALLOW_FEED_FETCH=off`, `HF_HUB_OFFLINE=1` | the Sleep engine's model calls and its web lookup (the plan's own search, ruling 27); `--search-model`'s pinned download; and what the person's own act fetches, which no gate stops: `POST /sources/save`, `cicada_save_url`, `cicada_record_watch` on an unsaved link (fetches the page's title through `net_guard`). Use `https://example.com/...` links only |
| Sleep engine | `CICADA_LLM_MODE=agent`, every model `haiku`, `CICADA_CLAUDE_CLI=bin/plan-claude` | `plan-claude` gives the `claude` child the real HOME so it finds the plan sign-in. It runs only `auth status [--json]` (answered with the email masked to `verify@example.invalid`) and the exact argv `api/services/agent_engine.py` builds: `-p` first, the pinned flags with their values (`--tools ""` or `WebSearch` plus its `--allowedTools`, `--setting-sources ""`), `--model haiku`, and only `--system-prompt=`, `--effort`, `--json-schema` after. It strips every key the engine strips and refuses `CICADA_CAPTURE` not `off`. `cv selftest` proves both against the engine module |
| MCP server | spawned per call with the run's env; session `verify-<run id>`, harness `verify` | nothing |
| CLI | `python -P -m api.cli` with the run's env and the harness marker set, so person-only commands refuse as from any agent's shell | nothing |
| App | a copy in the run dir stamped `com.rorosaga.cicada.verify.<run id>` / "Cicada Verify", started with `CFFIXED_USER_HOME=<run>/home`. Observed 2026-10-22: Application Support/Cicada (its snapshot cache; pictures, logos and folder state use the same lookup), Caches, HTTPStorages and WebKit all land under the scratch home, and `lsof` showed nothing open under the real `~/Library`. `cv app launch` refuses, and stops the app, if it opens anything under the real `~/.cicada`, `~/cicada`, Application Support/Cicada or Application Support/com.rorosaga.cicada*, or its cache never appears in the scratch home | `~/Library/Preferences/<run's id>.plist` (cfprefsd ignores the redirect), removed by `cv cleanup`. The login keychain, Contacts, Calendar, Messages and `NSFullUserName` are the real account's. Treat every Connect, Sign in and Install button as writing the real account (see Gotchas) |

Observed 2026-10-22: a scratch `HOME` (or `CLAUDE_CONFIG_DIR`) makes `claude auth status` report `loggedIn: false`,
which is why `plan-claude` exists. The backend's documented headless path, `CLAUDE_CODE_OAUTH_TOKEN` from
`claude setup-token`, also works without the real HOME, but minting that token is the person's step, never an agent's.
When the caller's shell has `CLAUDE_CODE_OAUTH_TOKEN` (a headless Linux run), `cv` takes it out of its own environment
as it starts, so none of its children (the backend, the MCP server, the CLI, git, the app build) inherits it. Once
`run.json` exists, `launch` writes the value into a 0600 file in the run dir (`secrets/claude-oauth-token`), and the
run's env carries only that file's path (`CICADA_VERIFY_PLAN_TOKEN_FILE`). `plan-claude` reads it into the engine's
`claude` child alone, the way it gives that child the real HOME on a Mac. `cleanup` deletes the file and masks any
copy of the value under the evidence dir and the run's `logs/` (which `--keep-state` keeps). `cv selftest` proves each
step against a stand-in token, including a `launch` that dies before `run.json`.

## Launch

```sh
$CV launch [--run-id ID] [--checkout PATH] [--evidence DIR] [--port N] [--search-model] [--no-owner] [--timeout 120]
```

Starts `python -m uvicorn api.main:app` from the checkout (default: the one holding the current directory; pass
`--checkout` to verify another worktree's branch with this skill) on a free port, with that checkout's venv (else its
main checkout's, else `CICADA_VERIFY_PYTHON`). Fails early when `claude` is not on PATH. An empty dir bootstraps
itself: the backend scaffolds the bank, makes its first commit and writes `api_token` into the scratch `CICADA_HOME`.
`launch` waits until the token-authed `/healthz` names the scratch root and the owner page, `/status` answers 200 and
the bank has a commit, then names the owner. It records the checkout's HEAD and a hash of its status, diff and
untracked files, and writes `launch/healthz.json`. Any failure after the backend started stops it.

`--search-model` fetches the pinned on-device search model (`scripts/fetch-embedding-model.sh`, ~130 MB,
sha256-checked) into the run, with a download cache under the run root, so meaning search works. Without it, recall
answers from words only and Sleep ends with the warning `Search by meaning wasn't updated`; `cv sleep` accepts that
one warning on a run without the model.

## Doctor

```sh
$CV doctor
```

Read only. Checks that the backend pid is alive and ours, owns the port, runs from the run's checkout, and admits the
token; that `/healthz` names the scratch root and a bank inside the run, at the checkout's `VERSION`; that the
checkout's HEAD and files are what launch recorded; that the plan answers through `plan-claude`; and, once the app is
built, that its bundle id is this run's, it was stamped from the run's checkout at the current HEAD and files, its pid
is ours and it holds nothing open under the person's real Cicada state (the four roots `app launch` checks). Exit 1 on any `FAIL`. Run it first
whenever anything looks off, and again after editing the checkout (then rebuild the app).

## Drive

```sh
$CV api GET /graph [--save api/graph.json]            # any route (starting with /), with the run's token
$CV capture --session verify-s1 --turn t1 --user "..." --assistant "..."   # POST /capture/turn, harness cursor
$CV sleep [--timeout 900]                              # trigger, wait, then check it read everything
$CV mcp init | list | schema cicada_recall | call cicada_recall '{"query": "alpha-project"}' [--timeout 120]
$CV cli [--save cli/recall.json] -- recall alpha-project   # the `cicada` command, in-process, on this run
$CV bank log | ls | cat entities/alpha-project.md      # read the scratch bank
```

- `capture` is the real capture door Cursor and Gemini CLI hooks use. Session ids are 8 to 128 characters of letters,
  digits, `.`, `_`, `-`; a shorter one is answered `refused` / `bad_session_id` and `capture` exits 1. One session id
  is one episode (G104); a second `--turn` on the same session extends it. Promotion needs two conversations, so a
  journey that wants a page captures two sessions that both name the thing.
- `sleep` uses the Claude plan at haiku; two short episodes took about 25 s on 2026-10-22. It exits 1 unless the run
  ends idle with no error, pause or cancel, every waiting episode processed, none requeued, nothing left unprocessed,
  and no warning but the expected one. Its commit carries `Cicada-Author: claude-haiku-*`, `Cicada-Engine: claude-cli`
  and one `Cicada-Session:` per conversation.
- `mcp` spawns `mcp/server.py` per call and speaks newline JSON-RPC: `initialize`, `notifications/initialized`, then
  `tools/list` or `tools/call`. The exchange goes to `evidence/mcp/<time>-<tool>.jsonl`, the server's stderr beside it.
  Each answer has `--timeout` seconds. `schema <tool>` prints a tool's input schema; read it before a first call.
- `cli` runs `python -P -m api.cli` with the run's env as an agent's shell; output goes to `evidence/cli/`. Commands
  that act as the person (`sleep start`, for example) answer `person_only`; use `cv sleep` or `cv api` for those.

### The app

```sh
$CV app build          # ./bundle.sh in the run's checkout, copy into the run, restamp, unregister bundle.sh's output
$CV app launch         # needs the run's backend up; waits for a window and the scratch-home cache, checks lsof
$CV app containment    # lsof sample, the scratch home's Application Support, real-folder changes since launch
$CV app shot home      # screencapture -x -o -l <our window id> -> evidence/app/home.png
$CV app click 300 200  # a real click at window-relative points; refused outside the window, under another window,
                       # or on an element whose accessibility text reads like a forbidden button (Gotchas)
$CV app windows        # our pid's windows as JSON
```

The person's app may be running with the same executable name. Everything here goes by our pid and our copy's path,
never by name. The app finds its backend through `CICADA_PORT` and its token through `CICADA_HOME`; it spawns no
backend because ours already holds the port. A run whose bank has had no Sleep may open on the welcome screen
(`Hello, Verify.`); click `button Set up later`, never `Get started`.

Drive it with macos-harness through the functions in `bin/harness.sh`. Source the file in the same Bash call as the
`vh` and `vclick` calls: macos-harness keeps its element numbers per calling shell.

```sh
CV="$(git rev-parse --show-toplevel)/.claude/skills/verify-cicada/bin/cv"; export CICADA_VERIFY_RUN=<run dir>
. "$(dirname "$CV")/harness.sh"
vclick 'button.*Description: Projects,'           # read, find the first matching line, click its number
vh get_app_state --disableDiff | grep -i alpha
$CV app shot projects
```

`vh` fails unless this run's app is running, so the harness never starts a copy outside the run. `vclick` refuses a
line that reads Connect, Disconnect, Sign in, Sign out, Install, Set up (not `Set up later`), Turn on, Turn off, Get
started, at login, Update, Restart Cicada, Open in Cursor, Save chats on their own, Remove bookmark, Allow Contacts or
Allow… (`cv deny`, case-insensitive; the full list is `FORBIDDEN_RE` in `bin/cv`). Sidebar pages are
buttons with `Description: <Page>,` (Home, Graph, Clusters, Skills, Sleep, Inbox, Sources, Projects, Settings).
Numbers change with every page; `vclick` reads fresh each time. When an element ignores an AX press, use the
screenshot and `$CV app click X Y` (points from the top-left of our window; a `cv app shot` PNG on a Retina screen is
2 px per point, so halve its pixel coordinates). Graph nodes live in a web view and are clicked this way.

## Evidence

Everything a verb writes lands under the evidence dir: `launch/`, `doctor/`, `capture/`, `sleep/` (status,
`bank-git-log.txt` with trailers, `entities.txt`), `mcp/` (JSON-RPC transcripts and stderr), `cli/` (argv, exit,
stdout, stderr), `api/` (with `--save`) and `app/` (PNG by window id, `containment/`). `cleanup` adds
`state-at-cleanup/` (run.json, logs, the bank's full git log).

A proof follows these standards:

- Exercise the real user path: `/capture/turn`, `/sleep/trigger`, the MCP stdio server, the CLI, the app's own
  controls. Never call a service function, write into `entities/`, or flip `processed:` by hand.
- Capture the action and the resulting state: the request and its answer, then a second, read-only view of the
  stored result (the bank's git log, a page file, `cicada_recall`, the app's screen).
- Verify side effects alongside what is visible: the episode file, the Sleep commit and its trailers, the page.
- The only stand-in is the model: the plan runs for real at haiku, so wording differs between runs. Assert on page
  ids, commit trailers and named facts, not on exact prose.
- Open every screenshot before you keep it. It must show only the run's synthetic data; delete one that shows
  anything of the person's and say so.

## Cleanup

```sh
$CV cleanup [--keep-state]
```

Refuses a directory without launch's marker. Snapshots run.json, logs and the bank's git log into
`evidence/state-at-cleanup/`, stops the app's and then the backend's process group, refuses to go on if either is
still ours and alive, unregisters the copy from LaunchServices, removes the run's `~/Library/Preferences` file, and
deletes the run dir unless `--keep-state`. Evidence is never removed. After a failed iteration, run cleanup too.
`cv residue` lists verify-id files left under the real `~/Library` by an interrupted run; `cv residue --remove --run
<dir>` deletes one stopped run's files and refuses without a run, so it never removes a concurrent run's.

## Gotchas

- The first build in a fresh worktree takes about a minute. A `.build/` carrying another checkout's absolute paths
  fails: `rm -rf app/CicadaApp/.build` in that checkout only, then `cv app build` again.
- A first launch can raise a macOS privacy prompt that blocks the window; `cv app launch` then times out with no
  window. Screenshot the whole screen, tell the person, and do not click the prompt for them.
- Never press a Connect, Disconnect, Sign in, Sign out, Install, Set up, Turn on/off or Update button in the app in a
  verify run, nor Open Cicada at login (it registers this copy as the person's login item), Restart Cicada (`open -n`
  drops the scratch home), Open in Cursor, Remove bookmark (drives Chrome) or Allow Contacts / Allow… (TCC prompts):
  Settings → Engines, Plans & keys, Integrations, Agents, Skills and General. The Claude plan's Disconnect signs
  the real `claude` out. `vclick` and `cv app click` refuse them; their `--allow-forbidden` only skips the check and
  never makes the press safe. They reach the real keychain, browsers, Contacts or Calendar,
  launchd or the harness configs, and an OAuth sign-in's callback defaults to `localhost:8000`, the person's own
  backend. The feature files mark these.
- ⌘-number shortcuts do not reach the app from the harness; click the sidebar button.
- The Sleep engine calls are real plan usage (haiku). Keep journeys small: two or three short conversations.
- After `cv selftest` fails, the engine's argv changed: update `bin/plan-claude` to match `agent_engine.build_argv`.

## Feature map

`features/README.md` indexes one file per user-facing feature: what it is, every entry point (app, API, MCP, CLI),
how to drive it with `cv`, and what proves it. Keep it current with `/pstack:maintain-verification-skill`.

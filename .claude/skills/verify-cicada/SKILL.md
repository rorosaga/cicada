---
name: verify-cicada
description: Run Cicada end to end on scratch state, fully isolated from the person's live install, and prove a behavior across its surfaces. A backend on a scratch HOME, CICADA_HOME, bank and port; the MCP server over stdio; a Sleep cycle on the Claude plan with haiku; the `cicada` CLI; and a second, separately identified copy of the macOS app driven with macos-harness. Use it to verify a change in the real app, API, MCP or CLI, to reproduce a bug before fixing it, or to capture screenshots and transcripts as evidence.
---

# verify-cicada

Every helper lives in `bin/` beside this file. `cv` is the dispatcher. Each run has one directory holding scratch
state and a `run.json` record (ports, pids, env), and one evidence directory that survives cleanup.

```sh
CV=.claude/skills/verify-cicada/bin/cv          # from the checkout root; any worktree works
$CV launch --run-id my-check --evidence ~/cicada-verify-evidence/my-check
export CICADA_VERIFY_RUN=<the "run" path launch printed>   # or pass --run <dir> to every verb
$CV doctor
```

Defaults: runs under `$CICADA_VERIFY_ROOT` (else `$TMPDIR/cicada-verify/<id>`), evidence under
`$CICADA_VERIFY_EVIDENCE` (else `~/cicada-verify-evidence/<id>`). With no `--run` and no `CICADA_VERIFY_RUN`, a verb
uses the newest run.

## What isolation means here

Never drive, query, POST to or kill the person's own install: their app (`~/Applications/Cicada.app`, bundle id
`com.rorosaga.cicada`), their backend on 127.0.0.1:8000, their `~/.cicada`, `~/cicada/memory` or a checkout's
`memory/`, or anything `com.cicada.*` in launchd. Never call the `mcp__cicada__*` tools of your own session: they are
wired to the person's bank. `cv` refuses ports 8000 and 8765 and kills only pids it recorded whose command line still
carries the marker it recorded.

| Surface | How a run is kept apart | What still touches the real account |
|---|---|---|
| Backend | `HOME`, `CICADA_HOME`, `CICADA_MEMORY_PATH`, `CICADA_PORT` all scratch; a clean env (only `PATH`, `TMPDIR`, locale, `USER` pass through); refuses to start when the worktree has an `api/.env` | nothing |
| Network | `CICADA_ALLOW_CONNECTOR_FETCH=off`, `CICADA_ALLOW_LOGO_FETCH=off`, `CICADA_ALLOW_FEED_FETCH=off`, `HF_HUB_OFFLINE=1` | the Sleep engine's model calls, and `--search-model`'s pinned download |
| Sleep engine | `CICADA_LLM_MODE=agent`, every model `haiku`, `CICADA_CLAUDE_CLI=bin/plan-claude` | `plan-claude` gives the `claude` child the real HOME so it finds the plan sign-in (login keychain, default config dir). It refuses any call without every lock Cicada pins (`-p --safe-mode --strict-mcp-config --setting-sources --no-session-persistence`), any model but haiku, and `CICADA_CAPTURE` not `off`. No credential is copied anywhere |
| MCP server | spawned per call with the run's env | nothing |
| App | a copy of the worktree's build stamped `com.rorosaga.cicada.verify` / "Cicada Verify", with `LSEnvironment` pointing at the run, started directly with the run's env; driven by pid and by its path | macOS keeps per-bundle-id files under the real `~/Library` (Foundation ignores `HOME`): Preferences, Caches, HTTPStorages, WebKit. All are named by the verify id; `cv cleanup` and `cv residue --remove` delete exactly those |

Observed 2026-10-22: a scratch `HOME` (or a scratch `CLAUDE_CONFIG_DIR`) makes `claude auth status` report
`loggedIn: false`, which is why `plan-claude` exists. The backend's documented headless path,
`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, also works without the real HOME, but minting that token is the
person's step, never an agent's.

## Launch

```sh
$CV launch [--run-id ID] [--evidence DIR] [--port N] [--search-model] [--timeout 120]
```

Starts `python -m uvicorn api.main:app` from the worktree (its own `api/.venv`, else the main checkout's, else
`CICADA_VERIFY_PYTHON`) on a free port. An empty dir bootstraps itself: the backend scaffolds the bank, makes its
first git commit (the owner page) and writes `api_token` into the scratch `CICADA_HOME`. Ready means usable, so
`launch` waits until the token-authed `/healthz` names the scratch root as `memoryRoot`, a `bankId` and the owner
page, `/status` answers 200, and the bank has a commit. It prints the run dir, port, pid and bank id, and writes
`launch/healthz.json` into evidence.

`--search-model` fetches the pinned on-device search model (`scripts/fetch-embedding-model.sh`, ~130 MB,
sha256-checked) into the run, with a download cache under the run root, so meaning search works. Without it, recall
answers from words only and Sleep ends "completed with warnings" (`Search by meaning wasn't updated`); that warning is
expected, not a failure.

## Doctor

```sh
$CV doctor
```

Read only. Checks that the backend pid is alive and ours, owns the port, runs from this worktree, and admits the token;
that `/healthz` names the scratch root and a bank inside the run, at this worktree's `VERSION`; that the worktree HEAD
is the one launched; that the plan answers through `plan-claude` (`auth status`, no model call); and, once the app is
launched, that its pid is ours, its bundle id is the verify id, it was stamped from this worktree, and it was built at
this HEAD. Exit 1 on any `FAIL`. Run it first whenever anything looks off.

## Drive

```sh
$CV api GET /graph [--save api/graph.json]            # any route, with the run's token
$CV api GET /inbox --save api/inbox.json
$CV capture --session s1 --turn t1 --user "..." --assistant "..."   # POST /capture/turn, harness cursor
$CV sleep [--timeout 900]                              # POST /sleep/trigger, poll /sleep/status, show commits + pages
$CV mcp init | list | schema cicada_recall | call cicada_recall '{"query": "alpha-project"}'
$CV cli [--save cli/recall.json] -- recall alpha-project   # the `cicada` command, in-process, on this run
$CV bank log | ls | cat entities/alpha-project.md      # read the scratch bank
```

- `capture` is the real capture door Cursor and Gemini CLI hooks use. One session id is one episode (G104); a second
  `--turn` on the same session extends it. Promotion needs two conversations, so a journey that wants a page captures
  two sessions that both name the thing.
- `sleep` uses the Claude plan at haiku. A run of two short episodes took about 25 s on 2026-10-22. Its commit carries
  `Cicada-Author: claude-haiku-*`, `Cicada-Engine: claude-cli` and one `Cicada-Session:` per conversation.
- `mcp` spawns `mcp/server.py` for each call and speaks newline JSON-RPC: `initialize`, `notifications/initialized`,
  then `tools/list` or `tools/call`. The whole exchange goes to `evidence/mcp/<time>-<tool>.jsonl`. `schema <tool>`
  prints a tool's input schema; read it before calling a tool whose arguments you have not used.
- `cli` runs `python -P -m api.cli` with the run's env; output goes to `evidence/cli/`. Commands that act as the person
  (for example `sleep start`) refuse from an agent's shell by design; use `cv sleep` or `cv api` for those.

### The app

```sh
$CV app build          # ./bundle.sh in this worktree, copy to <run>/app/Cicada Verify.app, restamp, build winctl
$CV app launch         # needs the run's backend up; waits for a window owned by our pid
$CV app shot home      # screencapture -x -o -l <our window id> -> evidence/app/home.png
$CV app click 300 200  # a real click at window-relative points, our pid only
$CV app windows        # our pid's windows as JSON
```

The person's app may be running with the same executable name. Everything here goes by our pid and our copy's path,
never by name. The app finds its backend through `CICADA_PORT` and its token through `CICADA_HOME`, both set at
launch and baked into the copy's `LSEnvironment`; it spawns no backend because ours already holds the port.

Drive it with macos-harness through the functions in `bin/harness.sh`. Source the file: macos-harness keeps its element
numbers per calling shell, so a wrapper process loses them.

```sh
. .claude/skills/verify-cicada/bin/harness.sh
vh get_app_state                                  # the full tree; vh passes --app <our copy's path>
vclick 'button.*Description: Projects,'           # read, find the first matching line, click its number
vclick 'button Description: alpha-project'
vh get_app_state --disableDiff | grep -i spectrogram
$CV app shot project-alpha
```

`vh` fails unless this run's app is running, so the harness never starts a copy outside the run. Sidebar pages are
buttons with `Description: <Page>` (Home, Graph, Clusters, Skills, Sleep, Inbox, Sources, Projects, Settings). Numbers
change with every page; `vclick` reads fresh each time. When an element ignores an AX press, use the screenshot and
`$CV app click X Y` (points from the top-left of our window; on a Retina screen a `cv app shot` PNG is 2 px per point,
so halve its pixel coordinates). The graph canvas is a web view whose nodes are not AX elements, so nodes are
clicked this way.

## Evidence

Everything a verb writes lands under the evidence dir: `launch/`, `doctor/`, `capture/`, `sleep/` (status,
`bank-git-log.txt` with trailers, `entities.txt`), `mcp/` (full JSON-RPC transcripts), `cli/` (argv, exit, stdout,
stderr), `api/` (with `--save`) and `app/` (PNG by window id). `cleanup` adds `state-at-cleanup/` (run.json, logs,
the bank's full git log).

A proof follows these standards:

- Exercise the real user path: `/capture/turn`, `/sleep/trigger`, the MCP stdio server, the CLI, the app's own
  controls. Never call a service function, write into `entities/`, or flip `processed:` by hand.
- Capture the action and the resulting state: the request and its answer, then a second, read-only view of the
  stored result (the bank's git log, a page file, `cicada_recall`, the app's screen).
- Verify side effects alongside what is visible: the episode file, the Sleep commit and its trailers, the page.
- The only stand-in is the model: the plan runs for real at haiku, so wording differs between runs. Assert on page
  ids, commit trailers and named facts, not on exact prose.

## Cleanup

```sh
$CV cleanup [--keep-state]
```

Snapshots run.json, logs and the bank's git log into `evidence/state-at-cleanup/`, stops the app pid and then the
backend's process group (it started both in their own sessions), refuses to go on if either is still ours and alive,
removes the verify bundle id's `~/Library` files, and deletes the run dir unless `--keep-state`. Evidence is never
removed. After a failed iteration, run cleanup too. `cv residue` lists any verify-id files left from an interrupted
run, `cv residue --remove` deletes them.

## Gotchas

- The first build in a fresh worktree takes about a minute. A `.build/` carrying another checkout's absolute paths
  fails: `rm -rf app/CicadaApp/.build` in THIS worktree only, then `cv app build` again.
- A first launch can raise a macOS privacy prompt that blocks the window; `cv app launch` then times out with no
  window. Screenshot the whole screen, tell the person, and do not click the prompt for them.
- Never use the app's Connect, Install or integration buttons in a verify run: they write to the real
  `~/.claude`, `~/.cursor`, `~/Library/LaunchAgents` or the person's browsers, because the app reads the real home.
  The feature files mark these.
- ⌘-number shortcuts do not reach the app from the harness; click the sidebar button.
- The plan's sign-in shows the account's email in `/sleep/engine` and `/connections` answers. Evidence stays local;
  never paste it into a commit, PR or doc.
- The Sleep engine calls are real plan usage (haiku). Keep journeys small: two or three short conversations.

## Feature map

`features/README.md` indexes one file per user-facing feature: what it is, every entry point (app, API, MCP, CLI),
how to drive it with `cv`, and what proves it. Keep it current with `/pstack:maintain-verification-skill`.

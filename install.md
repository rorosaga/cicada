# Install Cicada

Cicada is a memory for your AI agents that lives on your Mac. The easiest way to install it is to let
an agent you already use do it for you.

## Just want the app? (testers)

On an Apple silicon Mac (M1 or later) with macOS 14 or later, paste this into Terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-release.sh | bash
```

It downloads the latest release, checks it, puts Cicada in `~/Applications` and opens it. The app
carries everything it needs — its own Python, git and a small search model — so there is nothing else
to install, and it updates itself (Settings → General → *Install updates automatically*). Downloading
the zip from the Releases page in a browser works too, but because the app isn't notarized yet macOS
asks once: System Settings → Privacy & Security → **Open Anyway**. Details: [`docs/RELEASING.md`](docs/RELEASING.md).

## A server, or Homebrew (no app)

On a **Linux** machine with systemd, as the user who will own the memory (not root):

```sh
curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-server.sh | bash
```

It checks for `git`, `curl` and `uv` and names whichever is missing with the line that installs it; then it
installs the latest release, the `cicada` command and a background service that listens on this machine only. Run it
again to update; add `bash -s -- --uninstall` to remove it (the memory stays). It never asks for or prints a key or a
token. If it says lingering is off, the service stops at logout until the person runs the `sudo loginctl
enable-linger` line it prints — that is the person's step, not the agent's.

With **Homebrew** (a Mac or Linux), the same backend and command without the app:

```sh
brew tap rorosaga/cicada https://github.com/rorosaga/cicada
brew install cicada
cicada-setup
```

**Both lines work from the next release on** (`main` is still 0.3.1 and has neither file; a `main` URL answers 404
until then). Before it, a tester installs from `dev`:
`curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/dev/scripts/install-server.sh | CICADA_REF=dev bash`,
or for Homebrew `git clone -b dev https://github.com/rorosaga/cicada && brew tap rorosaga/cicada "$PWD/cicada" && brew
install --HEAD cicada`.

Connecting other machines to a server, and the topology: `docs/architecture/headless.md`.

The rest of this page installs Cicada **from source**, for developers.

## The one-paste way

Open Claude Code, Codex, Cursor's agent or any agent that can run commands in a terminal, and paste this:

> Install Cicada on this Mac for me. Follow https://github.com/rorosaga/cicada/blob/main/install.md step
> by step, ask me before installing any tool that's missing, and tell me when the app is open.

The agent reads the steps below and runs them, and it asks you before it installs anything new.
Nothing of yours is uploaded: Cicada keeps your memory on this computer.

## What the agent does

You can follow along, or run the steps yourself. You need a Mac with macOS 14 or later.

1. **Check the tools.**
   - `git --version`
   - `xcode-select -p` checks for Xcode's command line tools. If they are missing, ask first, then
     run `xcode-select --install`. It opens a macOS window; wait until it finishes.
   - `uv --version` checks for the Python tool Cicada uses. If it is missing, ask first, then run
     `curl -LsSf https://astral.sh/uv/install.sh | sh` and open a new shell.
2. **Get Cicada** into a folder that will stay put. The app and your agents point at this folder, so
   don't use Downloads or a temporary folder:
   `git clone https://github.com/rorosaga/cicada.git ~/cicada`
   If `~/cicada/install.sh` already exists, Cicada is already there: run `cd ~/cicada && git pull`
   instead. If `~/cicada` exists but has no `install.sh` (an older install may have put only a
   `memory` folder there), stop and ask the person what to do. Never move or delete it.
3. **Install the background service:** `cd ~/cicada && ./install.sh`
   It is safe to run again. It does six things:
   - sets up Python
   - fetches the on-device search model (about 130 MB, once; the same pinned files the release app ships)
   - creates the memory folder
   - starts Cicada's background service
   - registers Cicada with Claude Code
   - turns on saving each Claude Code (and Codex) conversation into Cicada

   If `~/.cursor` already exists, it also merges Cicada's user-level `sessionStart` hook into
   `~/.cursor/hooks.json` (unless `CICADA_RECALL=off`). This adds startup context only; automatic
   Cursor capture is unsupported. Add MCP separately with Settings → Agents → Open in Cursor, or copy the
   prompt beside it into Cursor's agent. Any other agent: Settings → Agents → *Another agent*.
   Remembers automatically turns the startup hook on/off independently; `./install.sh --uninstall`
   removes only Cicada's hook entries. `make doctor` reports configuration separately from connectivity.
   Invalid hook JSON is left unchanged. The local IDE path follows the
   [Cursor hook reference](https://cursor.com/docs/hooks); actual first-prompt timing is unverified.

   When an agent runs it, it never asks for or prints an API key. If you want to use a key, add it
   later in the app.
4. **Build and open the app:** `cd ~/cicada && make install-app && open ~/Applications/Cicada.app`
   The first build takes a few minutes.
5. **Check it's running:** `curl -s http://127.0.0.1:8000/healthz` should answer.
   Optional, only if the person asks for it: `make cli` links `~/.local/bin/cicada`, the command line that
   agents with a shell can use instead of the MCP tools. It needs no password and never replaces a
   `cicada` that is already there.
6. **Hand over.** Tell the person the app is open. Its Welcome screen takes it from there: connecting
   other agents, importing chat exports and turning on calendars.

## Rules for the agent

- Change nothing outside `~/cicada` except what `./install.sh` itself does.
- Never type, paste or print an API key or a password.
- If a step fails, stop. Show the person the last lines of the error and say in plain words what
  went wrong.
- `make doctor` is a fuller health check. On a brand-new memory, two of its checks only pass after
  Cicada's first read of your conversations, so don't retry it in a loop.

## Updating later

`cd ~/cicada && git pull && ./install.sh && make install-app`

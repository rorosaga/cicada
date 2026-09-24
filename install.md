# Install Cicada

Cicada is a memory for your AI agents that lives on your Mac. The easiest way to install it is to let
an agent you already use do it for you.

## The one-paste way

Open Claude Code or Codex in a terminal and paste this:

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
   It is safe to run again. It does five things:
   - sets up Python
   - creates the memory folder
   - starts Cicada's background service
   - registers Cicada with Claude Code
   - turns on saving each Claude Code (and Codex) conversation into Cicada

   When an agent runs it, it never asks for or prints an API key. If you want to use a key, add it
   later in the app.
4. **Build and open the app:** `cd ~/cicada && make install-app && open ~/Applications/Cicada.app`
   The first build takes a few minutes.
5. **Check it's running:** `curl -s http://127.0.0.1:8000/healthz` should answer.
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

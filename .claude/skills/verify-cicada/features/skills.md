# Skills

Third-party skills installed on the person's consent, pinned to what they saw, and skills Cicada drafts from how the person works, held until two conversations support them.

## Sub-features

- `skills-installed`, `skills-discover`, `skills-drafts`, `skill-propose` (agent asks), `skill-create` (agent drafts a held skill).

## How to get to it (user POV)

- Sidebar `Skills` (Installed, Discover, Drafts, Add a skill); Settings → Skills.
- MCP `cicada_skills`, `cicada_propose_skill`, `cicada_create_skill`.
- `GET /skills`, `/skills/recommended`, `POST /skills/install`; `cicada skills list | propose | create | check | install ...`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **List.** Run `$CV mcp call cicada_skills '{}'` and `$CV cli -- skills list`. `none yet` installed, plus Cicada's suggestions; after a Sleep, `GET /skills` may list a Sleep-made skill page under `noticed`.
- **Draft.** Run `$CV mcp call cicada_create_skill '{"skill": "verify-spectrogram", "description": "Turn a birdsong clip into a spectrogram.", "body": "1. Load the clip.", "reason": "verify"}'`. `Saved the skill verify-spectrogram, held`; `$CV api GET /skills` lists it under `drafts`, `state: held`, kept in the scratch `CICADA_HOME/skills/drafts/`.
- **App.** `vclick 'button.*Description: Skills,'`. `Installed, 0`, `Discover`, `Drafts, 1` and `No skills yet`; `$CV app shot skills`.

## Gotchas

- Forbidden in a verify run: Install and Add a skill. Installing writes into the harnesses' skill folders and fetches the skill's repository.

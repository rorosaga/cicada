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

- **List.** Run `$CV mcp call cicada_skills '{}'` and `$CV cli -- skills list`. Empty on a fresh run.
- **App.** `vclick 'button.*Description: Skills,'`. `No skills yet` and the three tabs; `$CV app shot skills`.

## Gotchas

- Installing writes into the harnesses' skill folders under the real home (the app and backend resolve them there); never install from a verify run.

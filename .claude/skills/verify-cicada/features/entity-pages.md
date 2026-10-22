# Entity pages and the Reader

Every page reads as an article with its claims, sources, history and blame; the Reader shows the conversation span a claim came from.

## Sub-features

- `page-read` shows a page's prose and claims.
- `page-history` lists its commits and diffs; `page-blame` who wrote each line.
- `page-edit` changes words or aliases with a reason (`cicada_edit_page`).
- `page-picture` sets, initials or clears its picture.
- `page-decay` changes its decay class.
- `reader-span` opens the evidence span behind a claim.

## How to get to it (user POV)

- Clicking a page anywhere (Home chip, Projects row, graph node, search result).
- `GET /entities/{entity_id}`, `GET /entities/{entity_id}/history`, `GET /entities/{entity_id}/history/{commit_hash}/diff`, `GET /entities/{entity_id}/blame`, `GET /entities/{entity_id}/claims`, `GET /entities/{entity_id}/provenance`; `GET /episodes/{episode_id}/span`.
- MCP `cicada_recall_detail`, `cicada_edit_page`; `cicada page list | history | decay`, `cicada picture set | initials | clear`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- `alpha-project` exists (the standard seed and one `$CV sleep`).

- **Read.** Run `$CV api GET /entities/alpha-project --save api/entity.json`. Title, `markdownContent`, claims, and `history` whose `author` is the `Cicada-Author` trailer (`claude-haiku-*`), not git's author.
- **History.** Run `$CV cli -- page history alpha-project`. The Sleep commit that made it.
- **Edit.** Copy one line of `markdownContent` exactly, then run `$CV mcp call cicada_edit_page '{"subject": "alpha-project", "reason": "verify run: name the library exactly", "edits": [{"old": "<exact line>", "new": "<replacement>"}]}'`. The verify harness is not on the trust list, so the reply says `Proposed, not applied … (inbox-NNN)` and `$CV bank log` shows `Page edit proposed` under `Cicada-Author: verify`.
- **Apply.** Run `$CV api POST /inbox/<inbox-NNN>/resolve '{"action": "answer", "optionKey": "apply"}'`. `$CV bank cat entities/alpha-project.md` carries the new words.
- **Blame.** Run `$CV api GET /entities/alpha-project/blame --save api/blame.json`. The Sleep commit and the edit, the edit as `author: verify`, `acceptedBy: user`.
- **App.** `vclick 'button.*Description: Clusters,'`, then `vclick 'button Project, alpha-project'`. The page opens beside the grid (`Content`, `Perspectives`); `$CV app shot page`.

## Gotchas

- The verify MCP session reports harness `verify`, which is not on the trust list, so `cicada_edit_page` proposes rather than writes. That is the rail working.
- Picture fetches are gated off in a verify run (`CICADA_ALLOW_LOGO_FETCH=off`).

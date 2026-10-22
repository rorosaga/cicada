# G61 (G208, ruling 36 D5) — "Where to check": sources on people, proposed by inference

Branch `feat/update-sources`, against `dev`. Unattended worker plan (saga-01, 2026-10-22); the critic and the per-task
reviews were done by the same worker against the code (no sub-agents allowed on this run), recorded in the report.

## Global constraints

- Extend G61's `sources:` (one store), never a parallel one. The frontmatter key keeps its name; only the words change
  ("Where to check").
- A proposal never writes the person's trust: it is an entry with `proposed: true`, untrusted (`fact_sources.trusted`
  false), never `person_photo.is_own_account`, never `source_refresh.tracked`, until the person takes it.
- Never a URL guessed from a name: every Sleep proposal is a URL already written on the record (the page's own text, or
  the person's own turn in one of the page's conversations).
- Ruling 29: Sleep settles a proposal question only when the person's own located words (a `user` turn of a
  conversation the page rests on, the same line naming the page) carry the link. Otherwise the person answers.
- `sources_removed` is respected by every machine writer (`fact_sources.is_tombstoned`).
- Picture ladder unchanged in order; Instagram joins the proxy rung; the proxy gate defaults ON (D5), its off switch
  still works.
- R12: every argument the primer names exists in the schema; the handshake stays ≤ 1,800 tokens.

## Rulings (this plan)

1. **The question rides the existing `clarification` kind with `asks: sources`** (the role-name pattern, `asks: name`):
   no new kind for the app to learn; the app's options card already draws it. Options `yes` / `no`.
2. **One question per page**, listing every pending proposal (`refs:`); the tail step keeps it in sync (refs updated,
   the question removed when none is left), so it is idempotent.
3. **Yes** = each listed, still-proposed entry becomes `accepted` (`proposed` dropped). **No** = each is removed with a
   `user` tombstone. Either commits as the person's answer through `inbox_service`.
4. **Sleep's own proposals: person pages** (GitHub, X, LinkedIn, Instagram, Google Scholar, ORCID profile URLs), plus a
   **project/tool page's own GitHub repo** when the repo's name is the page's name. Not handle paths of saved posts nor
   `Name (handle)` extraction names: identity from a post's path is too weak to propose unasked (left for G209).
5. **Agents propose with `cicada_add_source(inferred=true, evidence=[{episode, quote}])`**; the direct add stays for a
   source the person named. An inferred add is `proposed` and lands in the page's question on the next Sleep.
6. **Icons** follow the existing site-icon rules unchanged: a person page draws no site mark (G159); the wire carries a
   `linkKind` the app draws as its own glyph.

## Tasks

1. `fact_sources`: `proposed` / `evidence` fields; accepting drops `proposed`; `link_kind()` classifier.
2. `person_photo`: Instagram rung; gate default on; a proposal is never own-account.
3. `source_proposals` (new): candidates, propose, question sync, settle rule, resolver, dry run.
4. Sleep tail step `_source_proposals_safely`; inbox resolver route; `inbox_tend` rule `named_account`.
5. MCP `cicada_add_source(inferred, evidence)`, CLI row, handshake + skill text.
6. Wire: `EntitySource.proposed/evidence/linkKind/label/iconSite`.
7. `scripts/where_to_check_dry_run.py`.
8. Docs: storage.md, mcp.md, network.md, CLAUDE.md rail lines.

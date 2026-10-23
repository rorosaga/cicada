# New-user benchmark

Does memory work for a stranger? An invented person's two months, loaded through the doors a real install uses,
slept on with the Claude plan at haiku, then asked 25 questions through the MCP stdio server the way a new user's agent
would. Run it before each release; it costs one Sleep (~4 minutes, ~39 episodes) and 75 tool calls on the plan.

Everything in the fixture is invented (`persona.py`): names, companies, places, and `example.com` links. Nothing comes
from any real bank, and `api/tests/test_newuser_benchmark.py` fails if a link host other than `example.com` or an
address outside `example.invalid` appears.

## The person

Mara Quill, 2026-08-20 → 2026-10-20 (UTC):

| Source | Door | Count |
|---|---|---|
| ChatGPT export (`conversations.json` in the real tree shape, zipped) | `POST /intake/import` | 9 conversations |
| Claude.ai export (`conversations.json`, `users.json`, zipped) | `POST /intake/import` | 6 conversations |
| Claude Code sessions (JSONL with tool calls, under a scratch harness root) | `POST /capture/transcript`, with the hook's workspace observation | 15 sessions |
| Browser bookmarks (Netscape HTML) | `POST /sources/upload` | 3 links |
| Calendar window (what the app reads through EventKit) | `POST /sources/calendar-local/sync` | 6 events |

The hard cases: a person known by a nickname and a handle (Teo / Teodor Brandt / `tbrandt`); a job change with an
ending stated relative to the day ("a week from today"); a project that stalls (`tidepool-cli`, last touched
2026-09-03); a decision reversed (Supabase → own magic links); a trip with dates; two people named Sam; a
non-software project (a canoe); facts stated relative to the conversation day.

## Running it

From a worktree, with the verify-cicada skill (scratch HOME, CICADA_HOME, bank and port; never the live install):

```sh
CV=.claude/skills/verify-cicada/bin/cv
$CV launch --run-id newuser --no-owner --search-model --evidence ~/cicada-verify-evidence/newuser
api/.venv/bin/python -m benchmarks.newuser.load --run /tmp/cicada-verify/newuser      # owner, imports, hooks
CICADA_VERIFY_RUN=/tmp/cicada-verify/newuser $CV sleep --timeout 3600                  # one drain, plan + haiku
api/.venv/bin/python -m benchmarks.newuser.ask --run /tmp/cicada-verify/newuser --repeats 3 \
    --out ~/cicada-verify-evidence/newuser/results.jsonl
api/.venv/bin/python -m benchmarks.newuser.ask --summary ~/cicada-verify-evidence/newuser/results.jsonl
api/.venv/bin/python -m benchmarks.newuser.ask --compare before.jsonl after.jsonl
$CV cleanup --run /tmp/cicada-verify/newuser
```

`load.py` writes the fixture under the run directory, refuses ports 8000 and 8765, and posts each Claude Code session
with the observation the Stop hook makes (a git checkout for the two repositories), because a project page is born from
a repository the hook saw or the person's own words (ruling 36 D4).

## Grading

Each question in `questions.json` has `expect` groups (every group must match one of its spellings), `forbid` spellings
and, for one, `abstain`. `ask.py` grades by spelling into correct / partial / wrong / refused. That is a cheap first
pass, not a verdict: read the answers before quoting a number, fix a spelling list that misjudged a right answer, and
re-grade without new calls (`--regrade results.jsonl`). The reply size (characters, ~tokens) is on every line;
`cicada_recall` must stay under `RECALL_BUDGET` (40,000 characters). The handshake a stranger's agent receives is saved
beside the results (`*.handshake.txt`).

## What else to read after a run

- the inbox (`memory/inbox/*.md`): how many questions, of what kinds, and whether a stranger could answer them;
- duplicates: a person held in `pending_entities.jsonl` under a full name while a page holds the first name;
- decay: `tidepool-cli` should be the quietest project, and the job the person left should not read as current;
- the timeline (`q22`): new pages counted as new.

The first runs and their findings are in the 2026-10-22 report referenced from G148.

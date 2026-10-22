"""A synthetic new user: two months of one invented life, in the shapes a stranger's exports really have.

Every name, project, company, place and link here is invented (links are ``example.com``); nothing comes from any
real bank. The person is Mara Quill, and the life runs 2026-08-20 → 2026-10-20 (UTC), so a run on or after
2026-10-22 sees the last two days as silence. It carries the hard cases a real person has:

- a person known by a nickname and a handle (Teo / Teodor Brandt / ``tbrandt``);
- a job change, so an ending (Lumenfold → Harbor & Kiln), stated relative to the day it was said;
- a project that stalls and should fade (``tidepool-cli``, last touched 2026-09-03);
- a decision reversed later (fernpost's auth: Supabase on 2026-08-28, its own magic links on 2026-10-09);
- a trip with dates (Greyhollow, 2026-10-03 → 2026-10-06);
- two people sharing a first name (Sam Okafor, a former colleague; Sam Reyes, the climbing partner);
- a non-software project (a cedar-strip canoe);
- facts stated relative to the conversation day ("a week from today", "next Monday").

``build(out_dir)`` writes the files ``load.py`` posts: a ChatGPT export zip, a Claude.ai export zip, fifteen Claude
Code transcripts under a harness-root-shaped tree, a browser bookmarks file and the calendar window the app would
read. Stdlib only and deterministic: the same call writes the same bytes.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWNER = "Mara Quill"
#: A stable namespace so every uuid in the fixture is the same on every build.
_NS = uuid.UUID("6f1c3a52-7d0e-4b8a-9c11-2b5e8f0a4d31")


def _uid(*parts: object) -> str:
    return str(uuid.uuid5(_NS, "/".join(str(p) for p in parts)))


def _at(stamp: str, minutes: int = 0) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- ChatGPT (the canoe, the job offer, the trip plan, home life) ----------------------------------------------------

CHATGPT: list[dict] = [
    {"title": "Cedar strip canoe planning", "at": "2026-08-20T19:10", "turns": [
        ("user", "I'm finally building a canoe. A 15-foot cedar-strip canoe, in the garage, over the autumn. "
                 "I ordered western red cedar strips from a mill upstate, 1/4 inch bead-and-cove. What else do I "
                 "need before I start?"),
        ("assistant", "Congratulations! Beyond the strips you'll need a strongback, station forms cut from "
                      "plywood, staples or clamps, wood glue, a block plane, and later fiberglass cloth and epoxy."),
        ("user", "Good. I want it done before spring so I can paddle it at the lake in April. Budget is about "
                 "900 dollars all in."),
        ("assistant", "That's realistic for a 15-footer if you build the strongback from scrap and buy epoxy in "
                      "a kit. Plan roughly: forms and strongback, stripping, fairing, glassing, then trim."),
    ]},
    {"title": "Strongback and station forms", "at": "2026-08-29T17:40", "turns": [
        ("user", "Built the strongback today out of two 2x6s, it's dead level. Teo came over and helped me cut "
                 "the station forms on his bandsaw."),
        ("assistant", "Nice progress. Check that every form sits square to the centreline before you start "
                      "stripping; a twisted form shows up as a wavy sheer line later."),
        ("user", "Yep, we checked with a string line. Next weekend I start stripping the hull."),
    ]},
    {"title": "Giving notice", "at": "2026-09-04T16:20", "turns": [
        ("user", "Big news: I got the offer from Harbor & Kiln! Staff product designer. I gave notice at "
                 "Lumenfold this morning, so my last day at Lumenfold is a week from today."),
        ("assistant", "Congratulations! How did your manager take it?"),
        ("user", "Priya was gracious about it, honestly. She's been a good manager for three years even when "
                 "the roadmap was chaos. I'll miss working with her and with Sam Okafor on the product side."),
        ("assistant", "It's great to leave on good terms. Want help drafting a handover plan?"),
        ("user", "Later maybe. Harbor & Kiln makes field tools for ecologists, which is exactly the kind of work "
                 "I wanted. The salary bump is decent too."),
    ]},
    {"title": "Climbing trip planning", "at": "2026-09-08T20:05", "turns": [
        ("user", "Sam Reyes and I are planning a climbing trip to Greyhollow, the first weekend of October, "
                 "Saturday the 3rd to Tuesday the 6th. We'll camp at the north lot."),
        ("assistant", "Sounds fun. Is Sam leading or are you swapping leads?"),
        ("user", "Sam Reyes leads the harder pitches, he's been climbing for ten years; I'll lead the 5.8s. "
                 "Sam is my climbing partner from the bouldering gym, not Sam from work."),
        ("assistant", "Got it. Bring a rack for trad if Greyhollow has crack routes, and check the weather for "
                      "early October; nights can be cold."),
    ]},
    {"title": "Stripping the hull", "at": "2026-09-12T18:30", "turns": [
        ("user", "Canoe update: the hull is about 60 percent stripped. The cedar smells amazing. I'm doing a "
                 "few strips every evening after work."),
        ("assistant", "That's steady progress. Remember to stagger the scarf joints so no two line up."),
        ("user", "Yes. Also, yesterday was my last day at Lumenfold. Farewell lunch was lovely."),
    ]},
    {"title": "Night shifts and dinner plans", "at": "2026-09-24T21:00", "turns": [
        ("user", "Jules is on night shifts at St. Brennan's all this week (Jules is an ER nurse), so I'm "
                 "cooking batches. Can you suggest freezer meals that reheat well?"),
        ("assistant", "Lentil soups, chilli, baked pasta and curries all freeze and reheat well."),
        ("user", "Perfect. Also it's Teo's birthday on October 15th and we're doing dinner at Juniper Hall. "
                 "Gift ideas for someone who builds everything himself?"),
        ("assistant", "A good marking gauge, a Japanese pull saw, or a nice block plane would suit a maker."),
    ]},
    {"title": "Fiberglassing questions", "at": "2026-09-30T19:15", "turns": [
        ("user", "The hull is fully stripped and faired. I'm nervous about fiberglassing, so I signed up for an "
                 "epoxy and fiberglass workshop at the Alder Row Makerspace on October 17th."),
        ("assistant", "Good call. The workshop will cover wetting out the cloth and avoiding dry spots and "
                      "bubbles. Do the outside of the hull first."),
    ]},
    {"title": "Being a reference", "at": "2026-10-13T12:45", "turns": [
        ("user", "Sam Okafor asked me to be a reference for a product lead job. We worked together at "
                 "Lumenfold for two years, she ran product for the mobile app. What should I say?"),
        ("assistant", "Focus on concrete examples: a launch she led, how she handled conflict, how she worked "
                      "with design."),
        ("user", "She led the offline mode launch and was the best PM I've worked with. I'll write that."),
    ]},
    {"title": "After the epoxy class", "at": "2026-10-18T10:30", "turns": [
        ("user", "The epoxy class yesterday was great. Today I fiberglassed the outside of the hull, no dry "
                 "spots. Next is flipping it and glassing the inside."),
        ("assistant", "Well done! Let the outside cure fully before you flip it, and sand lightly between coats."),
        ("user", "Still aiming to paddle it in April."),
    ]},
]


# --- Claude.ai (work, the job change, coming back from the trip) -----------------------------------------------------

CLAUDE_AI: list[dict] = [
    {"name": "Feeling stuck at work", "at": "2026-08-25T13:00", "turns": [
        ("human", "I'm a senior product designer at Lumenfold and I've been feeling stuck. The roadmap changes "
                  "every two weeks. My manager Priya Nandakumar is supportive but can't fix it."),
        ("assistant", "That sounds draining. What would a better role look like for you?"),
        ("human", "Smaller team, a physical product or tools people use outdoors. I have an interview with "
                  "Harbor & Kiln next week."),
    ]},
    {"name": "Interview prep for Harbor & Kiln", "at": "2026-09-02T09:30", "turns": [
        ("human", "Interview prep: Harbor & Kiln is a studio that makes field tools for ecologists. The role is "
                  "staff product designer. Help me structure my portfolio walk-through."),
        ("assistant", "Lead with one deep case study, then two short ones. Show the messy middle, not just "
                      "the polished end."),
        ("human", "I'll lead with the offline mode work at Lumenfold."),
    ]},
    {"name": "Farewell note", "at": "2026-09-10T15:10", "turns": [
        ("human", "Help me write a farewell note to the Lumenfold design and product team. Thank Priya for "
                  "being a great manager and Sam Okafor for being the best PM partner."),
        ("assistant", "Here's a draft: 'After three years at Lumenfold, tomorrow is my last day...'"),
        ("human", "Lovely, I'll send it tomorrow morning."),
    ]},
    {"name": "Starting a new job", "at": "2026-09-14T08:15", "turns": [
        ("human", "I start at Harbor & Kiln next Monday and I'm nervous. How do I make a good first month as a "
                  "staff designer?"),
        ("assistant", "Listen first: meet everyone, map the product, find one small win in the first month."),
    ]},
    {"name": "First day notes", "at": "2026-09-22T18:00", "turns": [
        ("human", "First day at Harbor & Kiln was yesterday. My manager is Odile Marchetti, head of design. "
                  "I'll be designing the field data logger app first."),
        ("assistant", "Great start. What did you learn about the field data logger?"),
        ("human", "Ecologists use it in the rain with gloves on, so everything needs huge touch targets."),
    ]},
    {"name": "Back from Greyhollow", "at": "2026-10-07T19:40", "turns": [
        ("human", "Back from Greyhollow last night. Sam Reyes led a 5.10 crack on Sunday and I finally led "
                  "my first 5.9. Four days, cold nights, perfect rock."),
        ("assistant", "Congratulations on your first 5.9 lead! Will you go back?"),
        ("human", "Definitely, Sam and I want to go back in spring."),
    ]},
]


# --- Claude Code (fernpost with Teo, tidepool-cli that stalls, one dotfiles session) ---------------------------------

FERNPOST_CWD = "/home/mara/code/fernpost"
TIDEPOOL_CWD = "/home/mara/code/tidepool-cli"
DOTFILES_CWD = "/home/mara/dotfiles"

CLAUDE_CODE: list[dict] = [
    {"cwd": TIDEPOOL_CWD, "at": "2026-08-21T20:00", "turns": [
        ("user", "Let's start tidepool-cli: a small Python CLI that prints the tide table for a harbour so I "
                 "can plan kayak trips. Use click and httpx."),
        ("assistant", "Scaffolded tidepool-cli with a `tides` command, click and httpx, and a pyproject."),
        ("user", "Add a --days option, default 3."),
        ("assistant", "Added `--days` (default 3) and a table printer."),
    ]},
    {"cwd": TIDEPOOL_CWD, "at": "2026-08-24T21:10", "turns": [
        ("user", "tidepool-cli: parse the station list so I can search harbours by name."),
        ("assistant", "Added a `stations` command with a fuzzy name search over the cached station list."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-08-27T19:00", "turns": [
        ("user", "New project with Teo: fernpost, a tiny web app where neighbours on Alder Row post notes about "
                 "parcels they took in for each other. Next.js front end. Teo is tbrandt on GitHub, add him as a "
                 "collaborator in the README."),
        ("assistant", "Created the fernpost Next.js app, a README listing you and tbrandt (Teodor Brandt) as "
                      "maintainers, and a parcel-note model."),
        ("user", "Great. Keep it small, it's a side project."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-08-28T20:30", "turns": [
        ("user", "Decision for fernpost: we'll use Supabase for auth and its Postgres for data. Teo agreed, it's "
                 "the fastest way to ship."),
        ("assistant", "Wired Supabase auth (email sign-in) and the parcel_notes table on Supabase Postgres."),
        ("user", "Commit it."),
        ("assistant", "Committed: 'Use Supabase for auth and data'."),
    ]},
    {"cwd": TIDEPOOL_CWD, "at": "2026-08-31T10:00", "turns": [
        ("user", "tidepool-cli: cache responses for an hour so I don't hit the tide API on every call."),
        ("assistant", "Added an on-disk cache with a one-hour expiry."),
    ]},
    {"cwd": TIDEPOOL_CWD, "at": "2026-09-03T21:30", "turns": [
        ("user", "tidepool-cli: the NOAA station format changed and parsing breaks. I don't have time now, "
                 "I'll come back to the parser later."),
        ("assistant", "Left a failing test that reproduces the new format and a TODO in parse.py."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-09-06T11:00", "turns": [
        ("user", "fernpost: finish the Supabase sign-in flow. Teo will review the PR tonight."),
        ("assistant", "Finished the sign-in flow with Supabase's email link and opened a PR for review."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-09-16T20:45", "turns": [
        ("user", "fernpost: the Supabase free project got paused again for inactivity and the app was down all "
                 "weekend. That's the second time. Annoying."),
        ("assistant", "Free-tier projects pause after a week without traffic. Options: a keep-alive ping, a "
                      "paid tier, or self-hosting Postgres."),
        ("user", "Let's live with it for now."),
    ]},
    {"cwd": DOTFILES_CWD, "at": "2026-09-19T09:00", "turns": [
        ("user", "Clean up my zsh config: drop oh-my-zsh, keep the git aliases, add starship."),
        ("assistant", "Removed oh-my-zsh, kept your git aliases in aliases.zsh and added a starship init."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-09-27T14:00", "turns": [
        ("user", "fernpost: add a 'picked up' button on each parcel note and show notes from the last 7 days."),
        ("assistant", "Added the picked-up toggle and a seven-day filter on the notes list."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-10-09T19:30", "turns": [
        ("user", "Decision for fernpost: we're dropping Supabase. The free project keeps pausing, and Teo wants "
                 "to self-host everything. We'll roll our own magic-link auth on plain Postgres on Teo's small "
                 "VPS. This reverses the Supabase decision from August."),
        ("assistant", "Understood. Plan: a users table, a login_tokens table, an email sender, and a /login "
                      "route that sends a one-time link. Removing the Supabase client."),
        ("user", "Go."),
        ("assistant", "Removed Supabase, added the Postgres schema and the magic-link login route."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-10-11T15:20", "turns": [
        ("user", "fernpost: send the magic-link email through Postmark-style SMTP, from a noreply address."),
        ("assistant", "Added an SMTP sender with a noreply from-address and an email template."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-10-14T20:10", "turns": [
        ("user", "fernpost: store only a hash of each login token, never the token itself."),
        ("assistant", "Tokens are now stored as SHA-256 hashes; the link carries the raw token once."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-10-19T18:00", "turns": [
        ("user", "fernpost: login links expire after 15 minutes and work only once."),
        ("assistant", "Added a 15-minute expiry and single-use marking on the login_tokens table."),
        ("user", "Next session we do rate limiting on /login."),
    ]},
    {"cwd": FERNPOST_CWD, "at": "2026-10-20T21:00", "turns": [
        ("user", "fernpost: rate limit /login to 5 requests per email per hour."),
        ("assistant", "Added a per-email rate limiter (5/hour) on /login backed by a Postgres table."),
        ("user", "Stopping here. Next: write tests for the rate limiter, then deploy fernpost to Teo's VPS."),
        ("assistant", "Noted. The limiter has no tests yet; deploy is after those."),
    ]},
]


# --- Saved links and the calendar -------------------------------------------------------------------------------------

BOOKMARKS: list[tuple[str, str, str]] = [
    ("https://example.com/cedar-strip-canoe-guide", "Building a cedar-strip canoe, step by step", "2026-08-20T19:30"),
    ("https://example.com/magic-link-auth-done-right", "Magic-link auth done right", "2026-10-09T19:00"),
    ("https://example.com/greyhollow-climbing-topo", "Greyhollow climbing topo", "2026-09-08T20:30"),
]

CALENDAR_EVENTS: list[dict] = [
    {"id": "evt-farewell", "title": "Farewell lunch — Lumenfold team", "start": "2026-09-11T12:00:00+00:00",
     "end": "2026-09-11T13:30:00+00:00", "location": "Canteen on 4th"},
    {"id": "evt-onboarding", "title": "Harbor & Kiln onboarding", "start": "2026-09-21T09:00:00+00:00",
     "end": "2026-09-21T17:00:00+00:00", "location": "Harbor & Kiln studio"},
    {"id": "evt-greyhollow", "title": "Greyhollow climbing trip with Sam Reyes", "start": "2026-10-03T00:00:00+00:00",
     "end": "2026-10-07T00:00:00+00:00", "all_day": True, "location": "Greyhollow"},
    {"id": "evt-teo-bday", "title": "Teo's birthday dinner", "start": "2026-10-15T19:30:00+00:00",
     "end": "2026-10-15T22:00:00+00:00", "location": "Juniper Hall"},
    {"id": "evt-epoxy", "title": "Epoxy & fiberglass workshop", "start": "2026-10-17T10:00:00+00:00",
     "end": "2026-10-17T15:00:00+00:00", "location": "Alder Row Makerspace"},
    {"id": "evt-dentist", "title": "Dentist", "start": "2026-10-28T08:30:00+00:00",
     "end": "2026-10-28T09:00:00+00:00"},
]
CALENDAR_WINDOW = {"from": "2026-08-15T00:00:00+00:00", "to": "2026-11-30T00:00:00+00:00"}


# --- builders -------------------------------------------------------------------------------------------------------


def chatgpt_conversations() -> list[dict]:
    """The real export's tree: a null-message root, a hidden system node, then user/assistant nodes chained by
    ``parent``/``children``, ``current_node`` at the leaf, epoch-second floats."""
    out = []
    for i, conv in enumerate(CHATGPT):
        start = _at(conv["at"])
        root = _uid("gpt", i, "root")
        system = _uid("gpt", i, "system")
        mapping: dict[str, dict] = {
            root: {"id": root, "message": None, "parent": None, "children": [system]},
            system: {"id": system, "parent": root, "children": [], "message": {
                "id": system, "author": {"role": "system", "name": None, "metadata": {}}, "create_time": None,
                "update_time": None, "content": {"content_type": "text", "parts": [""]}, "status": "finished_successfully",
                "end_turn": True, "weight": 0.0, "metadata": {"is_visually_hidden_from_conversation": True},
                "recipient": "all"}},
        }
        prev = system
        t = start
        for j, (role, text) in enumerate(conv["turns"]):
            node = _uid("gpt", i, j)
            mapping[prev]["children"].append(node)
            mapping[node] = {"id": node, "parent": prev, "children": [], "message": {
                "id": node, "author": {"role": role, "name": None, "metadata": {}}, "create_time": t.timestamp(),
                "update_time": None, "content": {"content_type": "text", "parts": [text]},
                "status": "finished_successfully", "end_turn": role == "assistant", "weight": 1.0,
                "metadata": {"model_slug": "gpt-4o"} if role == "assistant" else {}, "recipient": "all"}}
            prev = node
            t += timedelta(minutes=2)
        out.append({"title": conv["title"], "create_time": start.timestamp(), "update_time": t.timestamp(),
                    "mapping": mapping, "moderation_results": [], "current_node": prev, "plugin_ids": None,
                    "conversation_id": _uid("gpt", i), "id": _uid("gpt", i), "is_archived": False,
                    "default_model_slug": "gpt-4o"})
    return out


def claude_conversations() -> list[dict]:
    """Claude.ai's export: ``chat_messages`` with ``sender`` human/assistant, the text both flat and as a content
    block, ISO times with microseconds."""
    out = []
    for i, conv in enumerate(CLAUDE_AI):
        start = _at(conv["at"])
        msgs = []
        t = start
        for j, (sender, text) in enumerate(conv["turns"]):
            stamp = t.strftime("%Y-%m-%dT%H:%M:%S.000000Z")
            msgs.append({"uuid": _uid("claude", i, j), "text": text, "sender": sender,
                         "content": [{"start_timestamp": stamp, "stop_timestamp": stamp, "type": "text",
                                      "text": text, "citations": []}],
                         "created_at": stamp, "updated_at": stamp, "attachments": [], "files": []})
            t += timedelta(minutes=3)
        out.append({"uuid": _uid("claude", i), "name": conv["name"],
                    "created_at": start.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                    "updated_at": t.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                    "account": {"uuid": _uid("account")}, "chat_messages": msgs})
    return out


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 21, 12, 0, 0))
            zf.writestr(info, data)
    return buf.getvalue()


def project_dir_name(cwd: str) -> str:
    """Claude Code's own folder name for a working directory: every `/` and `.` becomes `-`."""
    return cwd.replace("/", "-").replace(".", "-")


def session_id(i: int) -> str:
    return _uid("cc", i)


def claude_code_transcript(i: int) -> str:
    """One session's JSONL as Claude Code writes it: a summary line, user and assistant records chained by
    ``parentUuid``, each agent turn running one tool (``tool_use`` then a ``tool_result`` wearing the user role)
    before its final text."""
    sess = CLAUDE_CODE[i]
    sid = session_id(i)
    t = _at(sess["at"])
    lines: list[dict] = [{"type": "summary", "summary": "work session", "leafUuid": _uid("cc", i, "leaf")}]
    parent = None

    def rec(typ: str, message: dict, **extra) -> None:
        nonlocal parent, t
        u = _uid("cc", i, len(lines))
        line = {"parentUuid": parent, "isSidechain": False, "userType": "external", "cwd": sess["cwd"],
                "sessionId": sid, "version": "2.1.300", "gitBranch": "main", "type": typ, "message": message,
                "uuid": u, "timestamp": _iso(t)}
        line.update(extra)
        lines.append(line)
        parent = u
        t += timedelta(seconds=40)

    for j, (role, text) in enumerate(sess["turns"]):
        if role == "user":
            rec("user", {"role": "user", "content": text})
            continue
        tool = _uid("cc", i, j, "tool")
        rec("assistant", {"id": f"msg_{j}", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                          "content": [{"type": "tool_use", "id": tool, "name": "Edit", "input": {"file_path": "x"}}]})
        rec("user", {"role": "user", "content": [{"tool_use_id": tool, "type": "tool_result", "content": "ok"}]})
        rec("assistant", {"id": f"msg_{j}b", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                          "content": [{"type": "text", "text": text}]}, effort={"level": "medium"})
    return "\n".join(json.dumps(x) for x in lines) + "\n"


def bookmarks_html() -> str:
    rows = "\n".join(
        f'<DT><A HREF="{url}" ADD_DATE="{int(_at(at).timestamp())}">{title}</A>' for url, title, at in BOOKMARKS)
    return ("<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
            '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
            "<TITLE>Bookmarks</TITLE><H1>Bookmarks</H1>\n"
            f"<DL><p><DT><H3>Bookmarks bar</H3><DL><p>\n{rows}\n</DL><p></DL><p>\n")


def calendar_payload() -> dict:
    events = [{"id": e["id"], "calendarId": "cal-personal", "title": e["title"], "start": e["start"],
               "end": e.get("end"), "allDay": bool(e.get("all_day")), "location": e.get("location")}
              for e in CALENDAR_EVENTS]
    return {"window": CALENDAR_WINDOW, "calendars": [{"id": "cal-personal", "title": "Personal"}], "events": events}


def build(out_dir: Path) -> dict:
    """Write every file and return where each landed."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chatgpt = out_dir / "chatgpt-export.zip"
    chatgpt.write_bytes(_zip({
        "conversations.json": json.dumps(chatgpt_conversations()),
        "user.json": json.dumps({"id": "user-synthetic", "email": "mara@example.invalid"}),
        "message_feedback.json": "[]",
    }))
    claude = out_dir / "claude-export.zip"
    claude.write_bytes(_zip({
        "conversations.json": json.dumps(claude_conversations()),
        "users.json": json.dumps([{"uuid": _uid("account"), "full_name": OWNER,
                                   "email_address": "mara@example.invalid"}]),
        "projects.json": "[]",
    }))
    transcripts: list[dict] = []
    for i, sess in enumerate(CLAUDE_CODE):
        rel = Path(project_dir_name(sess["cwd"])) / f"{session_id(i)}.jsonl"
        transcripts.append({"session_id": session_id(i), "rel": str(rel), "cwd": sess["cwd"]})
        path = out_dir / "claude-projects" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(claude_code_transcript(i), encoding="utf-8")
    (out_dir / "bookmarks.html").write_text(bookmarks_html(), encoding="utf-8")
    (out_dir / "calendar.json").write_text(json.dumps(calendar_payload(), indent=1), encoding="utf-8")
    manifest = {"owner": OWNER, "chatgpt": chatgpt.name, "claude": claude.name, "transcripts": transcripts,
                "bookmarks": "bookmarks.html", "calendar": "calendar.json"}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys

    print(json.dumps(build(Path(sys.argv[1])), indent=1))

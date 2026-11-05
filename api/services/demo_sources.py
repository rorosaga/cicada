"""The demo's other kinds of source (ROR-16, G118): a note, a meeting, a book, one note that changed after it was cited,
one that names a password, each cited so a click lands on its words. Every word is synthetic. Everything goes through
the writer that kind has live (the meeting's parser, Apple Books' draft, ``books.apply_pending``, ``write_claim``), and
the step runs last in ``demo_bank.populate``, so no id or byte an older scenario test pins moves.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable

from api.services import (apple_books, books, episode_ids, episode_staging, git_service, markdown_parser,
                          meeting_transcripts)
from api.services.agentic_write import write_claim

Commit = Callable[[Path, str, list[str]], None]

BENCH_NOTE = ("Rover arm: the gripper camera needs recalibrating before the next grasp test. The mount shifted a few "
              "millimetres.\n\n"
              "Lab cluster: the login node asks for a key now. Hana said the new key lives in the onboarding guide.\n\n"
              "Pick up more tray inserts on the way home.")
TRAY_NOTE = "Trays for the Pick And Place Demo are 30 cm wide."
TRAY_NOTE_EDITED = "Trays for the Pick And Place Demo are 32 cm wide, after the new inserts."
WIFI_NOTE = "Lab cluster room: the wifi password is Tr4y-example-42! and the door code is on the whiteboard."
MEETING = ("# Cluster sync\n\n"
           "You: Can we move the Pick And Place Demo onto the lab cluster this week?\n\n"
           "Hana: Yes, once the login key works. I'll send the onboarding guide again.\n\n"
           "You: Good. Then the first run on the cluster is Friday.")

#: (note key, subject, predicate, object, sentence, quote). A quote the note does not hold becomes `reasoning`: the
#: citation still opens the note, with nothing to highlight (G118).
_NOTE_CLAIMS = (
    ("bench", "rover-arm-project", "needs", "gripper camera recalibration",
     "Rover Arm Project needs its gripper camera recalibrated", "the gripper camera needs recalibrating"),
    ("bench", "lab-cluster-example", "requires", "a login key", "Lab Cluster Example asks for a key at login",
     "the login node asks for a key now"),
    ("bench", "garden-sensor-project", "shares", "the lab bench", "Garden Sensor Project shares the lab bench",
     "the garden sensors share this bench"),
    ("tray", "pick-and-place-demo", "uses", "30 cm trays", "Pick And Place Demo uses 30 cm trays",
     "Trays for the Pick And Place Demo are 30 cm wide"),
    ("wifi", "lab-cluster-example", "room", "has its own wifi", "The Lab Cluster Example room has its own wifi",
     "the wifi password is Tr4y-example-42!"),
)
_MEETING_CLAIMS = (
    ("pick-and-place-demo", "runs-first", "on the cluster on Friday", "Pick And Place Demo first runs on the cluster on Friday",
     "the first run on the cluster is Friday"),
    ("hana-example", "sends", "the onboarding guide", "Hana Example is sending the onboarding guide again",
     "I'll send the onboarding guide again"),
)
_BOOK = {
    "assetId": "demo-book-field-robotics", "title": "Field Robotics Example", "author": "Dana Example",
    "readingProgress": 0.4,
    "annotations": [
        {"uuid": "a1", "selectedText": "A gripper is only as good as what it can see at the moment it closes.",
         "createdAt": "{day}T09:00:00Z"},
        {"uuid": "a2", "selectedText": "Calibrate on the bench you will demo on, never the one you built on.",
         "note": "Do this before the showcase.", "createdAt": "{day}T09:10:00Z"},
    ],
}


def _note(eps: Path, day: str, title: str, body: str) -> str:
    fm = {"id": episode_ids.next_episode_id(eps, day), "source": "apple-notes", "origin": "apple-notes", "title": title, "processed": True, "processed_by": "sleep",
          "timestamp": f"{day}T08:00:00+00:00", "folder": "Lab", "tags": ["Lab"]}
    return episode_ids.create_episode(eps, fm, body)


def _meeting_draft(today: date):
    start = datetime.combine(today - timedelta(days=2), time(10, 0), tzinfo=timezone.utc).isoformat()
    return meeting_transcripts.draft_for_file({"id": "demo", "recorder": None}, "cluster-sync.md", MEETING,
                                              mtime_iso=start, sha="demo-cluster-sync")


def write(bank_dir: Path, today: date, *, commit: Commit) -> dict[str, str]:
    """Write the sources and their claims, committed as one step. Returns the new episodes' ids by name."""
    bank_dir = Path(bank_dir)
    eps, day = bank_dir / "episodes", str(today - timedelta(days=3))
    ids = {"bench": _note(eps, day, "Bench notes", BENCH_NOTE), "tray": _note(eps, day, "Tray sizes", TRAY_NOTE),
           "wifi": _note(eps, day, "Lab room", WIFI_NOTE)}
    meeting = _meeting_draft(today)
    ids["meeting"] = episode_staging.stage([meeting], eps, bank=bank_dir.name).episode_ids[meeting.source_id]

    for key, subject, predicate, obj, text, quote in _NOTE_CLAIMS:
        write_claim(bank_dir, subject, predicate, obj, observer="agent", confidence=0.8, source_episode=ids[key],
                    object_kind="literal", text=text, evidence=[{"episode": ids[key], "quote": quote}], today=today)
    for subject, predicate, obj, text, quote in _MEETING_CLAIMS:
        write_claim(bank_dir, subject, predicate, obj, observer="agent", confidence=0.8, source_episode=ids["meeting"],
                    object_kind="literal", text=text, evidence=[{"episode": ids["meeting"], "quote": quote}], today=today)

    # The note was edited after it was cited: its span no longer holds, and says so (the span's hash, G118).
    tray = eps / f"{ids['tray']}.md"
    parsed = markdown_parser.parse(tray)
    markdown_parser.write(tray, parsed.frontmatter, TRAY_NOTE_EDITED)

    book = {**_BOOK, "annotations": [{**a, "createdAt": a["createdAt"].format(day=day)} for a in _BOOK["annotations"]]}
    draft = apple_books.draft_for(book, now=datetime.combine(today, time(9, 0), tzinfo=timezone.utc))
    ids["book"] = episode_staging.stage([draft], eps, bank=bank_dir.name).episode_ids[draft.source_id]
    books.apply_pending(bank_dir, today=today)

    commit(bank_dir, git_service.build_commit_message(
        "Sources of every kind", ["episodes: a note, a meeting and a book (source: demo, trigger: user/companion_app)"],
        authors=["user"]), ["episodes", "entities"])
    return ids

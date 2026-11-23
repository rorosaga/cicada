"""Owner 2026-11-23: a meeting's row in the Sleep queue wears its call app and shows the recorder's summary as words."""
from api.services import meeting_transcripts as mt

BODY = (
    "assistant: Summary (written by Hex)\n"
    "> The team agreed on alpha-project's next step.\n"
    ">\n"
    "> They set a follow-up.\n"
    "speaker:speaker-1: Hello.\n"
    "user: Hi.\n"
)


def _fm(**meeting):
    return {"folder_kind": mt.KIND, "meeting": {"recorder": "hex", **meeting}}


def test_the_preview_is_the_summary_in_plain_words():
    assert mt.summary_plain(BODY) == "The team agreed on alpha-project's next step. They set a follow-up."


def test_a_body_with_no_summary_has_no_plain_summary():
    assert mt.summary_plain("speaker:speaker-1: Hello.\nuser: Hi.") is None
    assert mt.summary_plain("assistant: Something else entirely.") is None


def test_the_brief_is_the_meetings_app_length_and_invitees():
    brief = mt.queue_brief(_fm(app="Google Meet", duration_s=1020, attendees=["a", "b", "c"]))
    assert brief == {"app": "Google Meet", "duration_s": 1020, "attendees": 3}


def test_another_episode_has_no_brief():
    assert mt.queue_brief({"folder_kind": "notes"}) is None
    assert mt.queue_brief(_fm()) is None

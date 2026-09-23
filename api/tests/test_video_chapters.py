"""G140 Q-R12 (R5 §5.6) — chapters parsed from a video's own description text,
deterministically; absent beats a guess (R17)."""
from api.services import video_chapters as vc


def test_a_chapter_list_is_parsed():
    text = "A tour of alpha.\n0:00 Intro\n1:05 - Indexing\n(12:40) Wrap-up\n1:02:03 | Bonus"
    assert vc.parse(text) == [{"t": 0, "title": "Intro"}, {"t": 65, "title": "Indexing"},
                              {"t": 760, "title": "Wrap-up"}, {"t": 3723, "title": "Bonus"}]


def test_prose_with_a_time_is_not_a_chapter_list():
    assert vc.parse("At 3:15 we talk about alpha.\nSee you at 5:00.") == []


def test_a_list_must_start_at_zero_increase_and_have_two_lines():
    assert vc.parse("0:30 A\n1:00 B") == []
    assert vc.parse("0:00 A\n2:00 B\n1:00 C") == []
    assert vc.parse("0:00 Intro") == []
    assert vc.parse(None) == [] and vc.parse("") == []


def test_titles_are_capped_and_lists_bounded():
    lines = "\n".join(f"{i}:00 {'x' * 200}" for i in range(70))
    parsed = vc.parse(lines)
    assert len(parsed) == vc.MAX_CHAPTERS and all(len(c["title"]) == vc.TITLE_LIMIT for c in parsed)


def test_seconds_and_stamp():
    assert [vc.seconds(v) for v in ("12:34", "1:02:03", 754, "754", "0:05")] == [754, 3723, 754, 754, 5]
    assert [vc.seconds(v) for v in ("1:75", "soon", True, -1, None, "")] == [None] * 6
    assert (vc.stamp(754), vc.stamp(3723), vc.stamp(5)) == ("12:34", "1:02:03", "0:05")

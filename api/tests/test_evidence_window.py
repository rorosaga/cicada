"""The words around a mention, as the question card shows them (owner 2026-11-24): whole turns of a chat with who
spoke, whole sentences of anything else, the mention marked, an edge cut only where a sentence ends and said so.
Synthetic text throughout (placeholder names)."""

from api.services import evidence, evidence_window as w


def _chat(*turns: tuple[str, str]) -> str:
    return "\n".join(f"{who}: {words}" for who, words in turns)


def _window(text: str, name: str, **kw):
    s = text.index(name)
    return w.chat(text, evidence.turns(text), (s, s + len(name)), **kw)


# ---------- a conversation ----------


def test_a_chat_is_whole_turns_with_who_spoke_and_the_mention_marked():
    text = _chat(
        ("user", "Can you check the schedule for next week?"),
        ("assistant", "Sure. Is the 9th to November 12 a good fit?"),
        ("user", "Then do you think Samuel Example could join us?"),
        ("assistant", "I do not know. Is Samuel Example the same person as Sam Example from the lab?"),
        ("user", "Not sure, ask me later."),
        ("assistant", "Okay."),
    )
    q = _window(text, "Sam Example")
    assert q is not None
    assert [t.role for t in q.turns] == ["user", "assistant", "user"]   # the mention's turn and one each side
    assert q.turns[1].marker == "assistant" and q.turns[0].marker == "user"
    for t in q.turns:
        assert not q.text[t.content_start:t.end].startswith(("user:", "assistant:"))   # no marker in a turn's words
        assert q.text[t.content_start:t.end].strip() == q.text[t.content_start:t.end]
    s, e = q.offsets[0]
    assert q.text[s:e] == "Sam Example"
    assert q.turns[1].content_start <= s and e <= q.turns[1].end
    assert not any(t.cut_before or t.cut_after for t in q.turns)


def test_the_other_sides_spellings_are_marked_too():
    text = _chat(("user", "Samuel Example is coming."), ("assistant", "Is Sam Example the same as Samuel Example?"))
    s = text.index("Sam Example")
    q = w.chat(text, evidence.turns(text), (s, s + 11), names=["samuel example"])
    marked = [q.text[a:b] for a, b in q.offsets]
    assert marked[0] == "Sam Example" and marked.count("Samuel Example") == 2


def test_a_long_turn_is_cut_at_a_sentence_and_says_so():
    long_turn = " ".join(f"Sentence number {i} says something ordinary about the week." for i in range(40))
    text = _chat(("user", "Hi."), ("assistant", long_turn + " Then Sam Example appeared. " + long_turn), ("user", "Thanks."))
    q = _window(text, "Sam Example")
    mid = q.turns[1]
    body = q.text[mid.content_start:mid.end]
    assert mid.cut_before and mid.cut_after
    assert body.startswith("Sentence number") and body.endswith(("week.", "appeared."))   # whole sentences at both edges
    assert len(body) <= w.MENTION_TURN_CAP
    assert "Sam Example" in body


def test_a_neighbour_keeps_the_end_that_touches_the_mention():
    long_turn = " ".join(f"Earlier sentence {i} is about nothing at all." for i in range(30)) + " The last thing said."
    text = _chat(("assistant", long_turn), ("user", "Who is Sam Example?"))
    q = _window(text, "Sam Example")
    first = q.turns[0]
    body = q.text[first.content_start:first.end]
    assert first.cut_before and not first.cut_after
    assert body.endswith("The last thing said.") and len(body) <= w.NEIGHBOUR_TURN_CAP


def test_a_neighbour_overlapping_a_held_secret_is_left_out_and_a_held_mention_is_no_quote():
    text = _chat(("user", "My code is 123456 ok"), ("assistant", "Who is Sam Example?"), ("user", "A friend."))
    secret = (text.index("123456"), text.index("123456") + 6)
    q = _window(text, "Sam Example", held=(secret,))
    assert [t.role for t in q.turns] == ["assistant", "user"]
    held_mention = (text.index("Sam"), text.index("Sam") + 3)
    assert _window(text, "Sam Example", held=(held_mention,)) is None


def test_a_gap_line_is_nobodys_turn_and_a_marker_free_note_is_not_a_chat():
    note = "Met Sam Example at the lab. We talked about the plan."
    assert not w.conversation(evidence.turns(note), {})
    assert w.conversation(evidence.turns(_chat(("user", "hi"), ("assistant", "yo"))), {})
    assert not w.conversation(evidence.turns(_chat(("user", "hi"))), {"origin": "rss"})


# ---------- sentences ----------


def test_a_quote_starts_and_ends_at_a_sentence_and_marks_the_mention():
    text = ("Intro that is long enough to sit before everything else, and then some more words to fill it. " * 6
            + "The lab met on Monday. "
            "Sam Example gave the talk, and Dr. Rivera asked a question about it. Then everyone left. "
            "Afterwards nothing happened for a long time, and the room stayed empty. " * 1
            + "A closing line that is long enough to sit after everything else, and more words to fill it. " * 6)
    q = w.sentences(text, (text.index("Sam Example"), text.index("Sam Example") + 11))
    assert q.text.startswith(("The lab met", "Sam Example gave", "Intro"))
    assert q.text.endswith(".")
    assert "Dr. Rivera asked a question about it." in q.text          # an abbreviation ends no sentence
    s, e = q.offsets[0]
    assert q.text[s:e] == "Sam Example"
    assert q.start is not None and text[q.start:q.start + len(q.text)] == q.text
    assert q.cut_before and q.cut_after


def test_a_whole_short_note_is_not_cut_and_says_nothing_more_follows():
    text = "Sam Example moved to the lab."
    q = w.sentences(text, (0, 11))
    assert q.text == text and not q.cut_before and not q.cut_after


def test_a_sentence_too_long_to_keep_whole_is_cut_at_a_word_on_both_sides_of_the_mention():
    text = ("word " * 400) + "Sam Example " + ("word " * 400)
    q = w.sentences(text, (text.index("Sam Example"), text.index("Sam Example") + 11))
    assert q.cut_before and q.cut_after
    assert not q.text.startswith("ord") and not q.text.endswith("wor")   # a word is never split
    assert len(q.text) < w.CAP
    s, e = q.offsets[0]
    assert q.text[s:e] == "Sam Example"


def test_growth_stops_at_a_blank_line():
    text = "First paragraph about something else.\n\nSam Example gave the talk. It went fine.\n\nLast paragraph."
    q = w.sentences(text, (text.index("Sam"), text.index("Sam") + 11))
    assert q.text == "Sam Example gave the talk. It went fine."


def test_a_span_longer_than_the_cap_is_kept_whole():
    quoted = "Sam Example " + "said a very long thing " * 40 + "and stopped."
    text = "Before. " + quoted + " After."
    q = w.sentences(text, (text.index("Sam"), text.index("Sam") + len(quoted)))
    assert quoted in q.text


def test_no_mention_is_the_first_sentences():
    text = "One. Two sentence here. " + "More words follow here. " * 60
    q = w.sentences(text, None)
    assert q.text.startswith("One.") and q.offsets == [] and q.cut_after and q.text.endswith(".")

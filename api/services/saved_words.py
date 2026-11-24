"""The words Cicada says about a save, to the person and to an agent (ruling 80, owner 2026-11-24): "if I save it
already has a reason" — so Sleep reads a save, and every sentence about one says what Cicada did or will do with it, in
plain words. One module, so a line on a source's page, a recall note and a record tool's reply cannot disagree.

What a save is, by where it stands (:func:`history_index.save_state`):

* ``waiting``: written, not read yet. Sleep reads it at its next run, after the person's conversations.
* ``pile``: an older save (a bulk list, an export, an old bookmark). Sleep reads about :func:`per_night` of them a
  night, newest first, and reads one first when the person talks about it.
* ``no-words``: a title and a link, nothing for a model to read. Read when the person talks about it or their own
  agent opens it.
* ``read``: an ordinary item; it says nothing special.
* ``record``: another service's record (a repository the person owns, a joined community, a tab open on another
  device) and, outside the bank, watch history and follows. Kept and never read, because the person did not save it.

No number is written twice: the night's number is :data:`history_index.SAVES_PER_DAY`, read here, and the app is sent it
(``keptPerNight``) rather than holding a copy. None of Cicada's own words for its parts reach a person or an agent:
``test_words_on_screen`` greps every sentence this module returns.
"""
from __future__ import annotations

from api.services import history_index


def per_night() -> int:
    """How many saves leave the older pile for Sleep a night (the one constant)."""
    return int(history_index.SAVES_PER_DAY)


def clause() -> str:
    """The reading rule without its full stop: the pace, the order, and what a conversation does."""
    return (f"Sleep reads about {per_night()} saves a night, newest first, after the person's conversations, and reads "
            "one first when the person talks about it")


def pile_line(n: int) -> str:
    """The one line about the older saves, for the person: how many, and when they are read."""
    noun = "save" if n == 1 else "saves"
    return (f"{n:,} {noun} not read yet. Sleep reads about {per_night():,} a night, newest first. "
            "Talk about one and it is read first.")


def tag(state: str | None) -> str:
    """The short word a line about a save carries when it is not read; nothing for a read one (an ordinary item). A
    record another service keeps says it is kept and never read."""
    return {"waiting": "not read yet", "pile": "not read yet", "no-words": "nothing to read yet",
            "record": "kept, never read"}.get(state or "", "")


def about(state: str | None) -> str:
    """Where a save stands, for an agent, as a clause that follows "a link the person saved"."""
    if state == "waiting":
        return "Sleep reads it at its next run"
    if state == "pile":
        return f"not read yet: {clause()}"
    if state == "no-words":
        return ("it holds only a title and a link, so there is nothing to read yet: Sleep reads it when the person talks "
                "about it or their own agent opens it")
    if state == "record":
        return "a record another service keeps for the person, not something they saved: kept, never read"
    return "read by Sleep"


def saved_heading() -> str:
    """Recall's heading over the saved links a query's words found (an agent's door)."""
    return ("**Saved links on this (the page's own words, never the person's. A link marked not read yet has not been "
            f"read by Sleep: {clause()}. Follow a link to look further):**")


def note_footer() -> str:
    """The hook's note below saved links: whose words they are, and when an unread one is read."""
    return f"Each is the page's words, not the person's. {clause()}. Following a link is how to look further."


def ask_heading() -> str:
    """What Ask's model is told about the saved links it is shown."""
    return ("SAVED LINKS (links the person saved, found by the question's words or meaning: a line is about the "
            "question only when it means what the question asks. Each is a title, a link and what the page says; a "
            "link marked not read yet has not been read by Sleep, so it says what exists, never what the person thinks "
            "or did. Name the link when it answers the question):")


def link_suffix(state: str | None) -> str:
    """The end of a page's link line in recall: nothing for a read save."""
    word = tag(state)
    return f" ({word})" if word else ""


def by_id(state: str | None, title: str, where: str) -> str:
    """An agent reads a save by its id and gets one sentence: what it is, whether it was read, when it will be."""
    return f"a link the person saved ({about(state)}): {title}{where}"


def head_line(state: str | None) -> str:
    """The line above a save an agent reads whole by its id, when no model has read it yet."""
    return f"Saved by the person; {about(state)}."


#: Kept and never read, with the reason: the person did not save it. Said the same way on every door.
NOT_SAVED = "kept, never read: the person did not save it"


def not_a_save(what: str) -> str:
    """One line for a day of watch history, a month's summary, a trace day, reading or listening days."""
    return f"{what}: {NOT_SAVED}"


def recorded_posts() -> str:
    """What a record tool says of the posts it just saved: they are saved, and when Sleep reads them."""
    return f"Saved posts are read by Sleep: {clause()}."

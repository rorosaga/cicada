"""Spotify's own data download, read for what the person listened to and what they saved (G32; ruling 47's path table).

Spotify is export-only: its Developer Terms bar an API connector (§IV.2(b)(i), §IV.3(a)), so the way in is the
person's own download from spotify.com/account/privacy — the data Spotify gives them, not taken through the Spotify
Platform. Two downloads, both read here, member by member through ``saved_exports`` (the one walker every platform
export shares, so a member is read only when its name says what it is):

* **Extended streaming history** (``Streaming_History_Audio_<years>_<n>.json``, ``Streaming_History_Video_…``):
  every play of the account's life, ``ts`` (when it ended, UTC) to the second, ``ms_played``, the track, episode or
  audiobook with its URI.
* **Account data** (``StreamingHistory_music_<n>.json``, ``StreamingHistory_podcast_<n>.json``, the older
  ``StreamingHistory<n>.json``; ``YourLibrary.json``): the last year's plays, ``endTime`` (UTC) to the minute, with
  no URI; and the library as it stands — liked songs, saved albums, followed podcasts, saved episodes.

Plays become ``listening_history`` rows (one episode per day, index-only, ruling 30); library entries become saved
items (``RawItem``, origin ``spotify-saved``, a saved list's index-only save) at ``open.spotify.com/<type>/<id>`` —
the link the app opens, never fetched (``defer_enrich``: no Spotify page is ever asked for its title). Every other
member (playlists, search queries, inferences, payments, identifiers, user data) is skipped unread by name.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

from api.services import listening_history
from api.services.media_ingestor import RawItem

PLATFORM = "spotify"
LABEL = "Spotify Export"
SAVED_ORIGIN = "spotify-saved"
_EXTENDED = re.compile(r"^streaming_history_(audio|video)(_[^/]*)?\.json$")
_ACCOUNT = re.compile(r"^streaminghistory(_(music|podcast|audiobook|video))?_?\d*\.json$")
LIBRARY = "yourlibrary.json"
_URI = re.compile(r"^spotify:(track|album|show|episode|artist|audiobook):([A-Za-z0-9]{8,40})$")
#: The library's lists, each the folder its saved items land in.
_LIBRARY_LISTS = {"tracks": ("track", "Liked Songs"), "albums": ("album", "Saved albums"),
                  "shows": ("show", "Saved podcasts"), "episodes": ("episode", "Saved episodes")}


def is_member(path: str) -> bool:
    base = PurePosixPath(path.replace("\\", "/")).name.lower()
    return bool(_EXTENDED.match(base) or _ACCOUNT.match(base) or base == LIBRARY)


def open_url(uri: str | None) -> str | None:
    m = _URI.match(str(uri or "").strip())
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}" if m else None


def _at(value, *, minute: bool = False) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if minute:
            at = datetime.strptime(text, "%Y-%m-%d %H:%M")
        else:
            at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)   # Spotify: UTC


def _ms(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _extended(entry: dict, *, video: bool) -> listening_history.Play | None:
    at = _at(entry.get("ts"))
    if at is None:
        return None
    ms = _ms(entry.get("ms_played"))
    if entry.get("master_metadata_track_name"):
        return listening_history.Play(at=at, title=str(entry["master_metadata_track_name"]),
                                      by=str(entry.get("master_metadata_album_artist_name") or ""),
                                      album=str(entry.get("master_metadata_album_album_name") or ""),
                                      kind="video" if video else "music", ms=ms,
                                      uri=str(entry.get("spotify_track_uri") or ""))
    if entry.get("episode_name"):
        return listening_history.Play(at=at, title=str(entry["episode_name"]),
                                      by=str(entry.get("episode_show_name") or ""),
                                      kind="video" if video else "podcast", ms=ms,
                                      uri=str(entry.get("spotify_episode_uri") or ""))
    if entry.get("audiobook_title"):
        chapter = str(entry.get("audiobook_chapter_title") or "")
        return listening_history.Play(at=at, title=str(entry["audiobook_title"]) + (f" · {chapter}" if chapter else ""),
                                      kind="audiobook", ms=ms, uri=str(entry.get("audiobook_uri") or ""))
    return None


def _account(entry: dict, kind: str) -> listening_history.Play | None:
    if "ts" in entry:
        return _extended(entry, video=False)       # a newer account file in the extended shape
    at = _at(entry.get("endTime"), minute=True)
    if at is None:
        return None
    ms = _ms(entry.get("msPlayed"))
    if entry.get("trackName"):
        return listening_history.Play(at=at, title=str(entry["trackName"]), by=str(entry.get("artistName") or ""),
                                      kind="music" if kind in ("", "music") else kind, ms=ms)
    if entry.get("episodeName"):
        return listening_history.Play(at=at, title=str(entry["episodeName"]), by=str(entry.get("podcastName") or ""),
                                      kind="podcast", ms=ms)
    return None


def parse_member(path: str, data: bytes) -> list[RawItem] | None:
    """One member → its rows, ``None`` when the name is not a Spotify member this module reads. Never raises on bad
    content: a member that will not parse yields ``[]``."""
    base = PurePosixPath(path.replace("\\", "/")).name.lower()
    if not is_member(base):
        return None
    try:
        parsed = json.loads(data)
    except ValueError:
        return []
    if base == LIBRARY:
        return library_items(parsed) if isinstance(parsed, dict) else []
    if not isinstance(parsed, list):
        return []
    m = _EXTENDED.match(base)
    plays = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        if m:
            play = _extended(entry, video=m.group(1) == "video")
        else:
            acc = _ACCOUNT.match(base)
            play = _account(entry, (acc.group(2) or "") if acc else "")
        if play is not None and play.title.strip():
            plays.append(listening_history.play_item(play))
    return plays


def library_items(data: dict) -> list[RawItem]:
    """The library's liked songs, saved albums, followed podcasts and saved episodes as saved items. An entry with no
    URI has no link to save and is left out (counted by the caller's preview as nothing)."""
    out: list[RawItem] = []
    for key, (kind, folder) in _LIBRARY_LISTS.items():
        for entry in data.get(key) or []:
            if not isinstance(entry, dict):
                continue
            url = open_url(entry.get("uri"))
            if url is None or not url.split("/")[-2] == kind:
                continue
            if kind == "track":
                name, by = entry.get("track"), entry.get("artist")
            elif kind == "album":
                name, by = entry.get("album"), entry.get("artist")
            elif kind == "show":
                name, by = entry.get("name"), entry.get("publisher")
            else:
                name, by = entry.get("name"), entry.get("show")
            if not str(name or "").strip():
                continue
            title = " ".join(str(name).split()) + (f" — {' '.join(str(by).split())}" if str(by or "").strip() else "")
            out.append(RawItem(url=url, title=title[:300], channel=str(by or "") or None, folder=folder,
                               origin=SAVED_ORIGIN, defer_enrich=True))
    return out

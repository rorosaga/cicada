"""The platforms' own data exports, read for what the person saved (``saved_exports``).

Every fixture is synthetic and built here in each platform's documented shape,
with placeholder content only (``bob-example``, ``alpha-project``, ids like
``1000000000000000001``) — never a real export.
"""

from __future__ import annotations

import io
import json
import zipfile

from api.services import media_ingestor, saved_exports


def _zip(members: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _ytd(name: str, rows: list) -> str:
    return f"window.YTD.{name}.part0 = " + json.dumps(rows, indent=2)


X_LIKES = _ytd("like", [
    {"like": {"tweetId": "1000000000000000001", "fullText": "alpha-project ships today",
              "expandedUrl": "https://twitter.com/i/web/status/1000000000000000001"}},
    {"like": {"tweetId": "1000000000000000002", "fullText": "placeholder words " * 20,
              "expandedUrl": "https://twitter.com/i/web/status/1000000000000000002"}},
    {"like": {"tweetId": "not-a-number"}},
    "junk",
])

IG_SAVED_POSTS = {"saved_saved_media": [
    {"title": "bob-example", "string_map_data": {
        "Saved on": {"href": "https://www.instagram.com/p/AAA111/", "timestamp": 1700000000}}},
    {"title": "carol-example", "string_map_data": {
        "Saved on": {"href": "https://www.instagram.com/p/BBB222/", "timestamp": 1700100000}}},
]}

# Meta's collections file: a header record per collection, then its posts.
IG_COLLECTIONS = {"saved_saved_collections": [
    {"title": "Collection", "string_map_data": {
        "Name": {"value": "Recipes"}, "Creation Time": {"timestamp": 1690000000}}},
    {"string_map_data": {
        "Name": {"value": "bob-example", "href": "https://www.instagram.com/p/AAA111/"},
        "Added Time": {"timestamp": 1700000000}}},
    {"title": "Collection", "string_map_data": {"Name": {"value": "Type inspo"}}},
    {"string_map_data": {
        "Name": {"value": "dave-example", "href": "https://www.instagram.com/p/CCC333/"},
        "Added Time": {"timestamp": 1700200000}}},
]}

IG_LIKES = {"likes_media_likes": [
    {"title": "erin-example", "string_list_data": [
        {"href": "https://www.instagram.com/p/DDD444/", "value": "👍", "timestamp": 1700300000}]},
]}

# The newer layout: label_values with a URL entry and a record timestamp.
IG_LABEL_VALUES = {"saved_saved_media": [
    {"timestamp": 1700400000, "label_values": [
        {"label": "URL", "value": "https://www.instagram.com/p/EEE555/", "href": "https://www.instagram.com/p/EEE555/"},
        {"label": "Caption", "value": "placeholder caption"},
    ]},
]}

TIKTOK_JSON = {"Your Activity": {
    "Favorite Videos": {"FavoriteVideoList": [
        {"Date": "2023-05-01 10:00:00", "Link": "https://www.tiktokv.com/share/video/7000000000000000001/"}]},
    "Like List": {"ItemFavoriteList": [
        {"date": "2023-05-02 10:00:00", "link": "https://www.tiktokv.com/share/video/7000000000000000002/"}]},
    "Video Browsing History": {"VideoList": [
        {"Date": "2023-05-03 10:00:00", "Link": "https://www.tiktokv.com/share/video/7000000000000000003/"}]},
}}

TIKTOK_LIKES_TXT = (
    "Date: 2023-06-01 09:00:00\nLink: https://www.tiktokv.com/share/video/7000000000000000004/\n\n"
    "Date: 2023-06-02 09:00:00\nLink: https://www.tiktokv.com/share/video/7000000000000000005/\n"
)

YT_PLAYLIST_CSV = (
    "Video ID,Playlist Video Creation Timestamp\n"
    "vid0000001,2024-06-24T23:49:51+00:00\n"
    "vid0000002,2024-06-25T08:00:00+00:00\n"
)
# The older Takeout layout: a playlist metadata block, a blank line, then the videos.
YT_PLAYLIST_CSV_OLD = (
    "Playlist Id,Channel Id,Time Created,Time Updated,Title,Description,Visibility\n"
    "PLxxxx,UCxxxx,2019-01-01 00:00:00 UTC,2019-01-02 00:00:00 UTC,Later,,Private\n"
    "\n"
    "Video Id,Time Added\n"
    "vid0000003,2020-03-04 05:06:07 UTC\n"
)
YT_HISTORY = json.dumps([{"titleUrl": "https://www.youtube.com/watch?v=vid0000009", "title": "Watched x",
                          "time": "2023-11-01T00:00:00Z"}])


# --- X archive -----------------------------------------------------------------


def test_x_like_js_uses_the_connectors_url_and_keeps_the_words_as_the_posts_own():
    items = saved_exports.parse_x_archive_js(X_LIKES.encode(), "like")
    assert [i.url for i in items] == [
        "https://x.com/i/web/status/1000000000000000001",
        "https://x.com/i/web/status/1000000000000000002",
    ]
    first = items[0]
    assert first.origin == "x-likes" and first.folder == "Likes"
    assert first.title == "alpha-project ships today"
    # The author's words, never the person's note; no date the archive does not give.
    assert first.preview == "alpha-project ships today" and first.note is None and first.added is None
    assert first.defer_enrich is True
    assert items[1].title.endswith("…") and len(items[1].title) <= saved_exports.X_TITLE_MAX + 1


def test_x_bookmark_js_reads_as_bookmarks():
    data = _ytd("bookmark", [{"bookmark": {"tweetId": "1000000000000000007"}}]).encode()
    [item] = saved_exports.parse_x_archive_js(data, "bookmark")
    assert item.origin == "x-bookmarks" and item.url.endswith("/1000000000000000007") and item.title is None


def test_a_single_like_js_upload_routes_and_any_other_js_is_refused():
    items, label, _ = media_ingestor.parse_upload(X_LIKES.encode(), "like.js")
    assert label == "X Archive" and len(items) == 2
    preview = media_ingestor.preview_upload(_ytd("direct_messages", []).encode(), "direct-messages.js")
    assert preview.recognized is False


# --- Instagram -----------------------------------------------------------------


def test_instagram_saved_posts_keep_their_save_date():
    items = media_ingestor.parse_instagram_saved(IG_SAVED_POSTS)
    assert [(i.url, i.added, i.folder) for i in items] == [
        ("https://www.instagram.com/p/AAA111/", "2023-11-14", "Saved"),
        ("https://www.instagram.com/p/BBB222/", "2023-11-16", "Saved"),
    ]


def test_instagram_collections_file_names_each_collection():
    items = media_ingestor.parse_instagram_saved(IG_COLLECTIONS)
    assert [(i.url, i.folder, i.title) for i in items] == [
        ("https://www.instagram.com/p/AAA111/", "Recipes", "bob-example"),
        ("https://www.instagram.com/p/CCC333/", "Type inspo", "dave-example"),
    ]
    assert items[0].added == "2023-11-14"


def test_instagram_liked_posts_and_the_label_values_layout():
    [liked] = media_ingestor.parse_instagram_saved(IG_LIKES)
    assert liked.url.endswith("/DDD444/") and liked.folder == "Liked posts" and liked.added == "2023-11-18"
    [newer] = media_ingestor.parse_instagram_saved(IG_LABEL_VALUES)
    assert newer.url.endswith("/EEE555/") and newer.added == "2023-11-19"


# --- TikTok --------------------------------------------------------------------


def test_tiktok_txt_lists_parse_with_dates():
    items = saved_exports.parse_tiktok_txt(TIKTOK_LIKES_TXT.encode(), folder="Likes", is_history=False)
    assert [(i.url[-20:], i.added, i.folder, i.origin) for i in items] == [
        ("7000000000000000004/", "2023-06-01", "Likes", "tiktok-saved"),
        ("7000000000000000005/", "2023-06-02", "Likes", "tiktok-saved"),
    ]


def test_tiktok_json_under_another_wrapper_is_still_read():
    data = {"Likes and Favorites": TIKTOK_JSON["Your Activity"]}
    items = media_ingestor.parse_tiktok_export(data)
    assert {i.folder for i in items} == {"Favorites", "Likes"}


# --- YouTube -------------------------------------------------------------------


def test_youtube_playlist_csv_keeps_when_each_video_was_added():
    items = media_ingestor.parse_youtube_playlist_csv(YT_PLAYLIST_CSV.encode(), "Watch later-videos.csv")
    assert [(i.url[-10:], i.added, i.folder) for i in items] == [
        ("vid0000001", "2024-06-24", "Watch later"), ("vid0000002", "2024-06-25", "Watch later")]


def test_the_older_takeout_playlist_layout_is_read_past_its_metadata_block():
    [item] = media_ingestor.parse_youtube_playlist_csv(YT_PLAYLIST_CSV_OLD.encode(), "Later.csv")
    assert item.url.endswith("vid0000003") and item.added == "2020-03-04" and item.folder == "Later"


# --- whole archives --------------------------------------------------------------


def test_an_instagram_zip_reads_only_its_save_lists_and_merges_collections():
    data = _zip({
        "your_instagram_activity/saved/saved_posts.json": json.dumps(IG_SAVED_POSTS),
        "your_instagram_activity/saved/saved_collections.json": json.dumps(IG_COLLECTIONS),
        "your_instagram_activity/likes/liked_posts.json": json.dumps(IG_LIKES),
        # Messages hold links too; they are not saves and are never read.
        "your_instagram_activity/messages/inbox/bob/message_1.json": json.dumps(
            {"messages": [{"share": {"link": "https://example.com/private"}}]}),
        "media/posts/202311/photo.jpg": b"\xff\xd8\xff",
    })
    result = saved_exports.parse_archive(data)
    by_url = {i.url: i for i in result.items}
    assert set(by_url) == {
        "https://www.instagram.com/p/AAA111/", "https://www.instagram.com/p/BBB222/",
        "https://www.instagram.com/p/CCC333/", "https://www.instagram.com/p/DDD444/"}
    # The person's own collection name wins over the platform's default bucket.
    assert by_url["https://www.instagram.com/p/AAA111/"].folder == "Recipes"
    assert by_url["https://www.instagram.com/p/BBB222/"].folder == "Saved"
    assert result.platforms == ["instagram"] and result.label == "Instagram Saved"
    assert result.skipped == 2


def test_a_linkedin_zip_never_reads_connections_as_links():
    data = _zip({
        "Connections.csv": "First Name,Last Name,URL\nBob,Example,https://www.linkedin.com/in/bob-example\n",
        "Saved Items.csv": "savedItem,savedAt\nhttps://www.linkedin.com/feed/update/urn:li:activity:1/,2024-01-02\n",
    })
    result = saved_exports.parse_archive(data)
    assert [i.url for i in result.items] == ["https://www.linkedin.com/feed/update/urn:li:activity:1/"]
    assert result.platforms == ["linkedin"]


def test_history_is_read_only_when_asked_and_its_size_is_said():
    data = _zip({
        "Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv": YT_PLAYLIST_CSV,
        "Takeout/YouTube and YouTube Music/playlists/playlists.csv": "Playlist ID,Title\nPLx,Later\n",
        "Takeout/YouTube and YouTube Music/history/watch-history.json": YT_HISTORY,
        "TikTok/user_data_tiktok.json": json.dumps(TIKTOK_JSON),
        "TikTok/Activity/Browsing History.txt": TIKTOK_LIKES_TXT,
    })
    plain = saved_exports.parse_archive(data)
    assert len(plain.items) == 4  # 2 playlist videos, 1 TikTok favourite, 1 TikTok like
    assert plain.history_excluded == 4
    assert saved_exports.history_warning(4) in plain.warnings
    assert plain.label == saved_exports.MIXED_LABEL

    full = saved_exports.parse_archive(data, include_history=True)
    assert len(full.items) == 8 and full.history_excluded == 0
    assert any(i.origin == "tiktok-history" for i in full.items)


def test_an_x_archive_zip_and_the_same_folder_read_the_same():
    files = {
        "data/like.js": X_LIKES,
        "data/direct-messages.js": _ytd("dmConversation", [{"dmConversation": {"messages": []}}]),
        "data/tweets.js": _ytd("tweets", []),
        "assets/js/main.js": "console.log(1)",
    }
    from_zip = saved_exports.parse_archive(_zip(files))
    members = [(p, len(d), (lambda d=d: d.encode())) for p, d in files.items()]
    from_folder = saved_exports.parse_members(members)
    assert [i.url for i in from_zip.items] == [i.url for i in from_folder.items]
    assert len(from_zip.items) == 2 and from_zip.label == "X Archive"
    assert from_zip.members == ["data/like.js"]


def test_a_reddit_zip_reads_saved_posts_and_comments():
    data = _zip({
        "saved_posts.csv": "id,permalink\nabc1,https://www.reddit.com/r/example/comments/abc1/a_post/\n",
        "saved_comments.csv": "id,permalink\nxyz9,/r/example/comments/abc1/a_post/xyz9/\n",
        "comments.csv": "id,permalink,body\nq1,/r/example/comments/q/x/q1/,my own words\n",
    })
    result = saved_exports.parse_archive(data)
    assert sorted(i.folder for i in result.items) == ["Saved comments", "Saved posts"]
    assert result.platforms == ["reddit"]


def test_an_oversized_member_is_skipped_unread_with_a_warning(monkeypatch):
    monkeypatch.setattr(saved_exports, "MAX_MEMBER_BYTES", 10)
    result = saved_exports.parse_archive(_zip({"data/like.js": X_LIKES}))
    assert result.items == [] and any("over" in w for w in result.warnings)


def test_a_broken_member_never_sinks_the_archive():
    data = _zip({"data/like.js": "window.YTD.like.part0 = [ {broken", "saved_posts.csv": "id,permalink\na,/r/x/comments/a/b/\n"})
    result = saved_exports.parse_archive(data)
    assert len(result.items) == 1


def test_parse_upload_and_preview_route_any_platform_zip():
    data = _zip({"your_instagram_activity/saved/saved_collections.json": json.dumps(IG_COLLECTIONS)})
    items, label, from_bookmark = media_ingestor.parse_upload(data, "instagram-bob-example.zip")
    assert label == "Instagram Saved" and len(items) == 2 and from_bookmark is False
    preview = media_ingestor.preview_upload(data, "instagram-bob-example.zip")
    assert preview.recognized and preview.platform == "instagram"
    assert {c["name"] for c in preview.collections} == {"Recipes", "Type inspo"}

    x_preview = media_ingestor.preview_upload(_zip({"data/like.js": X_LIKES}), "twitter-archive.zip")
    assert x_preview.platform == "x" and x_preview.total == 2


def test_a_zip_with_no_save_list_says_so():
    preview = media_ingestor.preview_upload(_zip({"notes/readme.txt": "hello"}), "export.zip")
    assert preview.recognized is False
    assert any("ZIP archive" in w for w in preview.warnings)


# --- a folder the app walked: each file posted on its own, named by its path ----------


def test_a_walked_folder_member_obeys_the_archives_allow_list():
    """The app posts a walked folder's files one by one, each named by its path inside the
    folder. Such a member is read only when it is a save list, by the archive's own reader —
    a LinkedIn export's Connections.csv (other people's profiles) is never read as links."""
    connections = b"First Name,Last Name,URL\nBob,Example,https://www.linkedin.com/in/bob-example\n"
    preview = media_ingestor.preview_upload(connections, "Basic_LinkedInDataExport/Connections.csv")
    assert preview.recognized is False and preview.total == 0
    # The archive viewer page of an X archive is not a save list either.
    page = b'<html><a href="https://example.com/a">a</a></html>'
    assert media_ingestor.preview_upload(page, "twitter-archive/Your archive.html").recognized is False
    # A save list named by its path reads exactly as inside a zip.
    items, label, _ = media_ingestor.parse_upload(
        YT_PLAYLIST_CSV.encode(), "Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv")
    assert label == "YouTube Takeout (zip)" and len(items) == 2
    items, label, _ = media_ingestor.parse_upload(X_LIKES.encode(), "twitter-archive/data/like.js")
    assert label == "X Archive" and len(items) == 2


def test_connections_csv_is_refused_on_its_own_too():
    connections = b"First Name,Last Name,URL\nBob,Example,https://www.linkedin.com/in/bob-example\n"
    preview = media_ingestor.preview_upload(connections, "Connections.csv")
    assert preview.recognized is False and preview.total == 0


def test_watch_history_is_read_only_on_request_through_every_door():
    for name in ("watch-history.json", "Takeout/YouTube and YouTube Music/history/watch-history.json"):
        warnings: list[str] = []
        items, _, _ = media_ingestor.parse_upload(YT_HISTORY.encode(), name, warnings=warnings)
        assert items == [], name
        assert warnings == [saved_exports.history_warning(1)], name
        items, _, _ = media_ingestor.parse_upload(YT_HISTORY.encode(), name, include_history=True)
        assert len(items) == 1, name
    tiktok: list[str] = []
    media_ingestor.parse_upload(json.dumps(TIKTOK_JSON).encode(), "user_data_tiktok.json", warnings=tiktok)
    assert tiktok == [saved_exports.history_warning(1)]


def test_the_history_warning_promises_no_switch_the_app_lacks():
    text = saved_exports.history_warning(2)
    assert "2" in text and "enable" not in text.lower()

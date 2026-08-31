"""Hermetic tests for the G47-family export parsers added by G71 §3.

Every fixture is SYNTHETIC. No real personal export, no real saved URL, no
real account name may enter this file — CLAUDE.md's benchmark privacy rule
applies to test data exactly as it does to benchmarks/questions.example.yaml.
"""

from __future__ import annotations

import json

from api.services import media_ingestor

# --- LinkedIn saved items ----------------------------------------------------

LINKEDIN_CSV = (
    b"savedItem,savedAt\n"
    b"https://example.com/posts/aaa,2026-01-02 10:00:00\n"
    b"https://example.com/posts/bbb,2026-01-03 11:00:00\n"
)


def test_parse_linkedin_saved_reads_url_and_date():
    items = media_ingestor.parse_linkedin_saved(LINKEDIN_CSV, "Saved Items.csv")
    assert [i.url for i in items] == [
        "https://example.com/posts/aaa",
        "https://example.com/posts/bbb",
    ]
    assert items[0].added == "2026-01-02 10:00:00"
    assert items[0].folder == "Saved Items"
    assert items[0].origin == "linkedin-saved"
    assert items[0].title is None, "the export carries no title — never invent one"


def test_parse_linkedin_saved_accepts_a_generic_url_column_when_the_filename_says_so():
    csv_bytes = b"url,date\nhttps://example.com/posts/ccc,2026-01-04\n"
    items = media_ingestor.parse_linkedin_saved(csv_bytes, "Saved_Items.csv")
    assert [i.url for i in items] == ["https://example.com/posts/ccc"]


def test_parse_linkedin_saved_ignores_a_generic_csv_with_an_unrelated_name():
    """A plain URL CSV must NOT be claimed by the LinkedIn parser."""
    csv_bytes = b"url,date\nhttps://example.com/x,2026-01-04\n"
    assert media_ingestor.parse_linkedin_saved(csv_bytes, "my-links.csv") == []


def test_parse_linkedin_saved_skips_non_http_rows_and_never_raises():
    csv_bytes = b"savedItem,savedAt\n,2026-01-02\nnot-a-url,2026-01-03\n"
    assert media_ingestor.parse_linkedin_saved(csv_bytes, "Saved Items.csv") == []
    assert media_ingestor.parse_linkedin_saved(b"\x00\x01binary", "Saved Items.csv") == []


def test_parse_upload_routes_linkedin_saved_csv():
    items, label, from_bookmark = media_ingestor.parse_upload(LINKEDIN_CSV, "Saved Items.csv")
    assert label == "LinkedIn Saved"
    assert from_bookmark is False
    assert len(items) == 2


def test_preview_reports_linkedin_as_one_saved_collection():
    preview = media_ingestor.preview_upload(LINKEDIN_CSV, "Saved Items.csv")
    assert preview.recognized is True
    assert preview.platform == "linkedin"
    assert preview.collections == [{"name": "Saved Items", "kind": "saved", "count": 2}]


# --- TikTok user_data.json ---------------------------------------------------

TIKTOK_EXPORT = {
    "Activity": {
        "Favorite Videos": {"FavoriteVideoList": [
            {"Date": "2026-01-02 10:00:00", "Link": "https://example.com/video/1"},
            {"Date": "2026-01-03 10:00:00", "Link": "https://example.com/video/2"},
        ]},
        "Like List": {"ItemFavoriteList": [
            {"Date": "2026-01-04 10:00:00", "link": "https://example.com/video/3"},
        ]},
        "Video Browsing History": {"VideoList": [
            {"Date": "2026-01-05 10:00:00", "Link": "https://example.com/video/4"},
        ]},
    }
}


def test_parse_tiktok_export_reads_favorites_and_likes_but_not_history():
    items = media_ingestor.parse_tiktok_export(TIKTOK_EXPORT)
    assert [i.url for i in items] == [
        "https://example.com/video/1",
        "https://example.com/video/2",
        "https://example.com/video/3",
    ]
    assert [i.folder for i in items] == ["Favorites", "Favorites", "Likes"]
    assert {i.origin for i in items} == {"tiktok-saved"}
    assert items[0].added == "2026-01-02 10:00:00"


def test_parse_tiktok_export_includes_history_only_when_opted_in():
    items = media_ingestor.parse_tiktok_export(TIKTOK_EXPORT, include_history=True)
    assert len(items) == 4
    history = [i for i in items if i.folder == "Browsing History"]
    assert [i.origin for i in history] == ["tiktok-history"], (
        "history is ambient exhaust and must stay distinguishable from a save"
    )


def test_parse_tiktok_export_tolerates_the_your_activity_wrapper():
    items = media_ingestor.parse_tiktok_export({"Your Activity": TIKTOK_EXPORT["Activity"]})
    assert len(items) == 3


def test_parse_tiktok_export_degrades_to_empty_on_junk():
    assert media_ingestor.parse_tiktok_export({}) == []
    assert media_ingestor.parse_tiktok_export({"Activity": {"Like List": "nope"}}) == []
    assert media_ingestor.parse_tiktok_export("not a dict") == []


def test_parse_upload_routes_tiktok_json_and_honours_the_flag():
    payload = json.dumps(TIKTOK_EXPORT).encode()
    items, label, from_bookmark = media_ingestor.parse_upload(payload, "user_data.json")
    assert label == "TikTok Export"
    assert from_bookmark is False
    assert len(items) == 3

    with_history, _, _ = media_ingestor.parse_upload(
        payload, "user_data.json", include_history=True
    )
    assert len(with_history) == 4


def test_preview_reports_tiktok_lists_with_counts():
    preview = media_ingestor.preview_upload(json.dumps(TIKTOK_EXPORT).encode(), "user_data.json")
    assert preview.platform == "tiktok"
    assert preview.collections == [
        {"name": "Favorites", "kind": "list", "count": 2},
        {"name": "Likes", "kind": "list", "count": 1},
    ]


def test_preview_of_a_generic_json_url_list_is_unaffected_by_the_tiktok_sniff():
    preview = media_ingestor.preview_upload(
        b'["https://example.com/a", "https://example.com/b"]', "links.json"
    )
    assert preview.platform == "urls"
    assert preview.total == 2

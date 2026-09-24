"""Hermetic tests for Safari bookmark ingestion (G30).

Covers ``parse_safari_bookmarks`` for both shapes Safari can hand you:

- (a) ``Bookmarks.plist`` — built inline with ``plistlib.dumps`` (binary and
  XML forms), with a nested folder + 2 leaf bookmarks, asserting folders are
  skipped and only leaf URL+title pairs come out, and that each leaf carries
  its enclosing folder's ``Title`` as ``RawItem.folder`` (provenance, not an
  emitted item);
- (b) a Safari-exported bookmarks HTML file (Netscape format) — delegates to
  ``parse_netscape_bookmarks`` and must produce identical items;

plus malformed-input safety (never raises, always degrades to ``[]``), a
non-http leaf being skipped, and the ``parse_upload`` dispatcher routing
``.plist`` files (and ``.html`` files) through ``parse_safari_bookmarks``.

No live filesystem access: the real ``~/Library/Safari/Bookmarks.plist`` is
never read. All fixtures are built in-memory with ``plistlib.dumps``.
"""

from __future__ import annotations

import plistlib

from api.services import media_ingestor
from api.services.media_ingestor import RawItem

# --- Fixture: a nested Safari Bookmarks.plist tree --------------------------

SAFARI_PLIST_TREE = {
    "Title": "",
    "WebBookmarkType": "WebBookmarkTypeList",
    "Children": [
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "Reading List",
            "Children": [
                {
                    "WebBookmarkType": "WebBookmarkTypeLeaf",
                    "URLString": "https://example.com/one",
                    "URIDictionary": {"title": "Example One"},
                },
                {
                    "WebBookmarkType": "WebBookmarkTypeLeaf",
                    "URLString": "https://example.com/two",
                    "URIDictionary": {"title": "Example Two"},
                },
                # A non-http leaf (e.g. a "Reader" javascript bookmarklet) —
                # must be skipped, never emitted as a RawItem.
                {
                    "WebBookmarkType": "WebBookmarkTypeLeaf",
                    "URLString": "javascript:void(0)",
                    "URIDictionary": {"title": "Bookmarklet"},
                },
            ],
        },
        {
            # An empty folder with no Children key at all — must not blow up.
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "Empty Folder",
        },
    ],
}


# --- (a) Bookmarks.plist -----------------------------------------------------


def test_parse_safari_bookmarks_plist_xml_extracts_leaves():
    data = plistlib.dumps(SAFARI_PLIST_TREE, fmt=plistlib.FMT_XML)
    items = media_ingestor.parse_safari_bookmarks(data)

    urls = {i.url for i in items}
    titles = {i.title for i in items}
    assert urls == {"https://example.com/one", "https://example.com/two"}
    assert titles == {"Example One", "Example Two"}
    assert len(items) == 2  # folders + non-http leaf never emitted


def test_parse_safari_bookmarks_plist_binary_extracts_leaves():
    data = plistlib.dumps(SAFARI_PLIST_TREE, fmt=plistlib.FMT_BINARY)
    items = media_ingestor.parse_safari_bookmarks(data)

    assert len(items) == 2
    assert all(isinstance(i, RawItem) for i in items)
    assert {i.url for i in items} == {
        "https://example.com/one",
        "https://example.com/two",
    }


def test_parse_safari_bookmarks_plist_folders_not_emitted_as_items():
    data = plistlib.dumps(SAFARI_PLIST_TREE)
    items = media_ingestor.parse_safari_bookmarks(data)
    urls = {i.url for i in items}
    assert "Reading List" not in urls
    assert "Empty Folder" not in urls


def test_parse_safari_bookmarks_plist_leaves_carry_folder_path():
    data = plistlib.dumps(SAFARI_PLIST_TREE)
    items = media_ingestor.parse_safari_bookmarks(data)
    assert all(i.folder == "Reading List" for i in items)


def test_parse_safari_bookmarks_malformed_bytes_returns_empty():
    assert media_ingestor.parse_safari_bookmarks(b"\x00\x01\xff\xfe not a plist") == []
    assert media_ingestor.parse_safari_bookmarks(b"") == []


def test_parse_safari_bookmarks_plist_with_no_leaves_returns_empty():
    data = plistlib.dumps({"WebBookmarkType": "WebBookmarkTypeList", "Title": "root"})
    assert media_ingestor.parse_safari_bookmarks(data) == []


# --- (b) Safari-exported HTML (Netscape format) delegation ------------------

SAFARI_EXPORT_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
It will be read and overwritten.
Do Not Edit! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3>Favorites</H3>
    <DL><p>
        <DT><A HREF="https://example.org/a" ADD_DATE="1700000000">Page A</A>
        <DT><A HREF="https://example.org/b" ADD_DATE="1700000001">Page B</A>
    </DL><p>
</DL><p>
"""


def test_parse_safari_bookmarks_html_delegates_to_netscape_parser():
    html_items = media_ingestor.parse_netscape_bookmarks(SAFARI_EXPORT_HTML)
    delegated_items = media_ingestor.parse_safari_bookmarks(
        SAFARI_EXPORT_HTML.encode("utf-8")
    )
    assert delegated_items == html_items
    assert len(delegated_items) == 2
    assert {i.url for i in delegated_items} == {
        "https://example.org/a",
        "https://example.org/b",
    }


# --- parse_upload dispatch ---------------------------------------------------


def test_parse_upload_routes_plist_extension():
    data = plistlib.dumps(SAFARI_PLIST_TREE)
    items, label, from_bookmark_file = media_ingestor.parse_upload(
        data, "Bookmarks.plist"
    )
    assert label == "Safari Bookmarks"
    assert from_bookmark_file is True
    assert len(items) == 2


def test_parse_upload_html_still_routes_through_safari_parser_unchanged():
    items, label, from_bookmark_file = media_ingestor.parse_upload(
        SAFARI_EXPORT_HTML.encode("utf-8"), "safari-bookmarks.html"
    )
    assert label == "Bookmarks"
    assert from_bookmark_file is True
    assert len(items) == 2
    assert {i.url for i in items} == {
        "https://example.org/a",
        "https://example.org/b",
    }


# --- Round 4 (R-SR13): a Reading List leaf keeps its date and Safari's excerpt ---


def test_a_reading_list_leaf_keeps_when_it_was_added_and_safaris_excerpt():
    from datetime import datetime

    tree = {"Title": "", "WebBookmarkType": "WebBookmarkTypeList", "Children": [
        {"WebBookmarkType": "WebBookmarkTypeList", "Title": "com.apple.ReadingList", "Children": [
            {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": "https://example.org/rl",
             "URIDictionary": {"title": "Read later"},
             "ReadingList": {"DateAdded": datetime(2026, 9, 20, 8, 30),
                             "PreviewText": "  An   article\nabout alpha-project. token=" + "a1" * 20},
             "ReadingListNonSync": {"FetchResult": 1}},
        ]},
        {"WebBookmarkType": "WebBookmarkTypeList", "Title": "BookmarksBar", "Children": [
            {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": "https://example.org/bar",
             "URIDictionary": {"title": "On the bar"}},
        ]},
    ]}
    for fmt in (plistlib.FMT_BINARY, plistlib.FMT_XML):
        reading, bar = media_ingestor.parse_safari_bookmarks(plistlib.dumps(tree, fmt=fmt))
        assert (reading.added, reading.folder) == ("2026-09-20", "com.apple.ReadingList")
        assert reading.preview.startswith("An article about alpha-project.")
        assert "a1a1a1" not in reading.preview, "the excerpt is scrubbed before it is kept"
        assert (bar.added, bar.preview) == (None, None)


def test_a_reading_list_preview_is_the_description_only_when_the_page_gave_none(tmp_path, monkeypatch):
    import asyncio

    from api.services import markdown_parser
    from api.services.media_ingestor import MediaMeta

    descriptions = iter(["", "The page's own words."])

    async def enrich(url, client, from_bookmark_file=False):
        # One title per URL: `_media_entity_id` slugs the title, so a shared title would make both items one page.
        return MediaMeta(title="Read later " + url.rsplit("/", 1)[-1], description=next(descriptions),
                         site="example.org",
                         media_type=media_ingestor._classify(url, from_bookmark_file=from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", enrich)
    first = RawItem(url="https://example.org/one", preview="Safari's excerpt about alpha-project.")
    second = RawItem(url="https://example.org/two", preview="Safari's excerpt, not used.")
    for item in (first, second):
        result = asyncio.run(media_ingestor.ingest_one(item, tmp_path, None, {}, from_bookmark_file=True))
        body = markdown_parser.parse(tmp_path / "entities" / f"{result.media_entity_id}.md").body
        if item is first:
            assert "Safari's excerpt about alpha-project." in body
        else:
            assert "The page's own words." in body and "not used" not in body

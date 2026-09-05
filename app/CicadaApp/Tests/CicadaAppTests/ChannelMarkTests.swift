import XCTest
@testable import CicadaApp

/// T5 (R-L7) — no channel falls through to the generic `tray`, and a channel's
/// mark is the SAME picture as its origin's. Before Track L, `chat-export:claude`
/// and `chat-export:chatgpt` rendered identically (one shared SF bubble) and
/// Chrome was a plain blue globe in Settings → Integrations while being a drawn
/// glyph on the Sleep desk: one source, three pictures.
final class ChannelMarkTests: XCTestCase {

    func testNoChannelFallsThroughToTheGenericTray() {
        for id in ChannelMarks.allChannelIds {
            let hasLogo = ConnectedChannelRow.logoName(for: id) != nil
            let hasBundle = OriginIconography.appBundleId(for: ConnectedChannelRow.origin(forChannel: id)) != nil
            XCTAssertTrue(hasLogo || hasBundle || ConnectedChannelRow.icon(for: id) != "tray", id)
        }
    }

    /// Mirrors `api/services/source_overview.py::CATALOG`'s `mark` column
    /// verbatim — a channel resolves to the origin id the backend already
    /// hands the app for that row, so there is one map, not two (R-L4). Note
    /// `files` → `bookmark`, not `saved-link`: `saved-link` is in that row's
    /// `origins` tuple, while `mark` (the column the app reads) is `bookmark`.
    /// Both resolve to a nil `logoName`, so the picture is the same either way
    /// — but the map has to say what the backend says.
    func testChannelOriginsMirrorTheBackendCatalog() {
        let expected: [String: String] = [
            "chat-export:claude": "claude-export", "chat-export:chatgpt": "chatgpt-export",
            "chrome-bookmarks": "chrome-bookmark", "safari-bookmarks": "safari-bookmark",
            "safari-tabs": "safari-tab", "notes": "apple-notes", "rss": "rss",
            "calendar": "calendar", "pinterest": "pinterest", "reddit": "reddit-saved",
            "x": "x-bookmarks", "telegram": "telegram", "files": "bookmark",
        ]
        XCTAssertEqual(Set(expected.keys), Set(ChannelMarks.allChannelIds))
        for (id, origin) in expected {
            XCTAssertEqual(ConnectedChannelRow.origin(forChannel: id), origin, id)
        }
    }

    /// An id the backend adds before this map does resolves to itself rather
    /// than trapping — `origin(forChannel:)` is total, and the T5 sweep above
    /// is what makes the missing row loud instead of silent.
    func testAnUnknownChannelResolvesToItself() {
        XCTAssertEqual(ConnectedChannelRow.origin(forChannel: "arc-bookmarks"), "arc-bookmarks")
    }

    /// The two chat exports must not render as the same picture.
    func testTheTwoChatExportsGetDifferentMarks() {
        XCTAssertEqual(ConnectedChannelRow.logoName(for: "chat-export:claude"), "claude-desktop")
        XCTAssertEqual(ConnectedChannelRow.logoName(for: "chat-export:chatgpt"), "chatgpt")
    }
}

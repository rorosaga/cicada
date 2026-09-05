import XCTest
@testable import CicadaApp

/// 2026-09-02 brief — the `+` sheet is logo-first and two-level: one tile per
/// family, Enter/click expands to its members, each with its own logo, routes
/// and live channel state. Keyboard: arrows move, Enter opens, Esc backs out.
final class ImportFamilyTests: XCTestCase {

    /// R6 — `AddSourceTile` stays the leaf identity; families are a layer in
    /// front. A tile listed in two families would show twice; a tile listed
    /// in none would be unreachable from the sheet's top level.
    func testEveryTileBelongsToExactlyOneFamily() {
        let all = ImportFamily.allCases.flatMap(\.members)
        XCTAssertEqual(Set(all).count, all.count, "a tile is listed in two families")
        XCTAssertEqual(Set(all), Set(AddSourceTile.allCases), "a tile is unreachable from the families level")
        for tile in AddSourceTile.allCases {
            XCTAssertTrue(ImportFamily.forTile(tile).members.contains(tile), tile.rawValue)
        }
    }

    func testFamiliesMatchTheBrief() {
        XCTAssertEqual(ImportFamily.browsers.members, [.safari, .chrome])
        XCTAssertEqual(ImportFamily.websites.members, [.tiktok, .instagram, .youtube, .linkedin, .reddit, .pinterest, .x])
        XCTAssertEqual(ImportFamily.chatExports.members, [.chatExport])
        XCTAssertEqual(ImportFamily.feedsAndCalendars.members, [.rssFeed, .calendar, .telegram])
        XCTAssertEqual(ImportFamily.files.members, [.bookmarksFile, .pasteLink, .appleNotes])
        XCTAssertEqual(ImportFamily.allCases.map(\.title), ["Browsers", "Websites & apps", "Chat exports", "Feeds & calendars", "Files"])
    }

    /// R-L1 — no tile is markless: a PNG, an installed app's icon, or its own
    /// SF Symbol. The drawn glyphs are gone (they were wrong on four axes for
    /// Chrome and an invented tint for Safari).
    func testEveryTileCarriesSomeMark() {
        for tile in AddSourceTile.allCases {
            XCTAssertTrue(tile.logoName != nil || tile.appBundleId != nil || !tile.icon.isEmpty,
                          "\(tile.rawValue) has no mark at all")
        }
    }

    func testFamilyPreviewMarksAreItsFirstBrandedMembers() {
        XCTAssertEqual(ImportFamily.browsers.previewMarks, [.safari, .chrome])
        XCTAssertEqual(ImportFamily.websites.previewMarks, [.tiktok, .instagram, .youtube, .linkedin])
        XCTAssertEqual(ImportFamily.chatExports.previewMarks, [.chatExport])
    }

    /// A family whose members carry no PNG and no installed-app icon still
    /// wears marks — never an empty cluster on the top-level tile. Files
    /// stopped being that family in Track L (R-L1 gave Apple Notes a bundle
    /// id, so it is the family's one branded member); `chatExports` is, and
    /// `testFamilyPreviewMarksAreItsFirstBrandedMembers` pins it. What is
    /// asserted here is the shape every family must hold.
    func testEveryFamilyWearsBetweenOneAndFourMarks() {
        XCTAssertEqual(ImportFamily.files.previewMarks, [.appleNotes],
                       "Apple Notes is the Files family's only branded member (R-L1)")
        for family in ImportFamily.allCases {
            XCTAssertFalse(family.previewMarks.isEmpty, family.rawValue)
            XCTAssertLessThanOrEqual(family.previewMarks.count, 4, family.rawValue)
        }
    }

    func testRouteLinesNameEveryWayIn() {
        XCTAssertEqual(AddSourceTile.safari.routeLines, ["Bookmarks (folders)", "Reading List", "iCloud tabs"])
        XCTAssertEqual(AddSourceTile.chrome.routeLines, ["Bookmarks (folders)"])
        XCTAssertEqual(AddSourceTile.tiktok.routeLines, ["Favourites & likes export", "Browsing history (opt-in)"])
        XCTAssertEqual(AddSourceTile.reddit.routeLines, ["Connect account", "GDPR export"])
        XCTAssertEqual(AddSourceTile.pinterest.routeLines, ["Connect account"])
        XCTAssertEqual(AddSourceTile.x.routeLines, ["Connect account"])
        XCTAssertEqual(AddSourceTile.instagram.routeLines, ["Saved export"])
        XCTAssertEqual(AddSourceTile.youtube.routeLines, ["Playlist / Takeout export"])
        for tile in AddSourceTile.allCases { XCTAssertFalse(tile.routeLines.isEmpty, tile.rawValue) }
    }

    // MARK: - Keyboard (R10)

    func testFocusMovesWithinAThreeColumnGridAndClamps() {
        var f = CatalogFocus(index: 0, columns: 3, count: 5)
        f = f.moved(.right); XCTAssertEqual(f.index, 1)
        f = f.moved(.down);  XCTAssertEqual(f.index, 4)
        f = f.moved(.down);  XCTAssertEqual(f.index, 4, "no row below")
        f = f.moved(.right); XCTAssertEqual(f.index, 4, "last item")
        f = f.moved(.up);    XCTAssertEqual(f.index, 1)
        f = f.moved(.left);  XCTAssertEqual(f.index, 0)
        f = f.moved(.left);  XCTAssertEqual(f.index, 0)
        f = f.moved(.up);    XCTAssertEqual(f.index, 0)
    }

    func testFocusOnAnEmptyGridStaysAtZero() {
        let f = CatalogFocus(index: 0, columns: 3, count: 0)
        XCTAssertEqual(f.moved(.down).index, 0)
    }

    /// A focus that somehow points past the end (the grid shrank underneath
    /// it) clamps back inside on the next move rather than indexing out of
    /// the members array.
    func testFocusPastTheEndClampsBackInside() {
        let f = CatalogFocus(index: 9, columns: 3, count: 2)
        XCTAssertEqual(f.moved(.right).index, 1)
        XCTAssertEqual(f.moved(.down).index, 1)
    }

    func testEscapeWalksBackOneLevel() {
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .flow(.safari)), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .members(.browsers)), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .families), .close)
    }
}

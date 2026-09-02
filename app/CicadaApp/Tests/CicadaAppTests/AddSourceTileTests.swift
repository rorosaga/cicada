import XCTest
@testable import CicadaApp

/// G68 §2.4 — a walkthrough tile may only offer the vendors whose files its
/// own "Choose file…" action can actually upload.
final class AddSourceTileTests: XCTestCase {

    /// Chat exports go to `POST /conversations/upload`; every other export
    /// platform goes to `POST /sources/upload`. Offering the wrong vendor on
    /// a tile sends the file to the wrong parser and reports "Imported 0" —
    /// G71 §4.1 split the old combined "Instagram & YouTube" tile into one
    /// tile per platform precisely so each tile's vendor list stays exact.
    func testEachWalkthroughTileOffersOnlyItsOwnVendors() {
        XCTAssertEqual(AddSourceTile.chatExport.vendors, [.claude, .chatgpt])
        XCTAssertEqual(AddSourceTile.instagram.vendors, [.instagram])
        XCTAssertEqual(AddSourceTile.youtube.vendors, [.takeout])
        XCTAssertEqual(AddSourceTile.tiktok.vendors, [.tiktok])
        XCTAssertEqual(AddSourceTile.linkedin.vendors, [.linkedin])
        XCTAssertEqual(AddSourceTile.reddit.vendors, [.redditExport])
    }

    func testNonWalkthroughTilesOfferNoVendors() {
        let walkthroughTiles: Set<AddSourceTile> = [
            .chatExport, .instagram, .youtube, .tiktok, .linkedin, .reddit,
        ]
        for tile in AddSourceTile.allCases where !walkthroughTiles.contains(tile) {
            XCTAssertTrue(tile.vendors.isEmpty, "\(tile.rawValue) should have no walkthrough")
        }
    }

    /// Every vendor is reachable from exactly one tile — no orphans, no
    /// duplicates.
    func testTheVendorsPartitionCleanlyAcrossTiles() {
        let offered = AddSourceTile.allCases.flatMap(\.vendors)
        XCTAssertEqual(offered.count, Set(offered).count, "a vendor is offered twice")
        XCTAssertEqual(Set(offered), Set(WalkthroughVendor.allCases), "a vendor is unreachable")
    }

    /// Every tile that maps to a backend channel keeps mapping to exactly one,
    /// so "Manage…" from a connected row is unambiguous.
    func testChannelToTileLookupStaysUnambiguous() {
        for tile in AddSourceTile.allCases {
            for channelId in tile.channelIds {
                XCTAssertEqual(AddSourceTile.forChannel(channelId), tile, channelId)
            }
        }
    }

    /// Esc backs out of a focused tile first and only closes the sheet from
    /// the top-level grid — one keypress should never discard a half-typed
    /// feed URL AND the sheet. With the family layer in front (Task 4) that
    /// is one step per level: flow → members → families → close.
    func testEscapeBacksOutBeforeItCloses() {
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .flow(.rssFeed)), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .members(.feedsAndCalendars)), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .families), .close)
    }

    /// Tile titles are short enough for a three-column grid without
    /// truncation.
    func testTileTitlesFitAThreeColumnGrid() {
        for tile in AddSourceTile.allCases {
            XCTAssertLessThanOrEqual(tile.title.count, 28, "\(tile.rawValue): \"\(tile.title)\"")
            XCTAssertFalse(tile.blurb.isEmpty, tile.rawValue)
        }
    }
}

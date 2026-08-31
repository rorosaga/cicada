import XCTest
@testable import CicadaApp

/// G68 §2.4 — a walkthrough tile may only offer the vendors whose files its
/// own "Choose file…" action can actually upload.
final class AddSourceTileTests: XCTestCase {

    /// Chat exports go to `POST /conversations/upload`; saved-content exports
    /// go to `POST /sources/upload`. Offering all four vendors on both tiles
    /// sent half of every choice to the wrong endpoint.
    func testEachWalkthroughTileOffersOnlyItsOwnVendors() {
        XCTAssertEqual(AddSourceTile.chatExport.vendors, [.claude, .chatgpt])
        XCTAssertEqual(AddSourceTile.savedContent.vendors, [.takeout, .instagram])
    }

    func testNonWalkthroughTilesOfferNoVendors() {
        for tile in AddSourceTile.allCases where tile != .chatExport && tile != .savedContent {
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
    /// the grid — one keypress should never discard a half-typed feed URL AND
    /// the sheet.
    func testEscapeBacksOutBeforeItCloses() {
        XCTAssertEqual(AddSourceSheet.escapeAction(expanded: .rssFeed), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(expanded: nil), .close)
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

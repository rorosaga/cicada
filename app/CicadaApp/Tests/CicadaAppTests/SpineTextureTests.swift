import SwiftUI
import XCTest
@testable import CicadaApp

final class SpineTextureTests: XCTestCase {
    func testKindMapIsTotalAndMatchesTheSpecTable() {
        let chat = "mcp claude-code claude-desktop cursor codex gemini-cli claude-export chatgpt-export gemini-export claude-web chatgpt perplexity claude-code-remote codex-remote vscode remote-app grok opencode hermes openclaw telegram".split(separator: " ").map(String.init)
        let page = "chrome-bookmark safari-bookmark safari-tab bookmark saved-link share-sheet brave-bookmark vivaldi-bookmark comet-bookmark dia-bookmark chrome-tab-group rss instagram-saved pinterest reddit-saved reddit x-bookmarks x-likes x linkedin-saved".split(separator: " ").map(String.init)
        let note = ["apple-notes", "wispr-flow", "folder"], video = ["youtube-playlist", "tiktok-saved", "tiktok-history"]
        let other = ["calendar", "calendar-local", "contacts-local", "unknown", "+more", "unlisted"]
        for (kind, origins) in [(SpineKind.chat, chat), (.page, page), (.note, note), (.video, video), (.other, other)] {
            for origin in origins { XCTAssertEqual(spineKind(for: origin), kind, origin) }
        }
        for origin in OriginIconography.allKnownOrigins {
            let expected: SpineKind = chat.contains(origin) ? .chat : page.contains(origin) ? .page : note.contains(origin) ? .note : video.contains(origin) ? .video : .other
            XCTAssertEqual(spineKind(for: origin), expected, origin)
        }
    }

    func testMaskTriplesAreBinaryUniformAlongStretchAxesAndHaveDistinctMarks() throws {
        let sheet = try SpriteTestAssets.sheet("room-spines")
        var marks = Set<String>()
        var edgeBands: [[Bool]] = []
        for kind in SpineKind.allCases {
            let clip = try SpriteTestAssets.clip(sheet, kind.rawValue)
            XCTAssertEqual(clip.order.count, 3)
            XCTAssertEqual(clip.seconds, [1, 1, 1])
            guard clip.order.count == 3 else { return XCTFail("three masks required") }
            let masks = try clip.order.map { try SpriteTestAssets.plane(sheet, frame: $0) }
            for mask in masks {
                XCTAssertTrue(mask.pixels.allSatisfy { $0.alpha == 0 || $0.alpha == 255 })
                XCTAssertEqual(Set(mask.pixels.filter { $0.alpha > 0 }.map(\.rgb)).count, 1)
                for x in 0..<20 {
                    for y in 1...10 { XCTAssertEqual(mask.at(x, y).alpha, mask.at(x, 1).alpha, "\(kind)/x\(x) y\(y)") }
                }
                for x in 4..<20 { for y in 0..<12 { XCTAssertEqual(mask.at(x, y).alpha, mask.at(4, y).alpha) } }
            }
            var mark = ""
            for y in 4...6 { for x in 20..<24 { mark += masks[1].at(x, y).alpha > 0 || masks[2].at(x, y).alpha > 0 ? "1" : "0" } }
            marks.insert(mark)
            // Outside rows 1–10 only the common top/bottom edge may appear, never a kind-specific mark.
            edgeBands.append([0, 11].flatMap { y in (20..<24).flatMap { x in [masks[1].at(x, y).alpha > 0, masks[2].at(x, y).alpha > 0] } })
            // The body under the mark is square and plain; all kind-specific ink is light/shade in the right four.
            for y in 1...10 { for x in 20..<24 { XCTAssertEqual(masks[0].at(x, y).alpha, masks[0].at(20, 1).alpha) } }
        }
        XCTAssertEqual(marks.count, 5)
        for edges in edgeBands.dropFirst() { XCTAssertEqual(edges, edgeBands[0]) }
    }

    func testSmallSpinesUseThePlainRectangle() {
        XCTAssertFalse(SpineTexture.usesTexture(cell: 3, size: CGSize(width: 26, height: 40)))
        XCTAssertFalse(SpineTexture.usesTexture(cell: 3, size: CGSize(width: 90, height: 14)))
        XCTAssertTrue(SpineTexture.usesTexture(cell: 3, size: CGSize(width: 27, height: 15)))
        XCTAssertFalse(SpineTexture.usesTexture(cell: 4, size: CGSize(width: 35, height: 40)))
        XCTAssertFalse(SpineTexture.usesTexture(cell: 4, size: CGSize(width: 90, height: 19)))
    }
}

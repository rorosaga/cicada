import XCTest
@testable import CicadaApp

/// The waiting pile's books (owner pick "A · Stack", 2026-10-16): the `room-books` sheet the app joins into a book of
/// any whole width, a colour per source kind, and the night frames the dark room draws.
final class BookArtTests: XCTestCase {
    func testKindMapIsTotalAndGivesConversationsWithPeopleTheirOwnColour() {
        let chat = "mcp claude-code claude-desktop cursor codex gemini-cli claude-export chatgpt-export gemini-export claude-web chatgpt perplexity claude-code-remote codex-remote vscode remote-app grok opencode hermes openclaw".split(separator: " ").map(String.init)
        let message = ["imessage", "telegram"]
        let page = "chrome-bookmark safari-bookmark safari-tab bookmark saved-link share-sheet brave-bookmark vivaldi-bookmark comet-bookmark dia-bookmark chrome-tab-group rss instagram-saved pinterest reddit-saved reddit x-bookmarks x-likes x linkedin-saved".split(separator: " ").map(String.init)
        let note = ["apple-notes", "wispr-flow", "folder"]
        let video = ["youtube-playlist", "youtube-history", "tiktok-saved", "tiktok-history"]
        for (kind, origins) in [(BookKind.chat, chat), (.message, message), (.page, page), (.note, note), (.video, video),
                                (.other, ["calendar", "calendar-local", "contacts-local", "unknown", "+more", "unlisted"])] {
            for origin in origins { XCTAssertEqual(bookKind(for: origin), kind, origin) }
        }
        for origin in OriginIconography.allKnownOrigins {
            let expected: BookKind = chat.contains(origin) ? .chat : message.contains(origin) ? .message
                : page.contains(origin) ? .page : note.contains(origin) ? .note : video.contains(origin) ? .video : .other
            XCTAssertEqual(bookKind(for: origin), expected, origin)
        }
    }

    func testCountStepsAreFewAndNeverProportional() {
        XCTAssertEqual([0, 1, 2, 9, 10, 49, 50, 5000].map(BookArt.step(count:)), [0, 0, 1, 1, 2, 2, 3, 3])
        XCTAssertEqual(BookArt.rows, [7, 9, 11, 13])
    }

    /// Every frame is a book from its top row, `rows[step]` tall, with rounded corners and a middle that is one column
    /// repeated — what lets the app draw any whole width as authored.
    func testEveryFrameIsATileableBookOfItsStep() throws {
        let sheet = try SpriteTestAssets.sheet(BookArt.sheetName)
        XCTAssertEqual(sheet.frameSize, CGSize(width: BookArt.sheetWidth, height: BookArt.rows.max()!))
        var mids = Set<UInt32>()
        for kind in BookKind.allCases {
            for tag in [kind.rawValue, kind.rawValue + "-night"] {
                let clip = try SpriteTestAssets.clip(sheet, tag)
                XCTAssertEqual(clip.order.count, BookArt.rows.count, tag)
                for (step, frame) in clip.order.enumerated() {
                    let plane = try SpriteTestAssets.plane(sheet, frame: frame)
                    let rows = BookArt.rows[step]
                    for y in 0..<plane.h {
                        for x in BookArt.leadingCap..<(BookArt.sheetWidth - BookArt.trailingCap) {
                            XCTAssertEqual(plane.at(x, y), plane.at(BookArt.leadingCap, y), "\(tag)/\(step) middle x\(x) y\(y)")
                        }
                        let inked = (0..<plane.w).contains { plane.at($0, y).alpha > 0 }
                        XCTAssertEqual(inked, y < rows, "\(tag)/\(step) row \(y)")
                    }
                    for (x, y) in [(0, 0), (plane.w - 1, 0), (0, rows - 1), (plane.w - 1, rows - 1)] {
                        XCTAssertEqual(plane.at(x, y).alpha, 0, "\(tag)/\(step) corner")
                    }
                    if !tag.hasSuffix("-night"), step == 0 { mids.insert(plane.at(BookArt.leadingCap, 3).rgb) }
                }
            }
        }
        XCTAssertEqual(mids.count, BookKind.allCases.count, "a colour per kind")
    }

    /// The joined book: exactly `width` × `rows` pixels, opaque inside its outline (nothing behind a book shows
    /// through it, DR-13), its caps the sheet's own, and the night book a different drawing.
    func testAJoinedBookIsItsCapsAndItsMiddleAtAnyWholeWidth() throws {
        let sheet = try SpriteTestAssets.sheet(BookArt.sheetName)
        for width in [BookArt.minWidth, 18, 24, 40] {
            let image = try XCTUnwrap(BookArt.image(kind: .message, step: 1, width: width, night: false, sheet: sheet))
            XCTAssertEqual([image.width, image.height], [width, 9])
            let book = SpriteTestAssets.Plane(image)
            let frame = try SpriteTestAssets.plane(sheet, frame: try SpriteTestAssets.clip(sheet, "message").order[1])
            for y in 0..<9 {
                for x in 0..<BookArt.leadingCap { XCTAssertEqual(book.at(x, y), frame.at(x, y)) }
                for x in 0..<BookArt.trailingCap {
                    XCTAssertEqual(book.at(width - BookArt.trailingCap + x, y), frame.at(BookArt.sheetWidth - BookArt.trailingCap + x, y))
                }
                for x in 1..<(width - 1) where y > 0 && y < 8 { XCTAssertEqual(book.at(x, y).alpha, 255) }
            }
            let night = try XCTUnwrap(BookArt.image(kind: .message, step: 1, width: width, night: true, sheet: sheet))
            XCTAssertNotEqual(SpriteTestAssets.Plane(night).pixels, book.pixels)
        }
        XCTAssertNil(BookArt.image(kind: .chat, step: 0, width: BookArt.minWidth - 1, night: false, sheet: sheet))
        XCTAssertNil(BookArt.image(kind: .chat, step: 4, width: 30, night: false, sheet: sheet))
    }
}

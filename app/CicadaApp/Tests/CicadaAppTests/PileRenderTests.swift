import SwiftUI
import XCTest
@testable import CicadaApp

/// The pile as the room draws it (owner pick "A · Stack", 2026-10-16), rendered offscreen — never the app. A book's
/// pixels land on whole cells of the lattice in the room's own lighting. `CICADA_WRITE_PILE=<dir>` writes the renders
/// (the realistic and crowded piles, day and night, at 5/4/3 pt per cell) for a person to look at.
@MainActor
final class PileRenderTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1; CicadaTheme.mode = .dark }

    private func books(_ pairs: [(String, Int)]) -> [BookSpec] {
        bookPileLayout(pairs.enumerated().map { i, p in OriginVolume(origin: p.0, count: p.1, chars: 1000 - i, remaining: p.1) })
    }

    private func render(_ pile: [BookSpec], night: Bool, cell: CGFloat) throws -> CGImage {
        let layout = deskSceneLayout(pixelScale: cell)
        let scenery = Scenery(base: .sunny, time: night ? .night : .day, overlay: nil, source: .chosen)
        let room = ZStack(alignment: .bottomLeading) {
            SceneryRoomArt(lampLit: true, scenery: scenery, cell: cell) {
                BookwormView(state: .reading, latticeCell: cell, caption: nil, lighting: scenery.lighting, lampLit: true)
            }
            BookPileView(books: pile, rows: [], layout: layout, night: night)
                .offset(x: layout.pileFrame.minX, y: -layout.pileFrame.minY)
        }
        .frame(width: layout.size.width, height: layout.size.height, alignment: .bottomLeading)
        .background(CicadaTheme.bgBase)
        // Still frames (an offscreen render cannot draw the sprites' layer player) in the dark appearance.
        .environment(\.spriteSnapshotDate, Date(timeIntervalSince1970: 0))
        .environment(\.colorScheme, .dark)
        // A mark's bundled logo reads the Store; an offscreen one with nothing in it (never a real bank).
        .environment(Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI()))
        let renderer = ImageRenderer(content: room)
        renderer.scale = 1
        return try XCTUnwrap(renderer.cgImage)
    }

    func test_eachBookIsItsSheetsPixelsOnTheLattice_dayAndNight() throws {
        let sheet = try SpriteTestAssets.sheet(BookArt.sheetName)
        let realistic = books([("claude-code", 4), ("imessage", 1)])
        let crowded = books([("claude-code", 34), ("chrome-bookmark", 12), ("imessage", 6), ("codex", 3),
                             ("apple-notes", 2), ("youtube-playlist", 2), ("rss", 1)])
        let dir = ProcessInfo.processInfo.environment["CICADA_WRITE_PILE"].map { URL(fileURLWithPath: $0) }
        for cell: CGFloat in [5, 4, 3] {
            let layout = deskSceneLayout(pixelScale: cell)
            for (name, pile) in [("real", realistic), ("crowded", crowded)] {
                for night in [false, true] {
                    let image = try render(pile, night: night, cell: cell)
                    let plane = SpriteTestAssets.Plane(image)
                    XCTAssertEqual([plane.w, plane.h], [Int(layout.size.width), Int(layout.size.height)])
                    for book in PileBooks.stack(pile) {
                        // A cell of the spine's body left of any plate (column 1, two rows down from the book's top):
                        // the sheet's own colour, filling the whole cell.
                        let frame = try SpriteTestAssets.plane(sheet, frame: try SpriteTestAssets.clip(
                            sheet, book.kind.rawValue + (night ? "-night" : "")).order[book.step])
                        let want = frame.at(1, 2)
                        let col = book.x + 1
                        let row = book.y + book.rows - 3   // from the column's bottom
                        let px = Int(layout.pileFrame.minX + CGFloat(col) * cell)
                        let py = plane.h - Int(layout.pileFrame.minY + CGFloat(row + 1) * cell)
                        for dy in 0..<Int(cell) { for dx in 0..<Int(cell) {
                            XCTAssertEqual(plane.at(px + dx, py + dy).rgb, want.rgb, "\(name) \(book.id) \(cell) pt night \(night)")
                        } }
                    }
                    if let dir {
                        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                        let url = dir.appendingPathComponent("pile-\(name)-\(night ? "night" : "day")-\(Int(cell))pt.png")
                        try NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])?.write(to: url)
                    }
                }
            }
        }
    }
}

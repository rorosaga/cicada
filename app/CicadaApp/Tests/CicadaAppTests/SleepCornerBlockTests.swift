import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// ROR-118 round 6 - the words beside the study room (title, headline, lamp line, buttons) are one block exactly as
/// tall as the room, so the pair reads as one balanced row in every state: the free height is shared by two springs
/// rather than left as a gap under the buttons, and the run's instrument is drawn by the page, under both.
@MainActor
final class SleepCornerBlockTests: XCTestCase {
    override func setUp() {
        CicadaTheme.uiScale = 1
        CicadaTheme.mode = .dark
    }

    /// The width the words get at the 1440 pt window: the 1040 pt page less its gutters, the room's 480 pt and the gap.
    private static let wordsWidth: CGFloat = 448
    private static let roomHeight = CGFloat(RoomLattice.rows) * 3

    private static func states() throws -> [(String, SleepStatusResponse, Bool)] {
        try [
            ("idle", SleepRunStripTests.finished(), false),
            ("empty", SleepRunStripTests.empty(), false),
            ("running-1", SleepRunStripTests.running(stage: 1), false),
            ("running-5", SleepRunStripTests.running(stage: 5), false),
            ("paused-user", SleepRunStripTests.paused("user"), false),
            ("paused-plan-window", SleepRunStripTests.paused("plan_window"), false),
            ("stopped", SleepRunStripTests.cancelled(), false),
            ("failed", SleepRunStripTests.failed(), false),
            ("just-finished", SleepRunStripTests.finished(), true),
        ]
    }

    private static func block(_ status: SleepStatusResponse, finished: Bool, host: SleepRunStripTests.Host) -> some View {
        let page = SleepRunStripTests.page(status, justFinished: finished)
        if finished { host.room.recentCycleCommit = "abc1234" }
        let context = page.roomContext(recentCycleCommit: host.room.recentCycleCommit, locale: SleepRunStripTests.en)
        let words = SleepRoomColumn(page: page, status: roomSentence(context), answers: [], room: host.room,
                                    leading: true, lastRead: "2 h ago",
                                    title: AnyView(EyebrowRow(eyebrow: "Sleep", bare: true) { EmptyView() }),
                                    fillHeight: roomHeight)
        return SleepRunStripTests.environment(words.frame(width: wordsWidth, alignment: .leading), host: host)
    }

    /// By construction: whatever the state says, the block is the room's height, so its top and bottom edges are the
    /// room's. A taller block (a state with more to say than the room is tall) would fail here.
    func test_theWordsBesideTheRoomAreExactlyTheRoomsHeight() async throws {
        for (name, status, finished) in try Self.states() {
            let host = try await SleepRunStripTests.host()
            host.sleep.status = status
            let hosting = NSHostingView(rootView: Self.block(status, finished: finished, host: host))
            hosting.frame = NSRect(x: 0, y: 0, width: Self.wordsWidth, height: 10)
            XCTAssertEqual(hosting.fittingSize.height, Self.roomHeight, accuracy: 0.5, "\(name): the block is the room's height")
        }
    }

    func test_writeTheCornerBlocksForComparison() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_CORNER_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_CORNER_SNAPSHOTS=<dir> to write the blocks beside a room-sized rectangle")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        for (name, status, finished) in try Self.states() {
            let host = try await SleepRunStripTests.host()
            host.sleep.status = status
            let row = HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                Self.block(status, finished: finished, host: host)
                Rectangle().fill(CicadaTheme.accent.opacity(0.35)).frame(width: 480, height: Self.roomHeight)
            }
            .padding(20).frame(width: 1020).background(CicadaTheme.bgBase)
            try SleepRunStripTests.write(row, width: 1020, to: dir, file: "corner-\(name).png")
        }
    }

    /// The same, read from pixels: the first and last rows of ink in the words' column against the room's rectangle,
    /// in every state. The title's cap top and the buttons' bottom edge land within a few points of the room's edges.
    func test_theInkOfTheWordsSharesTheRoomsTopAndBottomEdges() async throws {
        for (name, status, finished) in try Self.states() {
            let host = try await SleepRunStripTests.host()
            host.sleep.status = status
            let pad: CGFloat = 20
            let row = HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                Self.block(status, finished: finished, host: host)
                Rectangle().fill(Color.red).frame(width: 480, height: Self.roomHeight)
            }
            .padding(pad).frame(width: 1020).background(CicadaTheme.bgBase)
            let hosting = NSHostingView(rootView: row)
            hosting.appearance = NSAppearance(named: .darkAqua)
            hosting.frame = NSRect(x: 0, y: 0, width: 1020, height: hosting.fittingSize.height)
            let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
            window.appearance = hosting.appearance
            window.contentView = hosting
            hosting.layoutSubtreeIfNeeded(); hosting.display()
            let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2040,
                                                     pixelsHigh: Int(hosting.bounds.height * 2), bitsPerSample: 8,
                                                     samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
            rep.size = hosting.bounds.size
            hosting.cacheDisplay(in: hosting.bounds, to: rep)
            let ground = NSColor(CicadaTheme.bgBase).usingColorSpace(.deviceRGB)!
            func ink(_ x: Int, _ y: Int) -> Bool {
                guard let c = rep.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else { return false }
                return abs(c.redComponent - ground.redComponent) + abs(c.greenComponent - ground.greenComponent)
                    + abs(c.blueComponent - ground.blueComponent) > 0.12
            }
            let rows = rep.pixelsHigh
            let words = (0..<rows).filter { y in stride(from: 0, to: 900, by: 2).contains { ink($0, y) } }
            let room = (0..<rows).filter { ink(1700, $0) }
            let (wTop, wBottom) = (CGFloat(words.first!) / 2, CGFloat(words.last!) / 2)
            let (rTop, rBottom) = (CGFloat(room.first!) / 2, CGFloat(room.last!) / 2)
            print("EDGES \(name): words \(wTop)-\(wBottom), room \(rTop)-\(rBottom)")
            XCTAssertEqual(wTop, rTop, accuracy: 2, "\(name): top edges")
            XCTAssertEqual(wBottom, rBottom, accuracy: 2, "\(name): bottom edges")
        }
    }
}

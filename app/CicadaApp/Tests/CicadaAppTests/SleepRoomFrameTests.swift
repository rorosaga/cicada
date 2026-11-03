import SwiftUI
import XCTest
@testable import CicadaApp

/// The Sleep room after #305 (2026-10-16). Out of its card, the room showed what the card had hidden: the painted art
/// (a 110-column backdrop) stopped two thirds across the 160-column lattice, and the pile stood on bare page ground
/// beside it. The room is one painted room of the lattice's size at every step, and everything it holds is inside it.
final class SleepRoomFrameTests: XCTestCase {
    /// Every whole-point cell the room is drawn at: the page's 5/4/3 steps and the zoom-derived 2.
    private let cells: [CGFloat] = [5, 4, 3, 2]

    func test_thePaintedRoomIsTheLatticeAtEveryStep() {
        for cell in cells {
            let layout = deskSceneLayout(pixelScale: cell)
            XCTAssertEqual(layout.size, CGSize(width: CGFloat(RoomLattice.cols) * cell, height: CGFloat(RoomLattice.rows) * cell))
            XCTAssertEqual(layout.paintedFrame, CGRect(origin: .zero, size: layout.size),
                           "\(cell) pt — the painted art's width is the lattice's width")
        }
    }

    /// The pile, the worm, every prop (the lamp, the clock, the window…) and every hotspot sit inside the painted room.
    func test_everythingTheRoomHoldsIsInsideThePaintedRoom() {
        for cell in cells {
            let layout = deskSceneLayout(pixelScale: cell)
            let painted = layout.paintedFrame
            XCTAssertTrue(painted.contains(layout.pileFrame), "\(cell) pt — the pile \(layout.pileFrame) is outside \(painted)")
            let worm = CGRect(origin: layout.wormOrigin, size: CGSize(width: 64 * cell, height: 48 * cell))
            XCTAssertTrue(painted.contains(worm), "\(cell) pt — the worm")
            for layer in layout.layers {
                XCTAssertTrue(painted.contains(layout.frame(of: layer)), "\(cell) pt — \(layer.prop)")
            }
            let spots = deskHotspots(layout)
            XCTAssertEqual(Set(spots.keys), Set(DeskHotspot.allCases))
            for (spot, rect) in spots {
                XCTAssertTrue(painted.contains(rect), "\(cell) pt — the \(spot) hotspot \(rect) is outside \(painted)")
            }
        }
    }

    /// The layout is not enough: the backdrop's PIXELS must paint every cell of the lattice, the pile's columns
    /// included, in every lighting — a sheet narrower than its plan would draw bare page ground again.
    func test_theBackdropPaintsEveryCellOfTheLattice() throws {
        let sheet = try SpriteTestAssets.sheet("room-backdrop")
        let layer = try XCTUnwrap(DeskScene.plan.first { $0.prop == .backdrop })
        XCTAssertEqual([layer.cellX, layer.cellY, layer.w, layer.h], [0, 0, RoomLattice.cols, RoomLattice.rows])
        XCTAssertEqual(sheet.frameSize, CGSize(width: RoomLattice.cols, height: RoomLattice.rows))
        for tag in ["dark", "lit", "night-dark", "night-lit"] {
            for frame in try SpriteTestAssets.clip(sheet, tag).order {
                let plane = try SpriteTestAssets.plane(sheet, frame: frame)
                XCTAssertEqual(plane.ink.count, RoomLattice.cols * RoomLattice.rows, "\(tag) leaves a cell unpainted")
            }
        }
    }

    /// Owner 2026-11-03, on the floor fading into the page ground under the room: "remove that fade effect from
    /// everywhere." No file that draws the room masks it or lays a gradient over its edges, and the fade type is gone.
    func test_noRoomDrawsAFadeOverItsEdges() throws {
        let root = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views")
        for file in ["Sleep/StudyRoom.swift", "Sleep/DeskScene.swift", "Onboarding/OnboardingRoom.swift",
                     "Settings/ScenerySettings.swift"] {
            let text = try String(contentsOf: root.appendingPathComponent(file), encoding: .utf8)
            XCTAssertFalse(text.contains(".mask"), "\(file) masks the room")
            XCTAssertFalse(text.contains("RoomFloorFade"), "\(file) still fades the floor")
        }
        for file in ["Sleep/StudyRoom.swift", "Sleep/DeskScene.swift", "Onboarding/OnboardingRoom.swift"] {
            let text = try String(contentsOf: root.appendingPathComponent(file), encoding: .utf8)
            XCTAssertFalse(text.contains("Gradient("), "\(file) lays a gradient on the room")
        }
    }
}

/// The room ends in a hard edge (owner 2026-11-03): rendered over two different grounds, every pixel of its bottom five
/// cells — where the floor used to fade — is the same, so the floor is opaque to the last row and nothing is clipped.
@MainActor
final class SleepRoomEdgeTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1 }

    private func plane(_ view: some View, size: CGSize, over ground: Color) throws -> SpriteTestAssets.Plane {
        let framed = view.frame(width: size.width, height: size.height).background(ground)
            .environment(\.spriteSnapshotDate, Date(timeIntervalSince1970: 12 * 3600))
            .environment(\.scenePaused, true)
        let renderer = ImageRenderer(content: framed)
        renderer.scale = 1
        let context = try XCTUnwrap(CGContext(
            data: nil, width: Int(size.width), height: Int(size.height), bitsPerComponent: 8, bytesPerRow: 0,
            space: try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB)),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        renderer.render { _, draw in draw(context) }
        return SpriteTestAssets.Plane(try XCTUnwrap(context.makeImage()))
    }

    private func assertHardBottomEdge(_ view: some View, cell: CGFloat, _ name: String) throws {
        let size = deskSceneLayout(pixelScale: cell).size
        let red = try plane(view, size: size, over: .red), blue = try plane(view, size: size, over: .blue)
        XCTAssertEqual([red.w, red.h], [Int(size.width), Int(size.height)], name)
        let band = Int(cell) * 5
        for y in (red.h - band)..<red.h { for x in 0..<red.w {
            XCTAssertEqual(red.at(x, y), blue.at(x, y), "\(name): the ground shows through the floor at (\(x), \(y))")
            if red.at(x, y) != blue.at(x, y) { return }
        } }
    }

    func test_theRoomsFloorIsOpaqueToItsLastRow() throws {
        let suite = "com.cicada.room-edge.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(SceneryMode.choose.rawValue, forKey: SceneryMode.defaultsKey)
        for time in ["day", "night"] {
            defaults.set(time, forKey: ManualScenery.timeKey)
            defaults.set("sunny", forKey: ManualScenery.baseKey)
            for cell: CGFloat in [5, 3] {
                let scenery = Scenery(base: .sunny, time: time == "night" ? .night : .day, overlay: nil, source: .chosen)
                try assertHardBottomEdge(SceneryRoomArt(lampLit: true, scenery: scenery, cell: cell) {
                    BookwormView(state: .reading, latticeCell: cell, lighting: scenery.lighting, lampLit: true)
                }, cell: cell, "the Sleep room's art, \(time), \(cell) pt")
                try assertHardBottomEdge(OnboardingRoom(mood: .awake, cell: cell).defaultAppStorage(defaults),
                                         cell: cell, "the onboarding room, \(time), \(cell) pt")
            }
        }
    }
}

/// The room's three lines read as one group (2026-10-16): the live capture had ≈ 70 pt of empty slot between the
/// sentence and the controls, and Consolidate and the engine menu ≈ 66 pt apart.
@MainActor
final class SleepRoomGroupTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1 }

    func test_hugWidthTakesTheChildsWidthUpToTheCapAndTheOffer() {
        XCTAssertEqual(HugWidth.width(ideal: 185, maxWidth: 300, offered: 760), 185, "snug, never the whole cap")
        XCTAssertEqual(HugWidth.width(ideal: 420, maxWidth: 300, offered: 760), 300, "a long label stops at the cap")
        XCTAssertEqual(HugWidth.width(ideal: 185, maxWidth: 300, offered: 120), 120, "never past the offer")
        XCTAssertEqual(HugWidth.width(ideal: 185, maxWidth: 300, offered: nil), 185)
    }

    private func size(_ view: some View, width: CGFloat) throws -> CGSize {
        let renderer = ImageRenderer(content: view)
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        return try XCTUnwrap(renderer.nsImage).size
    }

    /// The engine button, measured as the row offers it: its frame is its own button, not the 300 pt cap.
    func test_theEngineButtonIsItsOwnWidthNotItsCap() throws {
        let label = "Example plan · small"
        let button = NeutralButton(title: label, trailingSystemImage: "chevron.down") {}
        let natural = try size(button.fixedSize(), width: 760)
        let hugged = try size(HugWidth(maxWidth: EngineQuickMenu.buttonMaxWidth) { button }, width: 760)
        XCTAssertLessThan(natural.width, EngineQuickMenu.buttonMaxWidth)
        XCTAssertEqual(hugged.width, natural.width, accuracy: 0.5)
        let long = NeutralButton(title: String(repeating: "a-very-long-model-name ", count: 4)) {}
        let capped = try size(HugWidth(maxWidth: EngineQuickMenu.buttonMaxWidth) { long }, width: 760).width
        XCTAssertLessThanOrEqual(capped, EngineQuickMenu.buttonMaxWidth + 0.5, "a long label truncates inside the cap")
        XCTAssertGreaterThan(capped, EngineQuickMenu.buttonMaxWidth - 24)
    }

    private func slotHeight(_ line: SentenceLine, width: CGFloat = SleepLayout.contentWidth) throws -> CGFloat {
        try size(RoomSentenceView(line: line).environment(IntakeRouter(api: FakeIntakeAPI())), width: width).height
    }

    /// Owner QA 2026-10-17 (amends R-Z5's reserved tail line): the headline reserves no empty line under it. A line
    /// with no tail is exactly the lead's height; a tail adds one line and no more.
    func test_aLineWithNoTailIsTheLeadAlone() throws {
        let bare = SentenceLine(lead: "1 to read — overdue.", numeral: "1", qualifier: "overdue", tone: .warning)
        var tailed = bare
        tailed.tail = "The lamp is off — I read when you ask."
        tailed.action = .openLamp
        let none = try slotHeight(bare)
        let lead = try size(Text("1 to read").font(CicadaTheme.displayFont(size: RoomSentenceView.leadSize)), width: 760).height
        let tailLine = try size(Text(verbatim: " ").font(RoomSentenceView.tailFont(size: RoomSentenceView.tailSize)),
                                width: 760).height
        XCTAssertEqual(none, lead, accuracy: 1, "no empty line is held under the headline")
        XCTAssertEqual(try slotHeight(tailed), lead + CicadaTheme.spacingXS + tailLine, accuracy: 1,
                       "a tail takes one line")
        XCTAssertFalse(SentenceSlot.drawsTail(bare))
        var blank = bare
        blank.tail = "  "
        XCTAssertFalse(SentenceSlot.drawsTail(blank), "a blank tail is no tail")
        XCTAssertTrue(SentenceSlot.drawsTail(tailed))
    }

    /// A tail at R-Z13's 80-character budget fits one line at the default zoom (at the display floor if it must), so
    /// at 1× the slot never grows; only a column too narrow for even that wraps — never cut.
    func test_aBudgetTailFitsOneLineAtTheDefaultZoom() throws {
        let bare = SentenceLine(lead: "Paused.")
        var full = bare
        full.tail = String("Stopped at your plan's limit, which resets on Tuesday at 2:00 PM. Continue then.".prefix(SentenceLine.maxTail))
        XCTAssertEqual(full.tail?.count, SentenceLine.maxTail)
        var short = bare
        short.tail = "Continue then."
        XCTAssertEqual(try slotHeight(full), try slotHeight(short), accuracy: 0.5)
        XCTAssertGreaterThan(try slotHeight(full, width: 420), try slotHeight(short, width: 420),
                             "a narrow column wraps the tail rather than cutting it")
    }
}

/// The pile stands on the painted room, and a count must never sit on the wall or floor behind it (DR-13). Since the
/// books (owner pick "A · Stack", 2026-10-16) a book is opaque art inside its outline and its count rests on a solid
/// plate of the page ground, so whatever is behind the pile never shows through a book.
@MainActor
final class SleepPileGroundTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1 }

    private func plane(_ book: PlacedBook, cell: CGFloat, over ground: Color) throws -> SpriteTestAssets.Plane {
        let view = PileBookButton(book: book, row: nil, episodes: [], room: nil, onOpenDetails: { _ in }, cell: cell)
        let size = CGSize(width: CGFloat(book.width) * cell, height: CGFloat(book.rows) * cell)
        let renderer = ImageRenderer(content: view.frame(width: size.width, height: size.height).background(ground))
        renderer.scale = 1
        return SpriteTestAssets.Plane(try XCTUnwrap(renderer.cgImage))
    }

    func test_nothingBehindABookShowsThroughIt() throws {
        // The fold carries its "+N" plate (no mark: a mark's logo reads the Store, which this render has none of);
        // a source's book at 2 pt carries none.
        let fold = PileBooks.stack([BookSpec(origin: "+more", count: 7, isRemainder: true)])[0]
        let source = PileBooks.stack([BookSpec(origin: "claude-code", count: 3)])[0]
        for (book, cell) in [(fold, CGFloat(5)), (source, CGFloat(2))] {
            XCTAssertNotNil(BookArt.image(kind: book.kind, step: book.step, width: book.width, night: false))
            let red = try plane(book, cell: cell, over: .red), blue = try plane(book, cell: cell, over: .blue)
            XCTAssertEqual([red.w, red.h], [book.width * Int(cell), book.rows * Int(cell)])
            // The interior, one cell in from every edge (the outline's rounded corners are the art's own).
            let c = Int(cell)
            for y in c..<(red.h - c) { for x in c..<(red.w - c) {
                XCTAssertEqual(red.at(x, y), blue.at(x, y), "\(book.id): the ground shows through at (\(x), \(y))")
                if red.at(x, y) != blue.at(x, y) { return }
            } }
        }
    }
}

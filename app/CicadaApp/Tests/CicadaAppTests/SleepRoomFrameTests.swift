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

    /// R-Z5 holds — no tail and a one-line tail reserve the same height, so nothing below moves — and the reserve is
    /// ONE tail line: under the lead there is at most one empty line, not two.
    func test_theSlotReservesOneTailLineAndHoldsIt() throws {
        let bare = SentenceLine(lead: "1 to read — overdue.", numeral: "1", qualifier: "overdue", tone: .warning)
        var tailed = bare
        tailed.tail = "The lamp is off — I read when you ask."
        tailed.action = .openLamp
        let none = try slotHeight(bare)
        XCTAssertEqual(try slotHeight(tailed), none, accuracy: 0.5, "a tail never reflows what sits below (R-Z5)")
        let lead = try size(Text("1 to read").font(CicadaTheme.displayFont(size: RoomSentenceView.leadSize)), width: 760).height
        let tailLine = try size(Text(verbatim: " ").font(CicadaTheme.displayFont(size: RoomSentenceView.tailSize, italic: true)),
                                width: 760).height
        XCTAssertEqual(SentenceSlot.reservedTailLines, 1)
        XCTAssertLessThanOrEqual(none, lead + CicadaTheme.spacingXS + tailLine + 1, "the slot holds a second, empty tail line")
    }

    /// A tail at R-Z13's 80-character budget fits one line at the default zoom (at the display floor if it must), so
    /// at 1× the slot never grows; only a column too narrow for even that wraps — never cut.
    func test_aBudgetTailFitsOneLineAtTheDefaultZoom() throws {
        let bare = SentenceLine(lead: "Paused.")
        var full = bare
        full.tail = String("Stopped at your plan's limit, which resets on Tuesday at 2:00 PM. Continue then.".prefix(SentenceLine.maxTail))
        XCTAssertEqual(full.tail?.count, SentenceLine.maxTail)
        XCTAssertEqual(try slotHeight(full), try slotHeight(bare), accuracy: 0.5)
        XCTAssertGreaterThan(try slotHeight(full, width: 420), try slotHeight(bare, width: 420),
                             "a narrow column wraps the tail rather than cutting it")
    }
}

/// The pile stands on the painted room now, and its spines are translucent at rest (85 %) and the folded remainder is a
/// 40 % fill — with nothing under them the wall and floor would show through behind each count (DR-13: no text on the
/// art). A spine rests on the page ground in its own silhouette, so whatever is behind it never shows.
@MainActor
final class SleepPileGroundTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1 }

    private func plane(_ spec: BookSpec, over ground: Color) throws -> SpriteTestAssets.Plane {
        let spine = SpineButton(spec: spec, row: nil, episodes: [], room: nil, onOpenDetails: { _ in },
                                height: 40, gap: 0, width: 200,
                                // The remainder carries its count; a source's spine is drawn bare here (its mark's
                                // logo reads the Store, which this offscreen render has none of).
                                showsLabel: spec.isRemainder, cell: 5)
        let renderer = ImageRenderer(content: spine.frame(width: 200, height: 40).background(ground))
        renderer.scale = 1
        return SpriteTestAssets.Plane(try XCTUnwrap(renderer.cgImage))
    }

    func test_nothingBehindASpineShowsThroughIt() throws {
        let specs = [BookSpec(origin: "claude-code", count: 3, height: 40, widthFraction: 1, isRemainder: false),
                     BookSpec(origin: "+more", count: 7, height: 40, widthFraction: 1, isRemainder: true)]
        for spec in specs {
            let red = try plane(spec, over: .red), blue = try plane(spec, over: .blue)
            XCTAssertEqual([red.w, red.h], [200, 40])
            // The spine's interior, two cells in from every edge (its silhouette's corners are the art's own).
            for y in 10..<30 { for x in 10..<190 {
                XCTAssertEqual(red.at(x, y), blue.at(x, y), "\(spec.origin): the ground shows through at (\(x), \(y))")
                if red.at(x, y) != blue.at(x, y) { return }
            } }
        }
    }
}

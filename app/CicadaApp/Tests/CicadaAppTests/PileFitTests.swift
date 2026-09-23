import XCTest
@testable import CicadaApp

/// Live check 2026-09-23 (Z-B1…Z-B3) — on a bank with hundreds of items across
/// four sources, four 40 pt spines and their gaps needed 168 pt of a 130 pt
/// column, so the pile grew out of the room and the card's clip cut its top
/// spine. The pile is the page's one volume encoding (R1/R9): it may be
/// COMPRESSED to fit, never cut, and every count it carried stays readable.
final class PileFitTests: XCTestCase {

    /// Every View-menu step (G130: 0.8…1.4 in 0.1).
    private let steps: [Double] = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]

    private func room(_ scale: Double) -> DeskSceneLayout {
        deskSceneLayout(pointSize: SleepView.wormPointSize, uiScale: scale)
    }

    private func sources(_ n: Int, chars: Int, count: Int = 300) -> [OriginVolume] {
        (0..<n).map { OriginVolume(origin: "origin-\($0)", count: count, chars: chars - $0, remaining: count) }
    }

    /// The queues the live check could not draw, and the extremes around them.
    private var queues: [(name: String, volumes: [OriginVolume])] {
        [("empty", []),
         ("one tiny book", sources(1, chars: 1, count: 1)),
         ("four sources, hundreds each (the live check)", sources(4, chars: 4_000_000)),
         ("eight sources at the ceiling", sources(8, chars: 50_000_000)),
         ("thirty sources, folded", sources(30, chars: 1_000_000_000, count: 50)),
         ("mixed", [OriginVolume(origin: "claude-code", count: 400, chars: 90_000_000, remaining: 400),
                    OriginVolume(origin: "safari-bookmark", count: 300, chars: 3_000_000, remaining: 300),
                    OriginVolume(origin: "rss", count: 200, chars: 400_000, remaining: 200),
                    OriginVolume(origin: "saved-link", count: 1, chars: 0, remaining: 1)])]
    }

    func test_theTallestPileFitsTheColumnAtEveryZoomStep() {
        for scale in steps {
            let layout = room(scale)
            XCTAssertLessThanOrEqual(layout.pileFrame.maxY, layout.size.height, "the column is inside the room")
            for queue in queues {
                let books = bookPileLayout(queue.volumes)
                let fit = fitPile(books, in: layout, uiScale: scale)
                XCTAssertLessThanOrEqual(books.count, PileFitting.maxSpines, queue.name)
                XCTAssertLessThanOrEqual(fit.totalHeight, layout.pileFrame.height + 0.001,
                                         "\(queue.name) at \(scale)× overflows its \(layout.pileFrame.height) pt column")
                XCTAssertEqual(fit.maxWidth, layout.pileFrame.width, "Z-B3: a full spine is the column's width")
            }
        }
    }

    /// Z-B1 — quantity is still said where it is true: every spine tall enough
    /// to carry its count as authored still carries it once compressed.
    func test_everySpineThatCarriedACountStillCarriesIt() {
        for scale in steps {
            let layout = room(scale)
            let unit = layout.cell / PileFitting.referenceCell
            for queue in queues {
                let books = bookPileLayout(queue.volumes)
                let fit = fitPile(books, in: layout, uiScale: scale)
                for spec in books where spec.height * unit >= fit.labelMinHeight {
                    XCTAssertTrue(fit.showsLabel(spec), "\(queue.name) at \(scale)×: \(spec.origin) lost its count")
                }
            }
        }
    }

    /// The cap is measured, not a round number: eight spines at the label floor
    /// fit every step; a ninth does not fit at 1.0×.
    func test_eightSpinesAtTheLabelFloorFitEveryStep_nineWouldNot() {
        for scale in steps {
            let layout = room(scale)
            let unit = layout.cell / PileFitting.referenceCell
            let perSpine = PileFitting.labelMinPoints * CGFloat(scale) + BookPileView.spineGap * unit
            XCTAssertLessThanOrEqual(CGFloat(PileFitting.maxSpines) * perSpine, layout.pileFrame.height, "\(scale)×")
        }
        let one = room(1.0)
        XCTAssertGreaterThan(CGFloat(PileFitting.maxSpines + 1) * (PileFitting.labelMinPoints + BookPileView.spineGap),
                             one.pileFrame.height)
        XCTAssertEqual(PileFitting.maxBooks, PileFitting.maxSpines - 1, "the eighth spine is the remainder")
        XCTAssertEqual(bookPileLayout(sources(30, chars: 1_000_000_000, count: 50)).count, PileFitting.maxSpines)
    }

    /// Compression keeps the pile's one comparison: largest first stays largest first.
    func test_compressionKeepsThePilesOrder() {
        let layout = room(1.0)
        let books = bookPileLayout(queues.first { $0.name == "mixed" }!.volumes)
        let fit = fitPile(books, in: layout, uiScale: 1.0)
        let heights = books.map { fit.height($0) }
        XCTAssertEqual(heights, heights.sorted(by: >))
        XCTAssertLessThan(heights.last ?? 0, heights.first ?? 0)
    }

    /// A pile that already fits is drawn exactly as authored.
    func test_aPileThatFitsIsDrawnAsAuthored() {
        let books = bookPileLayout([OriginVolume(origin: "claude-code", count: 3, chars: 2000, remaining: 3)])
        let fit = fitPile(books, in: room(1.0), uiScale: 1.0)
        XCTAssertEqual(fit.height(books[0]), 14, accuracy: 0.001)
        XCTAssertEqual(fit.gap, 2, accuracy: 0.001)
        XCTAssertTrue(fit.showsLabel(books[0]))
    }

    /// Z-B2 — the pile scales with the lattice it stands on.
    func test_thePileScalesWithTheLattice() {
        XCTAssertEqual(room(1.0).cell, PileFitting.referenceCell, "the heights were authored at 1.0×")
        let books = bookPileLayout([OriginVolume(origin: "rss", count: 3, chars: 2000, remaining: 3)])
        XCTAssertEqual(fitPile(books, in: room(1.1), uiScale: 1.1).height(books[0]), 14 * 6 / 5, accuracy: 0.001,
                       "1.1× snaps to 6 pt cells: the spine grows with the room, not by 1.1")
    }

    /// A source read through this cycle draws no spine, so it takes no height.
    func test_aSpineReadThroughTakesNoRoom() {
        let books = [BookSpec(origin: "rss", count: 4, height: 40, widthFraction: 0, isRemainder: false)]
        let fit = fitPile(books, in: room(1.0), uiScale: 1.0)
        XCTAssertEqual(fit.totalHeight, 0)
        XCTAssertEqual(fit.height(books[0]), 0)
    }
}

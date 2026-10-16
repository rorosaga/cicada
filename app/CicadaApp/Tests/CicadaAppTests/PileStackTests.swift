import XCTest
@testable import CicadaApp

/// The pile as a stack of books (owner pick "A · Stack", 2026-10-16): whole cells, inside the pile's column and the
/// painted room at every art scale, the fattest at the bottom, a second stack before anything is cut, and one "+N"
/// book for what neither stack holds. Each count sits on a plate inside its book's outline, or not at all.
final class PileStackTests: XCTestCase {
    private func books(_ pairs: [(String, Int)]) -> [BookSpec] {
        bookPileLayout(pairs.enumerated().map { i, p in OriginVolume(origin: p.0, count: p.1, chars: 1000 - i, remaining: p.1) })
    }

    private var realistic: [BookSpec] { books([("claude-code", 4), ("imessage", 1)]) }
    private var crowded: [BookSpec] {
        books([("claude-code", 34), ("chrome-bookmark", 12), ("imessage", 6), ("codex", 3), ("apple-notes", 2),
               ("youtube-playlist", 2), ("rss", 1)])
    }
    private var queues: [(String, [BookSpec])] {
        [("empty", []),
         ("realistic", realistic),
         ("crowded", crowded),
         ("seven at the top step", books((0..<7).map { ("origin-\($0)", 400) })),
         ("thirty sources", books((0..<30).map { ("origin-\($0)", 60 - $0) })),
         ("one read through", [BookSpec(origin: "rss", count: 3, remaining: 0), BookSpec(origin: "codex", count: 2)])]
    }

    func test_everyBookIsWholeCellsInsideTheColumnAndThePaintedRoom_atEveryScale() {
        for cell: CGFloat in [5, 4, 3, 2] {
            let layout = deskSceneLayout(pixelScale: cell)
            for (name, queue) in queues {
                let placed = PileBooks.stack(queue)
                for book in placed {
                    XCTAssertGreaterThanOrEqual(book.x, 0, name)
                    XCTAssertLessThanOrEqual(book.x + book.width, PileBooks.rightEdge, name)
                    XCTAssertGreaterThanOrEqual(book.y, PileBooks.base, name)
                    XCTAssertLessThanOrEqual(book.y + book.rows, PileBooks.columnHeight, name)
                    XCTAssertGreaterThanOrEqual(book.width, BookArt.minWidth, name)
                    let frame = CGRect(x: layout.pileFrame.minX + CGFloat(book.x) * cell,
                                       y: layout.pileFrame.minY + CGFloat(book.y) * cell,
                                       width: CGFloat(book.width) * cell, height: CGFloat(book.rows) * cell)
                    XCTAssertTrue(layout.pileFrame.contains(frame), "\(name) at \(cell) pt")
                    XCTAssertTrue(layout.paintedFrame.contains(frame), "\(name) at \(cell) pt")
                    XCTAssertEqual(frame.minX, frame.minX.rounded(), "\(name): whole points")
                }
                for (i, a) in placed.enumerated() {
                    for b in placed[(i + 1)...] {
                        let ra = CGRect(x: a.x, y: a.y, width: a.width, height: a.rows)
                        let rb = CGRect(x: b.x, y: b.y, width: b.width, height: b.rows)
                        XCTAssertFalse(ra.intersects(rb), "\(name): \(a.id) overlaps \(b.id)")
                    }
                }
            }
        }
    }

    func test_nothingIsLost_andAStackNeverPassesItsHeight() {
        for (name, queue) in queues {
            let placed = PileBooks.stack(queue)
            let unread = queue.filter { $0.remaining > 0 }
            XCTAssertEqual(placed.reduce(0) { $0 + $1.spec.count }, unread.reduce(0) { $0 + $1.count }, name)
            XCTAssertLessThanOrEqual(placed.filter(\.spec.isRemainder).count, 1, name)
            for x in Set(placed.map { $0.x + $0.width > PileBooks.leftStackEdge + 1 }) {
                let stack = placed.filter { ($0.x + $0.width > PileBooks.leftStackEdge + 1) == x }
                XCTAssertLessThanOrEqual(stack.reduce(0) { $0 + $1.rows }, PileBooks.maxStackRows, name)
                XCTAssertEqual(stack.map(\.y), stack.map(\.y).sorted(), "\(name): bottom-up")
            }
        }
        XCTAssertTrue(PileBooks.stack([BookSpec(origin: "rss", count: 3, remaining: 0)]).isEmpty, "read through: no book")
    }

    /// The owner's screenshot: Claude Code 4 and Messages 1 — two books, one stack, Messages a book like the rest.
    func test_theRealisticPileIsTwoBooksInOneStack() {
        let placed = PileBooks.stack(realistic)
        XCTAssertEqual(placed.map(\.spec.origin), ["claude-code", "imessage"])
        XCTAssertEqual(placed.map(\.kind), [.chat, .message])
        XCTAssertEqual(placed.map(\.rows), [9, 7])
        XCTAssertEqual(placed.map(\.y), [PileBooks.base, PileBooks.base + 9])
        XCTAssertEqual(placed.map(\.width), [40, 36])
        XCTAssertEqual(placed.map { $0.x + $0.width }, [PileBooks.rightEdge, PileBooks.rightEdge - 2])
    }

    /// Seven sources fit in two stacks without a fold; seven at the top step do not, and the "+N" carries the rest.
    func test_twoStacksBeforeAFold_andTheFoldCarriesTheRest() {
        let seven = PileBooks.stack(crowded)
        XCTAssertEqual(seven.count, 7)
        XCTAssertFalse(seven.contains { $0.spec.isRemainder })
        XCTAssertEqual(Set(seven.map(\.width)).isSubset(of: Set(PileBooks.narrow.values)), true, "two stacks are narrow")

        let big = PileBooks.stack(books((0..<7).map { ("origin-\($0)", 400) }))
        let fold = try? XCTUnwrap(big.first { $0.spec.isRemainder })
        XCTAssertEqual(fold?.kind, .other)
        XCTAssertEqual(fold?.spec.count, 400 * (7 - (big.count - 1)))
        XCTAssertEqual(big.last?.spec.isRemainder, true, "the fold lies on top")

        let thirty = PileBooks.stack(books((0..<30).map { ("origin-\($0)", 60 - $0) }))
        XCTAssertEqual(thirty.filter(\.spec.isRemainder).count, 1)
        XCTAssertEqual(thirty.last?.spec.isRemainder, true)
    }

    /// A count sits on a plate of whole cells inside its book's outline, clear of the bands' right end and the page
    /// block, or the book carries none (then the tooltip, popover and Waiting tab say it).
    func test_everyPlateFitsInsideItsBook_atEveryScaleAndZoom() {
        let cases: [(CGFloat, Double)] = [(5, 1), (4, 1), (3, 1), (2, 1.4), (3, 0.8), (4, 1.2), (5, 1.4)]
        for (cell, zoom) in cases {
            for (name, queue) in queues {
                for book in PileBooks.stack(queue) {
                    guard let plate = PileBooks.plate(for: book, cell: cell, uiScale: zoom) else { continue }
                    XCTAssertGreaterThanOrEqual(plate.x, book.x + 1, name)
                    XCTAssertLessThanOrEqual(plate.x + plate.width, book.x + book.width - PileBooks.plateTrail, name)
                    XCTAssertGreaterThanOrEqual(plate.y, book.y + 1, name)
                    XCTAssertLessThanOrEqual(plate.y + plate.height, book.y + book.rows - 1, name)
                    XCTAssertGreaterThanOrEqual(CGFloat(plate.height) * cell, PileBooks.platePoints * CGFloat(zoom) - 0.01)
                    if book.spec.isRemainder { XCTAssertFalse(plate.showsMark) }
                }
            }
        }
    }

    func test_theCountIsReadableWhereTheArtIsLargeEnough() {
        for cell: CGFloat in [5, 4, 3] {
            for book in PileBooks.stack(realistic) + PileBooks.stack(crowded) {
                XCTAssertNotNil(PileBooks.plate(for: book, cell: cell, uiScale: 1), "\(book.id) at \(cell) pt")
            }
        }
        for book in PileBooks.stack(realistic) {
            XCTAssertEqual(PileBooks.plate(for: book, cell: 5, uiScale: 1)?.showsMark, true, "\(book.id): its mark too")
        }
        // 2 pt (⌘+ with the Reader open): a 15 pt plate needs 8 rows, more than a 7-row book holds inside its outline.
        let thin = PileBooks.stack(realistic).first { $0.rows == 7 }!
        XCTAssertNil(PileBooks.plate(for: thin, cell: 2, uiScale: 1))
        XCTAssertEqual(PileBooks.label(BookSpec(origin: "+more", count: 5, isRemainder: true)), "+5")
        XCTAssertEqual(PileBooks.label(BookSpec(origin: "rss", count: 12)), "12")
    }
}

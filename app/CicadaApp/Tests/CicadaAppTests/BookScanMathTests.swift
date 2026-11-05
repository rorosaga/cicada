import CoreGraphics
import Foundation
import Vision
import XCTest
@testable import CicadaApp

/// G233 — the book scanner's pure half (corner mapping, the stability rule, the hold) and one real Vision run on a
/// barcode drawn here. The camera itself can only be proven with a camera.
final class BookScanMathTests: XCTestCase {
    private let isbn = "9780306406157"      // a published example number with a valid check digit
    private let price = "5901234123457"     // a valid EAN-13 that is not a book's (no 978/979 prefix)

    // MARK: corner mapping

    private func point(_ x: CGFloat, _ y: CGFloat, image: CGSize, view: CGSize, mirrored: Bool = false) -> CGPoint {
        ScanGeometry.viewPoint(CGPoint(x: x, y: y), imageSize: image, viewSize: view, mirrored: mirrored)
    }

    func testVisionsBottomLeftOriginBecomesAViewsTopLeft() {
        let size = CGSize(width: 400, height: 300)
        XCTAssertEqual(point(0, 0, image: size, view: size), CGPoint(x: 0, y: 300))   // Vision's bottom-left
        XCTAssertEqual(point(1, 1, image: size, view: size), CGPoint(x: 400, y: 0))   // its top-right
        XCTAssertEqual(point(0.25, 0.75, image: size, view: size), CGPoint(x: 100, y: 75))
    }

    func testAspectFillScalesToCoverAndCentresTheOverflow() {
        // A 1280×720 frame in a square 400 view: scale 400/720, the sides cropped equally.
        let image = CGSize(width: 1280, height: 720), view = CGSize(width: 400, height: 400)
        let scale = 400.0 / 720.0
        let centre = point(0.5, 0.5, image: image, view: view)
        XCTAssertEqual(centre.x, 200, accuracy: 0.001)
        XCTAssertEqual(centre.y, 200, accuracy: 0.001)
        let left = point(0, 0.5, image: image, view: view)
        XCTAssertEqual(left.x, (400 - 1280 * scale) / 2, accuracy: 0.001)   // off the view's left edge (cropped)
        XCTAssertLessThan(left.x, 0)
        // A tall view crops the other way: the height fits, the width overflows still, and y has no offset.
        let tall = point(0.5, 1, image: image, view: CGSize(width: 300, height: 600))
        XCTAssertEqual(tall.y, 0, accuracy: 0.001)
    }

    func testMirroringFlipsLeftAndRightOnly() {
        let image = CGSize(width: 1280, height: 720), view = CGSize(width: 760, height: 560)
        let plain = point(0.2, 0.3, image: image, view: view)
        let mirrored = point(0.2, 0.3, image: image, view: view, mirrored: true)
        XCTAssertEqual(mirrored.x, view.width - plain.x, accuracy: 0.001)
        XCTAssertEqual(mirrored.y, plain.y, accuracy: 0.001)
    }

    func testAQuadMapsAllFourCornersInOrder() {
        let quad = ScanQuad(topLeft: CGPoint(x: 0.2, y: 0.8), topRight: CGPoint(x: 0.6, y: 0.8),
                            bottomRight: CGPoint(x: 0.6, y: 0.4), bottomLeft: CGPoint(x: 0.2, y: 0.4))
        let size = CGSize(width: 100, height: 100)
        let plain = quad.viewPoints(imageSize: size, viewSize: size, mirrored: false)
        XCTAssertEqual(plain[0].x, 20, accuracy: 0.001)    // top-left stays top-left
        XCTAssertEqual(plain[0].y, 20, accuracy: 0.001)
        XCTAssertEqual(plain[2].x, 60, accuracy: 0.001)
        XCTAssertEqual(plain[2].y, 60, accuracy: 0.001)
        let mirrored = quad.viewPoints(imageSize: size, viewSize: size, mirrored: true)
        XCTAssertEqual(mirrored[0].x, 80, accuracy: 0.001) // and appears at the right when the feed is mirrored
        XCTAssertEqual(mirrored[0].y, 20, accuracy: 0.001)
    }

    // MARK: the stability rule

    private func reading(_ payload: String) -> BarcodeReading {
        let corner = CGPoint(x: 0.5, y: 0.5)
        return BarcodeReading(payload: payload, quad: ScanQuad(topLeft: corner, topRight: corner, bottomRight: corner, bottomLeft: corner))
    }

    func testTheSameISBNInThreeFramesInARowIsTaken() {
        var rule = BookScanStabilizer()
        XCTAssertNil(rule.feed([reading(isbn)]))
        XCTAssertNil(rule.feed([reading(isbn)]))
        XCTAssertEqual(rule.feed([reading(isbn)]), .book(isbn))
    }

    func testOneFrameOrAChangingNumberNeverFires() {
        var rule = BookScanStabilizer()
        XCTAssertNil(rule.feed([reading(isbn)]))
        XCTAssertNil(rule.feed([reading("9780140449136")]))   // another valid number resets the run
        XCTAssertNil(rule.feed([reading(isbn)]))
        XCTAssertNil(rule.feed([reading(isbn)]))
        XCTAssertEqual(rule.feed([reading(isbn)]), .book(isbn))
    }

    func testABadCheckDigitIsNotABookAndNeverCaptures() {
        var rule = BookScanStabilizer()
        let misread = "9780306406158"   // one digit off
        var events: [ScanEvent?] = []
        for _ in 0..<6 { events.append(rule.feed([reading(misread)])) }
        XCTAssertEqual(events.compactMap { $0 }, [.notABook], "told once, never captured")
    }

    func testFlickerOfNoCodeIsForgivenTwiceButNotThree() {
        var rule = BookScanStabilizer()
        _ = rule.feed([reading(isbn)])
        _ = rule.feed([reading(isbn)])
        XCTAssertNil(rule.feed([]))
        XCTAssertNil(rule.feed([]))
        XCTAssertEqual(rule.feed([reading(isbn)]), .book(isbn), "two empty frames did not reset the run")

        var other = BookScanStabilizer()
        _ = other.feed([reading(isbn)])
        _ = other.feed([reading(isbn)])
        for _ in 0..<3 { _ = other.feed([]) }
        XCTAssertNil(other.feed([reading(isbn)]), "three empty frames did")
    }

    func testTheSameNumberNeverFiresTwiceInASession() {
        var rule = BookScanStabilizer()
        var taken = 0
        for _ in 0..<10 { if case .book = rule.feed([reading(isbn)]) { taken += 1 } }   // held in view
        for _ in 0..<6 { _ = rule.feed([]) }                                          // taken away…
        for _ in 0..<10 { if case .book = rule.feed([reading(isbn)]) { taken += 1 } } // …and shown again
        XCTAssertEqual(taken, 1)
    }

    func testAFailedCaptureMayBeReadAgain() {
        var rule = BookScanStabilizer()
        for _ in 0..<3 { _ = rule.feed([reading(isbn)]) }
        rule.forget(isbn)
        for _ in 0..<6 { _ = rule.feed([]) }
        var again: ScanEvent?
        for _ in 0..<3 { again = rule.feed([reading(isbn)]) ?? again }
        XCTAssertEqual(again, .book(isbn))
    }

    func testAFailedCaptureWithTheBookStillInViewDoesNotRefireAtOnce() {
        var rule = BookScanStabilizer()
        var t = 0.0
        func frame() -> ScanEvent? { t += 0.05; return rule.feed([reading(isbn)], at: t) }
        var fired = 0
        for _ in 0..<3 { if case .book = frame() { fired += 1 } }
        XCTAssertEqual(fired, 1)
        rule.forget(isbn)                                    // the capture failed (a demo bank, the backend down)
        // Held continuously for just under the wait: nothing, however many frames.
        while t < BookScanStabilizer.retryAfterFailure - 0.1 { XCTAssertNil(frame()) }
        // Then it may fire again, once.
        var later = 0
        for _ in 0..<(Int(BookScanStabilizer.retryAfterFailure * 20) + 20) { if case .book = frame() { later += 1 } }
        XCTAssertEqual(later, 1)
    }

    func testAFailedCaptureIsReadAgainAtOnceWhenTheCodeLeavesAndReturns() {
        var rule = BookScanStabilizer()
        for i in 0..<3 { _ = rule.feed([reading(isbn)], at: Double(i) * 0.05) }
        rule.forget(isbn)
        for i in 3..<7 { _ = rule.feed([], at: Double(i) * 0.05) }
        var again: ScanEvent?
        for i in 7..<10 { again = rule.feed([reading(isbn)], at: Double(i) * 0.05) ?? again }
        XCTAssertEqual(again, .book(isbn))
    }

    func testAPayloadWithNonASCIIDigitsIsNotABookAndDoesNotCrash() {
        XCTAssertNil(BookISBN.parse("٠١٢٣٤٥٦٧٨٩"))         // 10 Arabic-Indic digits
        XCTAssertNil(BookISBN.parse("012345678\u{00B2}"))  // a superscript check digit
        XCTAssertNil(BookISBN.parse("0123456\u{00BD}89"))  // a fraction
        XCTAssertNil(BookISBN.parse("٩٧٨٠١٤٠٤٤٩١٣٦"))        // 13 Arabic-Indic digits
        XCTAssertNil(BookISBN.parse("978014044913\u{00B2}"))
        XCTAssertEqual(BookISBN.parse(isbn), isbn)
    }

    func testANonBookCodeBesideABookDoesNotHideTheBook() {
        var rule = BookScanStabilizer()
        var last: ScanEvent?
        for _ in 0..<3 { last = rule.feed([reading(price), reading(isbn)]) }
        XCTAssertEqual(last, .book(isbn))
    }

    func testAPriceCodeIsToldOnceAndNotCaptured() {
        var rule = BookScanStabilizer()
        let events = (0..<8).compactMap { _ in rule.feed([reading(price)]) }
        XCTAssertEqual(events, [.notABook])
    }

    // MARK: holding a highlight steady

    private func quad(_ x: CGFloat) -> ScanQuad {
        ScanQuad(topLeft: CGPoint(x: x, y: 0.8), topRight: CGPoint(x: x + 0.2, y: 0.8),
                 bottomRight: CGPoint(x: x + 0.2, y: 0.6), bottomLeft: CGPoint(x: x, y: 0.6))
    }

    func testAShapeThatVanishesIsHeldBrieflyThenGoes() {
        var hold = QuadHold()
        XCTAssertNotNil(hold.update(quad(0.3), at: 10))
        XCTAssertNotNil(hold.update(nil, at: 10.2), "one missed frame does not flicker it")
        XCTAssertNil(hold.update(nil, at: 10.5))
    }

    func testASmallMoveIsFollowedPartwayAndABigOneAtOnce() {
        var hold = QuadHold()
        _ = hold.update(quad(0.3), at: 0)
        let near = hold.update(quad(0.35), at: 0.05)
        XCTAssertEqual(near?.topLeft.x ?? 0, 0.3 + 0.05 * QuadHold.followFraction, accuracy: 0.0001)
        let far = hold.update(quad(0.7), at: 0.1)
        XCTAssertEqual(far, quad(0.7), "a different thing is taken as it is")
    }

    // MARK: Vision on a drawn barcode

    func testVisionReadsADrawnISBNAndItsCornersLandWhereItWasDrawn() throws {
        let canvas = CGSize(width: 1280, height: 720)
        let drawn = CGRect(x: 700, y: 200, width: 400, height: 220)   // top-left origin, in pixels
        let image = try XCTUnwrap(EAN13Drawing.image(digits: isbn, canvas: canvas, at: drawn))
        let readings = BookFrameVision.barcodes(VNImageRequestHandler(cgImage: image, options: [:]))
        let found = try XCTUnwrap(readings.first, "Vision read no barcode on the drawn image")
        XCTAssertEqual(found.payload, isbn)
        XCTAssertEqual(found.isbn, isbn)

        // The same mapping the window uses, onto a view the size of the canvas: the quad must sit on the drawing.
        let points = found.quad.viewPoints(imageSize: canvas, viewSize: canvas, mirrored: false)
        let box = points.reduce(CGRect.null) { $0.union(CGRect(origin: $1, size: .zero)) }
        XCTAssertEqual(box.midX, drawn.midX, accuracy: 40)
        XCTAssertEqual(box.midY, drawn.midY, accuracy: 40)
        XCTAssertLessThan(box.width, drawn.width * 1.2)
        XCTAssertGreaterThan(box.width, drawn.width * 0.6)
    }

    func testVisionFindsABookShapedRectangle() throws {
        let canvas = CGSize(width: 1280, height: 720)
        let image = try XCTUnwrap(EAN13Drawing.image(digits: isbn, canvas: canvas, at: CGRect(x: 520, y: 330, width: 240, height: 130),
                                                      book: CGRect(x: 440, y: 60, width: 400, height: 600)))
        let book = try XCTUnwrap(BookFrameVision.bookRectangle(VNImageRequestHandler(cgImage: image, options: [:])))
        let points = book.viewPoints(imageSize: canvas, viewSize: canvas, mirrored: false)
        let box = points.reduce(CGRect.null) { $0.union(CGRect(origin: $1, size: .zero)) }
        XCTAssertEqual(box.midX, 640, accuracy: 40)
        XCTAssertEqual(box.midY, 360, accuracy: 40)
    }

    /// The analysis cost of one 1280×720 frame on this Mac (barcodes every frame, the rectangle every third): measured
    /// on a drawn image, not a live feed. The camera drops late frames, so a slow Mac lowers the analysis rate and
    /// never the preview's.
    func testAnalysisTimeOfOneFrame() throws {
        let canvas = CGSize(width: 1280, height: 720)
        let image = try XCTUnwrap(EAN13Drawing.image(digits: isbn, canvas: canvas, at: CGRect(x: 520, y: 330, width: 240, height: 130),
                                                      book: CGRect(x: 440, y: 60, width: 400, height: 600)))
        func run(_ body: (VNImageRequestHandler) -> Void) -> Double {
            let clock = ContinuousClock()
            var times: [Double] = []
            for _ in 0..<30 {
                let start = clock.now
                body(VNImageRequestHandler(cgImage: image, options: [:]))
                let d = start.duration(to: clock.now)
                times.append(Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15)
            }
            return times.sorted()[times.count / 2]
        }
        _ = run { _ = BookFrameVision.barcodes($0) }   // warm-up
        let barcode = run { _ = BookFrameVision.barcodes($0) }
        let rectangle = run { _ = BookFrameVision.bookRectangle($0) }
        print("G233 analysis median ms per 1280x720 frame: barcodes \(barcode), rectangle \(rectangle)")
        XCTAssertLessThan(barcode, 100)
        XCTAssertLessThan(rectangle, 150)
    }
}

/// EAN-13 drawn module by module, so a test needs no photograph.
enum EAN13Drawing {
    private static let left = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
    private static let parity = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]

    static func modules(_ digits: String) -> [Bool] {
        let d = digits.compactMap { Int(String($0)) }
        var bits = "101"
        for (i, digit) in d[1...6].enumerated() {
            let l = left[digit]
            bits += parity[d[0]][parity[d[0]].index(parity[d[0]].startIndex, offsetBy: i)] == "L" ? l : String(l.reversed().map { $0 == "0" ? "1" : "0" })
        }
        bits += "01010"
        for digit in d[7...12] { bits += String(left[digit].map { $0 == "0" ? "1" : "0" }) }
        bits += "101"
        return bits.map { $0 == "1" }
    }

    /// `rect` is the barcode's box, top-left origin in pixels; `book` an optional dark rectangle behind it.
    static func image(digits: String, canvas: CGSize, at rect: CGRect, book: CGRect? = nil) -> CGImage? {
        guard let context = CGContext(data: nil, width: Int(canvas.width), height: Int(canvas.height), bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.setFillColor(CGColor(gray: 0.35, alpha: 1))
        context.fill(CGRect(origin: .zero, size: canvas))
        func flipped(_ r: CGRect) -> CGRect { CGRect(x: r.minX, y: canvas.height - r.maxY, width: r.width, height: r.height) }
        if let book {
            context.setFillColor(CGColor(gray: 0.92, alpha: 1))
            context.fill(flipped(book))
        }
        // White quiet zone, then the bars (95 modules wide).
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(flipped(rect.insetBy(dx: -rect.width * 0.08, dy: -rect.height * 0.08)))
        let module = rect.width / 95
        context.setFillColor(CGColor(gray: 0, alpha: 1))
        for (i, on) in modules(digits).enumerated() where on {
            context.fill(flipped(CGRect(x: rect.minX + CGFloat(i) * module, y: rect.minY, width: module, height: rect.height)))
        }
        return context.makeImage()
    }
}

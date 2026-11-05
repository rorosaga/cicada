import CoreGraphics
import Foundation

// G233 — the pure half of the book scanner: where Vision's normalised corners land on the shown feed, how long a code
// must be seen before it is taken, and how a highlight is held steady. No AVFoundation, no Vision, no view: all of it
// is tested with plain numbers (`BookScanMathTests`).

/// A four-cornered shape in Vision's own space: normalised 0…1 of the frame, origin at the BOTTOM-left.
struct ScanQuad: Equatable, Sendable {
    var topLeft: CGPoint
    var topRight: CGPoint
    var bottomRight: CGPoint
    var bottomLeft: CGPoint

    var corners: [CGPoint] { [topLeft, topRight, bottomRight, bottomLeft] }

    /// The four corners as points in a view that shows the frame aspect-FILL (the preview layer's `resizeAspectFill`:
    /// scaled until the view is covered, centred, the overflow cropped), top-left origin, optionally mirrored left to
    /// right as the feed is. Corners may fall outside the view when the part of the frame they sit on is cropped.
    func viewPoints(imageSize: CGSize, viewSize: CGSize, mirrored: Bool) -> [CGPoint] {
        corners.map { ScanGeometry.viewPoint($0, imageSize: imageSize, viewSize: viewSize, mirrored: mirrored) }
    }

    /// The largest a corner moved between two quads, in normalised units.
    func distance(to other: ScanQuad) -> CGFloat {
        zip(corners, other.corners).map { hypot($0.x - $1.x, $0.y - $1.y) }.max() ?? 0
    }

    func blended(toward other: ScanQuad, by t: CGFloat) -> ScanQuad {
        func mix(_ a: CGPoint, _ b: CGPoint) -> CGPoint { CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t) }
        return ScanQuad(topLeft: mix(topLeft, other.topLeft), topRight: mix(topRight, other.topRight),
                        bottomRight: mix(bottomRight, other.bottomRight), bottomLeft: mix(bottomLeft, other.bottomLeft))
    }
}

enum ScanGeometry {
    /// One Vision point (normalised, bottom-left origin) to a point in a view showing the frame aspect-fill.
    static func viewPoint(_ p: CGPoint, imageSize: CGSize, viewSize: CGSize, mirrored: Bool) -> CGPoint {
        guard imageSize.width > 0, imageSize.height > 0 else { return .zero }
        let scale = max(viewSize.width / imageSize.width, viewSize.height / imageSize.height)
        let offsetX = (viewSize.width - imageSize.width * scale) / 2
        let offsetY = (viewSize.height - imageSize.height * scale) / 2
        let x = p.x * imageSize.width * scale + offsetX
        let y = (1 - p.y) * imageSize.height * scale + offsetY   // Vision's y runs up; a view's runs down.
        return CGPoint(x: mirrored ? viewSize.width - x : x, y: y)
    }
}

/// What one analysed frame held. The camera hands the view one of these about every 50 ms.
struct ScanFrame: Equatable, Sendable {
    /// The frame's pixel size, which the corners are normalised against.
    var imageSize: CGSize
    var barcode: ScanQuad?
    /// True when `barcode` is a book's number (a valid ISBN); a price code or a QR is drawn but not taken.
    var barcodeIsBook = false
    var book: ScanQuad?
}

/// One barcode Vision read in a frame.
struct BarcodeReading: Equatable, Sendable {
    let payload: String
    let quad: ScanQuad
    /// The ISBN-13 it spells, when it is a book's number.
    var isbn: String? { BookISBN.parse(payload) }
}

enum ScanEvent: Equatable, Sendable {
    case book(String)
    case notABook
}

/// The rule that takes a scan by itself. **A book's number is taken when the same ISBN has been read in 3 analysed
/// frames in a row** (about 0.15 s at the 20 analyses a second the camera runs; a frame with no code at all is
/// forgiven twice, so a flicker of glare does not reset the count). One misread frame cannot fire it: an EAN-13 that
/// fails its check digit is never an ISBN at all, and a different number resets the run. **A number taken in this
/// session never fires again** (so a book still in view is not added twice and does not flash again); it is let go
/// only by ``forget(_:)`` when its lookup failed, and then not at once: a failure with the book still in view would
/// otherwise re-fire on the next frame, once per round trip. **A forgotten number may fire again after
/// ``retryAfterFailure`` seconds, or as soon as its code has left the view and come back (the person showing it again),
/// whichever comes first** — time alone would make a deliberate re-scan wait, the code leaving alone would let a book
/// held still retry never. A code that is not a book's number says so once per sighting.
struct BookScanStabilizer {
    static let framesNeeded = 3
    static let missesForgiven = 2
    /// How long a number whose capture failed waits before a book still in view may fire it again.
    static let retryAfterFailure: TimeInterval = 4

    private var key: String?
    private var streak = 0
    private var misses = 0
    private var told = false
    private(set) var taken = Set<String>()
    /// A forgotten number, and the time before which it may not fire.
    private var cooling = [String: TimeInterval]()
    /// The time of the latest frame fed (`forget` is called from elsewhere, with no clock of its own).
    private var clock: TimeInterval = 0

    /// `now` is the frame's own time in seconds (any steady clock); only differences matter.
    mutating func feed(_ readings: [BarcodeReading], at now: TimeInterval = 0) -> ScanEvent? {
        clock = now
        guard let reading = readings.first(where: { $0.isbn != nil }) ?? readings.first else {
            misses += 1
            if misses > Self.missesForgiven { key = nil; streak = 0; told = false; cooling = [:] }
            return nil
        }
        misses = 0
        let seen = reading.isbn ?? reading.payload
        if seen == key { streak += 1 } else { key = seen; streak = 1; told = false }
        guard streak >= Self.framesNeeded else { return nil }
        if let isbn = reading.isbn {
            guard !taken.contains(isbn) else { return nil }
            if let until = cooling[isbn] {
                guard now >= until else { return nil }
                cooling[isbn] = nil
            }
            taken.insert(isbn)
            return .book(isbn)
        }
        guard !told else { return nil }
        told = true
        return .notABook
    }

    /// A number whose capture failed may be read again.
    mutating func forget(_ isbn: String) {
        taken.remove(isbn)
        key = nil; streak = 0; told = false
        if misses <= Self.missesForgiven { cooling[isbn] = clock + Self.retryAfterFailure }   // already out of view: no wait
    }
}

/// Keeps a highlight steady: a corner moves part of the way to where it was just seen (so it follows without
/// trembling), a jump to somewhere else is taken at once, and a shape that vanishes is held 0.3 s before it goes
/// (so one missed frame does not flicker it).
struct QuadHold {
    static let holdSeconds: TimeInterval = 0.3
    static let followFraction: CGFloat = 0.6
    /// Beyond this (normalised) a quad is a different thing, not the same one moving.
    static let jump: CGFloat = 0.15

    private var shown: ScanQuad?
    private var lastSeen: TimeInterval = 0

    mutating func update(_ seen: ScanQuad?, at now: TimeInterval) -> ScanQuad? {
        if let seen {
            if let shown, shown.distance(to: seen) < Self.jump {
                self.shown = shown.blended(toward: seen, by: Self.followFraction)
            } else {
                shown = seen
            }
            lastSeen = now
        } else if now - lastSeen > Self.holdSeconds {
            shown = nil
        }
        return shown
    }
}

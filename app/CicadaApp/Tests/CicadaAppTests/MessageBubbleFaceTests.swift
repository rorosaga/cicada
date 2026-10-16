import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G179 (live report, 2026-10-16): on the Sleep page in dark appearance a waiting conversation with no Contacts photo
/// drew as a near-black disc with a hairline letter — the ground-coloured ring was stroked OVER the monogram's own hue
/// ring, and the letter was 7 pt medium. The face now sits inside the ground ring and a small monogram's letters are
/// half its height, semibold; since the owner's look at the one Messages row (2026-10-16) it is a filled disc, because a
/// hue ring round one letter read as "ⓘ". Rendered offscreen (never the app), light and dark, at the Sleep page's 20 pt and Home's
/// 18 pt.
@MainActor
final class MessageBubbleFaceTests: XCTestCase {
    private static let scale: CGFloat = 4

    override func tearDown() async throws {
        CicadaTheme.mode = .dark
    }

    func testABubblesSmallInitialsAreHalfTheHeightAndSemibold() {
        XCTAssertEqual(EntityPictureLayout.initialsType(units: 17, compact: true).size, 8.5)
        XCTAssertEqual(EntityPictureLayout.initialsType(units: 17, compact: true).weight, .semibold)
        XCTAssertEqual(EntityPictureLayout.initialsType(units: 40, compact: true).size, 40 * 0.36, accuracy: 0.001)
        XCTAssertEqual(EntityPictureLayout.initialsType(units: 40, compact: true).weight, .medium)
        XCTAssertEqual(EntityPictureLayout.initialsType(units: 20).size, 20 * 0.36, accuracy: 0.001,
                       "a row's 20 pt picture, beside its own name, keeps the proportion")
        XCTAssertEqual(EntityPictureLayout.initialsType(units: 20).weight, .medium)
        XCTAssertEqual(MessageBubbles.faceUnits(20), 17)
    }

    /// The monogram reads as a picture, never as an info glyph (owner, 2026-10-16): a disc filled with the person's hue
    /// over the ground (no ring around one letter), the letter in the primary text colour, and the outermost ring the
    /// ground's own colour so the bubbles stay cut apart.
    func testTheMonogramIsAFilledDiscInLightAndDark() throws {
        for mode in [AppColorScheme.light, .dark] {
            for size: CGFloat in [20, 18] {
                CicadaTheme.mode = mode
                let bitmap = try render(MessageBubbleFace(name: "Bob Example", photo: nil, size: size), mode: mode)
                let hue = rgb(CicadaTheme.entityColor(for: .person))
                let ground = rgb(CicadaTheme.bgBase)
                let text = rgb(CicadaTheme.textPrimary)
                let label = "\(mode == .dark ? "dark" : "light") \(Int(size)) pt"
                let side = size * Self.scale
                let centre = side / 2

                // The face's edge is one fill all the way round — the hue over the ground, strictly between the two in
                // every channel (whatever space the renderer blends in): no hue ring, no bare ground.
                let faceRadius = MessageBubbles.faceUnits(size) / 2 * Self.scale
                let edge = stride(from: 0.0, to: 360.0, by: 10.0).map { degrees -> (Double, Double, Double) in
                    let r = faceRadius - 0.75 * Self.scale
                    let a = degrees * .pi / 180
                    return pixel(bitmap, x: centre + r * cos(a), y: centre + r * sin(a))
                }
                let fill = edge[0]
                func between(_ v: Double, _ a: Double, _ b: Double) -> Bool { v > min(a, b) + 0.02 && v < max(a, b) - 0.02 }
                XCTAssertTrue(between(fill.0, hue.0, ground.0) && between(fill.1, hue.1, ground.1)
                              && between(fill.2, hue.2, ground.2), "\(label): the fill is the hue over the ground")
                XCTAssertEqual(edge.filter { close($0, fill, tolerance: 0.02) }.count, 36, "\(label): filled to its edge")

                // The ground ring outside it.
                let groundHits = stride(from: 0.0, to: 360.0, by: 30.0).filter { degrees in
                    let r = side / 2 - 0.6 * Self.scale
                    let a = degrees * .pi / 180
                    return close(pixel(bitmap, x: centre + r * cos(a), y: centre + r * sin(a)), ground)
                }
                XCTAssertEqual(groundHits.count, 12, "\(label): the ring that cuts bubbles apart is the ground's colour")

                // The letter: text-coloured pixels inside, a real share of the disc, not a hairline.
                let inner = faceRadius - 2 * Self.scale
                var inside = 0, letter = 0
                for y in stride(from: centre - inner, to: centre + inner, by: 1) {
                    for x in stride(from: centre - inner, to: centre + inner, by: 1)
                    where (x - centre) * (x - centre) + (y - centre) * (y - centre) <= inner * inner {
                        inside += 1
                        if close(pixel(bitmap, x: x, y: y), text, tolerance: 0.25) { letter += 1 }
                    }
                }
                let share = Double(letter) / Double(max(inside, 1))
                XCTAssertGreaterThan(share, 0.08, "\(label): the letters are \(Int(share * 100)) % of the face")
            }
        }
    }

    // MARK: Helpers

    private func render(_ view: some View, mode: AppColorScheme) throws -> NSBitmapImageRep {
        let content = view
            .background(CicadaTheme.bgBase)
            .environment(\.colorScheme, mode == .dark ? .dark : .light)
        let renderer = ImageRenderer(content: content)
        renderer.scale = Self.scale
        let image = try XCTUnwrap(renderer.cgImage)
        if let dir = ProcessInfo.processInfo.environment["BUBBLE_RENDER_DIR"], !dir.isEmpty {
            let rep = NSBitmapImageRep(cgImage: image)
            let file = URL(fileURLWithPath: dir)
                .appendingPathComponent("bubble-\(mode == .dark ? "dark" : "light")-\(image.width).png")
            try rep.representation(using: .png, properties: [:])?.write(to: file)
        }
        return NSBitmapImageRep(cgImage: image)
    }

    private func pixel(_ bitmap: NSBitmapImageRep, x: CGFloat, y: CGFloat) -> (Double, Double, Double) {
        let c = bitmap.colorAt(x: Int(x.rounded(.down)), y: Int(y.rounded(.down)))?.usingColorSpace(.sRGB)
        return (Double(c?.redComponent ?? 0), Double(c?.greenComponent ?? 0), Double(c?.blueComponent ?? 0))
    }

    private func rgb(_ color: Color) -> (Double, Double, Double) {
        let c = NSColor(color).usingColorSpace(.sRGB)
        return (Double(c?.redComponent ?? 0), Double(c?.greenComponent ?? 0), Double(c?.blueComponent ?? 0))
    }

    private func close(_ a: (Double, Double, Double), _ b: (Double, Double, Double), tolerance: Double = 0.12) -> Bool {
        abs(a.0 - b.0) <= tolerance && abs(a.1 - b.1) <= tolerance && abs(a.2 - b.2) <= tolerance
    }
}

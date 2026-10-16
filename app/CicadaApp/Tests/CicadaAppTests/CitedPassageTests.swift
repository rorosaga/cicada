import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// QA 2026-10-16 (P1): the Reader said "1 of 3 cited here" and moved between the spans, but no turn showed the wash or
/// the underline — from an entity chip and from the Inbox alike. Cause: the passage was a selectable `Text`, and on
/// macOS a selectable `Text` is drawn by the selectable-text path, which never calls a `TextRenderer`. `CitedPassage`
/// keeps the words selectable and draws the washes from an identical copy behind them.
///
/// These read real pixels from an `NSHostingView` in a (never shown) window, the path the app draws through.
@MainActor
final class CitedPassageTests: XCTestCase {
    override func setUp() {
        CicadaTheme.uiScale = 1
        CicadaTheme.mode = .dark
    }

    private let segments: [CitedSpan.Segment] = [
        .init(text: "We moved Lantern's storage from ", mark: .plain),
        .init(text: "CSV to sqlite-vec last week", mark: .current),
        .init(text: " and the recall got faster.", mark: .plain),
    ]

    /// The cause, pinned: the span renderer draws on a plain `Text` and draws nothing on a selectable one. If a later
    /// macOS lets a renderer reach selectable text, this fails and `CitedPassage`'s second copy can go.
    func test_aSelectableTextSkipsTheSpanRenderer() throws {
        guard #available(macOS 15, *) else { throw XCTSkip("the renderer path is macOS 15+") }
        let plain = try Self.accentPixels(CitedSpan.text(segments).foregroundStyle(Color.white).citedSpans())
        let selectable = try Self.accentPixels(CitedSpan.text(segments).foregroundStyle(Color.white)
            .textSelection(.enabled).citedSpans())
        XCTAssertGreaterThan(plain, 200, "the wash and underline draw on a plain Text")
        XCTAssertEqual(selectable, 0, "a selectable Text never reaches the renderer")
    }

    /// The fix: a `CitedPassage` is selectable and still washed and underlined.
    func test_aCitedPassageIsWashedAndUnderlined() throws {
        guard #available(macOS 15, *) else { throw XCTSkip("the renderer path is macOS 15+") }
        let passage = try Self.accentPixels(CitedPassage(segments: segments, font: CicadaTheme.quoteFont,
                                                         color: .white))
        XCTAssertGreaterThan(passage, 200)
        let unmarked = try Self.accentPixels(CitedPassage(segments: [.init(text: "No span here at all.", mark: .plain)],
                                                          color: .white))
        XCTAssertEqual(unmarked, 0, "nothing cited, nothing washed")
    }

    /// The wash sits exactly under the words: the passage draws the same pixels as the one-copy renderer did on a
    /// plain `Text` (the wash, the underline and the glyphs together), so neither copy is offset from the other.
    func test_theWashLandsUnderTheWords() throws {
        guard #available(macOS 15, *) else { throw XCTSkip("the renderer path is macOS 15+") }
        let reference = try Self.pixels(CitedSpan.text(segments).font(CicadaTheme.quoteFont)
            .lineSpacing(CicadaTheme.quoteLineSpacing).foregroundStyle(Color.white)
            .fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .leading)
            .citedSpans())
        let passage = try Self.pixels(CitedPassage(segments: segments, color: .white))
        XCTAssertEqual(reference.count, passage.count)
        let differing = zip(reference, passage).filter { abs(Int($0) - Int($1)) > 24 }.count
        XCTAssertLessThan(Double(differing) / Double(reference.count), 0.002,
                          "\(differing) channels differ: the wash copy is not under the words")
    }

    /// Both doors use it: the Reader's turns and the Inbox's quote never put the renderer on selectable text again.
    func test_noSelectablePassageCarriesTheRendererDirectly() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        for file in ["Views/Provenance/ReaderColumn.swift", "Views/Inbox/InboxFocusCard.swift"] {
            let source = try String(contentsOf: root.appendingPathComponent(file), encoding: .utf8)
            XCTAssertTrue(source.contains("CitedPassage("), file)
            XCTAssertFalse(source.contains(".citedSpans("), "\(file) puts the renderer on a selectable passage")
        }
    }

    // MARK: - Pixels

    private static func render(_ view: some View) throws -> NSBitmapImageRep {
        let hosting = NSHostingView(rootView: view.frame(width: 300).padding(10).background(Color.black))
        hosting.appearance = NSAppearance(named: .darkAqua)
        hosting.frame = NSRect(x: 0, y: 0, width: 320, height: 10)
        let height = hosting.fittingSize.height
        hosting.frame = NSRect(x: 0, y: 0, width: 320, height: height)
        let window = NSWindow(contentRect: hosting.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded()
        hosting.display()
        let rep = try XCTUnwrap(hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds))
        hosting.cacheDisplay(in: hosting.bounds, to: rep)
        return rep
    }

    /// Pixels clearly in the accent's hue (the wash over black, and the underline); white glyphs never count.
    static func accentPixels(_ view: some View) throws -> Int {
        let rep = try render(view)
        var n = 0
        for x in 0..<rep.pixelsWide {
            for y in 0..<rep.pixelsHigh {
                guard let c = rep.colorAt(x: x, y: y)?.usingColorSpace(.sRGB) else { continue }
                if c.blueComponent > 0.12, c.blueComponent > c.redComponent + 0.08 { n += 1 }
            }
        }
        return n
    }

    static func pixels(_ view: some View) throws -> [UInt8] {
        let rep = try render(view)
        var out: [UInt8] = []
        for y in 0..<rep.pixelsHigh {
            for x in 0..<rep.pixelsWide {
                let c = rep.colorAt(x: x, y: y)?.usingColorSpace(.sRGB)
                out += [c?.redComponent, c?.greenComponent, c?.blueComponent].map { UInt8((($0 ?? 0) * 255).rounded()) }
            }
        }
        return out
    }
}

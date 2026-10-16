import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Looks polish (2026-10-15) — type specimens on the wire and in words, the colour share shown only where area means
/// something, and the enlarged screenshot: its state, opening and closing, its fitted frame, and the keyboard path
/// that never animates (DR-60). Synthetic only; nothing reaches a backend.
@MainActor
final class LooksPolishTests: XCTestCase {
    static let refJSON = """
    {"id": "2026-10-15-ink-example-com", "title": "Ink", "site": "ink.example.com",
     "image": {"url": "/design/2026-10-15-ink-example-com/image?v=abc", "width": 2880, "height": 1800, "bytes": 1},
     "specimens": [
       {"family": "Newsreader", "generic": "serif",
        "roles": [{"role": "body", "size": 19, "weight": 400}, {"role": "drop_cap", "size": 88, "weight": 400}],
        "image": {"url": "/design/2026-10-15-ink-example-com/type/1?v=0123456789ab", "width": 140, "height": 120,
                  "bytes": 0}},
       {"family": "Menlo", "generic": "monospace", "roles": [{"role": "caption", "size": 12.5}], "image": null}]}
    """

    // MARK: Specimens

    func testSpecimensDecodeWithTheirRolesAndDrawing() throws {
        let ref = try JSONDecoder().decode(DesignRef.self, from: Data(Self.refJSON.utf8))
        XCTAssertEqual(ref.specimens.map(\.family), ["Newsreader", "Menlo"])
        XCTAssertEqual(ref.specimens[0].roles.map(\.role), ["body", "drop_cap"])
        XCTAssertEqual(ref.specimens[0].image?.width, 140)
        XCTAssertNil(ref.specimens[1].image)
        let old = try JSONDecoder().decode(DesignRef.self, from: Data(#"{"id": "x"}"#.utf8))
        XCTAssertTrue(old.specimens.isEmpty, "an older server sends none")
    }

    func testTheDrawingIsLoadedFromCicadasOwnAPIOnly() throws {
        let ref = try JSONDecoder().decode(DesignRef.self, from: Data(Self.refJSON.utf8))
        let path = try XCTUnwrap(ref.specimens[0].image?.url)
        XCTAssertTrue(StoredPreviewPath.loads(path) && APIClient.isPicturePath(path))
        XCTAssertFalse(StoredPreviewPath.loads("https://fonts.example.com/newsreader.woff2"),
                       "the app never loads a face a page names from the web")
    }

    func testASpecimenSaysWhereTheFamilyIsUsedAndWhenItIsAStandIn() {
        let roles = [DesignSpecimen.Role(role: "body", size: 19, weight: 400),
                     DesignSpecimen.Role(role: "drop_cap", size: 88), DesignSpecimen.Role(role: "caption", size: 12.5),
                     DesignSpecimen.Role(role: "link")]
        XCTAssertEqual(Copy.Looks.specimenUses(roles), "Body 19 px · Drop cap 88 px · Captions 12.5 px · Links")
        XCTAssertTrue(Copy.Looks.specimenGeneric("serif").contains("generic serif"))
        XCTAssertTrue(Copy.Looks.specimenGeneric(nil).contains("wasn't drawn"))
        XCTAssertEqual(LooksSpecimenFace.design("serif"), .serif)
        XCTAssertEqual(LooksSpecimenFace.design("ui-monospace"), .monospaced)
        XCTAssertEqual(LooksSpecimenFace.design("system-ui"), .default)
    }

    // MARK: The share rule

    func testTheShareShowsOnlyWhereAreaMeansSomething() {
        XCTAssertNil(Copy.Looks.share(0.0004, role: "ink"), "a thin ink line's area says nothing")
        XCTAssertNil(Copy.Looks.share(0.002, role: "accent"))
        XCTAssertEqual(Copy.Looks.share(0.9, role: "ground"), "90 %")
        XCTAssertEqual(Copy.Looks.share(0.05, role: "wash"), "5 %")
        XCTAssertEqual(Copy.Looks.share(0.003, role: "wash"), "< 1 %", "never \"0 %\" for something that is there")
        XCTAssertEqual(Copy.Looks.share(0.12, role: nil), "12 %")
        XCTAssertNil(Copy.Looks.share(0, role: nil), "a colour with no share shows none")
    }

    // MARK: The enlarged screenshot

    func testTheKeyboardOpensAndClosesInOneFrame() {
        XCTAssertEqual(LooksZoom.trigger(for: .keyDown), .keyboard)
        XCTAssertEqual(LooksZoom.trigger(for: .leftMouseUp), .pointer)
        XCTAssertEqual(LooksZoom.trigger(for: nil), .pointer)
        XCTAssertEqual(LooksZoom.style(.keyboard, reduceMotion: false), .instant, "DR-60: a key never animates")
        XCTAssertEqual(LooksZoom.style(.keyboard, reduceMotion: true), .instant)
        XCTAssertEqual(LooksZoom.style(.pointer, reduceMotion: false), .zoom)
        XCTAssertEqual(LooksZoom.style(.pointer, reduceMotion: true), .fade, "DR-66: Reduce Motion only fades")
        var zoom = LooksZoom()
        zoom.present("a", from: CGRect(x: 10, y: 20, width: 160, height: 100), style: .instant)
        XCTAssertTrue(zoom.isPresented && zoom.expanded, "the keyboard path presents at its fitted frame at once")
        let fitted = CGRect(x: 0, y: 0, width: 800, height: 500)
        XCTAssertEqual(zoom.frame(fitted: fitted), fitted)
        zoom.dismiss()
        XCTAssertFalse(zoom.isPresented || zoom.expanded)
    }

    func testThePointerGrowsFromTheThumbnailAndShrinksBack() {
        let thumb = CGRect(x: 40, y: 80, width: 220, height: 138)
        let fitted = CGRect(x: 100, y: 60, width: 1200, height: 750)
        var zoom = LooksZoom()
        zoom.present("a", from: thumb, style: .zoom)
        XCTAssertTrue(zoom.isPresented)
        XCTAssertFalse(zoom.expanded, "it appears on the thumbnail, then grows")
        XCTAssertEqual(zoom.frame(fitted: fitted), thumb)
        zoom.expanded = true
        XCTAssertEqual(zoom.frame(fitted: fitted), fitted)
        zoom.expanded = false
        XCTAssertEqual(zoom.frame(fitted: fitted), thumb, "closing shrinks back to where it came from")
        XCTAssertTrue(zoom.isPresented, "and leaves only when the shrink is done")
        zoom.dismiss()
        XCTAssertFalse(zoom.isPresented)
    }

    func testItShrinksBackToThePictureThatIsThereNow() {
        let book = LooksFrameBook()
        let fallback = CGRect(x: 1, y: 1, width: 10, height: 10)
        XCTAssertEqual(book.frame(for: "a", fallback: fallback), fallback)
        book.tiles["a"] = CGRect(x: 0, y: 0, width: 200, height: 125)
        XCTAssertEqual(book.frame(for: "a", fallback: fallback).width, 200)
        book.detail = ("a", CGRect(x: 900, y: 120, width: 330, height: 206))
        XCTAssertEqual(book.frame(for: "a", fallback: fallback).minX, 900,
                       "a tile's click opens the look beside the board: it shrinks into the detail's picture")
        XCTAssertEqual(book.frame(for: "b", fallback: fallback), fallback)
    }

    func testAViewportShotFitsWholeAndATallShotFitsTheWidthAndScrolls() {
        let board = CGSize(width: 1200, height: 800)
        let wide = LooksZoom.fitted(image: CGSize(width: 2880, height: 1800), in: board, margin: 40)
        XCTAssertFalse(wide.scrolls)
        XCTAssertEqual(wide.frame.width, 1120, accuracy: 0.5)
        XCTAssertEqual(wide.frame.height, 700, accuracy: 0.5)
        XCTAssertEqual(wide.frame.midX, 600, accuracy: 0.5)
        XCTAssertEqual(wide.frame.midY, 400, accuracy: 0.5)
        let tall = LooksZoom.fitted(image: CGSize(width: 1440, height: 9000), in: board, margin: 40)
        XCTAssertTrue(tall.scrolls, "a full-page shot scrolls")
        XCTAssertEqual(tall.frame.width, 1120, accuracy: 0.5)
        XCTAssertEqual(tall.frame.height, 720, accuracy: 0.5)
        let small = LooksZoom.fitted(image: CGSize(width: 300, height: 200), in: board, margin: 40)
        XCTAssertEqual(small.frame.size, CGSize(width: 300, height: 200), "never larger than its own pixels")
        let unknown = LooksZoom.fitted(image: .zero, in: board, margin: 40)
        XCTAssertFalse(unknown.frame.isEmpty)
    }

    /// DR-60 at the source: every keyboard-reachable path into the zoom runs in `Instant`, and Esc belongs to the
    /// zoom while it shows (the detail column drops its own Esc).
    func testTheSourceKeepsTheKeyboardPathInstant() throws {
        let files = try ThemeTokenTests.swiftSources()
        let page = try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix("Views/Looks/LooksPage.swift") }),
                              encoding: .utf8)
        XCTAssertTrue(page.contains("case .instant, .zoom: Instant.run { zoom.present("))
        XCTAssertTrue(page.contains("case .instant: Instant.run { zoom.dismiss() }"))
        XCTAssertTrue(page.contains(".keyboardShortcut(escapeCloses ? .cancelAction : nil)"))
        XCTAssertTrue(page.contains("escapeCloses: !zoom.isPresented"))
        let overlay = try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix("Views/Looks/LooksZoom.swift") }),
                                 encoding: .utf8)
        XCTAssertTrue(overlay.contains("shortcut: .cancelAction) { onClose(LooksZoom.currentTrigger()) }"))
        XCTAssertFalse(overlay.contains("withAnimation"), "the overlay itself never animates; the board decides")
    }

    func testTheOverlayAndASpecimenRenderOffscreen() throws {
        let ref = try JSONDecoder().decode(DesignRef.self, from: Data(Self.refJSON.utf8))
        var zoom = LooksZoom()
        zoom.present(ref.summary.id, from: CGRect(x: 20, y: 20, width: 200, height: 125), style: .instant)
        let overlay = LooksZoomOverlay(zoom: zoom, summary: ref.summary, onClose: { _ in })
            .frame(width: 900, height: 600)
        XCTAssertNotNil(ImageRenderer(content: overlay).nsImage)
        let list = LooksSpecimenList(specimens: ref.specimens).frame(width: 340)
        XCTAssertNotNil(ImageRenderer(content: list).nsImage)
    }
}

import AppKit
import CoreText
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M3 / plan R-M15 — the bundled display face resolves in every
/// layout the app ships in, registers idempotently, and degrades to the
/// system face (never to blank) when it is missing.
final class CicadaFontsTests: XCTestCase {
    override class func setUp() {
        super.setUp()
        CicadaFonts.registerBundled()
    }

    func testTheBundledFilesAreTheFacesTheThemeAsksFor() throws {
        for name in CicadaFonts.all {
            let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource(name, ext: "ttf", in: CicadaFonts.directory),
                                    "\(name).ttf is not bundled")
            let descriptors = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor] ?? []
            let names = descriptors.compactMap { CTFontDescriptorCopyAttribute($0, kCTFontNameAttribute) as? String }
            XCTAssertEqual(names, [name], "\(name).ttf carries PostScript name(s) \(names)")
        }
    }

    func testTheLicenceTravelsWithTheFonts() throws {
        let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource("OFL", ext: "txt", in: CicadaFonts.directory))
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("SIL OPEN FONT LICENSE Version 1.1"))
        XCTAssertTrue(text.contains("Instrument Serif Project Authors"))
    }

    /// CoreText answers a second registration of the same file with 105
    /// (already registered, measured) — success here.
    func testRegistrationMakesBothFacesResolveAndIsIdempotent() {
        XCTAssertEqual(CicadaFonts.registerBundled(), CicadaFonts.all)
        XCTAssertEqual(CicadaFonts.registerBundled(), CicadaFonts.all)
        for name in CicadaFonts.all { XCTAssertNotNil(NSFont(name: name, size: 28), name) }
    }

    /// The PR #70 class: `bundle.sh` re-nests the resource bundle, so a
    /// lookup that only works in the flat `swift test` layout ships broken.
    /// Both layouts are built from bytes; a bundle with no fonts reports none.
    func testTheFontsDirectoryResolvesInBothBundleLayoutsAndAnEmptyBundleDegrades() throws {
        let ttf = try Data(contentsOf: XCTUnwrap(
            Bundle.cicadaResources.cicadaResource(CicadaFonts.displayRegular, ext: "ttf", in: CicadaFonts.directory)))
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("font-layouts-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let file = "\(CicadaFonts.displayRegular).ttf"
        let flat = root.appendingPathComponent("Flat.bundle")
        try write(ttf, to: flat.appendingPathComponent("Resources/fonts/\(file)"))
        let nested = root.appendingPathComponent("Nested.bundle")
        try write(ttf, to: nested.appendingPathComponent("Contents/Resources/fonts/\(file)"))
        try write(Data("""
        <?xml version="1.0" encoding="UTF-8"?>
        <plist version="1.0"><dict>
        <key>CFBundleIdentifier</key><string>com.rorosaga.cicada.resources.test</string>
        <key>CFBundlePackageType</key><string>BNDL</string>
        </dict></plist>
        """.utf8), to: nested.appendingPathComponent("Contents/Info.plist"))
        for url in [flat, nested] {
            let bundle = try XCTUnwrap(Bundle(url: url), url.lastPathComponent)
            XCTAssertNotNil(bundle.cicadaResource(CicadaFonts.displayRegular, ext: "ttf", in: CicadaFonts.directory),
                            "the display face is unreachable in the \(url.lastPathComponent) layout")
        }
        let empty = root.appendingPathComponent("Empty.bundle")
        try FileManager.default.createDirectory(at: empty.appendingPathComponent("Resources"),
                                                withIntermediateDirectories: true)
        XCTAssertEqual(CicadaFonts.registerBundled(in: try XCTUnwrap(Bundle(url: empty))), [],
                       "a bundle without fonts reports none — titles fall back to SF, never to blank")
    }

    func testDisplayFontIsTheBundledFaceClampedToItsFloor() {
        XCTAssertEqual(CicadaTheme.displayFont(size: 28),
                       Font.custom(CicadaFonts.displayRegular, size: CicadaTheme.scaled(28)))
        XCTAssertEqual(CicadaTheme.displayFont(size: 28, italic: true),
                       Font.custom(CicadaFonts.displayItalic, size: CicadaTheme.scaled(28)))
        XCTAssertEqual(CicadaTheme.displayFont(size: 12), CicadaTheme.displayFont(size: CicadaTheme.displayMinimumSize))
        XCTAssertEqual(CicadaTheme.quoteFont, CicadaTheme.font(size: 13, design: .serif).italic())
    }

    private func write(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }
}

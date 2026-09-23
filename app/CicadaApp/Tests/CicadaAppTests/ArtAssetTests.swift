import AppKit
import CryptoKit
import XCTest
@testable import CicadaApp

/// G137 R-M6 / plan R-M20 — the painted Meadow art ships with its provenance,
/// the way the brand marks do (`LogoAssetTests`, Track L). A memory app whose
/// thesis is provenance does not ship a painting it cannot account for.
final class ArtAssetTests: XCTestCase {

    struct Manifest: Decodable { let assets: [Entry] }
    struct Entry: Decodable {
        let id: String
        let file: String
        let variant: String
        let role: String
        let pairsWith: String
        let generator: String
        let prompt: String
        let date: String
        let licence: String
        let processing: String
        let sha256: String
    }

    static let roles: Set<String> = ["cloud", "grass-corner", "grass-edge", "hero"]
    /// Longest side in pixels: 2× the largest point size each role is drawn at (R-M20).
    static let longestSideCap: [String: Int] = ["cloud": 800, "grass-corner": 640, "hero": 2400]
    static let byteBudget = 4 * 1024 * 1024

    private func manifest() throws -> Manifest {
        let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource("art.manifest", ext: "json", in: MeadowArt.directory),
                                "art.manifest.json is not bundled")
        return try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: url))
    }

    private func bundled() -> [URL] {
        let urls = ["png", "jpg"].flatMap { Bundle.cicadaResources.cicadaResources(ext: $0, in: MeadowArt.directory) }
        XCTAssertFalse(urls.isEmpty, "no bundled art — every assertion below would pass vacuously")
        return urls
    }

    private func url(_ file: String) throws -> URL {
        let ns = file as NSString
        return try XCTUnwrap(Bundle.cicadaResources.cicadaResource(ns.deletingPathExtension, ext: ns.pathExtension,
                                                                   in: MeadowArt.directory), "\(file) is not bundled")
    }

    private func rep(_ file: String) throws -> NSBitmapImageRep {
        try XCTUnwrap(NSBitmapImageRep(data: Data(contentsOf: url(file))), "\(file) did not decode")
    }

    func testTheManifestListsEveryBundledFileAndNothingElse() throws {
        XCTAssertEqual(Set(try manifest().assets.map(\.file)), Set(bundled().map(\.lastPathComponent)),
                       "a painting without a manifest entry has no provenance; an entry without a file is a lie")
    }

    func testEveryFileMatchesItsManifestHash() throws {
        for entry in try manifest().assets {
            let hex = SHA256.hash(data: try Data(contentsOf: url(entry.file))).map { String(format: "%02x", $0) }.joined()
            XCTAssertEqual(hex, entry.sha256, "\(entry.file) is not the bytes its manifest entry describes")
        }
    }

    func testEveryEntryCarriesItsProvenanceAndItsTwin() throws {
        let entries = try manifest().assets
        let byFile = Dictionary(uniqueKeysWithValues: entries.map { ($0.file, $0) })
        for e in entries {
            for (field, value) in [("generator", e.generator), ("prompt", e.prompt),
                                   ("licence", e.licence), ("processing", e.processing)] {
                XCTAssertFalse(value.trimmingCharacters(in: .whitespaces).isEmpty, "\(e.file) has no \(field)")
            }
            XCTAssertNotNil(e.date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression), "\(e.file) date")
            XCTAssertNotNil(e.sha256.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression), "\(e.file) sha256")
            XCTAssertTrue(Self.roles.contains(e.role), "\(e.file) role \(e.role)")
            XCTAssertEqual(e.id, (e.file as NSString).deletingPathExtension)
            XCTAssertEqual(e.variant, e.id.hasSuffix(MeadowArt.darkSuffix) ? "dark" : "light", e.file)
            let twin = try XCTUnwrap(byFile[e.pairsWith], "\(e.file) pairs with \(e.pairsWith), which is not listed")
            XCTAssertNotEqual(twin.variant, e.variant, "\(e.file) and its twin are the same variant")
            XCTAssertEqual(twin.pairsWith, e.file, "\(e.file) ↔ \(e.pairsWith) is not a pair")
        }
    }

    /// Every light painting has a `-dark` sibling of the same pixel size — a
    /// theme flip must never move the layout.
    func testEveryPaintingHasADarkSiblingOfTheSameSize() throws {
        for e in try manifest().assets where e.variant == "light" {
            XCTAssertEqual(e.pairsWith, "\(e.id)\(MeadowArt.darkSuffix).\((e.file as NSString).pathExtension)")
            let light = try rep(e.file), dark = try rep(e.pairsWith)
            XCTAssertEqual(light.pixelsWide, dark.pixelsWide, e.file)
            XCTAssertEqual(light.pixelsHigh, dark.pixelsHigh, e.file)
        }
    }

    func testEveryArtCaseResolvesItsOwnPaintingInBothThemes() {
        for art in MeadowArt.allCases {
            for mode in AppColorScheme.allCases {
                XCTAssertEqual(MeadowArt.url(for: art, mode: mode)?.deletingPathExtension().lastPathComponent,
                               MeadowArt.fileName(for: art, mode: mode),
                               "\(art.rawValue) does not resolve its own \(mode.rawValue) painting")
            }
        }
    }

    /// A generator that returns a painted rectangle would put a slab of sky
    /// over the page. `y == 0` is the TOP row of a decoded PNG (measured).
    func testSpritesAreCutOutNotPlates() throws {
        for e in try manifest().assets where e.role != "hero" {
            let r = try rep(e.file)
            let (w, h) = (r.pixelsWide, r.pixelsHigh)
            // A cloud is clear at all four corners; grass grows up from the
            // bottom, so only its top corners are sky.
            let corners = e.role == "cloud" ? [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)] : [(0, 0), (w - 1, 0)]
            for (x, y) in corners {
                XCTAssertLessThan(r.colorAt(x: x, y: y)?.alphaComponent ?? 1, 0.5,
                                  "\(e.file) is opaque at (\(x),\(y)) — it would paint a rectangle over the page")
            }
        }
    }

    func testArtStaysInsideItsPixelAndByteBudget() throws {
        var total = 0
        for e in try manifest().assets {
            let r = try rep(e.file)
            if e.role == "grass-edge" {
                XCTAssertLessThanOrEqual(r.pixelsHigh, 240, e.file)
                XCTAssertLessThanOrEqual(r.pixelsWide, 2400, e.file)
            } else {
                XCTAssertLessThanOrEqual(max(r.pixelsWide, r.pixelsHigh), Self.longestSideCap[e.role] ?? 0, e.file)
            }
            total += try Data(contentsOf: url(e.file)).count
        }
        XCTAssertLessThanOrEqual(total, Self.byteBudget, "the Meadow art is \(total) bytes")
    }

    /// The PR #70 class, for art: both layouts built from bytes.
    func testArtResolvesInBothBundleLayouts() throws {
        let png = try Data(contentsOf: url("cloud-1.png"))
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("art-layouts-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let flat = root.appendingPathComponent("Flat.bundle")
        try write(png, to: flat.appendingPathComponent("Resources/art/probe.png"))
        let nested = root.appendingPathComponent("Nested.bundle")
        try write(png, to: nested.appendingPathComponent("Contents/Resources/art/probe.png"))
        try write(Data("""
        <?xml version="1.0" encoding="UTF-8"?>
        <plist version="1.0"><dict>
        <key>CFBundleIdentifier</key><string>com.rorosaga.cicada.resources.test</string>
        <key>CFBundlePackageType</key><string>BNDL</string>
        </dict></plist>
        """.utf8), to: nested.appendingPathComponent("Contents/Info.plist"))
        for bundleURL in [flat, nested] {
            let bundle = try XCTUnwrap(Bundle(url: bundleURL), bundleURL.lastPathComponent)
            XCTAssertNotNil(bundle.cicadaResource("probe", ext: "png", in: MeadowArt.directory),
                            "art is unreachable in the \(bundleURL.lastPathComponent) layout")
        }
    }

    private func write(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }
}

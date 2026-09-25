import AppKit
import CryptoKit
import XCTest
@testable import CicadaApp

/// G137 R-M6 / round-4 T-Home (docs/design/ART_DIRECTION.md §6) — the painted Meadow ships with its provenance, the
/// way the brand marks do (`LogoAssetTests`, Track L). A memory app whose thesis is provenance does not ship a
/// painting it cannot account for. Round 4 replaced the light/`-dark` pairs with one composition in three lights, so
/// the pairing rules became set rules: every set ships day, afternoon and night at one size, and a cut-out layer's
/// three files share one alpha, so a crossfade mid-drift never changes a cloud's or a clump's shape (R-HO8).
final class ArtAssetTests: XCTestCase {

    struct Manifest: Decodable { let assets: [Entry] }
    struct Entry: Decodable {
        let id: String
        let file: String
        let role: String
        let set: String
        let scene: String
        let framing: String?
        let generator: String
        let prompt: String
        let reference: String?
        let date: String
        let licence: String
        let processing: String
        let masterSha256: String?
        let sha256: String
    }

    static let roles: Set<String> = ["hero", "pane", "cloud", "grass-corner", "grass-edge"]
    static let layerRoles: Set<String> = ["cloud", "grass-corner", "grass-edge"]
    /// Longest side in pixels (ART_DIRECTION §6): 2× the largest point size each role is drawn at. Ceilings, not exact
    /// sizes — the heroes and corners ship at the generator's ceiling, 2376 and 990 (R-HO8).
    static let longestSideCap: [String: Int] = ["hero": 2880, "pane": 1800, "cloud": 1200, "grass-corner": 1200]
    /// ART_DIRECTION §6's per-file caps catch one bad export; the total is the binding limit. Round 4 raised it from
    /// 4 MiB to 20 MiB: 36 files at the resolution the owner asked for (R-HO8).
    static let byteCap: [String: Int] = ["hero": 1_400_000, "pane": 800_000, "cloud": 400_000,
                                         "grass-corner": 900_000, "grass-edge": 500_000]
    static let byteBudget = 20 * 1024 * 1024

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

    /// The alpha byte of every pixel, whatever the decoded layout (a palette PNG decodes to RGBA too).
    private func alphaPlane(_ file: String) throws -> [UInt8] {
        let r = try rep(file)
        XCTAssertTrue(r.hasAlpha, file)
        XCTAssertEqual(r.bitsPerSample, 8, file)
        XCTAssertFalse(r.isPlanar, file)
        let bytesPerPixel = r.bitsPerPixel / 8
        let alpha = r.bitmapFormat.contains(.alphaFirst) ? 0 : bytesPerPixel - 1
        let data = try XCTUnwrap(r.bitmapData, file)
        var out: [UInt8] = []
        out.reserveCapacity(r.pixelsWide * r.pixelsHigh)
        for y in 0..<r.pixelsHigh {
            let row = data + y * r.bytesPerRow
            for x in 0..<r.pixelsWide { out.append(row[x * bytesPerPixel + alpha]) }
        }
        return out
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

    func testEveryEntryCarriesItsProvenanceAndItsPlaceInASet() throws {
        let scenes = Set(SceneTime.allCases.map(\.rawValue))
        for e in try manifest().assets {
            for (field, value) in [("generator", e.generator), ("prompt", e.prompt),
                                   ("licence", e.licence), ("processing", e.processing)] {
                XCTAssertFalse(value.trimmingCharacters(in: .whitespaces).isEmpty, "\(e.file) has no \(field)")
            }
            XCTAssertNotNil(e.date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression), "\(e.file) date")
            XCTAssertNotNil(e.sha256.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression), "\(e.file) sha256")
            XCTAssertTrue(Self.roles.contains(e.role), "\(e.file) role \(e.role)")
            XCTAssertTrue(scenes.contains(e.scene), "\(e.file) scene \(e.scene)")
            XCTAssertEqual(e.id, (e.file as NSString).deletingPathExtension)
            XCTAssertEqual(e.id, "\(e.set)-\(e.scene)", "\(e.file) is named <set>-<scene>")
            if e.role == "pane" {
                let framing = try XCTUnwrap(e.framing, "\(e.file) is a pane with no framing")
                XCTAssertNotNil(PaneFraming(rawValue: framing), "\(e.file) framing \(framing)")
                XCTAssertEqual(e.set, "pane-\(framing)")
            }
            for text in [e.prompt, e.processing, e.generator] {
                XCTAssertFalse(text.contains("/Users/") || text.contains("/private/"),
                               "\(e.file) names a path on the author's machine (the privacy rule)")
            }
        }
    }

    func testTheDarkSiblingRetired() {
        XCTAssertFalse(bundled().contains { $0.lastPathComponent.contains("-dark") },
                       "round 4 retired `-dark`: every painting ships as -day, -afternoon, -night (R-HO8)")
    }

    func testEverySetShipsInAllThreeScenesAtOneSize() throws {
        let bySet = Dictionary(grouping: try manifest().assets, by: \.set)
        XCTAssertFalse(bySet.isEmpty)
        for (set, entries) in bySet {
            XCTAssertEqual(Set(entries.map(\.scene)), Set(SceneTime.allCases.map(\.rawValue)),
                           "\(set) is not day · afternoon · night")
            XCTAssertEqual(Set(entries.map(\.role)).count, 1, "\(set) mixes roles")
            let sizes = Set(try entries.map { e -> String in
                let r = try rep(e.file)
                return "\(r.pixelsWide)x\(r.pixelsHigh)"
            })
            XCTAssertEqual(sizes.count, 1, "\(set) changes size between scenes \(sizes) — a crossfade would move it")
        }
    }

    func testALayerSetSharesOneAlphaAcrossItsScenes() throws {
        let layers = Dictionary(grouping: try manifest().assets.filter { Self.layerRoles.contains($0.role) }, by: \.set)
        XCTAssertFalse(layers.isEmpty, "no layer sets — this check would pass vacuously")
        for (set, entries) in layers {
            let planes = try entries.map { try alphaPlane($0.file) }
            for plane in planes.dropFirst() {
                XCTAssertTrue(plane == planes[0], "\(set)'s alpha differs between scenes — a crossfade would change its shape")
            }
        }
    }

    func testEveryArtCaseResolvesItsOwnPaintingInEveryScene() {
        for art in MeadowArt.allCases {
            for time in SceneTime.allCases {
                XCTAssertEqual(MeadowArt.url(for: art, time: time)?.deletingPathExtension().lastPathComponent,
                               MeadowArt.fileName(for: art, time: time),
                               "\(art.baseName) does not resolve its own \(time.rawValue) painting")
            }
        }
    }

    /// A generator that returns a painted rectangle would put a slab of sky over the page. `y == 0` is the TOP row of
    /// a decoded PNG (measured).
    func testSpritesAreCutOutNotPlates() throws {
        for e in try manifest().assets where Self.layerRoles.contains(e.role) {
            let r = try rep(e.file)
            let (w, h) = (r.pixelsWide, r.pixelsHigh)
            // A cloud is clear at all four corners; grass grows up from the bottom, so only its top corners are sky.
            let corners = e.role == "cloud" ? [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)] : [(0, 0), (w - 1, 0)]
            for (x, y) in corners {
                XCTAssertLessThan(r.colorAt(x: x, y: y)?.alphaComponent ?? 1, 0.5,
                                  "\(e.file) is opaque at (\(x),\(y)) — it would paint a rectangle over the page")
            }
        }
    }

    /// Task 5 review round 1 (G137): Pillow's `resize` on a palette image silently swaps any filter for NEAREST, so a
    /// manifest could say Lanczos over nearest-neighbour bytes the hash test cannot see; a real Lanczos pass leaves far
    /// more than 256 colours. Round 4 (R-HO8): an entry that records an INDEXED PNG (the grass edge, "indexed PNG with
    /// tRNS") is exempt by its own words. Neither "quantized" nor "palette" exempts: the posterised layers keep
    /// thousands of colours, the cloud entries say "not quantized", and the night clouds are RGBA "graded toward the
    /// night palette".
    func testAFileRecordedAsLanczosResizedWasNotNearestNeighbour() throws {
        let resized = try manifest().assets.filter {
            $0.file.hasSuffix(".png") && $0.processing.localizedCaseInsensitiveContains("lanczos")
                && !$0.processing.localizedCaseInsensitiveContains("indexed png")
        }
        XCTAssertFalse(resized.isEmpty, "no PNG records a Lanczos resize — this check would pass vacuously")
        for e in resized {
            let r = try rep(e.file)
            let bytesPerPixel = r.bitsPerPixel / 8
            XCTAssertEqual(r.bitsPerSample, 8, "\(e.file) is not 8 bits per sample")
            XCTAssertFalse(r.isPlanar, "\(e.file) is planar")
            let data = try XCTUnwrap(r.bitmapData, "\(e.file) has no bitmap data")
            var colours = Set<UInt32>()
            for y in 0..<r.pixelsHigh {
                let row = data + y * r.bytesPerRow
                for x in 0..<r.pixelsWide {
                    var v: UInt32 = 0
                    for b in 0..<min(bytesPerPixel, 4) { v = v << 8 | UInt32(row[x * bytesPerPixel + b]) }
                    colours.insert(v)
                }
            }
            XCTAssertGreaterThan(colours.count, 256,
                                 "\(e.file) has \(colours.count) colours; its manifest says Lanczos, the bytes say nearest")
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
            let bytes = try Data(contentsOf: url(e.file)).count
            XCTAssertLessThanOrEqual(bytes, Self.byteCap[e.role] ?? 0, "\(e.file) is \(bytes) bytes")
            total += bytes
        }
        XCTAssertLessThanOrEqual(total, Self.byteBudget, "the Meadow art is \(total) bytes")
    }

    /// The PR #70 class, for art: both layouts built from bytes.
    func testArtResolvesInBothBundleLayouts() throws {
        let png = try Data(contentsOf: url("cloud-1-day.png"))
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

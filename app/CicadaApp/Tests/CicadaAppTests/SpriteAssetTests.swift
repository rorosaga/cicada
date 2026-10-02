import AppKit
import CryptoKit
import XCTest
@testable import CicadaApp

final class SpriteAssetTests: XCTestCase {
    struct Manifest: Decodable { let note: String; let assets: [[String: String]] }
    private func manifest() throws -> Manifest {
        try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: SpriteTestAssets.url("sprites.manifest", ext: "json")))
    }

    func testManifestListsEveryBundledFileAndAllScenerySheets() throws {
        let manifest = try manifest()
        let urls = ["png", "json"].flatMap { Bundle.cicadaResources.cicadaResources(ext: $0, in: "sprites") }
            .filter { $0.lastPathComponent != "sprites.manifest.json" }
        let names = try manifest.assets.flatMap { [try XCTUnwrap($0["png"]), try XCTUnwrap($0["json"])] }
        XCTAssertEqual(Set(names), Set(urls.map(\.lastPathComponent)))
        XCTAssertEqual(names.count, SpriteTestAssets.sheetNames.count * 2)
        XCTAssertEqual(Set(try manifest.assets.map { try XCTUnwrap($0["id"]) }), Set(SpriteTestAssets.sheetNames))
    }

    func testEveryRawFileMatchesItsSha256() throws {
        for entry in try manifest().assets {
            for ext in ["png", "json"] {
                let file = try XCTUnwrap(entry[ext])
                let bytes = try Data(contentsOf: SpriteTestAssets.url((file as NSString).deletingPathExtension, ext: ext))
                let hash = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
                XCTAssertEqual(hash, entry[ext + "Sha256"], file)
            }
        }
    }

    func testEveryEntryHasProvenanceAndNoMachinePaths() throws {
        let required = ["id", "png", "json", "role", "generator", "script", "source", "authoring", "date", "licence", "processing", "pngSha256", "jsonSha256"]
        let roles: Set<String> = ["worm", "worm-small", "room", "weather", "skyfx", "clock", "fly", "spines"]
        for entry in try manifest().assets {
            for field in required { XCTAssertFalse(try XCTUnwrap(entry[field], field).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) }
            XCTAssertTrue(roles.contains(try XCTUnwrap(entry["role"])))
            XCTAssertNotNil(try XCTUnwrap(entry["date"]).range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression))
            for key in ["pngSha256", "jsonSha256"] { XCTAssertNotNil(try XCTUnwrap(entry[key]).range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression)) }
            for value in entry.values { XCTAssertFalse(value.contains("/Users/") || value.contains("/private/")) }
            let id = try XCTUnwrap(entry["id"])
            XCTAssertEqual(entry["png"], id + ".png"); XCTAssertEqual(entry["json"], id + ".json")
        }
        XCTAssertFalse(try manifest().note.isEmpty)
    }

    func testPaletteKeysRolesBinaryAlphaAndReservedHues() throws {
        let palette = try SpriteTestAssets.palette()
        XCTAssertLessThanOrEqual(palette.colors.count, 87)
        XCTAssertEqual(Set(palette.colors.map(\.key)).count, palette.colors.count)
        XCTAssertEqual(Set(palette.colors.map(\.hex)).count, palette.colors.count)
        let legal = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,-/:;<=>?@[]^{}~")
        let reserved: Set<UInt32> = [0x22C55E, 0xEF4444, 0xF59E0B, 0x3B82F6, 0x4A9EFF, 0x8B5CF6, 0x3BD97A, 0x6B7280, 0x999999]
        for color in palette.colors {
            XCTAssertEqual(color.key.count, 1)
            XCTAssertTrue(color.key.allSatisfy { legal.contains($0) })
            XCTAssertNotNil(color.hex.range(of: #"^#[0-9A-Fa-f]{6}$"#, options: .regularExpression))
            XCTAssertTrue(color.role.contains("."))
            XCTAssertFalse(reserved.contains(try XCTUnwrap(UInt32(color.hex.dropFirst(), radix: 16))))
        }
        let allowed = Set(palette.roles.keys)
        for name in SpriteTestAssets.sheetNames {
            let sheet = try SpriteTestAssets.sheet(name)
            for pixel in SpriteTestAssets.Plane(sheet.image).pixels {
                XCTAssertTrue(pixel.alpha == 0 || pixel.alpha == 255, name)
                if pixel.alpha > 0 { XCTAssertTrue(allowed.contains(pixel.rgb), "\(name): \(pixel.rgb)") }
            }
            let text = try String(contentsOf: SpriteTestAssets.url(name, ext: "json"))
            XCTAssertFalse(text.contains("/Users/") || text.contains("/private/"))
        }
    }

    func testByteBudgetAndSheetSideCaps() throws {
        var bytes = try Data(contentsOf: SpriteTestAssets.url("sprites.manifest", ext: "json")).count
        for name in SpriteTestAssets.sheetNames {
            let sheet = try SpriteTestAssets.sheet(name)
            XCTAssertLessThanOrEqual(max(sheet.image.width, sheet.image.height), 2048, name)
            for ext in ["png", "json"] { bytes += try Data(contentsOf: SpriteTestAssets.url(name, ext: ext)).count }
        }
        XCTAssertLessThanOrEqual(bytes, 6 * 1024 * 1024)
    }

    func testSpritesResolveInBothBundleLayoutsFromBytes() throws {
        let probe = try SpriteSheetTests.fixture()
        let data = try Data(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "probe", withExtension: "png", subdirectory: "sprites")))
        XCTAssertEqual(probe.image.width, 4)
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("sprite-layouts-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let flat = root.appendingPathComponent("Flat.bundle"), nested = root.appendingPathComponent("Nested.bundle")
        func write(_ data: Data, _ url: URL) throws {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url)
        }
        try write(data, flat.appendingPathComponent("Resources/sprites/probe.png"))
        try write(data, nested.appendingPathComponent("Contents/Resources/sprites/probe.png"))
        try write(Data("""
        <?xml version="1.0" encoding="UTF-8"?>
        <plist version="1.0"><dict><key>CFBundleIdentifier</key><string>com.cicada.sprites.test</string>
        <key>CFBundlePackageType</key><string>BNDL</string></dict></plist>
        """.utf8), nested.appendingPathComponent("Contents/Info.plist"))
        for path in [flat, nested] {
            let bundle = try XCTUnwrap(Bundle(url: path))
            XCTAssertNotNil(bundle.cicadaResource("probe", ext: "png", in: "sprites"))
            XCTAssertEqual(bundle.cicadaResources(ext: "png", in: "sprites").count, 1)
        }
    }
}

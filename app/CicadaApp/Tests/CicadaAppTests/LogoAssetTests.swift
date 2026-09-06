import XCTest
import AppKit
@testable import CicadaApp

/// T3/T4 (R-L7) — the bundled brand marks are square, big enough, and
/// transparent in the corners unless they are a declared opaque plate; every
/// monochrome mark ships the `-dark` sibling that keeps it from disappearing on
/// `CicadaTheme.surfaceElevated` (`#23252E` in dark mode).
///
/// This is the test that would have caught `x.png` (white on opaque black) and
/// `codex.png` (black on opaque white) shipping as opaque squares inside a
/// rounded card, and the 128 px favicon rasters of 2026-08-31 breaking the
/// 256 px floor batch 1 had held. It only *actually* catches the first of those
/// since the corner check replaced `rep.hasAlpha`, which was true of a fully
/// opaque channel and so proved nothing at all.
final class LogoAssetTests: XCTestCase {

    /// The 2026-08-31 favicon-service rasters (`cf2c449`). 128 px is the size
    /// the source served; upscaling would be fake resolution, so they are
    /// exempted by name and replaced only when a vendor SVG is sourced for
    /// them. `telegram` was on this list until Track L refetched it from
    /// Commons at 256 px — so if that fetch is the one R10 rejects, put
    /// `"telegram"` back and say so in task 2's "left out" note. `codex` was
    /// never on it: batch 1 shipped at 256.
    static let legacy128: Set<String> = [
        "instagram", "linkedin", "pinterest", "reddit", "tiktok", "youtube", "x", "x-dark",
    ]

    /// Marks that are a single flat colour and therefore invisible in one of
    /// the two themes without a sibling (R4). `codex` and `x` are the two
    /// recuts and are certain; `chatgpt` is here because its Commons SVG is
    /// monochrome — if R10's eyeball pass rejects that SVG and no `chatgpt`
    /// mark ships, drop it from this set in the same commit that drops the
    /// asset, and say so in task 2's "left out" note.
    ///
    /// `ollama` is on the list because R4's own condition — "iff its rasterized
    /// mark is achromatic" — was answered by measurement, not by opinion:
    /// `tools/monoflip.swift` reads every pixel and exits 3 on any hue, and it
    /// accepted the rasterized llama. Membership here is therefore always
    /// decided by the tool; nothing is added to this set by eye.
    static let needsDarkVariant: Set<String> = ["chatgpt", "codex", "ollama", "x"]

    private func logoURLs() throws -> [URL] {
        let urls = Bundle.cicadaResources.cicadaResources(ext: "png", in: "logos")
        XCTAssertFalse(urls.isEmpty, "no bundled logos found — this test would pass vacuously")
        return urls
    }

    private func names() throws -> Set<String> {
        Set(try logoURLs().map { $0.deletingPathExtension().lastPathComponent })
    }

    /// Rasters that are opaque to the corner and are shipped that way on
    /// purpose: they are the vendor's own app icon, a coloured plate whose
    /// background IS the mark, so there is nothing to cut out. Every surface
    /// that draws them clips (`PlatformTile`, `ConnectView.AgentTile`), which
    /// is what keeps them from showing square corners inside a rounded card.
    /// Adding an id here is a decision to clip it, not a way past the test.
    ///
    /// Measured, not assumed: both sample a minimum alpha of 1.00 across the
    /// whole raster, corners at 0.996. `hermes` is deliberately NOT here — it
    /// is a full-bleed plate too, but it feathers its outermost pixel to 0.02
    /// (0.91 one pixel in), so it passes on its own and adding it would claim
    /// an exemption it does not use. That 0.02 is also why the threshold below
    /// is 0.5 and not an exact zero.
    static let opaquePlate: Set<String> = ["claude-code", "claude-desktop"]

    func testEveryMarkIsSquareBigEnoughAndKeepsItsCornersTransparent() throws {
        for url in try logoURLs() {
            let name = url.deletingPathExtension().lastPathComponent
            guard let rep = NSBitmapImageRep(data: try Data(contentsOf: url)) else {
                XCTFail("\(name).png did not decode")
                continue  // keep checking the rest rather than returning out of the loop
            }
            XCTAssertEqual(rep.pixelsWide, rep.pixelsHigh, "\(name).png is not square")
            let floor = Self.legacy128.contains(name) ? 128 : 256
            XCTAssertGreaterThanOrEqual(rep.pixelsWide, floor, "\(name).png is \(rep.pixelsWide) px")

            // NOT `rep.hasAlpha`. That reports the channel EXISTS, which is
            // true of a fully opaque one: `claude-code.png` and
            // `claude-desktop.png` are 100% opaque and passed it, which is how
            // a full-bleed square shipped into a rounded tile unnoticed. The
            // behaviour the message names — "renders as a hard square" — is a
            // property of the CORNER PIXELS, so test those.
            guard !Self.opaquePlate.contains(name) else { continue }
            let w = rep.pixelsWide, h = rep.pixelsHigh
            for (x, y) in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)] {
                let alpha = rep.colorAt(x: x, y: y)?.alphaComponent ?? 1
                XCTAssertLessThan(alpha, 0.5,
                                  "\(name).png is opaque at (\(x),\(y)) — it renders as a hard "
                                  + "square. Recut it with alpha, or add it to `opaquePlate` and "
                                  + "make sure every surface that draws it clips.")
            }
        }
    }

    /// T2 (R-L7) — every bundled PNG is claimed by some map. Catches an
    /// orphaned asset (dead bytes in every shipped app) and a renamed id that
    /// left its file behind. The reverse direction of T1
    /// (`OriginIconographyTests.testEveryDeclaredLogoExistsInTheBundle`),
    /// which nothing tested before Track L.
    func testEveryBundledMarkIsClaimedBySomeMap() throws {
        // Reserved for G119 (Arc/Firefox/Brave as *channels*): the marks are
        // fetched and licence-recorded now, while the channel ids that will
        // claim them do not exist yet (R1 — a deliberate, reviewed state).
        let reservedForG119: Set<String> = ["firefox", "brave"]
        // The contributors list's own map (task 6): the marks a provider badge
        // can wear. Task 4 inlined these four names while `ContributorIdentity`
        // did not exist yet; now that it does, T2 reads the real map, so
        // dropping a provider mark there fails here instead of leaving the
        // file behind as dead bytes.
        let providerMarks: [String] = ContributorIdentity.allProviderMarks
        // `ConnectView.AgentTile` ids: the setup catalog's own map, which is a
        // tile list rather than an origin list and so is not reachable from
        // any of the three switches below.
        let agentTileMarks: [String] = [
            "claude-code", "cursor", "openclaw", "codex", "claude-desktop", "hermes", "gemini-cli",
        ]
        // Assembled step by step, not as one `+` chain: the chain was a single
        // expression the type-checker gave up on ("unable to type-check this
        // expression in reasonable time").
        var claimed = Set<String>(providerMarks)
        claimed.formUnion(agentTileMarks)
        claimed.formUnion(OriginIconography.allKnownOrigins.compactMap(OriginIconography.logoName(for:)))
        claimed.formUnion(AddSourceTile.allCases.compactMap(\.logoName))
        claimed.formUnion(ChannelMarks.allChannelIds.compactMap(ConnectedChannelRow.logoName(for:)))
        for name in try names() {
            let base = name.hasSuffix("-dark") ? String(name.dropLast(5)) : name
            XCTAssertTrue(claimed.contains(base) || reservedForG119.contains(base),
                          "\(name).png is bundled but nothing maps to it")
        }
    }

    /// The regression this file could not see: `swift test` runs against the
    /// FLAT bundle SwiftPM emits, and every assertion above passed over a
    /// shipped app where not one mark resolved.
    ///
    /// `bundle.sh` re-nests the resource bundle for `codesign` (`Resources` →
    /// `Contents/Resources`), which consumes the `Resources` path component
    /// the old `subdirectory: "Resources/logos"` spelled out. Both layouts are
    /// built here from bytes rather than asserted against whichever one this
    /// process happens to run in — a test that only checks the live bundle is
    /// exactly the test that missed this.
    func testAMarkResolvesInBothBundleLayouts() throws {
        let png = try Data(contentsOf: XCTUnwrap(try logoURLs().first))
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("logo-layouts-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        // Flat: what `swift build` / `swift test` load.
        let flat = root.appendingPathComponent("Flat.bundle")
        try write(png, to: flat.appendingPathComponent("Resources/logos/probe.png"))

        // Nested: what every `.app` `bundle.sh` assembles actually ships.
        let nested = root.appendingPathComponent("Nested.bundle")
        try write(png, to: nested.appendingPathComponent("Contents/Resources/logos/probe.png"))
        try write(Data("""
        <?xml version="1.0" encoding="UTF-8"?>
        <plist version="1.0"><dict>
        <key>CFBundleIdentifier</key><string>com.rorosaga.cicada.resources.test</string>
        <key>CFBundlePackageType</key><string>BNDL</string>
        </dict></plist>
        """.utf8), to: nested.appendingPathComponent("Contents/Info.plist"))

        for url in [flat, nested] {
            let bundle = try XCTUnwrap(Bundle(url: url), "\(url.lastPathComponent) is not a bundle")
            XCTAssertNotNil(bundle.cicadaResource("probe", ext: "png", in: "logos"),
                            "a bundled mark is unreachable in the \(url.lastPathComponent) layout "
                            + "— every provider badge in that build draws a blank square")
            XCTAssertEqual(bundle.cicadaResources(ext: "png", in: "logos").count, 1,
                           "\(url.lastPathComponent): the plural lookup disagrees with the single one")
        }
    }

    /// Foundation answers an EMPTY resource name with the directory's FIRST
    /// file, and `logoName ?? ""` call sites would then draw an unrelated
    /// brand. The guard moved into `Bundle.cicadaResource` with this fix, so
    /// it is pinned where it now lives.
    func testAnEmptyNameNeverResolvesToSomeOtherBrand() {
        XCTAssertNil(Bundle.cicadaResources.cicadaResource("", ext: "png", in: "logos"))
        XCTAssertFalse(LogoImage.exists(name: ""))
    }

    private func write(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try data.write(to: url)
    }

    func testEveryDarkSiblingHasABaseMark() throws {
        let all = try names()
        for name in all where name.hasSuffix("-dark") {
            XCTAssertTrue(all.contains(String(name.dropLast(5))), "\(name).png has no base mark")
        }
    }

    func testEveryMonochromeMarkShipsItsDarkSibling() throws {
        let all = try names()
        for name in Self.needsDarkVariant {
            XCTAssertTrue(all.contains(name), "\(name).png is missing")
            XCTAssertTrue(all.contains("\(name)-dark"), "\(name) is monochrome but ships no -dark sibling")
        }
    }
}

import XCTest
import AppKit
@testable import CicadaApp

/// T3/T4 (R-L7) — the bundled brand marks are square, big enough, and carry an
/// alpha channel; every monochrome mark ships the `-dark` sibling that keeps it
/// from disappearing on `CicadaTheme.surfaceElevated` (`#23252E` in dark mode).
///
/// This is the test that would have caught `x.png` (white on opaque black) and
/// `codex.png` (black on opaque white) shipping as opaque squares inside a
/// rounded card, and the 128 px favicon rasters of 2026-08-31 breaking the
/// 256 px floor batch 1 had held.
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
        let urls = Bundle.cicadaResources.urls(
            forResourcesWithExtension: "png", subdirectory: "Resources/logos"
        ) ?? []
        XCTAssertFalse(urls.isEmpty, "no bundled logos found — this test would pass vacuously")
        return urls
    }

    private func names() throws -> Set<String> {
        Set(try logoURLs().map { $0.deletingPathExtension().lastPathComponent })
    }

    func testEveryMarkIsSquareBigEnoughAndHasAlpha() throws {
        for url in try logoURLs() {
            let name = url.deletingPathExtension().lastPathComponent
            guard let rep = NSBitmapImageRep(data: try Data(contentsOf: url)) else {
                XCTFail("\(name).png did not decode")
                continue  // keep checking the rest rather than returning out of the loop
            }
            XCTAssertEqual(rep.pixelsWide, rep.pixelsHigh, "\(name).png is not square")
            let floor = Self.legacy128.contains(name) ? 128 : 256
            XCTAssertGreaterThanOrEqual(rep.pixelsWide, floor, "\(name).png is \(rep.pixelsWide) px")
            XCTAssertTrue(rep.hasAlpha, "\(name).png has no alpha — it will render as a hard square")
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
        // Task 6 introduces `ContributorIdentity.allProviderMarks`; until it
        // lands, the four names it will return are inlined here so T2 ships
        // whole with task 4 rather than half-covering the bundle. Replace
        // this literal with `+ ContributorIdentity.allProviderMarks` there.
        let providerMarks: [String] = ["claude", "chatgpt", "gemini", "ollama"]
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

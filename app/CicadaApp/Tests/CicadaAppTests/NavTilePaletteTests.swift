import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-11-24 (DESIGN_RULES §9, §3.9): the sidebar's icon tiles. The palette is nine hues in the theme, each with
/// a dark and a light value; this holds every number the rule states — the glyph's contrast, the tile's against its
/// ground, how far apart the hues sit for normal and colour-deficient eyes — and that nothing outside the theme spells one.
final class NavTilePaletteTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1.0 }
    override func tearDown() {
        CicadaTheme.mode = .dark
        CicadaTheme.uiScale = 1.0
        super.tearDown()
    }

    private let pages: [AppTab] = [.home, .graph, .clusters, .skills, .sleep, .sources, .projects, .agents, .traces]

    private func hex(_ tab: AppTab, _ mode: AppColorScheme) -> UInt32 {
        let pair = NavTilePalette.pair(for: tab)
        return mode == .dark ? pair.dark : pair.light
    }

    private func rgb(_ color: Color) -> [Int] {
        let c = NSColor(color).usingColorSpace(.sRGB)!
        return [c.redComponent, c.greenComponent, c.blueComponent].map { Int(($0 * 255).rounded()) }
    }

    private func bytes(_ hex: UInt32) -> [Int] { [Int((hex >> 16) & 0xFF), Int((hex >> 8) & 0xFF), Int(hex & 0xFF)] }

    func testEveryDestinationHasATokenAndTheInboxWearsHomes() {
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for tab in pages {
                XCTAssertEqual(rgb(CicadaTheme.navTile(tab)), bytes(hex(tab, mode)), "\(tab) \(mode.rawValue)")
            }
            XCTAssertEqual(rgb(CicadaTheme.navTile(.inbox)), rgb(CicadaTheme.navTile(.home)), "the Inbox draws no cell (ruling 48 (2))")
            XCTAssertEqual(rgb(CicadaTheme.tileHome), rgb(CicadaTheme.navTile(.home)))
            XCTAssertEqual(rgb(CicadaTheme.tileTraces), rgb(CicadaTheme.navTile(.traces)))
        }
        XCTAssertEqual(Set(pages.map { NavTilePalette.pair(for: $0) }).count, pages.count, "one hue per destination")
    }

    /// DR-3 — a glyph is held to 3:1. The lowest is Clusters in dark, 3.17:1.
    func testTheWhiteGlyphClearsThreeToOneOnEveryTile() {
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for tab in pages {
                let ratio = ThemeTokenTests.contrast(CicadaTheme.tileGlyph, CicadaTheme.navTile(tab))
                XCTAssertGreaterThanOrEqual(ratio, 3.0, "\(tab) \(mode.rawValue): \(ratio)")
            }
        }
    }

    /// Increase Contrast — the same hue 25 % deeper, and the glyph reads as text (4.5:1).
    func testIncreaseContrastDeepensEveryTileToTextContrast() {
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for tab in pages {
                let tile = CicadaTheme.navTile(tab, increasedContrast: true)
                let ratio = ThemeTokenTests.contrast(CicadaTheme.tileGlyph, tile)
                XCTAssertGreaterThanOrEqual(ratio, 4.5, "\(tab) \(mode.rawValue): \(ratio)")
                XCTAssertGreaterThan(ratio, ThemeTokenTests.contrast(CicadaTheme.tileGlyph, CicadaTheme.navTile(tab)))
            }
        }
        XCTAssertEqual(NavTilePalette.deepened(0xFFFFFF), 0xBFBFBF)
        XCTAssertEqual(NavTilePalette.deepened(0x000000), 0x000000)
    }

    /// The tile is a shape on the rail's own surface: at least 3:1 from it in both themes.
    func testEveryTileReadsAgainstTheRail() {
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for tab in pages {
                let ratio = ThemeTokenTests.contrast(CicadaTheme.navTile(tab), CicadaTheme.bgRail)
                XCTAssertGreaterThanOrEqual(ratio, 3.0, "\(tab) \(mode.rawValue): \(ratio)")
            }
        }
    }

    // MARK: - Hues told apart

    /// Machado, Oliveira and Fernandes 2009, severity 1.0, applied in linear sRGB.
    private static let deficiencies: [(String, [[Double]])] = [
        ("protanopia", [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]),
        ("deuteranopia", [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]),
        ("tritanopia", [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]),
    ]

    private static func linear(_ byte: Int) -> Double {
        let v = Double(byte) / 255
        return v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4)
    }

    private static func lab(_ l: [Double]) -> [Double] {
        let x = 0.4124 * l[0] + 0.3576 * l[1] + 0.1805 * l[2]
        let y = 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2]
        let z = 0.0193 * l[0] + 0.1192 * l[1] + 0.9505 * l[2]
        func f(_ t: Double) -> Double { t > 0.008856 ? cbrt(t) : 7.787 * t + 16.0 / 116 }
        let (fx, fy, fz) = (f(x / 0.95047), f(y), f(z / 1.08883))
        return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
    }

    private func deltaE(_ a: UInt32, _ b: UInt32, matrix: [[Double]]?) -> Double {
        func seen(_ h: UInt32) -> [Double] {
            let l = bytes(h).map(Self.linear)
            guard let m = matrix else { return Self.lab(l) }
            return Self.lab((0..<3).map { i in (0..<3).reduce(0.0) { $0 + m[i][$1] * l[$1] } })
        }
        let (p, q) = (seen(a), seen(b))
        return (0..<3).reduce(0.0) { $0 + pow(p[$1] - q[$1], 2) }.squareRoot()
    }

    /// Ten hues cannot all be told apart by hue alone, so this is the floor, not a promise of perfection: CIE76 ΔE 16
    /// for normal vision, 9 for each simulated deficiency. The label, never the colour, carries the meaning.
    func testTheNineHuesAreToldApartForEveryEye() {
        for mode in AppColorScheme.allCases {
            for (i, a) in pages.enumerated() {
                for b in pages[(i + 1)...] {
                    let normal = deltaE(hex(a, mode), hex(b, mode), matrix: nil)
                    XCTAssertGreaterThanOrEqual(normal, 16, "\(a)/\(b) \(mode.rawValue)")
                    for (name, matrix) in Self.deficiencies {
                        let d = deltaE(hex(a, mode), hex(b, mode), matrix: matrix)
                        XCTAssertGreaterThanOrEqual(d, 9, "\(a)/\(b) \(mode.rawValue) under \(name)")
                    }
                }
            }
        }
    }

    // MARK: - Separate from the accent and the data hues; spelled only in the theme

    /// DR-5 / DR-8 — a tile hue is neither a data hue nor a semantic one; none sits on the entity or semantic colours.
    func testNoTileIsAnotherTokensValue() {
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            let others: [Color] = [CicadaTheme.success, CicadaTheme.warning, CicadaTheme.danger, CicadaTheme.info,
                                   CicadaTheme.progressFill, CicadaTheme.meadow, CicadaTheme.mediaPink, CicadaTheme.hubGold]
                + EntityType.allCases.map { CicadaTheme.entityColor(for: $0) }
            for tab in pages {
                XCTAssertFalse(others.contains { rgb($0) == rgb(CicadaTheme.navTile(tab)) }, "\(tab) \(mode.rawValue)")
            }
        }
    }

    func testTheTileIsSpelledOnlyThroughTheTheme() throws {
        let text = try String(contentsOf: try source("Views/Shell/NavRail.swift"), encoding: .utf8)
        XCTAssertTrue(text.contains("CicadaTheme.navTile(tab, increasedContrast: contrast == .increased)"))
        XCTAssertTrue(text.contains("CicadaTheme.tileGlyph"))
        XCTAssertTrue(text.contains(".ringed(.resting, in: shape)"), "depth is a ring (DR-9)")
        XCTAssertFalse(text.contains("Color(hex:"), "a tile colour is a theme token")
        XCTAssertFalse(text.contains("LinearGradient"), "a flat fill, no gradient")
        XCTAssertFalse(text.contains(".shadow("), "DR-10")
        // The palette's own file owns the nine values.
        let palette = try String(contentsOf: try source("Theme/NavTilePalette.swift"), encoding: .utf8)
        XCTAssertEqual(palette.components(separatedBy: "Pair(dark: 0x").count - 1, 9, "nine tokens")
    }

    func testTheTileAndItsGlyphScaleWithTheTextSize() {
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            XCTAssertEqual(CicadaTheme.scaled(ShellMetrics.navTile), 24 * scale, accuracy: 0.06, "tile at \(scale)")
            XCTAssertEqual(CicadaTheme.iconPoints(.navTile), 13 * scale, accuracy: 0.06, "glyph at \(scale)")
            XCTAssertEqual(CicadaTheme.radiusTile, 6, "radii stay put under zoom (DR-12)")
            XCTAssertLessThanOrEqual(CicadaTheme.scaled(ShellMetrics.navTile), CicadaTheme.scaled(ShellMetrics.railCell),
                                     "the tile fits the rail's 36 pt cell, so the badge hangs off its corner as before")
            XCTAssertLessThan(CicadaTheme.scaled(ShellMetrics.navTile), CicadaTheme.scaled(ShellMetrics.sidebarRow))
        }
    }

    private func source(_ path: String) throws -> URL {
        let files = try ThemeTokenTests.swiftSources()
        return try XCTUnwrap(files.first { $0.path.hasSuffix(path) }, "\(path) is missing")
    }
}

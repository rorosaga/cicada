import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Track Z Z10 — the optional sky band (spec decision 16, Z-B16). It shows only
/// a sky the window agrees with, it is a tint and never a block, text over it
/// stays legible, and whether it ships is one constant decided by looking at
/// the composites this file writes on request. `@MainActor` for `ImageRenderer`.
@MainActor
final class SkyBandTests: XCTestCase {

    func test_theBandShowsOnlyASkyTheWindowAgreesWith() {
        XCTAssertEqual(SkyBand.phase(for: .night), .night)
        XCTAssertEqual(SkyBand.phase(for: .dawn), .dusk)
        XCTAssertEqual(SkyBand.phase(for: .clear), .day)
        XCTAssertEqual(SkyBand.phase(for: .fair), .day)
        for grey in [WindowWeather.overcast, .storm, .curtains] {
            XCTAssertNil(SkyBand.phase(for: grey), "\(grey): no grey band — the window and the sentence say it")
        }
    }

    func test_oneSwitch_andIncreaseContrastHidesIt() {
        XCTAssertFalse(SkyBand.isDrawn(ships: false, contrast: .standard))
        XCTAssertFalse(SkyBand.isDrawn(ships: true, contrast: .increased), "§11")
        XCTAssertTrue(SkyBand.isDrawn(ships: true, contrast: .standard))
    }

    /// Z-B16 — the wash is clear before the room card starts, so it never sits
    /// behind a number. The card is below `spacingXL` (24) of padding, the
    /// title's line (at least its 28 pt size) and a `spacingLG` (16) gap, all
    /// at uiScale 1 — and the band scales with them.
    func test_theBandEndsAboveTheRoomCard() {
        XCTAssertLessThanOrEqual(SkyBand.height, 24 + PageTitle.size + 16)
    }

    /// The build's two gates, both modes, every sky the band can show.
    func test_aTintNotABlock_andTheTitleStaysLegible() {
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for phase in CicadaTheme.SkyPhase.allCases {
                let band = ThemeTokenTests.blend(SkyBand.top(phase), over: CicadaTheme.background,
                                                 alpha: CicadaTheme.skyBandOpacity)
                let tint = ThemeTokenTests.contrast(band, CicadaTheme.background)
                let title = ThemeTokenTests.contrast(CicadaTheme.textPrimary, band)
                XCTAssertLessThanOrEqual(tint, SkyBand.maxTintRatio, "\(phase) in \(mode): \(tint)")
                XCTAssertGreaterThanOrEqual(title, SkyBand.minTitleContrast, "\(phase) in \(mode): \(title)")
            }
        }
    }

    /// Opt-in art check (the `WindowSpritesTests` convention):
    /// `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests` writes the
    /// page's top 320 pt — band, title, a card — for every sky the band shows,
    /// in both themes, plus a no-band control per theme, for a person to look
    /// at, and prints each sky's measured tint and title ratios for the record.
    func test_writeCompositesWhenAsked() throws {
        guard ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1" else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-composites")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            for phase in CicadaTheme.SkyPhase.allCases {
                let band = ThemeTokenTests.blend(SkyBand.top(phase), over: CicadaTheme.background,
                                                 alpha: CicadaTheme.skyBandOpacity)
                let tint = ThemeTokenTests.contrast(band, CicadaTheme.background)
                let title = ThemeTokenTests.contrast(CicadaTheme.textPrimary, band)
                print("sky band ratio: \(mode.rawValue) \(phase) tint \(String(format: "%.2f", tint)):1 "
                      + "title \(String(format: "%.1f", title)):1")
            }
            let weathers: [WindowWeather?] = [nil]
                + WindowWeather.all.filter { SkyBand.phase(for: $0) != nil }.map(Optional.some)
            for weather in weathers {
                let page = ZStack(alignment: .top) {
                    CicadaTheme.background
                    if let weather { SleepSkyBand(weather: weather) }
                    VStack(alignment: .leading, spacing: 16) {
                        PageTitle(Copy.sleepPageTitle)
                        RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius).fill(CicadaTheme.surface)
                            .frame(height: 180)
                    }
                    .padding(24)
                }
                .frame(width: 760, height: 320)
                let renderer = ImageRenderer(content: page)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.nsImage)
                let rep = NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation))
                try XCTUnwrap(rep?.representation(using: .png, properties: [:]))
                    .write(to: dir.appendingPathComponent("sky-band-\(weather?.rawValue ?? "none")-\(mode.rawValue).png"))
            }
        }
        print("sky band composites: \(dir.path)")
    }
}

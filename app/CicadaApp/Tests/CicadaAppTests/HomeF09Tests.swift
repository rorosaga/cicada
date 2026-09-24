import SwiftUI
import XCTest
@testable import CicadaApp

/// F-09 (round-4 decision 8; R-HO6, R-HO11–R-HO15) — Home's numbers, words and first-time inset as pure rules and
/// source checks, the `HomeLayoutTests` pattern.
@MainActor
final class HomeF09Tests: XCTestCase {
    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testTheBandIsF09sLivingBand() {
        XCTAssertEqual(HomeBandLayout.bandHeight, 208, "F-09 (R-HO6)")
    }

    func testTheTipShowsOnlyAfterStartAndNeverAfterItIsHidden() throws {
        XCTAssertFalse(AppearanceTipPolicy.visible(armed: false, dismissed: false))
        XCTAssertTrue(AppearanceTipPolicy.visible(armed: true, dismissed: false))
        XCTAssertFalse(AppearanceTipPolicy.visible(armed: true, dismissed: true), "once hidden it lives only in Settings")
        XCTAssertEqual(AppearanceTipPolicy.dismissedKey, "cicada.home.appearanceTipDismissed")
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.tip.\(UUID().uuidString)"))
        AppearanceTipPolicy.arm(defaults)
        XCTAssertTrue(defaults.bool(forKey: AppearanceTipPolicy.armedKey))
    }

    func testTheWelcomesStartArmsTheTipAndTheDemoDoesNot() throws {
        XCTAssertTrue(try source("Support/LiveSetupEffects.swift").contains("AppearanceTipPolicy.arm()"))
        XCTAssertFalse(OnboardingFlow.demoSteps.contains {
            if case .recordGettingStarted = $0 { return true }
            return false
        }, "the demo plan records no Getting started, so it never arms the tip")
    }

    func testTheTipSitsBesideTheColumnOnlyWhenItFits() {
        XCTAssertEqual(AppearanceTipLayout.placement(pageWidth: 1384, scale: 1), .side, "1440 × 900 with the rail")
        XCTAssertEqual(AppearanceTipLayout.placement(pageWidth: 1144, scale: 1), .inline, "1200 × 800")
        XCTAssertEqual(AppearanceTipLayout.placement(pageWidth: 1384, scale: 1.4), .inline)
        XCTAssertEqual(AppearanceTipLayout.placement(pageWidth: 0, scale: 0), .inline, "a zero width never traps")
    }

    func testTheTipsPickersFitItsCard() throws {
        let saved = CicadaTheme.uiScale
        defer { CicadaTheme.uiScale = saved }
        for scale in [1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let room = CicadaTheme.scaled(AppearanceTipLayout.width - 2 * AppearanceTipLayout.padding)
            let pickers: [AnyView] = [
                AnyView(PillPicker(title: Copy.scene, selection: .constant(HeroScenePreference.automatic),
                                   options: HeroScenePreference.allCases.map { PillOption(value: $0, label: $0.label) },
                                   compact: true)),
                AnyView(PillPicker(title: Copy.appearance, selection: .constant(AppearancePreference.system),
                                   options: AppearancePreference.allCases.map { PillOption(value: $0, label: $0.label) },
                                   compact: true)),
            ]
            for picker in pickers {
                let width = try XCTUnwrap(ImageRenderer(content: picker.fixedSize()).nsImage).size.width
                XCTAssertLessThanOrEqual(width, room + 0.5, "at \(scale)× the pills need \(width) of \(room) pt")
            }
        }
    }

    func testTodayAndNeedsYouSayF09sWords() {
        let us = Locale(identifier: "en_US")
        XCTAssertEqual(Copy.homeOriginCount("Chrome", 2_104, locale: us), "Chrome 2,104")
        XCTAssertEqual(Copy.homeNeedsYouCount(3, locale: us), "Needs you · 3")
        XCTAssertEqual(Copy.homeNeedsYouCount(0, locale: us), "Needs you")
        XCTAssertEqual(Copy.homeTodayAccessibility(2_540, origins: [("Chrome", 2_104), ("Calendar", 312)], locale: us),
                       "2,540 captured today, mostly Chrome 2,104, Calendar 312")
        for text in Copy.sceneLabels {
            XCTAssertLessThanOrEqual(text.count, 60, text)
        }
        for text in Copy.sceneLabels + Copy.sceneSentences {
            XCTAssertFalse(text.lowercased().contains("claim"), text)
            XCTAssertFalse(text.contains("$"), text)
            XCTAssertFalse(text.lowercased().contains("token"), text)
        }
    }

    func testTodayIsOneRowToSourcesAndNeedsYouIsTheInboxsIconRows() throws {
        let sections = try source("Views/Home/HomeSections.swift")
        XCTAssertTrue(sections.contains("selectedTab = .sources"), "R-HO11 — Today opens Sources")
        XCTAssertFalse(sections.contains("routeToSourceDetail"), "R-HO11 — one row, one link")
        XCTAssertTrue(sections.contains("InboxRowSlots(entity: false, source: false)"), "R-HO12 — glyph · question · age")
        XCTAssertTrue(sections.contains("showsOpenButton: false"))
        XCTAssertTrue(sections.contains("linkTitle: Copy.homeOpenInbox"))
        XCTAssertTrue(sections.contains("LastReadSection("), "R-HO13 — Last read stays")
    }
}

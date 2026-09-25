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

    /// Runs the plans through the spy rather than grepping a source file: the r4-home final review found the arm
    /// folded into the shared `recordGettingStarted` effect, which Home's card also calls, and a string check passed.
    func testTheWelcomesStartArmsTheTipAndTheDemoDoesNot() async {
        for plan in [OnboardingFlow.finishSteps(recorded: []), OnboardingFlow.laterSteps(name: "Ada", ownerSaved: false),
                     OnboardingFlow.laterSteps(name: "Ada", ownerSaved: true)] {
            let fx = FakeSetupEffects()
            await SetupRunner().run(plan, effects: fx)
            XCTAssertEqual(fx.calls.filter { $0 == "armTip" }.count, 1, "\(plan)")
        }
        let demo = FakeSetupEffects()
        await SetupRunner().run(SetupRunner.demoPlan, effects: demo)
        XCTAssertFalse(demo.calls.contains("armTip"), "the demo never arms the tip")
        XCTAssertTrue(demo.calls.contains("createDemoBank"))
    }

    /// Home's *Also found* row calls the effect directly; it records the row and never arms the tip.
    func testTheCardsDirectRecordNeverArmsTheTip() throws {
        let live = try source("Support/LiveSetupEffects.swift")
        let body = try XCTUnwrap(live.range(of: "func recordGettingStarted").map { live[$0.lowerBound...] })
        let record = body.prefix(while: { $0 != "}" })
        XCTAssertFalse(record.contains("AppearanceTipPolicy"), "arming lives in armAppearanceTip, called by SetupRunner")
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

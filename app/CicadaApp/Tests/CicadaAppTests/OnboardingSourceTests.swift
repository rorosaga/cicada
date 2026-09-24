import XCTest
@testable import CicadaApp

/// Rules a rendered view cannot show, held as source checks (the `HomeF09Tests` pattern).
final class OnboardingSourceTests: XCTestCase {
    func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// R-OB5 — "an untouched engine choice keeps the configured engine": F-05 writes nothing itself; only
    /// `EngineChooser`'s click does (R-AG12's one write rule).
    func testWhoReadsWritesNothingOfItsOwn() throws {
        let text = try source("Views/Onboarding/WhoReadsPage.swift")
        XCTAssertTrue(text.contains("EngineChooser()"))
        for write in [".apply(", ".set(mode:", "saveEngine", "PUT"] { XCTAssertFalse(text.contains(write), write) }
    }

    /// R-OB14 — F-06 turns nothing on for the person: no switch is set on appear.
    func testKeepRunningSetsNothingOnAppear() throws {
        let text = try source("Views/Onboarding/KeepRunningPage.swift")
        XCTAssertFalse(text.contains("setEnabled(true)"))
        XCTAssertTrue(text.contains("BackgroundServiceButton"), "the same control as Settings → General")
        XCTAssertTrue(try source("Views/Settings/SettingsGeneralView.swift").contains("BackgroundServiceButton"))
    }

    /// R-OB12 — onboarding bundles; Settings → Agents never does (R-H11).
    func testOnlyOnboardingBundlesRecall() throws {
        XCTAssertTrue(try source("Views/Onboarding/AgentsPage.swift").contains("bundleAutoRecall: true"))
        XCTAssertFalse(try source("Views/Connect/ConnectView.swift").contains("bundleAutoRecall"))
    }
}

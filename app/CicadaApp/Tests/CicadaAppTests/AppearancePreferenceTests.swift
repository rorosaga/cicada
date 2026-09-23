import XCTest
@testable import CicadaApp

/// G139 / R-O4 — Appearance gains System without moving what paints: the
/// preference is stored under the key the sun/moon toggle has always
/// written, and `AppColorScheme` stays the resolved two-value mode.
final class AppearancePreferenceTests: XCTestCase {
    func testStoredValuesDecodeAsBeforeAndDefaultStaysDark() {
        XCTAssertEqual(AppearancePreference.stored(nil), .dark)
        XCTAssertEqual(AppearancePreference.stored("bogus"), .dark)
        XCTAssertEqual(AppearancePreference.stored("light"), .light)
        XCTAssertEqual(AppearancePreference.stored("dark"), .dark)
        XCTAssertEqual(AppearancePreference.stored("system"), .system)
        XCTAssertEqual(AppearancePreference.allCases.map(\.rawValue), ["system", "light", "dark"])
        XCTAssertEqual(AppColorScheme.allCases.map(\.rawValue), ["light", "dark"], "the resolved mode never grows")
    }

    func testResolution() {
        XCTAssertEqual(AppearancePreference.system.resolved(systemIsDark: true), .dark)
        XCTAssertEqual(AppearancePreference.system.resolved(systemIsDark: false), .light)
        XCTAssertEqual(AppearancePreference.light.resolved(systemIsDark: true), .light)
        XCTAssertEqual(AppearancePreference.dark.resolved(systemIsDark: false), .dark)
    }

    func testThemeStoreResolvesAStoredSystemPreference() {
        let suite = "appearance-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("system", forKey: ThemeStore.defaultsKey)
        XCTAssertEqual(ThemeStore(defaults: defaults, systemIsDark: false).mode, .light)
        XCTAssertEqual(ThemeStore(defaults: defaults, systemIsDark: true).mode, .dark)
        defaults.set("light", forKey: ThemeStore.defaultsKey)
        XCTAssertEqual(ThemeStore(defaults: defaults, systemIsDark: true).mode, .light)
    }

    func testTheSystemReadIsTheGlobalInterfaceStyle() {
        let suite = "appearance-style-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("Dark", forKey: "AppleInterfaceStyle")
        XCTAssertTrue(AppearancePreference.systemIsDark(defaults))
        defaults.removeObject(forKey: "AppleInterfaceStyle")
        defaults.set("Light", forKey: "AppleInterfaceStyle")
        XCTAssertFalse(AppearancePreference.systemIsDark(defaults))
    }
}

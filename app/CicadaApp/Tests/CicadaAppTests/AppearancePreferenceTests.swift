import SwiftUI
import XCTest
@testable import CicadaApp

/// G139 / R-O4 — Appearance gains System without moving what paints: the
/// preference is stored under the key the sun/moon toggle has always
/// written, and `AppColorScheme` stays the resolved two-value mode.
final class AppearancePreferenceTests: XCTestCase {
    /// Owner 2026-10-26: "the default is system" — absent or unknown follows the Mac; an explicit choice the retired
    /// sidebar toggle or Settings wrote is kept on upgrade.
    func testStoredValuesDecodeAsBeforeAndTheDefaultIsSystem() {
        XCTAssertEqual(AppearancePreference.defaultChoice, .system)
        XCTAssertEqual(AppearancePreference.stored(nil), .system)
        XCTAssertEqual(AppearancePreference.stored("bogus"), .system)
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

    /// G139 final review — a flip re-resolves `mode` from the stored
    /// preference wherever it is heard (the app-scope observer, or a window's
    /// `onAppear` after being closed through one), and never touches an
    /// explicit Light/Dark choice. "Light" is written explicitly because a
    /// suite also reads the real global domain.
    func testRefreshFollowsTheSystemOnlyForASystemPreference() {
        let suite = "appearance-refresh-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("system", forKey: ThemeStore.defaultsKey)
        defaults.set("Light", forKey: "AppleInterfaceStyle")
        let store = ThemeStore(defaults: defaults)
        XCTAssertEqual(store.mode, .light)
        defaults.set("Dark", forKey: "AppleInterfaceStyle")
        store.refreshSystemAppearance()
        XCTAssertTrue(store.systemIsDark)
        XCTAssertEqual(store.mode, .dark)
        defaults.set("light", forKey: ThemeStore.defaultsKey)
        store.refreshSystemAppearance()
        XCTAssertEqual(store.mode, .light, "an explicit choice outranks the system")
    }

    /// A fresh install (no stored value) follows the Mac; an upgrade with the toggle's "dark" stays dark.
    func testAFreshInstallFollowsTheMacAndAnUpgradeKeepsItsChoice() {
        let suite = "appearance-default-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        XCTAssertEqual(ThemeStore(defaults: defaults, systemIsDark: false).mode, .light)
        XCTAssertEqual(ThemeStore(defaults: defaults, systemIsDark: true).mode, .dark)
        defaults.set("dark", forKey: ThemeStore.defaultsKey)
        XCTAssertEqual(ThemeStore(defaults: defaults, systemIsDark: false).mode, .dark)
    }

    /// Every `@AppStorage` of the key defaults to the one default — a view that still said "dark" would show Dark
    /// as chosen on a fresh install while the window followed the Mac.
    func testEveryReaderOfTheKeyDefaultsToSystem() throws {
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for line in text.components(separatedBy: .newlines)
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//")
                && (line.contains("@AppStorage(ThemeStore.defaultsKey)") || line.contains("@AppStorage(\"cicada.colorScheme\")")) {
                XCTAssertTrue(line.contains("AppearancePreference.defaultChoice.rawValue"),
                              "\(file.lastPathComponent): \(line.trimmingCharacters(in: .whitespaces))")
            }
        }
    }

    /// The side panel carries no appearance control any more; Settings → General's picker is the one door (with the
    /// palette's Switch to light/dark actions).
    func testTheSidePanelHasNoAppearanceToggle() throws {
        let rail = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "NavRail.swift" })
        let text = try String(contentsOf: rail, encoding: .utf8)
        XCTAssertFalse(text.contains("ThemeStore.defaultsKey"))
        XCTAssertFalse(text.contains("switchToLight"))
        let general = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "SettingsGeneralView.swift" })
        XCTAssertTrue(try String(contentsOf: general, encoding: .utf8).contains("AppearancePicker(selection: appearance)"))
    }

    func testThePickerOrderAndItsArrowKeys() {
        XCTAssertEqual(AppearancePreference.pickerOrder, [.light, .dark, .system])
        XCTAssertEqual(AppearancePreference.stepped(.light, by: 1), .dark)
        XCTAssertEqual(AppearancePreference.stepped(.system, by: 1), .system, "stops at the end")
        XCTAssertEqual(AppearancePreference.stepped(.light, by: -1), .light, "stops at the start")
        XCTAssertEqual(AppearancePreference.stepped(.system, by: -1), .dark)
        for choice in AppearancePreference.allCases { XCTAssertFalse(choice.help.isEmpty) }
    }

    /// DR-60: a key press switches in one frame; a pointer's choice eases; Reduce Motion never animates.
    func testASwitchAnimatesOnlyFromThePointer() {
        XCTAssertNil(AppearanceMotion.animation(eventType: .keyDown, reduceMotion: false))
        XCTAssertNil(AppearanceMotion.animation(eventType: .leftMouseUp, reduceMotion: true))
        XCTAssertNotNil(AppearanceMotion.animation(eventType: .leftMouseUp, reduceMotion: false))
    }

    /// The miniatures paint each appearance's own palette, whatever the window shows.
    @MainActor
    func testTheMiniaturesPaintBothPalettes() {
        XCTAssertNotEqual(AppearancePalette.light.base, AppearancePalette.dark.base)
        XCTAssertNotEqual(AppearancePalette.light.text, AppearancePalette.dark.text)
        for choice in AppearancePreference.allCases {
            let host = NSHostingView(rootView: AppearanceMiniature(choice: choice))
            host.frame = CGRect(x: 0, y: 0, width: AppearanceMiniature.width, height: AppearanceMiniature.height)
            host.layoutSubtreeIfNeeded()
            XCTAssertEqual(host.fittingSize.width, AppearanceMiniature.width, accuracy: 1, choice.rawValue)
        }
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

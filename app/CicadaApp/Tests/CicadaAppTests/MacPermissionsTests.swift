import XCTest
@testable import CicadaApp

/// Onboarding's Permissions step and Settings → Privacy & data's card (owner 2026-11-03, G92): one row per macOS
/// permission, its state by preflight only, one button that does the right thing for its kind. Everything here runs on
/// fakes: no test opens System Settings, reads a real permission or raises a prompt.
@MainActor
final class MacPermissionsTests: XCTestCase {
    // MARK: Which rows show

    func testEveryPermissionShowsExceptChromeWithoutChromeAndTracesWhileTracesAreOff() {
        XCTAssertEqual(MacPermissionRows.visible(tracesOn: false, chromeInstalled: true),
                       [.fullDiskAccess, .contacts, .calendars, .reminders, .chrome, .notes, .notifications],
                       "traces are off by default: their two permissions stay out of the list (ruling 38)")
        XCTAssertFalse(MacPermissionRows.visible(tracesOn: false, chromeInstalled: false).contains(.chrome))
        XCTAssertEqual(MacPermissionRows.visible(tracesOn: true, chromeInstalled: true),
                       MacPermission.allCases.filter { $0 != .localNetwork })
        XCTAssertFalse(MacPermissionRows.visible(tracesOn: true, chromeInstalled: true).contains(.localNetwork),
                       "Local Network is asked only at the person's first share or add-device click (G132, owner D4)")
    }

    // MARK: What each row's one button does

    func testEachKindGetsItsOwnButton() {
        XCTAssertEqual(MacPermissionRows.action(.fullDiskAccess, state: .notYet), .drag(.fullDiskAccess))
        XCTAssertEqual(MacPermissionRows.action(.accessibility, state: .notYet), .drag(.accessibility))
        XCTAssertEqual(MacPermissionRows.action(.screenRecording, state: .notYet), .drag(.screenRecording))
        for permission in [MacPermission.contacts, .calendars, .reminders, .notifications, .chrome, .notes,
                           .localNetwork] {
            XCTAssertEqual(MacPermissionRows.action(permission, state: .notYet), .ask, "\(permission): macOS's prompt")
            XCTAssertEqual(MacPermissionRows.action(permission, state: .denied), .openSettings,
                           "\(permission): refused once, macOS never asks again — the exact list instead")
        }
        for permission in MacPermission.allCases {
            XCTAssertEqual(MacPermissionRows.action(permission, state: .granted), .none, "\(permission): a green dot only")
        }
    }

    func testDragListsAreTheThreeWithNoPromptAndTheirListsAreTheHelpersOwn() {
        XCTAssertEqual(MacPermission.allCases.filter { if case .drag = $0.way { true } else { false } },
                       [.fullDiskAccess, .accessibility, .screenRecording])
        for kind in TracePermission.allCases {
            let permission = MacPermission.allCases.first { $0.way == .drag(kind) }
            XCTAssertEqual(permission?.settingsURL(), PermissionDragHelperModel.settingsURL(for: kind))
        }
    }

    func testEveryRowOpensItsExactListInSystemSettings() {
        let expected: [MacPermission: String] = [
            .fullDiskAccess: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
            .contacts: "x-apple.systempreferences:com.apple.preference.security?Privacy_Contacts",
            .calendars: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars",
            .reminders: "x-apple.systempreferences:com.apple.preference.security?Privacy_Reminders",
            .chrome: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
            .notes: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
            .notifications: "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=com.example.app",
            .accessibility: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            .screenRecording: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
            .localNetwork: "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork",
        ]
        for permission in MacPermission.allCases {
            XCTAssertEqual(permission.settingsURL(bundleId: "com.example.app").absoluteString, expected[permission])
        }
    }

    // MARK: Automation, by preflight

    func testAutomationAnswersMapAndANotRunningAppKeepsTheLastAnswer() throws {
        XCTAssertEqual(MacPermissionRows.automationState(0), .granted)
        XCTAssertEqual(MacPermissionRows.automationState(-1743), .denied)
        XCTAssertEqual(MacPermissionRows.automationState(-1744), .notYet)
        XCTAssertNil(MacPermissionRows.automationState(-600), "not running: the preflight cannot say")

        let defaults = try XCTUnwrap(UserDefaults(suiteName: "MacPermissionsTests.automation"))
        defaults.removePersistentDomain(forName: "MacPermissionsTests.automation")
        let memory = AutomationMemory(defaults: defaults)
        XCTAssertNil(memory.last(MacPermission.notesBundleId))
        memory.note(MacPermission.notesBundleId, .granted)
        XCTAssertEqual(memory.last(MacPermission.notesBundleId), .granted)
        memory.note(MacPermission.notesBundleId, .denied)
        XCTAssertEqual(memory.last(MacPermission.notesBundleId), .denied)
        XCTAssertEqual(AutomationMemory.key("com.apple.Notes"), "cicada.permission.automation.com.apple.Notes")
    }

    // MARK: The live list, on fakes

    func testTheListNeverAsksOnItsOwnAndAsksOnlyTheRowClicked() async {
        let probe = FakeProbe([.contacts: .notYet, .calendars: .notYet, .fullDiskAccess: .notYet])
        let asker = FakeAsker(probe: probe, grants: .contacts)
        let model = PermissionListModel(probe: probe, asker: asker)
        var landed: [MacPermission] = []
        model.onGranted = { landed.append($0) }

        await model.refresh([.contacts, .calendars, .fullDiskAccess])
        await model.refresh([.contacts, .calendars, .fullDiskAccess])
        XCTAssertEqual(asker.asked, [], "looking is never asking")
        XCTAssertEqual(model.states[.contacts], .notYet)

        await model.ask(.contacts)
        XCTAssertEqual(asker.asked, [.contacts], "one prompt, for the row clicked")
        XCTAssertEqual(model.states[.contacts], .granted)
        XCTAssertEqual(landed, [.contacts], "the grant the person asked for lands once")

        // Something allowed in System Settings that this showing never asked for turns green without a sound.
        probe.states[.calendars] = .granted
        await model.refresh([.contacts, .calendars, .fullDiskAccess])
        XCTAssertEqual(model.states[.calendars], .granted)
        XCTAssertEqual(landed, [.contacts])

        // A drag row: the click notes the ask; the grant lands on a later look (the poll, or back from Settings).
        model.noteAsked(.fullDiskAccess)
        probe.states[.fullDiskAccess] = .granted
        await model.refresh([.fullDiskAccess])
        XCTAssertEqual(landed, [.contacts, .fullDiskAccess])
        await model.refresh([.fullDiskAccess])
        XCTAssertEqual(landed, [.contacts, .fullDiskAccess], "never twice")
    }

    func testNewlyGrantedIsOnlyWhatWasAskedAndTurnedGreen() {
        XCTAssertEqual(MacPermissionRows.newlyGranted(before: [.contacts: .notYet], after: [.contacts: .granted],
                                                      asked: [.contacts]), [.contacts])
        XCTAssertEqual(MacPermissionRows.newlyGranted(before: [:], after: [.contacts: .granted], asked: [.contacts]),
                       [.contacts])
        XCTAssertEqual(MacPermissionRows.newlyGranted(before: [.contacts: .granted], after: [.contacts: .granted],
                                                      asked: [.contacts]), [])
        XCTAssertEqual(MacPermissionRows.newlyGranted(before: [.contacts: .notYet], after: [.contacts: .granted],
                                                      asked: []), [])
        XCTAssertEqual(MacPermissionRows.grantedCount([.contacts, .notes], states: [.contacts: .granted, .notes: .denied]), 1)
    }

    // MARK: Where a relaunch comes back

    func testTheStepsAndSettingsPlacesRoundTripAndComeBackToThemselves() {
        for place in [PermissionPlace.onboardingPermissions(rerun: false), .onboardingPermissions(rerun: true), .settings] {
            XCTAssertEqual(PermissionPlace(word: place.word), place)
        }
        XCTAssertTrue(PermissionPlace.onboardingPermissions(rerun: false).isOnboarding)
        XCTAssertTrue(PermissionPlace.onboardingPermissions(rerun: false).isPermissionsStep)
        XCTAssertFalse(PermissionPlace.onboardingPermissions(rerun: false).isRerun)
        XCTAssertTrue(PermissionPlace.onboardingPermissions(rerun: true).isRerun)
        XCTAssertNil(PermissionPlace.onboardingPermissions(rerun: true).browser)
        XCTAssertFalse(PermissionPlace.settings.isOnboarding, "the app shell takes a Settings marker, never onboarding")
        XCTAssertFalse(PermissionPlace.onboarding(browser: "safari").isPermissionsStep)
        let marker = PermissionResume(kind: .fullDiskAccess, place: .onboardingPermissions(rerun: true),
                                      at: Date(timeIntervalSince1970: 1_800_000_000))
        XCTAssertEqual(PermissionResume.decode(marker.encoded), marker)
        XCTAssertEqual(PermissionResume.reopensOnboarding(marker, gateShows: false), .rerun)
    }

    // MARK: Words and rails, as source

    func testOneShortLinePerRowAndTheStepFitsOnboardingsWordBudget() {
        for permission in MacPermission.allCases {
            let line = Copy.MacPermissions.unlocks(permission)
            XCTAssertLessThanOrEqual(OnboardingWords.count([line]), 12, "\(permission): one short line")
            XCTAssertFalse(line.contains("!") || line.contains("\n"))
        }
        XCTAssertLessThanOrEqual(OnboardingWords.count([Copy.MacPermissions.title]), OnboardingWords.titleCap)
        XCTAssertLessThanOrEqual(OnboardingWords.count([Copy.MacPermissions.subline]), OnboardingWords.bodyCap)
    }

    /// The probe never raises a prompt: no requesting API appears in it, and Automation's preflight passes `false`.
    func testTheLiveProbeHasNoPromptingCall() throws {
        let text = try String(contentsOf: Self.source("Services/MacPermissionsLive.swift"), encoding: .utf8)
        let probe = try XCTUnwrap(text.components(separatedBy: "struct LiveMacPermissionAsker").first)
        for call in ["requestAccess", "requestFullAccess", "requestAuthorization", "ask: true", "CGRequestScreenCaptureAccess",
                     "AXIsProcessTrustedWithOptions", "openApplication"] {
            XCTAssertFalse(probe.contains(call), "the probe must never ask: \(call)")
        }
        XCTAssertTrue(probe.contains("automationStatus(bundleId, ask: false)"))
        let asker = try XCTUnwrap(text.components(separatedBy: "struct LiveMacPermissionAsker").last)
        XCTAssertTrue(asker.contains("if let launched = launch.launched { launched.terminate() }"),
                      "an app opened only for the Automation ask is quit again; one already running is left alone")
        let list = try String(contentsOf: Self.source("Views/Common/PermissionList.swift"), encoding: .utf8)
        XCTAssertTrue(list.contains("openAtOnce: true"), "a drag row opens the list with the helper over it, one click")
    }

    private static func source(_ relative: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/\(relative)")
    }
}

private final class FakeProbe: MacPermissionProbe, @unchecked Sendable {
    var states: [MacPermission: MacPermissionState]
    init(_ states: [MacPermission: MacPermissionState]) { self.states = states }
    func state(_ permission: MacPermission) async -> MacPermissionState { states[permission] ?? .notYet }
}

@MainActor
private final class FakeAsker: MacPermissionAsker {
    let probe: FakeProbe
    let grants: MacPermission
    var asked: [MacPermission] = []
    init(probe: FakeProbe, grants: MacPermission) { self.probe = probe; self.grants = grants }
    func ask(_ permission: MacPermission) async {
        asked.append(permission)
        if permission == grants { probe.states[permission] = .granted }
    }
}

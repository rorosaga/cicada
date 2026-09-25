import AppKit
import XCTest
@testable import CicadaApp

/// R-OB18 — the quiet login start. macOS marks a login-item launch on the 'oapp' event itself; the event is current
/// only during `applicationDidFinishLaunching`, so the delegate asks there, and everything after is a pure table.
@MainActor
final class LaunchKindTests: XCTestCase {
    /// The AE constants import as `UInt32` (`AEEventID` / `AEKeyword` / `OSType`), never `Int` — an `Int` parameter
    /// here does not compile (checked with `swiftc` against the macOS SDK, 2026-09-24).
    private func event(_ id: AEEventID = AEEventID(kAEOpenApplication), propData: OSType? = nil) -> NSAppleEventDescriptor {
        let event = NSAppleEventDescriptor(eventClass: AEEventClass(kCoreEventClass), eventID: id,
                                           targetDescriptor: nil, returnID: AEReturnID(kAutoGenerateReturnID),
                                           transactionID: AETransactionID(kAnyTransactionID))
        if let propData {
            event.setParam(NSAppleEventDescriptor(enumCode: propData), forKeyword: AEKeyword(keyAEPropData))
        }
        return event
    }

    func testALoginItemLaunchIsQuietAndEverythingElseIsNot() {
        XCTAssertEqual(LaunchKind.from(event: event(propData: OSType(keyAELaunchedAsLogInItem))), .loginItem)
        XCTAssertEqual(LaunchKind.from(event: event()), .interactive, "a double-click, Spotlight, `open`")
        XCTAssertEqual(LaunchKind.from(event: nil), .interactive, "unknown is never quiet")
        XCTAssertEqual(LaunchKind.from(event: event(AEEventID(kAEReopenApplication),
                                                    propData: OSType(keyAELaunchedAsLogInItem))),
                       .interactive, "only the launch event can carry the mark")
        XCTAssertEqual(LaunchKind.from(event: event(propData: OSType(keyAELaunchedAsServiceItem))), .interactive)
    }

    func testTheLaunchArgumentCanOnlyMakeALaunchQuieter() {
        XCTAssertEqual(LaunchKind.resolve(event: nil, arguments: ["/x/Cicada", "-CicadaLaunchKind", "loginItem"]),
                       .loginItem)
        XCTAssertEqual(LaunchKind.resolve(event: event(propData: OSType(keyAELaunchedAsLogInItem)),
                                          arguments: ["-CicadaLaunchKind", "interactive"]), .loginItem)
        XCTAssertEqual(LaunchKind.resolve(event: nil, arguments: ["-CicadaLaunchKind"]), .interactive)
    }

    func testOnlyAMarkedLaunchNobodyAskedAboutClosesItsFirstWindow() {
        XCTAssertEqual(QuietLaunch.firstWindow(kind: .loginItem, userAsked: false), .close)
        XCTAssertEqual(QuietLaunch.firstWindow(kind: .loginItem, userAsked: true), .show)
        XCTAssertEqual(QuietLaunch.firstWindow(kind: .interactive, userAsked: false), .show)
        XCTAssertEqual(QuietLaunch.firstWindow(kind: nil, userAsked: false), .show, "unknown is never quiet")
    }

    func testTheFirstWindowIsDecidedOnceAndALaterWindowAlwaysShows() {
        var closed = 0, activated = 0
        let state = LaunchState(activate: { activated += 1 }, closeMainWindows: { closed += 1 })
        state.record(.loginItem)
        XCTAssertEqual(activated, 0, "a login start steals no focus")
        XCTAssertEqual(closed, 0, "no window had appeared yet")
        XCTAssertEqual(state.firstWindowAction(), .close)
        XCTAssertEqual(state.firstWindowAction(), .show, "a Dock click's new window shows")
    }

    /// SwiftUI may put its window up before the delegate hears the launch event: that window is then closed by the
    /// record, unless the person already asked for it.
    func testAWindowThatBeatTheEventIsClosedByTheRecord() {
        var closed = 0
        let state = LaunchState(activate: {}, closeMainWindows: { closed += 1 })
        XCTAssertEqual(state.firstWindowAction(), .show, "the kind is not known yet")
        state.record(.loginItem)
        XCTAssertEqual(closed, 1)

        var closedAfterAsk = 0
        let asked = LaunchState(activate: {}, closeMainWindows: { closedAfterAsk += 1 })
        _ = asked.firstWindowAction()
        asked.userAskedForWindow()
        asked.record(.loginItem)
        XCTAssertEqual(closedAfterAsk, 0, "a window the person asked for is never closed")
    }

    func testAnInteractiveLaunchActivatesOnceAndARecordIsFinal() {
        var activated = 0
        let state = LaunchState(activate: { activated += 1 }, closeMainWindows: {})
        state.record(.interactive)
        state.record(.loginItem)
        XCTAssertEqual(activated, 1)
        XCTAssertEqual(state.kind, .interactive, "the launch event is heard once")
    }

    func testShowMainWindowOpensOneWhenNoneExists() {
        let router = AppRouter()
        var opened = 0
        router.adoptOpenMainWindow { opened += 1 }
        let state = LaunchState(activate: {}, closeMainWindows: {})
        router.showMainWindow(launch: state)
        XCTAssertEqual(opened, 1, "headless: no NSApp, so no window — SwiftUI's openWindow is asked")
        XCTAssertTrue(state.userAsked)
    }

    // MARK: Wiring, as source checks (an NSApplication cannot be stood up in the suite)

    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testTheDelegateHearsTheLaunchBeforeAnythingElse() throws {
        let text = try source("Support/DockOpenQueue.swift")
        let body = try XCTUnwrap(text.range(of: "func applicationDidFinishLaunching").map { text[$0.upperBound...] })
        let record = try XCTUnwrap(body.range(of: "LaunchState.shared.record(")).lowerBound
        let guardLine = try XCTUnwrap(body.range(of: "guard ReminderAvailability.current")).lowerBound
        XCTAssertLessThan(record, guardLine, "the reminder guard returns early under `swift test`; the launch kind must not")
    }

    func testTheAppNoLongerActivatesInInitAndEveryOpenPathCanOpenAWindow() throws {
        let app = try source("CicadaApp.swift")
        let initBody = try XCTUnwrap(app.range(of: "init() {").map { app[$0.upperBound...] })
        let initEnd = try XCTUnwrap(initBody.range(of: "static let mainWindowID")).lowerBound
        XCTAssertFalse(initBody[..<initEnd].contains("activate(ignoringOtherApps"), "R-OB18: activation is the launch's")
        XCTAssertGreaterThanOrEqual(app.components(separatedBy: "appRouter.showMainWindow()").count - 1, 3,
                                    "Open Cicada, a Dock open and a reminder tap")
        XCTAssertTrue(app.contains("LaunchState.shared.firstWindowAction()"))
        XCTAssertTrue(try source("Support/ShellCommands.swift").contains("router.adoptOpenMainWindow"))
    }
}

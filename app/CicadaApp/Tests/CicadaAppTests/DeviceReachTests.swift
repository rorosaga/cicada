import XCTest
@testable import CicadaApp

/// G212 (owner 2026-10-29): Settings → Devices' guided reach step and each device's kind and key state, from the
/// backend's words alone. Synthetic answers; nothing runs Tailscale, nothing touches a keychain.
final class DeviceReachTests: XCTestCase {
    private func reach(_ json: String) throws -> DeviceReach {
        try JSONDecoder().decode(DeviceReach.self, from: Data(json.utf8))
    }

    func testEveryStepHasOneLineAndOnlyTheCommandStepsShowACommand() throws {
        for step in ["install", "open", "sign-in", "turn-on", "serve", "unfunnel", "ready"] {
            let line = Copy.DevicesPage.Reach.step(step)
            XCTAssertFalse(line.isEmpty, step)
            XCTAssertNotEqual(line, Copy.DevicesPage.Reach.step("not-a-step"), "\(step) has its own words")
        }
        let serve = try reach(#"{"tailscale":"running","step":"serve","command":"tailscale serve --bg --https=8443 8000","url":null,"check":null}"#)
        XCTAssertEqual(serve.command, "tailscale serve --bg --https=8443 8000")
        XCTAssertFalse(DeviceReachText.on(serve))
        XCTAssertNil(DeviceReachText.checkLine(serve), "no check line before the address is served")
        let missing = try reach(#"{"tailscale":"missing","step":"install","command":null}"#)
        XCTAssertNil(missing.command)
        XCTAssertEqual(DeviceReachText.word(missing), Copy.Status.notConnected)
    }

    func testAServedAddressIsGreenOnlyWhileItsCheckPasses() throws {
        let ok = try reach(#"{"tailscale":"running","step":"ready","url":"https://mac.example.ts.net:8443","check":{"ok":true,"failed":null,"ms":41}}"#)
        XCTAssertTrue(DeviceReachText.on(ok))
        XCTAssertEqual(DeviceReachText.line(ok), Copy.DevicesPage.Reach.readyAt("https://mac.example.ts.net:8443"))
        XCTAssertEqual(DeviceReachText.checkLine(ok), Copy.DevicesPage.Reach.ready)
        for failed in ["dns", "overlay", "backend", "not-cicada", "other-cicada"] {
            let bad = try reach(#"{"tailscale":"running","step":"ready","url":"https://mac.example.ts.net:8443","check":{"ok":false,"failed":"\#(failed)","ms":3000}}"#)
            XCTAssertFalse(DeviceReachText.on(bad), failed)
            XCTAssertEqual(DeviceReachText.checkLine(bad), Copy.DevicesPage.Reach.failed(failed))
            XCTAssertNotEqual(Copy.DevicesPage.Reach.failed(failed), Copy.DevicesPage.Reach.failed("unknown"),
                              "\(failed) names its own step")
        }
    }

    /// Owner 2026-10-29, "Yes, one click": a click runs the serve step's shown command or a served address's off —
    /// never a funnel command, never on any other step.
    func testOnlyTheServeAndAServedAddressOfferAClick() throws {
        let serve = try reach(#"{"tailscale":"running","step":"serve","command":"tailscale serve --bg --https=8443 8000"}"#)
        XCTAssertEqual(DeviceReachText.action(serve), .serve)
        let ready = try reach(#"{"tailscale":"running","step":"ready","url":"https://mac.example.ts.net:8443","stopCommand":"tailscale serve --https=8443 off"}"#)
        XCTAssertEqual(ready.stopCommand, "tailscale serve --https=8443 off")
        XCTAssertEqual(DeviceReachText.action(ready), .stop)
        let unfunnel = try reach(#"{"tailscale":"running","step":"unfunnel","command":"tailscale funnel --https=443 off"}"#)
        XCTAssertNil(DeviceReachText.action(unfunnel), "a funnel command is only ever copied")
        let older = try reach(#"{"tailscale":"running","step":"ready","url":"https://mac.example.ts.net:8443"}"#)
        XCTAssertNil(DeviceReachText.action(older), "an older backend names no off, so none is offered")
        for step in ["install", "open", "sign-in", "turn-on"] {
            XCTAssertNil(DeviceReachText.action(try reach(#"{"step":"\#(step)"}"#)), step)
        }
        let answer = try JSONDecoder().decode(DeviceReachServe.self, from: Data(
            #"{"ok":false,"message":"Serve isn't on for your tailnet yet.","ran":"tailscale serve --bg --https=8443 8000","reach":{"step":"serve"}}"#.utf8))
        XCTAssertEqual(answer.message, "Serve isn't on for your tailnet yet.")
        XCTAssertEqual(answer.reach?.step, "serve")
        XCTAssertTrue(Copy.DevicesPage.Reach.willRun("tailscale serve --https=8443 off")
                        .contains("tailscale serve --https=8443 off"), "the dialog names the exact command")
    }

    func testAnOlderBackendsAnswerStillDecodes() throws {
        let sparse = try reach("{}")
        XCTAssertEqual(sparse.step, "install")
        let row = try JSONDecoder().decode(DeviceStatusRow.self, from: Data(#"{"id":"d1","name":"Example Phone","role":"device"}"#.utf8))
        XCTAssertNil(row.kind)
        XCTAssertNil(row.keyBound)
        XCTAssertFalse(DevicesSettingsView.detail(row, now: Date()).contains("key-bound"))
    }

    func testEachDeviceRowSaysWhatItMayDoAndWhetherItsTokenNeedsItsKey() throws {
        let now = Date()
        let phone = try JSONDecoder().decode(DeviceStatusRow.self, from: Data(
            #"{"id":"d1","name":"Example Phone","role":"device","kind":"capture","keyBound":true}"#.utf8))
        XCTAssertEqual(DevicesSettingsView.detail(phone, now: now), "Capture only · Key-bound")
        let laptop = DeviceStatusRow(deviceId: "d2", name: "laptop", kind: "full", keyBound: false)
        XCTAssertEqual(DevicesSettingsView.detail(laptop, now: now), "Full access · Not yet key-bound")
        var since = phone
        since.keyBoundAt = "2026-10-29T09:00:00+00:00"
        XCTAssertTrue(DevicesSettingsView.detail(since, now: now).hasPrefix("Capture only · Key-bound since "))
        let server = DeviceStatusRow(deviceId: nil, name: "Studio", role: "server", kind: "full", keyBound: false)
        XCTAssertEqual(DevicesSettingsView.detail(server, now: now), "", "the server row carries no kind")
    }

    /// Review 2026-10-29: the same phone paired again leaves its old row; that row is offered for revoking, only it.
    func testAnOlderRowOfTheSameNameIsOfferedOnlyAfterAPairing() {
        let rows = [DeviceStatusRow(deviceId: nil, name: "Example Phone", role: "server"),
                    DeviceStatusRow(deviceId: "old", name: "Example  phone"),
                    DeviceStatusRow(deviceId: "new", name: "Example Phone"),
                    DeviceStatusRow(deviceId: "other", name: "laptop")]
        XCTAssertEqual(DevicesSettingsView.olderTwins(rows, newDeviceId: "new").map(\.deviceId), ["old"])
        XCTAssertTrue(DevicesSettingsView.olderTwins(rows, newDeviceId: nil).isEmpty, "nothing without a pairing")
        XCTAssertTrue(DevicesSettingsView.olderTwins(rows, newDeviceId: "other").isEmpty)
    }
}

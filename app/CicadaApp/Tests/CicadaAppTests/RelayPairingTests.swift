import XCTest
@testable import CicadaApp

/// G132 phase 3b — Settings → Devices' relay: the address rule the backend enforces, the six digits as both screens
/// show them, when a pairing is over, the QR's payload (v2, sorted keys, the backend's own field names), and the words.
final class RelayPairingTests: XCTestCase {
    func testTheRelayAddressIsWssOrALoopbackWs() {
        XCTAssertEqual(RelayRules.address("wss://relay.example.net/"), "wss://relay.example.net")
        XCTAssertEqual(RelayRules.address(" ws://127.0.0.1:8443 "), "ws://127.0.0.1:8443")
        XCTAssertNil(RelayRules.address("ws://relay.example.net"))
        XCTAssertNil(RelayRules.address("https://relay.example.net"))
        XCTAssertNil(RelayRules.address("wss://name:pw@relay.example.net"))
        XCTAssertNil(RelayRules.address("wss://relay.example.net/?x=1"))
        XCTAssertNil(RelayRules.address(""))
    }

    func testTheSixDigitsAreSpacedAsBothScreensShowThem() {
        XCTAssertEqual(RelayRules.digits("123 456"), "123 456")
        XCTAssertEqual(RelayRules.digits("123456"), "123 456")
        XCTAssertNil(RelayRules.digits("12345"))
        XCTAssertNil(RelayRules.digits(nil))
    }

    func testAPairingIsOverOnlyInAnEndState() {
        for state in ["done", "void", "cancelled", "expired", "failed"] { XCTAssertTrue(RelayRules.finished(state)) }
        for state in ["waiting", "confirm", "connecting", nil] { XCTAssertFalse(RelayRules.finished(state)) }
    }

    func testTheQRPayloadIsTheBackendsV2WithSortedKeys() throws {
        let raw = #"{"v":2,"code":"ABCD-EFGH","relay":"wss://relay.example.net","slot":"s1","home":{"ed":"E","x":"X"}}"#
        let qr = try JSONDecoder().decode(RelayQR.self, from: Data(raw.utf8))
        XCTAssertEqual(qr.json, #"{"code":"ABCD-EFGH","home":{"ed":"E","x":"X"},"relay":"wss://relay.example.net","slot":"s1","v":2}"#)
        XCTAssertNil(qr.url)
    }

    func testTheSessionAndTheJoinDecodeWithDefaults() throws {
        let s = try JSONDecoder().decode(RelaySession.self, from: Data(#"{"id":"p1","state":"waiting"}"#.utf8))
        XCTAssertEqual(s.state, "waiting")
        XCTAssertNil(s.sas)
        XCTAssertFalse(s.typed)
        let j = try JSONDecoder().decode(RelayJoinState.self, from: Data(#"{"state":null}"#.utf8))
        XCTAssertNil(j.state)
    }

    func testTheWordsArePlainAndProviderNeutral() {
        let words = [Copy.Relay.detailOff, Copy.Relay.detailOn, Copy.Relay.voided, Copy.Relay.compare,
                     Copy.Relay.pairLead, Copy.Relay.joinDetail, Copy.Devices.revokeMessage]
        for line in words {
            for name in ["Tailscale", "Cloudflare", "Fly", "Hetzner", "relay.cicada"] {
                XCTAssertFalse(line.contains(name), line)
            }
            XCTAssertFalse(line.contains("›") || line.contains("»"), line)
        }
        XCTAssertTrue(Copy.Relay.voided.hasPrefix("Two devices answered this code"))
        XCTAssertTrue(Copy.Devices.revokeMessage.contains("cannot take back the copy it already holds"))
    }
}

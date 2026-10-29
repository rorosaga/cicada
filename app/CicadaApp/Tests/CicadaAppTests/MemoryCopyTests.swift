import XCTest
@testable import CicadaApp

/// G132 phase 1 — the Devices page's *One memory on your computers*: the wire it reads (`/sync/publish`,
/// `/sync/replica`) decodes as the backend sends it, the words stay provider-neutral and show no path, variable or seq.
final class MemoryCopyTests: XCTestCase {
    func testTheReplicaStateDecodesAsTheBackendSendsIt() throws {
        let json = """
        {"mode": "replica", "conflict": null, "home": "home.example.ts.net",
         "replica": {"status": "diverged", "text": "This copy no longer matches.", "seq": 12, "homeSeq": 14,
                     "behind": 2, "bankId": "b", "appliedAt": null, "lastContact": null, "lastApply": {}},
         "outbox": {"waiting": 2, "held": 1, "expired": 0, "dropped": 0, "rejected": 3, "oldestAt": 1.5, "captures": 4}}
        """
        let state = try JSONDecoder().decode(ReplicaState.self, from: Data(json.utf8))
        XCTAssertTrue(state.isReplica)
        XCTAssertTrue(state.needsCopyAgain)
        XCTAssertEqual(state.onItsWay, 7)
        XCTAssertEqual(state.replica?.behind, 2)
        let local = try JSONDecoder().decode(ReplicaState.self, from: Data(
            #"{"mode": "local", "conflict": null, "replica": null, "outbox": null}"#.utf8))
        XCTAssertFalse(local.isReplica)
        XCTAssertEqual(local.onItsWay, 0)
        let publish = try JSONDecoder().decode(PublishState.self, from: Data(
            #"{"publish": true, "source": "settings", "demo": false, "log": {"state": "publishing"}}"#.utf8))
        XCTAssertTrue(publish.publish)
    }

    func testTheBackendsOwnSentenceIsShown() {
        XCTAssertEqual(MemoryCopyModel.detail(#"{"detail": "That code was not accepted."}"#), "That code was not accepted.")
        XCTAssertNil(MemoryCopyModel.detail("not json"))
    }

    func testTheWordsNameNoProviderPathOrVariable() {
        let words = [Copy.MemoryCopy.shareTitle, Copy.MemoryCopy.shareDetail, Copy.MemoryCopy.copyTitle,
                     Copy.MemoryCopy.copyDetail, Copy.MemoryCopy.copyOff, Copy.MemoryCopy.restarting,
                     Copy.MemoryCopy.behind(3), Copy.MemoryCopy.onItsWay(1)]
        for text in words {
            for banned in ["Tailscale", "Claude", "ChatGPT", "CICADA_", "~/", "replica_of", "seq"] {
                XCTAssertFalse(text.contains(banned), "\(text) names \(banned)")
            }
        }
        XCTAssertEqual(Copy.MemoryCopy.onItsWay(1), "1 change made here is on its way.")
    }
}

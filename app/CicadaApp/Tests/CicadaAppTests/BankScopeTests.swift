import XCTest
@testable import CicadaApp

/// G183(d) — every mutating request names the bank its operation started in (`X-Cicada-Bank`); the server refuses
/// one whose bank is no longer active (`bank_mismatch`).
final class BankScopeTests: XCTestCase {
    func testOnlyWritesNameABankAndTheOriginWinsOverTheScreen() {
        XCTAssertEqual(BankScope.value(method: "POST", origin: "alpha-project", onScreen: "beta"), "alpha-project")
        XCTAssertEqual(BankScope.value(method: "put", origin: nil, onScreen: "beta"), "beta", "the send-time fallback")
        for method in ["PATCH", "DELETE"] { XCTAssertNotNil(BankScope.value(method: method, origin: "a", onScreen: nil)) }
        XCTAssertNil(BankScope.value(method: "GET", origin: "a", onScreen: "b"), "reads are never bound")
        XCTAssertNil(BankScope.value(method: "POST", origin: nil, onScreen: nil))
        XCTAssertNil(BankScope.value(method: "POST", origin: "", onScreen: nil))
        XCTAssertEqual(BankScope.value(method: "POST", origin: "my bank", onScreen: nil), "my%20bank", "percent-encoded")
    }

    func testABindingIsInheritedByTheWorkItRuns() async {
        let seen = await BankScope.bound(to: "alpha-project") { BankScope.origin }
        XCTAssertEqual(seen, "alpha-project")
        let nested = await BankScope.bound(to: "alpha-project") { await BankScope.bound(to: nil) { BankScope.origin } }
        XCTAssertEqual(nested, "alpha-project", "a nil binding keeps the enclosing one")
        XCTAssertNil(BankScope.origin)
    }

    func testTheMismatchIsKnownByItsCodeOnly() {
        XCTAssertTrue(BankScope.isMismatch(APIError.httpError(409, #"{"code":"bank_mismatch","detail":"x"}"#)))
        XCTAssertFalse(BankScope.isMismatch(APIError.httpError(409, #"{"code":"sleep_writing","detail":"x"}"#)))
        XCTAssertFalse(BankScope.isMismatch(APIError.httpError(409, #"{"detail":"bank_mismatch"}"#)))
        XCTAssertFalse(BankScope.isMismatch(APIError.httpError(400, #"{"code":"bank_mismatch"}"#)))
        XCTAssertFalse(BankScope.isMismatch(nil))
    }

    @MainActor
    func testAMismatchRollsBackAndSaysMemorySwitched() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        store.inbox.value = try JSONDecoder().decode([InboxItem].self, from: Data(
            #"[{"id":"inbox-001","kind":"decay","requiredInput":"choice","title":"Still tracking alpha-project?"}]"#.utf8))
        api.replies[.inbox] = .notModified
        api.writeError = APIError.httpError(409, #"{"code":"bank_mismatch","detail":"Memory switched before this was saved — nothing was written."}"#)
        let ok = await store.perform(InboxResolve(id: "inbox-001", action: "archive"))
        XCTAssertFalse(ok)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001"], "rolled back")
        XCTAssertEqual(store.toast, "Memory switched — try that again")
        XCTAssertEqual(DecayChangeFailure.message(api.writeError!), Copy.memorySwitched)
    }
}

import XCTest
@testable import CicadaApp

/// G183(d), review findings 1–2 — a bank switch is ONE serialized transition. The fake server here is bank-aware:
/// it moves its active bank BEFORE answering the activation (as `routers/banks.py` does, ahead of its migrations),
/// and logs every write with the bank it landed in (`bankWrites`), so a write sent into the wrong bank shows.
@MainActor
final class BankSwitchTests: XCTestCase {
    private static let twoItems = """
    [{"id":"inbox-001","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use now?",
      "question":"What does alpha-project use now?",
      "options":[{"key":"a","label":"Tool Example A"},{"key":"b","label":"Tool Example B"}]},
     {"id":"inbox-002","kind":"merge_suggestion","requiredInput":"merge","title":"Same as tool-example-a?"}]
    """
    private static let refusal = "Cicada is reading — stop it first, or wait for it to finish, then switch."

    /// Bank A on screen and on the server, with two inbox questions; every inbox reconcile answers 304.
    private func makeStore() async throws -> (Store, FakeSyncAPI) {
        let api = FakeSyncAPI()
        api.serverBank = "A"
        api.replies[.inbox] = .notModified
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: api)
        await store.hydrate(bank: "A")
        store.banks.value = api.roster(active: "A")
        store.inbox.value = try JSONDecoder().decode([InboxItem].self, from: Data(Self.twoItems.utf8))
        store.graceWait = { _ in try? await Task.sleep(for: .seconds(3600)) }
        return (store, api)
    }

    @discardableResult
    private func hold(_ store: Store, _ id: String) -> Bool {
        store.hold(InboxResolve(id: id, action: "resolve", optionKey: "b"),
                   label: "Answered", shortLabel: "Answered", question: "q", kind: .conflict, channel: nil)
    }

    private func eventually(_ condition: @autoclosure () -> Bool,
                            file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<200_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never happened", file: file, line: line)
    }

    // MARK: Finding 1 — no write lands in the wrong bank

    /// The answer held before the switch goes to the bank it was made in, before the POST; once the server has moved
    /// (the activation parked after it), a new answer and an expiring window send nothing anywhere.
    func testAnswersDuringTheWaitNeverReachTheNewBank() async throws {
        let (store, api) = try await makeStore()
        hold(store, "inbox-001")
        let token = store.heldResolve!.token
        api.gateActivate = true
        let switching = Task { await store.activateBank("B") }
        await api.waitForParkedActivations(1)
        XCTAssertEqual(api.serverBank, "B", "the server moved before answering")
        XCTAssertEqual(store.bank, "A", "the app has not")
        XCTAssertEqual(api.bankWrites.first, "resolveInbox:inbox-001:resolve:b:nil@A", "R-DI3: the held answer first")

        // The next answer, during the wait: refused with a word, its question stays.
        XCTAssertFalse(hold(store, "inbox-002"))
        XCTAssertEqual(store.toast, Copy.switchingMemory)
        XCTAssertNil(store.heldResolve)
        XCTAssertTrue(store.visibleInbox.map(\.id).contains("inbox-002"))
        // The first answer's window expiring now sends nothing more.
        await store.expire(token: token)
        // Any other bank-scoped write is held back too.
        let direct = await store.perform(InboxResolve(id: "inbox-002", action: "archive"))
        XCTAssertFalse(direct)

        api.releaseActivate()
        let ok = await switching.value
        XCTAssertTrue(ok)
        XCTAssertEqual(api.bankWrites, ["resolveInbox:inbox-001:resolve:b:nil@A", "activateBank:B@A"],
                       "nothing was written into B while the app still showed A")
        XCTAssertEqual(store.bank, "B")
        XCTAssertNil(store.bankSwitch)
        XCTAssertTrue(hold(store, "inbox-002"), "answers go again once the new bank is on screen")
    }

    /// An answer already on the wire (sent by the next tap) lands before the switch is posted.
    func testAnAnswerAlreadyOnTheWireLandsBeforeTheSwitch() async throws {
        let (store, api) = try await makeStore()
        api.gateWrites = true
        hold(store, "inbox-001")
        hold(store, "inbox-002")      // sends inbox-001 now; it parks on the wire
        await api.waitForParkedWrite()
        let switching = Task { await store.activateBank("B") }
        await eventually(store.bankSwitch != nil)
        // The held inbox-002 is flushed (and parks); inbox-001 is still on the wire.
        await eventually(api.writes.count == 2)
        XCTAssertFalse(api.writes.contains("activateBank:B"), "the switch waits for both answers")
        api.gateWrites = false
        api.releaseWriteGate()
        _ = await switching.value
        XCTAssertEqual(api.bankWrites.suffix(1), ["activateBank:B@A"])
        XCTAssertTrue(api.bankWrites.dropLast().allSatisfy { $0.hasSuffix("@A") })
    }

    // MARK: Finding 2 — serialized, generation-owned

    /// A second switch from any door while the first flushes its held answer is refused, never interleaved.
    func testASecondSwitchDuringTheHeldFlushIsRefused() async throws {
        let (store, api) = try await makeStore()
        hold(store, "inbox-001")
        api.gateWrites = true
        let first = Task { await store.activateBank("B") }
        await api.waitForParkedWrite()          // the held answer is on the wire
        XCTAssertEqual(store.switchingBank, "B", "reserved before the first await")
        let second = await store.activateBank("C")
        XCTAssertFalse(second)
        XCTAssertEqual(store.toast, Copy.switchingMemory)
        XCTAssertEqual(store.switchingBank, "B", "the refused switch does not touch the marker")
        api.gateWrites = false
        api.releaseWriteGate()
        let ok = await first.value
        XCTAssertTrue(ok)
        XCTAssertEqual(store.bank, "B")
        XCTAssertEqual(api.serverBank, "B")
        XCTAssertFalse(api.writes.contains("activateBank:C"))
        XCTAssertNil(store.switchingBank)
    }

    func testASecondSwitchDuringThePostIsRefused() async throws {
        let (store, api) = try await makeStore()
        api.gateActivate = true
        let first = Task { await store.activateBank("B") }
        await api.waitForParkedActivations(1)
        let refused = await store.activateBank("C")
        XCTAssertFalse(refused)
        XCTAssertEqual(store.switchingBank, "B")
        api.releaseActivate()
        _ = await first.value
        XCTAssertEqual(store.bank, "B")
        XCTAssertEqual(api.writes.filter { $0.hasPrefix("activateBank") }, ["activateBank:B"])
        XCTAssertNil(store.switchingBank)
    }

    /// The first switch fails while a second was asked for: the second was refused, the failure clears only its own
    /// marker, and a new switch afterwards owns a fresh one.
    func testTheFirstFailingWhileASecondWasAskedClearsOnlyItsOwnMarker() async throws {
        let (store, api) = try await makeStore()
        api.activateErrors["B"] = APIError.httpError(409, #"{"detail":"\#(Self.refusal)"}"#)
        api.gateWrites = true
        let first = Task { await store.activateBank("B") }
        await api.waitForParkedWrite()
        let generation = store.bankSwitch?.generation
        let refusedSecond = await store.activateBank("C")
        XCTAssertFalse(refusedSecond)
        api.gateWrites = false
        api.releaseWriteGate()
        let ok = await first.value
        XCTAssertFalse(ok)
        XCTAssertEqual(store.bank, "A", "a refusal changes nothing")
        XCTAssertEqual(store.inbox.value?.count, 2)
        XCTAssertEqual(store.banks.value?.active, "A")
        XCTAssertNil(store.bankSwitch)
        XCTAssertEqual(store.toast, Self.refusal)

        api.gateActivate = true
        let next = Task { await store.activateBank("C") }
        await api.waitForParkedActivations(1)
        XCTAssertEqual(store.switchingBank, "C")
        XCTAssertNotEqual(store.bankSwitch?.generation, generation, "a new switch owns a new generation")
        api.releaseActivate()
        let landed = await next.value
        XCTAssertTrue(landed)
        XCTAssertEqual(store.bank, "C")
    }

    // MARK: SSE and the confirmation, both orders

    /// SSE sees the server on the target first: the Store moves there, and the confirmation does not hydrate again.
    func testSSEBeforeTheConfirmationForTheSameTarget() async throws {
        let (store, api) = try await makeStore()
        api.gateActivate = true
        let switching = Task { await store.activateBank("B") }
        await api.waitForParkedActivations(1)
        await store.refresh([.banks])                       // a `version` event's fan-out
        XCTAssertEqual(store.bank, "B")
        XCTAssertEqual(store.switchingBank, "B", "writes stay held until the switch completes")
        XCTAssertFalse(hold(store, "inbox-001"))
        api.releaseActivate()
        let confirmed = await switching.value
        XCTAssertTrue(confirmed)
        XCTAssertEqual(store.bank, "B")
        XCTAssertNil(store.bankSwitch)
    }

    /// Another client moves the server on to C while this switch to B waits; SSE shows C first. The older answer
    /// (a roster saying B) must not put B back on screen.
    func testANewerBankSeenOverSSEIsNeverOverwrittenByAnOlderConfirmation() async throws {
        let (store, api) = try await makeStore()
        api.gateActivate = true
        let switching = Task { await store.activateBank("B") }
        await api.waitForParkedActivations(1)
        api.serverBank = "C"                                // another client
        await store.refresh([.banks])
        XCTAssertEqual(store.bank, "C")
        var shown: [String] = []
        store.onBankChanged = { [unowned store] in shown.append(store.bank) }
        api.releaseActivate()                               // answers the roster as of the switch to B
        _ = await switching.value
        XCTAssertEqual(shown, [], "B is never put back on screen, not even for a moment")
        XCTAssertEqual(store.bank, "C", "the server's newer bank stands")
        XCTAssertEqual(store.banks.value?.active, "C")
        XCTAssertNil(store.bankSwitch)
    }

    /// The confirmation first, SSE after: the switch lands on B, and a later move by the server is followed.
    func testSSEAfterTheConfirmation() async throws {
        let (store, api) = try await makeStore()
        let switched = await store.activateBank("B")
        XCTAssertTrue(switched)
        XCTAssertEqual(store.bank, "B")
        XCTAssertEqual(store.banks.value?.active, "B")
        api.serverBank = "C"
        await store.refresh([.banks])
        XCTAssertEqual(store.bank, "C")
    }

    /// The roster the activation answers is used: the app lands where the server says it is.
    func testTheActivationsRosterDecidesWhereTheAppLands() async throws {
        let (store, api) = try await makeStore()
        let switched = await store.activateBank("B")
        XCTAssertTrue(switched)
        XCTAssertEqual(store.banks.value?.banks.first(where: { $0.name == "B" })?.active, true)
        XCTAssertEqual(api.writes.first, "activateBank:B")
    }
    // MARK: Fix round 2 — the server's bank check is the safety net

    /// Re-review finding 2: hold one answer, hold a second (the first is queued to send, its task not yet run), and
    /// switch at once. Both accepted answers land in the bank they were made in before the switch is posted; none is
    /// dropped, and the sent callback runs once per landed answer.
    func testTwoHoldsThenAnImmediateSwitchLandBothAnswersInTheOldBank() async throws {
        let (store, api) = try await makeStore()
        var sent = 0
        store.onHeldResolveSent = { sent += 1 }
        XCTAssertTrue(hold(store, "inbox-001"))
        XCTAssertTrue(hold(store, "inbox-002"))     // inbox-001 is queued now, not yet on the wire
        let ok = await store.activateBank("B")
        XCTAssertTrue(ok)
        XCTAssertEqual(Set(api.bankWrites.prefix(2)),
                       ["resolveInbox:inbox-001:resolve:b:nil@A", "resolveInbox:inbox-002:resolve:b:nil@A"])
        XCTAssertEqual(api.bankWrites.last, "activateBank:B@A")
        XCTAssertEqual(sent, 2)
        XCTAssertTrue(store.sendingInboxIds.isEmpty)
    }

    /// An answer that still reaches the server after it moved (another client switched it) names its own bank, so it
    /// is refused, not filed in the other bank: the question comes back, it says so, and no "sent" is reported.
    func testALateAnswerIsRefusedByTheServerAndItsQuestionReopens() async throws {
        let (store, api) = try await makeStore()
        var sent = 0
        store.onHeldResolveSent = { sent += 1 }
        XCTAssertTrue(hold(store, "inbox-001"))
        api.serverBank = "B"                        // the server moved; the app has not heard yet
        await store.flushHeld()
        XCTAssertEqual(api.bankWrites, [], "nothing was written into B")
        XCTAssertEqual(store.toast, Copy.memorySwitched)
        XCTAssertTrue(store.visibleInbox.map(\.id).contains("inbox-001"), "the question is open again")
        XCTAssertEqual(sent, 0)
    }

    /// Re-review finding 1: a picture upload admitted in A and still in flight when the switch to B completes is
    /// refused by the server (`bank_mismatch`), rolled back, and says "Memory switched — try that again".
    func testAPictureUploadPausedAcrossASwitchIsRefusedAndRolledBack() async throws {
        let (store, api) = try await makeStore()
        let pictures = PictureStore(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)) { _ in nil }
        api.gateWritePrefix = "useEntityInitials"
        let upload = Task {
            await store.perform(EntityPictureWrite(entityId: "bob-example", type: .person, bank: "A",
                                                   action: .useInitials, inputs: nil, store: store, pictures: pictures))
        }
        await api.waitForParkedWrite()
        XCTAssertNotNil(store.pictureOverrides[Store.pictureKey(bank: "A", id: "bob-example")], "painted at once")
        let switched = await store.activateBank("B")
        XCTAssertTrue(switched)
        XCTAssertEqual(api.serverBank, "B")
        api.releaseWriteGate()
        let landed = await upload.value
        XCTAssertFalse(landed)
        XCTAssertNil(store.pictureOverrides[Store.pictureKey(bank: "A", id: "bob-example")], "rolled back")
        XCTAssertEqual(store.toast, Copy.memorySwitched)
        XCTAssertFalse(api.bankWrites.contains { $0.hasPrefix("useEntityInitials") }, "never written into B")
    }

    /// Leaving the demo (the server picks the bank) is the same transition: it reserves, refuses a second switch, and
    /// lands where the server's roster says.
    func testADemoLeaveIsTheSameSerializedTransition() async throws {
        let (store, api) = try await makeStore()
        api.serverBank = "A"
        var release: CheckedContinuation<Void, Never>?
        let leaving = Task {
            try await store.switchBank(to: nil, post: { () async -> BanksResponse in
                await withCheckedContinuation { release = $0 }
                api.serverBank = "C"
                return api.roster(active: "C")
            }, roster: { $0 })
        }
        await eventually(release != nil)
        XCTAssertNotNil(store.bankSwitch)
        XCTAssertNil(store.switchingBank, "no named target")
        let refused = await store.activateBank("B")
        XCTAssertFalse(refused)
        XCTAssertFalse(hold(store, "inbox-001"))
        release?.resume()
        _ = try await leaving.value
        XCTAssertEqual(store.bank, "C")
        XCTAssertNil(store.bankSwitch)
    }
}

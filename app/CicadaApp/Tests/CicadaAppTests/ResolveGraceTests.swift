import XCTest
@testable import CicadaApp

/// DR-42 — one tap resolves, and Undo is a SEND DELAY: nothing is POSTed until the window closes,
/// the next answer starts, the bank changes, the window closes or the app quits. An undone answer
/// therefore writes no commit, no claim and no G113 `resolution` event (R-DI2 … R-DI4).
@MainActor
final class ResolveGraceTests: XCTestCase {
    private static let twoItems = """
    [{"id":"inbox-001","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use now?",
      "question":"What does alpha-project use now?",
      "options":[{"key":"a","label":"Tool Example A"},{"key":"b","label":"Tool Example B"}]},
     {"id":"inbox-002","kind":"merge_suggestion","requiredInput":"merge","title":"Same as tool-example-a?"}]
    """

    private func makeStore() throws -> (Store, FakeSyncAPI) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: api)
        api.replies[.inbox] = .notModified
        api.honorsCancellation = true
        store.inbox.value = try JSONDecoder().decode([InboxItem].self, from: Data(Self.twoItems.utf8))
        // The window never closes on its own unless a test says so.
        store.graceWait = { _ in try? await Task.sleep(for: .seconds(3600)) }
        return (store, api)
    }

    private func hold(_ store: Store, _ id: String, action: String = "resolve", optionKey: String? = "b") {
        store.hold(InboxResolve(id: id, action: action, optionKey: optionKey),
                   label: "Answered · Tool Example B", shortLabel: "Answered", question: "q",
                   kind: .conflict, channel: nil)
    }

    private func eventually(_ condition: @autoclosure () -> Bool,
                            file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<200_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never happened", file: file, line: line)
    }

    func testAHeldAnswerSendsNothingAndHidesItsQuestionAtOnce() throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        XCTAssertEqual(api.writes, [], "a tap is not a commit")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-002"], "the badge, Home and the palette agree at once")
        XCTAssertEqual(store.currentHeld?.id, "inbox-001")
    }

    func testUndoInsideTheWindowSendsNothingEver() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        let token = try XCTUnwrap(store.heldResolve?.token)
        XCTAssertEqual(store.undoHeld(), "inbox-001")
        await store.expire(token: token)
        await store.flushHeld()
        XCTAssertEqual(api.writes, [], "an undone answer emits no G113 verdict")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"])
    }

    func testTheWindowClosingSendsTheAnswerOnce() async throws {
        let (store, api) = try makeStore()
        store.graceWait = { _ in }
        hold(store, "inbox-001")
        await eventually(api.writes == ["resolveInbox:inbox-001:resolve:b:nil"])
        XCTAssertNil(store.heldResolve)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-002"], "still hidden until a snapshot drops it")
    }

    /// Task 2 review round 1 — the main path: an answer left to time out. The send runs inside the
    /// window's own task; if expiring cancelled that task, the POST died as `URLError.cancelled`, the
    /// question came back and the "reverted" toast showed for an answer that was never refused.
    func testAnAnswerLeftToTimeOutIsSavedNotCancelledByItsOwnWindow() async throws {
        let (store, api) = try makeStore()
        store.graceWait = { _ in }
        hold(store, "inbox-001")
        await eventually(api.writes.count == 1 && store.sendingInboxIds.isEmpty)
        XCTAssertEqual(api.writes, ["resolveInbox:inbox-001:resolve:b:nil"], "exactly one POST")
        XCTAssertNil(store.toast, "no failure toast")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-002"], "no rollback")
    }

    /// Task 2 review round 1 — quit waits for an answer already on the wire too, not only a held one.
    func testQuitWaitsForAnAnswerAlreadyBeingSent() async throws {
        let (store, api) = try makeStore()
        api.gateWrites = true
        hold(store, "inbox-001")
        hold(store, "inbox-002", action: "skip", optionKey: nil)
        await api.waitForParkedWrite()
        _ = store.undoHeld()
        XCTAssertNil(store.heldResolve)
        XCTAssertTrue(store.hasAnswerInFlight, "the first answer is still on the wire")
        let drained = Task { await store.sendHeldAndDrain() }
        await Task.yield()
        api.releaseWriteGate()
        await drained.value
        XCTAssertFalse(store.hasAnswerInFlight)
    }

    func testTheNextAnswerSendsThePreviousAtOnce() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        hold(store, "inbox-002", action: "skip", optionKey: nil)
        XCTAssertEqual(store.visibleInbox.map(\.id), [], "the first is on the wire, the second is held — neither flashes back")
        await eventually(api.writes.count == 1)
        XCTAssertEqual(api.writes, ["resolveInbox:inbox-001:resolve:b:nil"])
        XCTAssertEqual(store.heldResolve?.id, "inbox-002")
    }

    /// R-DI3 — every bank switch is `ActivateBank`; it sends the held answer before the bank moves.
    func testABankSwitchSendsTheHeldAnswerFirst() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        _ = await store.perform(ActivateBank(name: "work"))
        XCTAssertEqual(Array(api.writes.prefix(2)), ["resolveInbox:inbox-001:resolve:b:nil", "activateBank:work"])
    }

    func testAFailedSendPutsTheQuestionBackAndSaysSo() async throws {
        let (store, api) = try makeStore()
        api.failWrites = true
        hold(store, "inbox-001")
        await store.flushHeld()
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"])
        XCTAssertEqual(store.toast, "Couldn't resolve that item — reverted")
    }

    /// R-DI4 — a skipped question is still pending: gone for the window, back after the send.
    func testASkippedQuestionComesBackOnceItIsSent() async throws {
        let (store, _) = try makeStore()
        hold(store, "inbox-002", action: "skip", optionKey: nil)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001"])
        await store.flushHeld()
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"])
    }

    /// R-DI3 — ids repeat across banks; a hold is only ever sent to the bank it was made in.
    func testAHoldIsNeverSentIntoAnotherBank() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        store.bank = "another-bank"
        XCTAssertNil(store.currentHeld, "a hold from another bank hides nothing here")
        await store.flushHeld()
        XCTAssertEqual(api.writes, [])
        XCTAssertEqual(store.toast, Copy.Inbox.answerNotSaved)
    }

    /// R-DI3 — answered elsewhere inside the window (MCP, an organic Sleep resolve): nothing to send, and no
    /// "reverted" toast for an answer that was never refused.
    func testAQuestionThatVanishedInsideTheWindowSendsNothing() async throws {
        let (store, api) = try makeStore()
        hold(store, "inbox-001")
        store.inbox.value = store.inbox.value?.filter { $0.id != "inbox-001" }
        await store.flushHeld()
        XCTAssertEqual(api.writes, [])
        XCTAssertNil(store.toast)
    }

    func testTheMenuBarHearsWhenAHeldAnswerLands() async throws {
        let (store, _) = try makeStore()
        var heard = 0
        store.onHeldResolveSent = { heard += 1 }
        hold(store, "inbox-001")
        await store.flushHeld()
        XCTAssertEqual(heard, 1)
    }

    func testQuitWaitsOnlyWhenSomethingIsHeldAndNeverPastItsLimit() async {
        XCTAssertEqual(QuitFlush.reply(hasHeld: false), .terminateNow)
        XCTAssertEqual(QuitFlush.reply(hasHeld: true), .terminateLater)
        let hung = await QuitFlush.run({ try? await Task.sleep(for: .seconds(60)) }, limit: .milliseconds(50))
        XCTAssertFalse(hung, "a backend that is gone never keeps the app open")
        let quick = await QuitFlush.run({}, limit: .seconds(5))
        XCTAssertTrue(quick)
    }

    func testTheViewModelAnswersThroughTheHoldAndUndoReturnsTheQuestion() throws {
        let (store, api) = try makeStore()
        let vm = InboxViewModel(store: store)
        let item = try XCTUnwrap(store.inbox.value?.first)
        vm.answer(item, QuestionResolution(action: "resolve", optionKey: "b"))
        XCTAssertEqual(vm.pendingCount, 1, "the rail badge drops on the tap")
        XCTAssertEqual(api.writes, [])
        XCTAssertEqual(store.heldResolve?.label, "Answered · Tool Example B")
        XCTAssertEqual(vm.undo(reopen: false)?.id, "inbox-001")
        XCTAssertEqual(vm.pendingCount, 2)
    }
}

/// R-DI5 — what the Undo row says: words, never the action's wire name.
final class UndoLabelTests: XCTestCase {
    private func item(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    func testEveryActionHasItsWords() throws {
        let conflict = try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","options":[{"key":"b","label":"Tool Example B"}]}"#)
        let info = try item(#"{"id":"i","kind":"conflict","requiredInput":"choice","title":"t","informational":true}"#)
        func words(_ r: QuestionResolution, _ i: InboxItem) -> [String] {
            let w = UndoLabel.of(r, item: i)
            return [w.full, w.short]
        }
        XCTAssertEqual(words(.init(action: "resolve", optionKey: "b"), conflict), ["Answered · Tool Example B", "Answered"])
        XCTAssertEqual(words(.init(action: "resolve", answer: "Tool C", optionKey: "neither"), conflict), ["Answered · Tool C", "Answered"])
        XCTAssertEqual(words(.init(action: "resolve", optionKey: "remind_later"), conflict), ["Not now", "Not now"])
        XCTAssertEqual(words(.init(action: "answer", answer: "a colleague"), conflict), ["Answered · a colleague", "Answered"])
        XCTAssertEqual(words(.init(action: "defer", remindDays: 7), conflict), ["Not now", "Not now"])
        XCTAssertEqual(words(.init(action: "dismiss"), info), ["Got it", "Got it"])
        XCTAssertEqual(words(.init(action: "dismiss"), conflict), ["Dismissed", "Dismissed"])
        XCTAssertEqual(words(.init(action: "skip"), conflict), ["Skipped", "Skipped"])
        XCTAssertEqual(words(.init(action: "reject", mergeTarget: "x"), conflict), ["Kept separate", "Kept"])
        XCTAssertEqual(words(.init(action: "merge", mergeTarget: "x"), conflict), ["Merged", "Merged"])
        XCTAssertEqual(words(.init(action: "keep_active"), conflict), ["Kept", "Kept"])
        XCTAssertEqual(words(.init(action: "archive"), conflict), ["Archived", "Archived"])
    }
}

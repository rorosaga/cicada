import XCTest
@testable import CicadaApp

/// G183(d) for the Mac readers with a per-memory cursor or digest (YouTube history, Messages, tab groups, Contacts).
/// A run reads past one memory's cursor, so every batch it posts names THAT memory — never the one on screen when the
/// batch leaves, which after a switch is the other memory: its post would land there while the first memory's cursor
/// moved past what it never received. And a switch that lands mid-run starts the new memory's own read at once: a run
/// for the old memory is stopped, never joined.
@MainActor
final class GatedWatchHistoryAPI: WatchHistorySyncAPI {
    var hold = false
    private(set) var banks: [String?] = []
    func syncWatchHistory(_ payload: WatchHistoryPayload) async throws -> WatchHistorySyncResult {
        banks.append(BankScope.origin)
        if hold { try await Task.sleep(for: .seconds(30)) }
        return WatchHistorySyncResult(received: payload.visits.count, kept: payload.visits.count,
                                      added: payload.visits.count, videos: payload.visits.count)
    }
}

@MainActor
final class WatcherBankBindingTests: XCTestCase {
    private var bank = "alpha"

    private func eventually(_ what: String, _ condition: () -> Bool) async -> Bool {
        let deadline = ContinuousClock.now + .seconds(3)
        while !condition() {
            guard ContinuousClock.now < deadline else { XCTFail("timed out waiting for \(what)"); return false }
            try? await Task.sleep(for: .milliseconds(20))
        }
        return true
    }

    // MARK: YouTube history

    private func historyWatcher(_ api: GatedWatchHistoryAPI, _ history: SyntheticChromeHistory,
                                _ defaults: UserDefaults) -> WatchHistoryWatcher {
        WatchHistoryWatcher(api: api, reader: ChromeWatchHistoryReader(historyFile: history.url), defaults: defaults,
                            checkInterval: .seconds(3600), bank: { [unowned self] in self.bank })
    }

    func testWatchHistoryPostsNameTheMemoryWhoseCursorTheyAdvance() async throws {
        let history = try SyntheticChromeHistory()
        defer { history.remove() }
        history.visit("https://www.youtube.com/watch?v=aaaaaaaaaaa", title: "Video one", at: "2026-10-14T09:14:03Z")
        let api = GatedWatchHistoryAPI()
        let w = historyWatcher(api, history, UserDefaults(suiteName: "wh-bind-\(UUID())")!)
        await w.enable()
        XCTAssertEqual(api.banks, ["alpha"])
    }

    func testASwitchMidHistoryReadStartsTheNewMemorysOwnRead() async throws {
        let history = try SyntheticChromeHistory()
        defer { history.remove() }
        history.visit("https://www.youtube.com/watch?v=aaaaaaaaaaa", title: "Video one", at: "2026-10-14T09:14:03Z")
        let api = GatedWatchHistoryAPI()
        api.hold = true
        let w = historyWatcher(api, history, UserDefaults(suiteName: "wh-switch-\(UUID())")!)
        let first = Task { await w.enable() }
        guard await eventually("alpha's post", { api.banks.count == 1 }) else { w.cancel(); return }
        bank = "beta"
        api.hold = false
        let switched = Task { await w.bankChanged() }
        let started = await eventually("beta's own read", { api.banks.count == 2 })
        w.cancel()
        _ = await first.value
        _ = await switched.value
        guard started else { return }
        XCTAssertEqual(api.banks, ["alpha", "beta"])
        XCTAssertEqual(w.cursor(bank: "beta"), 1, "the memory on screen read past its own cursor")
        XCTAssertEqual(w.cursor(bank: "alpha"), 0, "the stopped read recorded nothing for the memory it left")
        XCTAssertEqual(w.status, .watching, "the stopped run never paints over the new one's row")
    }

    // MARK: Messages

    private func messagesWatcher(_ api: FakeMessagesAPI, _ chat: SyntheticChatDB) -> MessagesWatcher {
        MessagesWatcher(api: api, reader: MessagesReader(database: chat.url),
                        defaults: UserDefaults(suiteName: "msg-bind-\(UUID())")!,
                        folder: chat.dir, debounce: .milliseconds(10), minimumInterval: .zero,
                        makeWatch: { _, _ in nil }, bank: { [unowned self] in self.bank },
                        lookUpCards: { _ in [:] }, lookUpSharedPhotos: { _ in [:] })
    }

    private func tickedChat() throws -> (SyntheticChatDB, String) {
        let chat = try SyntheticChatDB()
        let rowid = chat.chat("+15550000001")
        chat.message(rowid, minute: 0, fromMe: true, text: "Plan the alpha-project launch?")
        chat.message(rowid, minute: 1, fromMe: false, text: "Step one: list the tasks.")
        return (chat, MessagesReader.conversationId(chatGuid: "iMessage;-;+15550000001"))
    }

    func testMessagesPostsNameTheMemoryWhoseCursorTheyAdvance() async throws {
        let (chat, id) = try tickedChat()
        defer { chat.close() }
        let api = FakeMessagesAPI()
        api.ticked = [id]
        let w = messagesWatcher(api, chat)
        await w.bankChanged()
        XCTAssertEqual(api.banks, ["alpha"])
    }

    func testASwitchMidMessagesReadStartsTheNewMemorysOwnRead() async throws {
        let (chat, id) = try tickedChat()
        defer { chat.close() }
        let api = FakeMessagesAPI()
        api.ticked = [id]
        api.hold = true
        let w = messagesWatcher(api, chat)
        let first = Task { await w.bankChanged() }
        guard await eventually("alpha's post", { api.banks.count == 1 }) else { w.cancel(); return }
        bank = "beta"
        api.hold = false
        let switched = Task { await w.bankChanged() }
        let started = await eventually("beta's own read", { api.banks.count == 2 })
        w.cancel()
        _ = await first.value
        _ = await switched.value
        guard started else { return }
        XCTAssertEqual(api.banks, ["alpha", "beta"])
        XCTAssertGreaterThan(w.cursor(bank: "beta", id: id).rowid, 0)
        XCTAssertEqual(w.cursor(bank: "alpha", id: id), MessagesCursor(), "the stopped read recorded nothing")
        XCTAssertEqual(w.status, .watching)
    }

    // MARK: Tab groups

    private func tabGroupsDirectory() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("TabBind-\(UUID().uuidString)/Sessions")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var w = SNSSWriter(version: 3)
        w.tabWindow(window: 1, tab: 1)
        w.navigation(tab: 1, index: 0, url: "https://example.com/alpha/doc", title: "Design doc")
        w.metadata(high: 1, low: 2, title: "alpha-project", color: 1, collapsed: false)
        w.group(tab: 1, high: 1, low: 2)
        w.marker()
        try w.data.write(to: dir.appendingPathComponent("Session_1"))
        return dir
    }

    private func tabWatcher(_ api: FakeTabGroupsAPI, _ dir: URL) -> TabGroupWatcher {
        TabGroupWatcher(api: api, defaults: UserDefaults(suiteName: "tab-bind-\(UUID())")!, directory: dir,
                        debounce: .milliseconds(20), minimumInterval: .zero, makeWatch: { _, _ in nil },
                        bank: { [unowned self] in self.bank })
    }

    func testTabGroupPostsNameTheMemoryWhoseDigestTheyRecord() async throws {
        let dir = try tabGroupsDirectory()
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        let api = FakeTabGroupsAPI()
        let w = tabWatcher(api, dir)
        await w.enable()
        XCTAssertEqual(api.banks, ["alpha"])
    }

    func testASwitchMidTabGroupsReadStartsTheNewMemorysOwnRead() async throws {
        let dir = try tabGroupsDirectory()
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        let api = FakeTabGroupsAPI()
        api.hold = true
        let w = tabWatcher(api, dir)
        let first = Task { await w.enable() }
        guard await eventually("alpha's post", { api.banks.count == 1 }) else { w.cancel(); return }
        bank = "beta"
        api.hold = false
        let switched = Task { await w.bankChanged() }
        let started = await eventually("beta's own read", { api.banks.count == 2 })
        w.cancel()
        _ = await first.value
        _ = await switched.value
        guard started else { return }
        XCTAssertEqual(api.banks, ["alpha", "beta"])
        XCTAssertEqual(w.status, .watching)
    }

    // MARK: Contacts

    private func contactsReader(_ store: FakeContactStore, _ api: FakeContactsAPI) -> ContactsReader {
        ContactsReader(store: store, api: api, defaults: UserDefaults(suiteName: "contacts-bind-\(UUID())")!,
                       retryAfter: .seconds(3600), bank: { [unowned self] in self.bank })
    }

    func testContactsPostsNameTheMemoryTheyAreRecordedFor() async throws {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = contactsReader(store, api)
        await r.connect()
        XCTAssertEqual(api.banks, ["alpha"])
    }

    func testASwitchMidContactsReadStartsTheNewMemorysOwnRead() async throws {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        api.hold = true
        let r = contactsReader(store, api)
        let first = Task { await r.connect() }
        guard await eventually("alpha's post", { api.banks.count == 1 }) else { r.cancel(); return }
        bank = "beta"
        api.hold = false
        let switched = Task { await r.bankChanged() }
        let started = await eventually("beta's own read", { api.banks.count == 2 })
        r.cancel()
        _ = await first.value
        _ = await switched.value
        guard started else { return }
        XCTAssertEqual(api.banks, ["alpha", "beta"])
        XCTAssertEqual(r.status, .watching)
    }
}

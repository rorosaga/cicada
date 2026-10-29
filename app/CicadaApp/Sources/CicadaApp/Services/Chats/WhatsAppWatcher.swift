import Foundation
import Observation

/// G179 (2026-10-28) — the WhatsApp chats the person ticked, read by the APP from WhatsApp Desktop's store and posted
/// per memory: the Messages model (`MessagesWatcher`), for a second app.
///
/// **Nothing is read before a tick.** The tick list shows names and last activity only. **A tick is live from now:**
/// the chat's cursor starts at its newest row, so only what is said after the tick is read — and the backend refuses
/// anything older itself. **History on ask:** "Read history" asks the backend to open the chat back to its first
/// message and reads it from the start. **When it reads:** on launch and on a bank switch when something is ticked, on
/// a tick, on Refresh, and on an FSEvents change in WhatsApp's group container (it writes the store's `-wal` on every
/// message) — debounced `debounce` and floored at `minimumInterval`. Every read runs off the main actor
/// (`Task.detached`); the main actor only keeps state and posts.
@MainActor
@Observable
final class WhatsAppWatcher {
    nonisolated static let channel = "whatsapp"
    nonisolated static let source = "whatsapp"

    enum Status: Equatable {
        case idle, syncing, watching
        case needsAccess(BrowserFileError)
        case missing
        case failed(String)
    }

    private(set) var status: Status = .idle
    private(set) var chats: [WhatsAppChat] = []
    private(set) var tickedIds: Set<String> = []
    private(set) var historyIds: Set<String> = []
    private(set) var cards: [String: MessagesContactCard] = [:]
    private(set) var listing = false
    /// File change → posted, seconds, the last 50 live passes — the area doc's number.
    private(set) var liveSeconds: [Double] = []

    @ObservationIgnored private let api: any ChatSourcesAPI
    @ObservationIgnored private let reader: WhatsAppReader
    @ObservationIgnored private let lights: BrowserWatcher?
    @ObservationIgnored private let activity: SyncActivity?
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let folder: URL
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let minimumInterval: Duration
    @ObservationIgnored private let makeWatch: FolderWatchFactory
    @ObservationIgnored private let bank: @MainActor () -> String
    @ObservationIgnored private let lookUpCards: @Sendable ([String]) async -> [String: MessagesContactCard]
    @ObservationIgnored private var watch: FSEventsWatch?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?
    @ObservationIgnored private var lastStarted: ContinuousClock.Instant?
    @ObservationIgnored private var changedAt: ContinuousClock.Instant?

    init(api: any ChatSourcesAPI = APIClient.shared, reader: WhatsAppReader = WhatsAppReader(store: WhatsAppReader.standardStore),
         lights: BrowserWatcher? = nil, activity: SyncActivity? = nil, defaults: UserDefaults = .standard,
         folder: URL = WhatsAppReader.container, debounce: Duration = .seconds(3), minimumInterval: Duration = .seconds(15),
         makeWatch: FolderWatchFactory? = nil, bank: @escaping @MainActor () -> String = { "default" },
         lookUpCards: @escaping @Sendable ([String]) async -> [String: MessagesContactCard] = { await MessagesContacts.cards(for: $0) }) {
        self.api = api
        self.reader = reader
        self.lights = lights
        self.activity = activity
        self.defaults = defaults
        self.folder = folder
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.makeWatch = makeWatch ?? { path, onChange in FSEventsWatch(path: path, handler: onChange) }
        self.bank = bank
        self.lookUpCards = lookUpCards
    }

    private func cursorKey(_ bank: String, _ id: String) -> String {
        ServerConnection.current.scoped("cicada.whatsapp.cursor.\(bank).\(id)")
    }

    func cursor(bank: String, id: String) -> Int64? {
        defaults.object(forKey: cursorKey(bank, id)) == nil ? nil : Int64(defaults.integer(forKey: cursorKey(bank, id)))
    }

    private func save(_ cursor: Int64, bank: String, id: String) { defaults.set(Int(cursor), forKey: cursorKey(bank, id)) }

    // MARK: Lifecycle

    func start() { Task { await self.bankChanged() } }

    func bankChanged() async {
        let answer = try? await api.fetchChatTicks(source: Self.source)
        tickedIds = answer?.tickedIds ?? []
        historyIds = Set(answer?.conversations.filter(\.history).map(\.id) ?? [])
        guard !tickedIds.isEmpty else {
            disarm()
            return
        }
        arm()
        await run()
    }

    /// The name the backend may keep: the Contacts card's, else WhatsApp's own partner or group name — never the number.
    func postedName(of chat: WhatsAppChat) -> String {
        if let card = cards[chat.id], !card.name.isEmpty { return card.name }
        return chat.partnerName.allSatisfy({ $0.isNumber || "+ ()-".contains($0) }) ? "" : chat.partnerName
    }

    func name(of chat: WhatsAppChat) -> String {
        let posted = postedName(of: chat)
        return posted.isEmpty ? (chat.phoneHandle ?? Copy.Chats.unnamed) : posted
    }

    // MARK: The list

    func loadList() async {
        listing = true
        defer { listing = false }
        let reader = self.reader
        do {
            chats = try await Task.detached(priority: .userInitiated) { try reader.chats() }.value
            if status == .missing || isNeedsAccess { status = tickedIds.isEmpty ? .idle : .watching }
        } catch let error as BrowserFileError {
            status = Self.status(for: error)
            publish()
            return
        } catch {
            status = .failed(Copy.Chats.whatsAppUnreadable)
            return
        }
        let phones = chats.compactMap(\.phoneHandle)
        let found = await lookUpCards(phones)
        cards = Dictionary(uniqueKeysWithValues: chats.compactMap { chat in
            chat.phoneHandle.flatMap { found[$0] }.map { (chat.id, $0) } })
        if let answer = try? await api.describeChats(source: Self.source, ids: chats.map { ($0.id, $0.group) }) {
            tickedIds = answer.tickedIds.union(tickedIds.subtracting(chats.map(\.id)))
            historyIds = Set(answer.conversations.filter(\.history).map(\.id))
        }
    }

    private var isNeedsAccess: Bool { if case .needsAccess = status { true } else { false } }

    /// Tick or untick. A tick is the consent to LIVE reading: the chat's cursor starts at its newest row.
    func setTicked(_ chat: WhatsAppChat, _ on: Bool) async throws {
        let bank = self.bank()
        if on, cursor(bank: bank, id: chat.id) == nil {
            let reader = self.reader
            let top = try await Task.detached(priority: .userInitiated) { try reader.newest(chat) }.value
            save(top, bank: bank, id: chat.id)
        }
        let answer = try await api.updateChat(source: Self.source, id: chat.id, name: postedName(of: chat), group: chat.group,
                                              ticked: on, history: nil)
        tickedIds = answer.tickedIds
        if on {
            arm()
            await run()
        } else if tickedIds.isEmpty {
            disarm()
        }
    }

    /// The person's ask: this chat's history, back to the first message WhatsApp keeps on this Mac.
    func readHistory(_ chat: WhatsAppChat) async throws {
        let answer = try await api.updateChat(source: Self.source, id: chat.id, name: postedName(of: chat), group: chat.group,
                                              ticked: nil, history: true)
        historyIds = Set(answer.conversations.filter(\.history).map(\.id))
        save(0, bank: bank(), id: chat.id)
        await run()
    }

    func syncNow() async throws -> String {
        guard !tickedIds.isEmpty else { throw BrowserImportActions.ImportActionError.failed(Copy.Chats.tickFirst) }
        return try await run().get()
    }

    @discardableResult
    func run() async -> Result<String, Error> {
        if let running { return await running.result }
        guard !tickedIds.isEmpty else { return .failure(CancellationError()) }
        let bank = self.bank()
        let task = Task { @MainActor [weak self] () throws -> String in
            guard let self else { throw CancellationError() }
            return try await BankScope.bound(to: bank) { try await self.perform(bank: bank) }
        }
        running = task
        lastStarted = .now
        activity?.began(Self.channel, detail: Copy.Chats.reading, cancel: { [weak self] in self?.running?.cancel() })
        status = .syncing
        publish()
        let result = await task.result
        running = nil
        activity?.ended(Self.channel)
        switch result {
        case .success:
            status = .watching
            if let changedAt {
                liveSeconds = Array((liveSeconds + [Self.seconds(ContinuousClock.now - changedAt)]).suffix(50))
                self.changedAt = nil
            }
        case .failure(let error) where SyncCancellation.isCancellation(error): status = .watching
        case .failure(let error as BrowserFileError): status = Self.status(for: error)
        case .failure(let error): status = .failed(Self.failureMessage(error))
        }
        publish()
        return result
    }

    private func perform(bank: String) async throws -> String {
        let reader = self.reader
        let ticked = tickedIds
        let found = try await Task.detached(priority: .utility) { try reader.chats(ids: ticked) }.value
        var posted = 0
        for chat in found {
            let name = postedName(of: chat)
            var names: [String: String] = [:]
            if chat.group {
                names = try await Task.detached(priority: .utility) { try reader.memberNames(chat) }.value
            }
            var cursor = self.cursor(bank: bank, id: chat.id) ?? 0
            for batch in 0..<20 {   // bounded catch-up: at most 20 batches per pass; the window is re-read once
                let since = cursor
                let pass = try await Task.detached(priority: .utility) {
                    try reader.read(chat, name: name, memberNames: names, since: since, recheck: batch == 0)
                }.value
                try Task.checkCancellation()
                if pass.count > 0 { _ = try await api.postWhatsApp(pass.json) }
                cursor = pass.cursor
                save(cursor, bank: bank, id: chat.id)
                posted += pass.count
                guard pass.hasMore else { break }
                // A full batch that did not move the cursor would read the same rows forever: say so, never spin.
                if pass.cursor <= since { throw WhatsAppReadError.stalled }
            }
        }
        return posted > 0 ? Copy.Chats.synced(posted) : Copy.Chats.upToDate
    }

    // MARK: Watching

    private func arm() {
        guard watch == nil else { return }
        watch = makeWatch(folder.path) { [weak self] in self?.changed() }
        if status == .idle { status = .watching }
        publish()
    }

    private func disarm() {
        watch?.stop()
        watch = nil
        pending?.cancel()
        pending = nil
        if running == nil { status = .idle }
        publish()
    }

    private func changed() {
        guard !tickedIds.isEmpty else { return }
        if changedAt == nil { changedAt = .now }
        pending?.cancel()
        pending = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(for: self.debounce)
            guard !Task.isCancelled else { return }
            if let last = self.lastStarted {
                let elapsed = ContinuousClock.now - last
                if elapsed < self.minimumInterval { try? await Task.sleep(for: self.minimumInterval - elapsed) }
                guard !Task.isCancelled else { return }
            }
            await self.run()
        }
    }

    nonisolated static func seconds(_ d: Duration) -> Double {
        Double(d.components.seconds) + Double(d.components.attoseconds) / 1e18
    }

    static func failureMessage(_ error: Error) -> String {
        if let read = error as? WhatsAppReadError { return read.errorDescription ?? Copy.Chats.whatsAppUnreadable }
        if error is URLError { return Copy.sourceBackendDown }
        guard let api = error as? APIError else { return Copy.Chats.syncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.Chats.syncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.sourceNeedsUpdate
        case .serverUnreachable: return Copy.sourceBackendDown
        default: return Copy.Chats.syncFailed
        }
    }

    private static func status(for error: BrowserFileError) -> Status {
        if case .missing = error { return .missing }
        return .needsAccess(error)
    }

    private func publish() {
        let light: BrowserWatchState? = switch status {
        case .idle: tickedIds.isEmpty ? nil : .watching
        case .syncing: .syncing
        case .watching: .watching
        case .needsAccess: .blocked
        case .missing: .absent
        case .failed: .failed
        }
        let error: BrowserFileError? = if case .needsAccess(let e) = status { e } else { nil }
        lights?.publish(light, error: error, for: Self.channel)
    }
}

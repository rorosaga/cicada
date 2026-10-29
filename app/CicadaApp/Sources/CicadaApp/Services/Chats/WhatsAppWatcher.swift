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
    /// chats-ux-v2 — the profile picture WhatsApp keeps for each listed chat, ≤ 128 px, in memory only.
    private(set) var pictures: [String: Data] = [:]
    /// The photo last posted per ticked chat (its bytes' hash), so an unchanged one is never posted again.
    @ObservationIgnored private var postedPhotos: [String: Int] = [:]
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
    /// Whether Contacts may be read (a test passes a fake; `MessagesContacts`' one door otherwise).
    @ObservationIgnored private let lookUpContactsAllowed: @Sendable () -> Bool
    /// The phone handles this session actually looked up in Contacts: only for one of them can "no single card" be
    /// said (`MessagesWatcher.postedCard`, the Messages rule).
    @ObservationIgnored private(set) var lookedUp: Set<String> = []
    /// Group members' cards, by phone handle (only when Contacts is allowed) — never posted, only their ids.
    @ObservationIgnored private var memberCards: [String: MessagesContactCard] = [:]
    @ObservationIgnored private var watch: FSEventsWatch?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var running: Task<String, Error>?
    @ObservationIgnored private var lastStarted: ContinuousClock.Instant?
    @ObservationIgnored private var changedAt: ContinuousClock.Instant?

    init(api: any ChatSourcesAPI = APIClient.shared, reader: WhatsAppReader = WhatsAppReader(store: WhatsAppReader.standardStore),
         lights: BrowserWatcher? = nil, activity: SyncActivity? = nil, defaults: UserDefaults = .standard,
         folder: URL = WhatsAppReader.container, debounce: Duration = .seconds(3), minimumInterval: Duration = .seconds(15),
         makeWatch: FolderWatchFactory? = nil, bank: @escaping @MainActor () -> String = { "default" },
         lookUpCards: @escaping @Sendable ([String]) async -> [String: MessagesContactCard] = { await MessagesContacts.cards(for: $0) },
         lookUpContactsAllowed: @escaping @Sendable () -> Bool = { MessagesContacts.allowed }) {
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
        self.lookUpContactsAllowed = lookUpContactsAllowed
    }

    /// Look these handles up, and remember them as looked up only when Contacts could really be read.
    private func lookUp(_ handles: [String]) async -> [String: MessagesContactCard] {
        guard !handles.isEmpty else { return [:] }
        let allowed = lookUpContactsAllowed()
        let found = await lookUpCards(handles)
        if allowed { lookedUp.formUnion(handles) }
        return found
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
    /// The person's own chat is named for what it is (its card is the person's own, never a correspondent's).
    func postedName(of chat: WhatsAppChat) -> String {
        if chat.isSelf { return Copy.Chats.selfChat }
        if let card = cards[chat.id], !card.name.isEmpty { return card.name }
        return chat.partnerName.allSatisfy({ $0.isNumber || "+ ()-".contains($0) }) ? "" : chat.partnerName
    }

    func name(of chat: WhatsAppChat) -> String {
        let posted = postedName(of: chat)
        return posted.isEmpty ? (chat.phoneHandle ?? Copy.Chats.unnamed) : posted
    }

    /// chats-ux-v2 — the picker's picture: the Contacts card's photo, else the one WhatsApp keeps for the chat.
    func thumbnail(of chat: WhatsAppChat) -> Data? { cards[chat.id]?.thumbnail ?? pictures[chat.id] }

    /// chats-ux-v2 (owner 2026-10-29: "why I can't search my chats") — the chats a search keeps, most recent first (the
    /// list's own order): a name fragment (case and accents ignored) or a fragment of a one-to-one chat's number.
    func filtered(_ query: String) -> [WhatsAppChat] {
        ChatSearch.filter(chats, query: query, name: { self.name(of: $0) }, digits: \.searchDigits)
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
        // The person's own number is no correspondent: never looked up as one (its card is their own).
        let phones = chats.filter { !$0.isSelf }.compactMap(\.phoneHandle)
        let found = await lookUp(phones)
        cards = Dictionary(uniqueKeysWithValues: chats.compactMap { chat in
            chat.phoneHandle.flatMap { found[$0] }.map { (chat.id, $0) } })
        if let answer = try? await api.describeChats(source: Self.source, ids: chats.map { ($0.id, $0.group) }) {
            tickedIds = answer.tickedIds.union(tickedIds.subtracting(chats.map(\.id)))
            historyIds = Set(answer.conversations.filter(\.history).map(\.id))
        }
        // chats-ux-v2 — pictures last: the rows and their ticks never wait on them (≈80 ms for 300, measured).
        let listed = chats
        pictures = await Task.detached(priority: .userInitiated) {
            Dictionary(uniqueKeysWithValues: listed.compactMap { chat in reader.picture(chat).map { (chat.id, $0) } })
        }.value
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
            var memberPosted: [String: String] = [:]
            var contact: String?
            if chat.group {
                names = try await Task.detached(priority: .utility) { try reader.memberNames(chat) }.value
                // One person across sources: each member's ONE card by Contacts id, the Messages rule.
                let jids = try await Task.detached(priority: .utility) { try reader.memberJids(chat) }.value
                let handles = jids.compactMap { jid in WhatsAppChat.phoneHandle(jid: jid).map { (jid, $0) } }
                let missing = handles.map(\.1).filter { memberCards[$0] == nil && !lookedUp.contains($0) }
                for (handle, card) in await lookUp(missing) { memberCards[handle] = card }
                for (jid, handle) in handles {
                    if let posted = MessagesWatcher.postedCard(memberCards[handle], looked: lookedUp.contains(handle)) {
                        memberPosted[jid] = posted
                    }
                }
            } else if !chat.isSelf, let handle = chat.phoneHandle {
                if cards[chat.id] == nil, !lookedUp.contains(handle),
                   let card = await lookUp([handle])[handle] { cards[chat.id] = card }
                contact = MessagesWatcher.postedCard(cards[chat.id], looked: lookedUp.contains(handle))
            }
            var cursor = self.cursor(bank: bank, id: chat.id) ?? 0
            for batch in 0..<20 {   // bounded catch-up: at most 20 batches per pass; the window is re-read once
                let since = cursor
                let pass = try await Task.detached(priority: .utility) {
                    try reader.read(chat, name: name, memberNames: names, since: since, recheck: batch == 0,
                                    contact: contact, memberCards: memberPosted)
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
        await postPhotos(found)
        return posted > 0 ? Copy.Chats.synced(posted) : Copy.Chats.upToDate
    }

    /// chats-ux-v2 — a ticked chat's WhatsApp picture, posted like a Messages chat's shared photo (`messages_photos`:
    /// outside every bank, the page's picture through the chat's correspondent — never for a group or the person's own
    /// chat, which have none). Posted only when it changed; a failure leaves the face a monogram, never the sync.
    private func postPhotos(_ ticked: [WhatsAppChat]) async {
        let reader = self.reader
        let pairs = await Task.detached(priority: .utility) {
            ticked.map { chat in (chat.id, chat.group || chat.isSelf ? nil : reader.picture(chat)) }
        }.value
        let changed = pairs.filter { id, data in postedPhotos[id] != data?.hashValue ?? 0 }
        guard !changed.isEmpty else { return }
        if (try? await api.putChatPhotos(changed.map { MessagesPhotoPayload(conversation: $0.0, photo: $0.1) })) != nil {
            for (id, data) in changed { postedPhotos[id] = data?.hashValue ?? 0 }
        }
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
        return Copy.Chats.failure(error)
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

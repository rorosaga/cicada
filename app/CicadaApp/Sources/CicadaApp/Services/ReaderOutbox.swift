import CryptoKit
import Foundation

/// G181 phase 3 — what the Mac's readers could not deliver to the server, kept on this Mac until it answers again.
///
/// Only in server mode (`ServerConnection.isServer`): with a backend on this Mac a failed post is retried by the reader
/// itself, as before. The readers keep their own cursors and advance them only on success, so the outbox is a faster
/// path, never the only one: when the server comes back the waiting posts go first (oldest first), and the readers'
/// next pass re-sends anything newer — the server's dedup (`episode_staging`'s hash, each reader's index) makes a resend
/// harmless.
///
/// `$CICADA_HOME/spool/app/` (0700), one JSON file per post (0600, written atomically) — the twin of the hooks' spool
/// (`api/hooks/hook_spool.py`), with the same keep/drop rule: no answer, 401/403, 409 and 5xx wait; 400/404/405/413/422
/// can never land and are dropped. An entry is named by what it is (route, memory and body hashed), so a reader that
/// posts the same bytes again while the server is away (an unchanged bookmarks file at every look) keeps one entry,
/// and different bytes on one route (two browsers, two conversations) each wait, in order. Bounded by count, bytes and
/// age; the oldest go first. Nothing here holds a token — the request is signed when it is sent.
actor ReaderOutbox {
    struct Entry: Codable, Equatable, Sendable {
        var v = 1
        let method: String
        let path: String
        let body: Data
        /// The `X-Cicada-Bank` value the original request carried: a post is never re-filed into another memory.
        let bank: String?
        let queuedAt: Date
    }

    struct FlushResult: Equatable, Sendable {
        var sent = 0
        var dropped = 0
        var waiting = 0
    }

    /// Statuses a resend can never fix (`hook_client.FINAL_STATUSES`).
    static let finalStatuses: Set<Int> = [400, 404, 405, 413, 422]
    static let maxEntries = 200
    static let maxBytes = 64 * 1024 * 1024
    static let maxAge: TimeInterval = 7 * 24 * 3600

    /// The reader routes that queue, by path (a preview never does): each posts bytes only this Mac can read.
    static let routes: [String] = [
        "/sources/sync-bookmarks",
        "/sources/sync-safari-tabs",
        "/sources/sync-notes",
        "/sources/folders/",
        "/sources/calendar-local/sync",
        "/sources/contacts-local/sync",
        "/sources/tab-groups/sync",
        "/sources/watch-history/sync",
        "/sources/messages/sync",
        "/capture/local-source/wispr-flow",
    ]

    /// Whether a post to `path` may wait here: a reader's post of bytes, never a preview or a read-only look.
    static func queues(_ path: String) -> Bool {
        if path.contains("preview=true") { return false }
        let bare = path.split(separator: "?", maxSplits: 1).first.map(String.init) ?? path
        if bare.hasPrefix("/sources/folders/") { return bare.hasSuffix("/sync") }
        return routes.contains(bare)
    }

    let folder: URL
    private let now: @Sendable () -> Date
    private var flushing = false

    init(folder: URL, now: @escaping @Sendable () -> Date = { Date() }) {
        self.folder = folder
        self.now = now
    }

    static func folder(cicadaHome: URL) -> URL {
        cicadaHome.appendingPathComponent("spool/app", isDirectory: true)
    }

    private func ensureFolder() throws {
        let fm = FileManager.default
        try fm.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try? fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: folder.path)
    }

    private func name(for entry: Entry) -> String {
        var key = Data("\(entry.method)\u{0}\(entry.path)\u{0}\(entry.bank ?? "")\u{0}".utf8)
        key.append(entry.body)
        return "p-" + SHA256.hash(data: key).prefix(16).map { String(format: "%02x", $0) }.joined() + ".json"
    }

    /// Keep one post. Returns false when it is not a reader's post (nothing was written).
    @discardableResult
    func put(method: String, path: String, body: Data, bank: String?) throws -> Bool {
        guard Self.queues(path) else { return false }
        try ensureFolder()
        let entry = Entry(method: method, path: path, body: body, bank: bank, queuedAt: now())
        let target = folder.appendingPathComponent(name(for: entry))
        let staging = folder.appendingPathComponent(".\(target.lastPathComponent).\(UUID().uuidString.prefix(6)).tmp")
        let data = try JSONEncoder().encode(entry)
        guard FileManager.default.createFile(atPath: staging.path, contents: data,
                                             attributes: [.posixPermissions: 0o600]) else {
            throw CocoaError(.fileWriteUnknown)
        }
        if FileManager.default.fileExists(atPath: target.path) {
            _ = try FileManager.default.replaceItemAt(target, withItemAt: staging)
        } else {
            try FileManager.default.moveItem(at: staging, to: target)
        }
        trim()
        return true
    }

    /// Waiting posts, oldest first, each with its file.
    func entries() -> [(file: URL, entry: Entry)] {
        let files = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        let decoder = JSONDecoder()
        return files.filter { $0.pathExtension == "json" && !$0.lastPathComponent.hasPrefix(".") }
            .compactMap { file in
                guard let data = try? Data(contentsOf: file), let entry = try? decoder.decode(Entry.self, from: data) else {
                    try? FileManager.default.removeItem(at: file)  // unreadable: never resent, never kept forever
                    return nil
                }
                return (file, entry)
            }
            .sorted { $0.entry.queuedAt < $1.entry.queuedAt }
    }

    func count() -> Int { entries().count }

    /// Whether a post `matches` still waits (the APIClient asks before sending a newer one on the same route).
    func has(where matches: (Entry) -> Bool) -> Bool { entries().contains { matches($0.entry) } }

    /// Past the bounds the oldest go first: too old, then too many, then too large.
    private func trim() {
        var list = entries()
        let cutoff = now().addingTimeInterval(-Self.maxAge)
        for item in list where item.entry.queuedAt < cutoff { try? FileManager.default.removeItem(at: item.file) }
        list.removeAll { $0.entry.queuedAt < cutoff }
        var bytes = list.reduce(0) { $0 + $1.entry.body.count }
        while !list.isEmpty && (list.count > Self.maxEntries || bytes > Self.maxBytes) {
            let oldest = list.removeFirst()
            bytes -= oldest.entry.body.count
            try? FileManager.default.removeItem(at: oldest.file)
        }
    }

    /// Answers about the server or this device, not one post: every later post would get the same, so a flush stops.
    static let stopsAll: Set<Int> = [401, 403]

    /// Send what waits, oldest first. No answer (the server is still away) or a refused token stops the flush. Any
    /// other answer that does not land — a 409 for a memory that is not the active one, a 5xx — is about that post:
    /// it waits, kept, and so does every newer post on its route and memory (a snapshot never overtakes an older one),
    /// but the other memories' and routes' posts still go (owner decision 6, 2026-10-16: a refused post for another
    /// memory never blocks the active memory's). `send` answers the HTTP status, or nil when no answer came. One
    /// flush at a time. `matches` narrows it to one route's posts (the APIClient sends those before a newer post on
    /// that route).
    func flush(where matches: @Sendable (Entry) -> Bool = { _ in true },
               send: @Sendable (Entry) async -> Int?) async -> FlushResult {
        guard !flushing else { return FlushResult(waiting: count()) }
        flushing = true
        defer { flushing = false }
        trim()
        var result = FlushResult()
        var held: Set<String> = []
        for item in entries() where matches(item.entry) {
            let lane = Self.lane(item.entry)
            if held.contains(lane) { continue }
            let status = await send(item.entry)
            if let status, (200...299).contains(status) {
                try? FileManager.default.removeItem(at: item.file)
                result.sent += 1
            } else if let status, Self.finalStatuses.contains(status) {
                try? FileManager.default.removeItem(at: item.file)
                result.dropped += 1
            } else if let status, !Self.stopsAll.contains(status) {
                held.insert(lane)
            } else {
                break
            }
        }
        result.waiting = count()
        return result
    }

    /// A post's lane: its route and its memory. Order holds within a lane; lanes never wait on each other.
    static func lane(_ entry: Entry) -> String {
        let bare = entry.path.split(separator: "?", maxSplits: 1).first.map(String.init) ?? entry.path
        return "\(entry.method) \(bare)\u{0}\(entry.bank ?? "")"
    }
}

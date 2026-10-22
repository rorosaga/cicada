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
///
/// **Each post names the memory it was read for** (G202, D2 of the 2026-10-22 two-device test): the server's address
/// (`base`) and the bank's id there (`bankId`, `X-Cicada-Bank-Id`) beside its name. A flush sends only the posts whose
/// address is the one this app uses now, and re-sends the id, so the server refuses (409 `bank_mismatch`) a post meant
/// for another of its memories; the rest wait, never dropped, and the Devices page counts them apart. A post written
/// before (`v` 1, no address) goes to whichever server this app uses, as it always did.
actor ReaderOutbox {
    struct Entry: Codable, Equatable, Sendable {
        var v = 2
        let method: String
        let path: String
        let body: Data
        /// The `X-Cicada-Bank` value the original request carried: a post is never re-filed into another memory.
        let bank: String?
        let queuedAt: Date
        /// The server it was read for (`APIClient.baseURL`); nil in a post written before G202.
        var base: String? = nil
        /// That bank's id on that server (`X-Cicada-Bank-Id`), when this app had heard it.
        var bankId: String? = nil
    }

    /// Two addresses name the same server: scheme and host without case, a trailing slash ignored — the hooks' rule
    /// (`hook_spool.same_server`).
    static func sameServer(_ a: String?, _ b: String?) -> Bool {
        guard let a, let b, !a.isEmpty, !b.isEmpty else { return false }
        return normalized(a) == normalized(b)
    }

    static func normalized(_ base: String) -> String {
        guard let parts = URLComponents(string: base.trimmingCharacters(in: .whitespaces)),
              let scheme = parts.scheme, let host = parts.host else { return base }
        var path = parts.path
        while path.hasSuffix("/") { path.removeLast() }
        let port = parts.port.map { ":\($0)" } ?? ""
        return "\(scheme.lowercased())://\(host.lowercased())\(port)\(path)"
    }

    /// Whether `entry` may go to `base`: one that names no server goes wherever this app points; one that does, only
    /// there. A nil `base` (a caller that does not filter) takes every post.
    static func isFor(_ entry: Entry, base: String?) -> Bool {
        guard let base, let meant = entry.base, !meant.isEmpty else { return true }
        return sameServer(meant, base)
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
        if let base = entry.base {
            key.append(Data("\(Self.normalized(base))\u{0}\(entry.bankId ?? "")\u{0}".utf8))
        }
        key.append(entry.body)
        return "p-" + SHA256.hash(data: key).prefix(16).map { String(format: "%02x", $0) }.joined() + ".json"
    }

    /// Keep one post. Returns false when it is not a reader's post (nothing was written).
    @discardableResult
    func put(method: String, path: String, body: Data, bank: String?, bankId: String? = nil,
             base: String? = nil) throws -> Bool {
        guard Self.queues(path) else { return false }
        try ensureFolder()
        let entry = Entry(method: method, path: path, body: body, bank: bank, queuedAt: now(), base: base,
                          bankId: bankId)
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

    /// What waits, by server: `here` for `base`, `elsewhere` for a server this app no longer uses (D3, G202). A nil
    /// `base` (This Mac) counts every post that names a server as elsewhere, and one that names none as here.
    func waiting(for base: String?) -> (here: Int, elsewhere: Int) {
        var here = 0, elsewhere = 0
        for item in entries() {
            if base == nil ? item.entry.base == nil : Self.isFor(item.entry, base: base) { here += 1 } else { elsewhere += 1 }
        }
        return (here, elsewhere)
    }

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
    /// `base`: only the posts read for that server go (D2, G202); the others wait for theirs, and `waiting` counts
    /// only `base`'s. nil sends every post (the behaviour before G202, kept for callers that do not filter).
    func flush(for base: String? = nil, where matches: @Sendable (Entry) -> Bool = { _ in true },
               send: @Sendable (Entry) async -> Int?) async -> FlushResult {
        guard !flushing else { return FlushResult(waiting: base == nil ? count() : waiting(for: base).here) }
        flushing = true
        defer { flushing = false }
        trim()
        var result = FlushResult()
        var held: Set<String> = []
        for item in entries() where Self.isFor(item.entry, base: base) && matches(item.entry) {
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
        result.waiting = base == nil ? count() : waiting(for: base).here
        return result
    }

    /// A post's lane: its route and its memory (server, bank name and id). Order holds within a lane; lanes never wait
    /// on each other.
    static func lane(_ entry: Entry) -> String {
        let bare = entry.path.split(separator: "?", maxSplits: 1).first.map(String.init) ?? entry.path
        let server = entry.base.map(normalized) ?? ""
        return "\(entry.method) \(bare)\u{0}\(entry.bank ?? "")\u{0}\(server)\u{0}\(entry.bankId ?? "")"
    }
}

/// D3 (G202) — what the hooks on this Mac left waiting (`$CICADA_HOME/spool/capture`, `api/hooks/hook_spool.py`):
/// counted by the server each capture was meant for, never read beyond that. The app never sends these; a hook's
/// next firing, an agent's next call or `cicada status` does.
enum HookSpool {
    static func folder(cicadaHome: URL) -> URL {
        cicadaHome.appendingPathComponent("spool/capture", isDirectory: true)
    }

    /// `here`: captures for `base` (a capture that names no server counts here on a server, elsewhere on This Mac);
    /// `elsewhere`: for a server this Mac no longer uses.
    static func waiting(cicadaHome: URL, base: String?) -> (here: Int, elsewhere: Int) {
        let files = (try? FileManager.default.contentsOfDirectory(at: folder(cicadaHome: cicadaHome),
                                                                  includingPropertiesForKeys: nil)) ?? []
        var here = 0, elsewhere = 0
        for file in files where file.pathExtension == "json" && !file.lastPathComponent.hasPrefix(".") {
            guard let data = try? Data(contentsOf: file),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            let meant = (object["target"] as? [String: Any])?["base"] as? String
            if let base, meant == nil || ReaderOutbox.sameServer(meant, base) { here += 1 } else { elsewhere += 1 }
        }
        return (here, elsewhere)
    }
}

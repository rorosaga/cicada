import Foundation

/// Disk persistence for Store snapshots — disposable cache, versioned envelope.
actor SnapshotCache {
    /// Bump this whenever a cached payload gains a field the UI *reads*, in the
    /// same change that adds the field — the disk cache is the third half of
    /// CLAUDE.md's "ship the ETag and its client mapping together" rule.
    ///
    /// Why it is load-bearing (final review, finding 2): a hydrate restores the
    /// payload **and its etag**, so the next refresh sends `If-None-Match`,
    /// takes a 304, and keeps the old body. A field added since that body was
    /// written therefore stays at its decode default until some unrelated bank
    /// write moves the server's etag. Version 2 is `SourceOverview.activity`
    /// (G125 v3): a pre-`activity` payload decodes fine (`[:]`), still passes
    /// `memorySourceRows`' `episodes > 0` filter, and renders a flat sparkline
    /// plus "0 of the last 4 weeks had captures" beside a count line reading
    /// "312 captured" — the page contradicting itself. Dropping the envelope
    /// costs exactly one cold render on upgrade, which is what this field is
    /// for.
    ///
    /// Nothing pins the value: `load`'s own `env.schema == Self.schema` guard
    /// is its only reader, and a mismatch is a cache miss, not an error.
    static let schema = 2
    private struct Envelope<T: Codable>: Codable { let schema: Int; let etag: String?; let savedAt: Date; let payload: T }

    private let root: URL
    private var pending: [String: Task<Void, Never>] = [:]
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cicada/cache", isDirectory: true)
    }

    private func url(_ domain: SyncDomain, bank: String) -> URL {
        let safe = bank.replacingOccurrences(of: "/", with: "_")
        return root.appendingPathComponent(safe, isDirectory: true).appendingPathComponent("\(domain.rawValue).json")
    }

    func load<T: Codable>(_ domain: SyncDomain, bank: String, as: T.Type) -> (value: T, etag: String?)? {
        guard let data = try? Data(contentsOf: url(domain, bank: bank)),
              let env = try? decoder.decode(Envelope<T>.self, from: data),
              env.schema == Self.schema else { return nil }
        return (env.payload, env.etag)
    }

    func save<T: Codable>(_ value: T, etag: String?, domain: SyncDomain, bank: String) {
        let key = "\(bank)/\(domain.rawValue)"
        pending[key]?.cancel()
        let env = Envelope(schema: Self.schema, etag: etag, savedAt: Date(), payload: value)
        guard let data = try? encoder.encode(env) else { return }
        let target = url(domain, bank: bank)
        pending[key] = Task { [target] in
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            try? FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? data.write(to: target, options: .atomic)
        }
    }

    func flush() async {
        for (_, task) in pending { _ = await task.value }
        pending.removeAll()
    }

    func clear(bank: String) {
        for (key, task) in pending where key.hasPrefix("\(bank)/") { task.cancel(); pending[key] = nil }
        try? FileManager.default.removeItem(at: root.appendingPathComponent(bank.replacingOccurrences(of: "/", with: "_")))
    }
}

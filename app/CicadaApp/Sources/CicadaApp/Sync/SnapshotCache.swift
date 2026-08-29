import Foundation

/// Disk persistence for Store snapshots — disposable cache, versioned envelope.
actor SnapshotCache {
    static let schema = 1
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

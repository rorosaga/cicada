import AppKit
import Foundation

/// Per-bank disk + memory cache for entity logos (G59).
///
/// Order: memory → `~/Library/Application Support/Cicada/logos/<bank>/<id>` →
/// `GET /entities/{id}/logo`. A 404 (no logo for this entity) is remembered in
/// memory as a negative result so a graph full of concept nodes doesn't
/// re-ask on every scroll; negatives are **not** written to disk, so a restart
/// picks up whatever the Sleep cycle warmed in the meantime.
///
/// Concurrent callers for the same entity share one fetch: the actor suspends
/// across the network `await`, so without an in-flight map a second caller
/// (the inbox row and the detail card for the same entity render together)
/// would miss the memory cache and issue a second `GET`, running the server's
/// whole three-rung ladder twice.
actor LogoStore {
    static let shared = LogoStore()

    typealias Fetcher = @Sendable (String) async throws -> Data?

    private var memory: [String: NSImage] = [:]
    private var misses: Set<String> = []
    private var inFlight: [String: Task<NSImage?, Never>] = [:]
    private let root: URL
    private let fetch: Fetcher

    init(root: URL? = nil, fetch: @escaping Fetcher = { try await APIClient.shared.fetchEntityLogo(id: $0) }) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cicada/logos", isDirectory: true)
        self.fetch = fetch
    }

    private func key(_ entityId: String, _ bank: String) -> String { "\(bank)/\(entityId)" }

    private func fileURL(_ entityId: String, _ bank: String) -> URL {
        let safeBank = bank.replacingOccurrences(of: "/", with: "_")
        let safeId = entityId.replacingOccurrences(of: "/", with: "_")
        return root.appendingPathComponent(safeBank, isDirectory: true)
            .appendingPathComponent("\(safeId).img")
    }

    func image(entityId: String, bank: String) async -> NSImage? {
        guard !entityId.isEmpty else { return nil }
        let k = key(entityId, bank)
        if let hit = memory[k] { return hit }
        if misses.contains(k) { return nil }

        let url = fileURL(entityId, bank)
        if let data = try? Data(contentsOf: url), let image = NSImage(data: data) {
            memory[k] = image
            return image
        }

        if let running = inFlight[k] { return await running.value }
        let task = Task<NSImage?, Never> { await self.performFetch(key: k, entityId: entityId, url: url) }
        inFlight[k] = task
        let image = await task.value
        if inFlight[k] == task { inFlight[k] = nil }
        return image
    }

    private func performFetch(key k: String, entityId: String, url: URL) async -> NSImage? {
        let data: Data?
        do {
            data = try await fetch(entityId)
        } catch {
            return nil  // transient: don't poison the cache with a network blip
        }
        guard let data, let image = NSImage(data: data) else {
            misses.insert(k)
            return nil
        }
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
        memory[k] = image
        return image
    }

    /// Base64 `data:` URL for the graph canvas (Task 11), which cannot fetch
    /// through the bearer-authenticated API from inside the WKWebView.
    func dataURL(entityId: String, bank: String) async -> String? {
        guard let image = await image(entityId: entityId, bank: bank),
              let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:])
        else { return nil }
        return "data:image/png;base64," + png.base64EncodedString()
    }

    /// Drop everything for one bank (bank switch, or a manual refresh).
    func clear(bank: String) {
        let prefix = "\(bank)/"
        memory = memory.filter { !$0.key.hasPrefix(prefix) }
        misses = misses.filter { !$0.hasPrefix(prefix) }
        for (key, task) in inFlight where key.hasPrefix(prefix) {
            task.cancel()
            inFlight[key] = nil
        }
    }
}

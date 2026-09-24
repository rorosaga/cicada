import AppKit
import CryptoKit
import Foundation

/// C11 (G146 plan R-PE11) — the pictures `LogoStore` does not hold: an uploaded or Contacts picture
/// (`/entities/{id}/picture?v=…`, with the bearer) and a media page's thumbnail (the provider's https URL, never with
/// the bearer — R-PE6). Keyed by the URL itself: `v=` is the bytes' own hash, so a new picture is a new key and nothing
/// is ever stale. Memory → `~/Library/Application Support/Cicada/pictures/<bank>/` → the network, one fetch per key in
/// flight, misses remembered in memory only (a restart re-asks) — `LogoStore`'s pattern.
actor PictureStore {
    static let shared = PictureStore()

    typealias Fetcher = @Sendable (PictureURL) async throws -> Data?

    /// A thumbnail is a preview, not an archive: anything bigger is refused, not decoded.
    static let maxExternalBytes = 4 * 1024 * 1024

    private var memory: [String: NSImage] = [:]
    private var misses: Set<String> = []
    private var inFlight: [String: Task<NSImage?, Never>] = [:]
    private let root: URL
    private let fetch: Fetcher

    init(root: URL? = nil, fetch: @escaping Fetcher = { try await PictureStore.defaultFetch($0) }) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cicada/pictures", isDirectory: true)
        self.fetch = fetch
    }

    private func key(_ url: PictureURL, _ bank: String) -> String { "\(bank)|\(url.cacheKey)" }

    private func fileURL(_ key: String, bank: String) -> URL {
        let digest = SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
        return root.appendingPathComponent(bank.replacingOccurrences(of: "/", with: "_"), isDirectory: true)
            .appendingPathComponent("\(digest.prefix(32)).img")
    }

    func image(_ url: PictureURL, bank: String) async -> NSImage? {
        let k = key(url, bank)
        if let hit = memory[k] { return hit }
        if misses.contains(k) { return nil }
        let file = fileURL(k, bank: bank)
        if let data = try? Data(contentsOf: file), let image = NSImage(data: data) {
            memory[k] = image
            return image
        }
        if let running = inFlight[k] { return await running.value }
        let task = Task<NSImage?, Never> { await self.load(url, key: k, file: file) }
        inFlight[k] = task
        let image = await task.value
        if inFlight[k] == task { inFlight[k] = nil }
        return image
    }

    private func load(_ url: PictureURL, key k: String, file: URL) async -> NSImage? {
        let data: Data?
        do {
            data = try await fetch(url)
        } catch {
            return nil   // transient: a network blip never poisons the cache
        }
        guard let data, let image = NSImage(data: data) else {
            misses.insert(k)
            return nil
        }
        store(data, image: image, key: k, file: file)
        return image
    }

    /// R-PE10 — an upload's own bytes under the URL the server will answer, so the new picture never re-downloads.
    func prime(_ url: PictureURL, bank: String, data: Data) {
        guard let image = NSImage(data: data) else { return }
        let k = key(url, bank)
        misses.remove(k)
        store(data, image: image, key: k, file: fileURL(k, bank: bank))
    }

    private func store(_ data: Data, image: NSImage, key k: String, file: URL) {
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: file, options: .atomic)
        memory[k] = image
    }

    /// A bank switch forgets what is in memory for that bank (`LogoStore.clear`'s rule; the disk copy is keyed by URL).
    func clear(bank: String) {
        let prefix = "\(bank)|"
        memory = memory.filter { !$0.key.hasPrefix(prefix) }
        misses = misses.filter { !$0.hasPrefix(prefix) }
        for (k, task) in inFlight where k.hasPrefix(prefix) {
            task.cancel()
            inFlight[k] = nil
        }
    }

    static func defaultFetch(_ url: PictureURL) async throws -> Data? {
        switch url {
        case .api(let path):
            return try await APIClient.shared.fetchPictureBytes(path: path)
        case .external(let remote):
            let (data, response) = try await externalSession.data(for: externalRequest(remote))
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  (http.value(forHTTPHeaderField: "Content-Type") ?? "").lowercased().hasPrefix("image/"),
                  data.count <= maxExternalBytes else { return nil }
            return data
        }
    }

    /// R-PE6 — a provider's thumbnail is asked for with nothing of Cicada's: no bearer, no cookies, no cache.
    static func externalRequest(_ url: URL) -> URLRequest {
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.httpShouldHandleCookies = false
        return request
    }

    private static let externalSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        return URLSession(configuration: config)
    }()
}

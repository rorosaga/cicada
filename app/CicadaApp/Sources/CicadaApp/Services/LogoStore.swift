import AppKit
import Foundation

/// Per-bank disk + memory cache for entity logos (G59).
///
/// Order: memory → `~/Library/Application Support/Cicada/logos/<bank>/<id>` →
/// `GET /entities/{id}/logo`. A 404 (no logo for this entity) is remembered in
/// memory as a negative result so a graph full of concept nodes doesn't
/// re-ask on every scroll; negatives are **not** written to disk, so a restart
/// picks up whatever the Sleep cycle warmed in the meantime.
actor LogoStore {
    static let shared = LogoStore()

    private var memory: [String: NSImage] = [:]
    private var misses: Set<String> = []
    private let root: URL

    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cicada/logos", isDirectory: true)
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

        let data: Data?
        do {
            data = try await APIClient.shared.fetchEntityLogo(id: entityId)
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
    }
}

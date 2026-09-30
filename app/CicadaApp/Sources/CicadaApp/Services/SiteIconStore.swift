import AppKit

/// G166 — the favicons of the sites Settings → Reading the web lists. They come from `GET /reading/sites/{site}/icon`
/// (the icon service, told the site's name; the site itself is never contacted) and are kept in memory per bank, so a
/// list that redraws never asks again. A 404 is "no icon": the row draws its own mark. Nothing is written to disk.
actor SiteIconStore {
    static let shared = SiteIconStore()

    typealias Fetcher = @Sendable (String) async throws -> Data?

    private enum Answer { case image(NSImage), none, transient }

    private var images: [String: NSImage] = [:]
    private var misses: Set<String> = []
    private var inFlight: [String: Task<Answer, Never>] = [:]
    /// G61 S3-b — a source row's mark is asked of the page that lists the site (`GET /entities/{id}/sources/icon/{site}`),
    /// which serves only a trusted site of THAT page; `(entity, site)`.
    typealias EntityFetcher = @Sendable (String, String) async throws -> Data?

    private let fetch: Fetcher
    private let fetchForEntity: EntityFetcher

    init(fetch: @escaping Fetcher = { try await APIClient.shared.fetchSiteIcon(site: $0) },
         fetchForEntity: @escaping EntityFetcher = { try await APIClient.shared.fetchEntitySourceIcon(entityId: $0, site: $1) }) {
        self.fetch = fetch
        self.fetchForEntity = fetchForEntity
    }

    private func key(_ site: String, _ bank: String, _ entity: String? = nil) -> String {
        entity.map { "\(bank)|\(site)|\($0)" } ?? "\(bank)|\(site)"
    }

    /// `entity` set: the icon of a site a source on that page names; nil: a Settings/Feed site (the surfaced list).
    func image(site: String, bank: String, entity: String? = nil) async -> NSImage? {
        let k = key(site, bank, entity)
        if let hit = images[k] { return hit }
        if misses.contains(k) { return nil }
        if let running = inFlight[k], case .image(let image) = await running.value { return image }
        if inFlight[k] != nil { return nil }
        let fetch = self.fetch
        let fetchForEntity = self.fetchForEntity
        let task = Task<Answer, Never> {
            do {
                let bytes = if let entity { try await fetchForEntity(entity, site) } else { try await fetch(site) }
                guard let data = bytes, let image = NSImage(data: data) else { return .none }
                return .image(image)
            } catch {
                return .transient   // a network blip never poisons the cache
            }
        }
        inFlight[k] = task
        let answer = await task.value
        inFlight[k] = nil
        switch answer {
        case .image(let image): images[k] = image; return image
        case .none: misses.insert(k); return nil
        case .transient: return nil
        }
    }

    /// A bank switch forgets what is held for that bank (the list is per bank).
    func clear(bank: String) {
        let prefix = "\(bank)|"
        images = images.filter { !$0.key.hasPrefix(prefix) }
        misses = misses.filter { !$0.hasPrefix(prefix) }
    }
}

import AppKit

/// G166 — the favicons of the sites Settings → Reading the web lists — and, since 2026-10-19/20, every saved link's
/// own site icon, at most `maxConcurrent` requests at a time. They come from `GET /reading/sites/{site}/icon`
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

    /// Owner ruling 2026-10-19 — a saved link's row asks its own site's icon by the link's media id
    /// (`GET /sources/saved/{id}/site-icon`); the answer is kept per site, so one site's rows ask once.
    typealias SavedFetcher = @Sendable (String) async throws -> Data?

    /// Owner 2026-10-20 — the same icon for a saved link Sleep has not made a page of yet, by its episode's id
    /// (`GET /sources/saved/episodes/{id}/site-icon`). Kept under the same per-site key as `SavedFetcher`'s answer.
    typealias SavedEpisodeFetcher = @Sendable (String) async throws -> Data?

    /// How a saved link's own icon is asked: by its media page's id, or — before Sleep made the page — its episode's.
    enum SavedRef: Equatable, Sendable {
        case media(String)
        case episode(String)

        /// The id a miss is remembered under.
        var tag: String {
            switch self {
            case .media(let id): "media:\(id)"
            case .episode(let id): "episode:\(id)"
            }
        }
    }

    /// At most this many icon requests are on the wire at once (owner 2026-10-20: a 500-row list never bursts). Rows
    /// ask as they appear (a lazy stack), answers are kept per site, and a row that scrolled away before its turn
    /// asks nothing.
    static let maxConcurrent = 4

    private let fetch: Fetcher
    private let fetchForEntity: EntityFetcher
    private let fetchForSaved: SavedFetcher
    private let fetchForSavedEpisode: SavedEpisodeFetcher
    private let maxConcurrent: Int
    private var running = 0
    private var waiters: [CheckedContinuation<Void, Never>] = []
    /// The most requests ever on the wire at once (tests read it).
    private(set) var peakRunning = 0

    init(fetch: @escaping Fetcher = { try await APIClient.shared.fetchSiteIcon(site: $0) },
         fetchForEntity: @escaping EntityFetcher = { try await APIClient.shared.fetchEntitySourceIcon(entityId: $0, site: $1) },
         fetchForSaved: @escaping SavedFetcher = { try await APIClient.shared.fetchSavedLinkSiteIcon(mediaEntityId: $0) },
         fetchForSavedEpisode: @escaping SavedEpisodeFetcher = {
             try await APIClient.shared.fetchSavedEpisodeSiteIcon(episodeId: $0)
         },
         maxConcurrent: Int = SiteIconStore.maxConcurrent) {
        self.fetch = fetch
        self.fetchForEntity = fetchForEntity
        self.fetchForSaved = fetchForSaved
        self.fetchForSavedEpisode = fetchForSavedEpisode
        self.maxConcurrent = max(1, maxConcurrent)
    }

    private func acquire() async {
        if running < maxConcurrent {
            running += 1
            peakRunning = max(peakRunning, running)
            return
        }
        // The slot is handed over by `release`, so `running` is unchanged when this resumes.
        await withCheckedContinuation { waiters.append($0) }
    }

    private func release() {
        if waiters.isEmpty { running -= 1 } else { waiters.removeFirst().resume() }
    }

    private func key(_ site: String, _ bank: String, _ entity: String? = nil, saved: Bool = false) -> String {
        if saved { return "\(bank)|\(site)|saved" }
        return entity.map { "\(bank)|\(site)|\($0)" } ?? "\(bank)|\(site)"
    }

    /// `entity` set: the icon of a site a source on that page names; `savedItem` set: a saved link's own site (asked of
    /// that site only, by the backend); neither: a Settings/Feed site (the surfaced list).
    func image(site: String, bank: String, entity: String? = nil, savedItem: String? = nil) async -> NSImage? {
        await image(site: site, bank: bank, entity: entity, saved: savedItem.map(SavedRef.media))
    }

    /// The one door every mark goes through. A saved link's icon is kept per site, whichever id asked it, so one
    /// site's rows — pages and waiting episodes alike — share it; a saved link's miss is kept per id (review of #372: a
    /// 404 for one id — a page the route refuses — never hides the icon another id of that site is served).
    func image(site: String, bank: String, entity: String? = nil, saved: SavedRef?) async -> NSImage? {
        let k = key(site, bank, entity, saved: saved != nil)
        let missKey = saved.map { "\(k)|\($0.tag)" } ?? k
        if let hit = images[k] { return hit }
        if misses.contains(missKey) { return nil }
        // A caller that joins a running request takes its answer. Once it resumes, the first caller may already have
        // cleared `inFlight`, so re-checking it would ask the same question again (2026-10-05).
        if let running = inFlight[k] { return await joined(running) }
        await acquire()
        // While this caller waited its turn the row may have gone (its `.task` cancelled) or another caller may have
        // asked the same site: either way nothing new is asked.
        if Task.isCancelled || images[k] != nil || misses.contains(missKey) || inFlight[k] != nil {
            release()
            if let hit = images[k] { return hit }
            if let running = inFlight[k] { return await joined(running) }
            return nil
        }
        let fetch = self.fetch
        let fetchForEntity = self.fetchForEntity
        let fetchForSaved = self.fetchForSaved
        let fetchForSavedEpisode = self.fetchForSavedEpisode
        let task = Task<Answer, Never> {
            do {
                let bytes: Data? = switch saved {
                case .media(let id): try await fetchForSaved(id)
                case .episode(let id): try await fetchForSavedEpisode(id)
                case nil: if let entity { try await fetchForEntity(entity, site) } else { try await fetch(site) }
                }
                guard let data = bytes, let image = NSImage(data: data) else { return .none }
                return .image(image)
            } catch {
                return .transient   // a network blip never poisons the cache
            }
        }
        inFlight[k] = task
        let answer = await task.value
        inFlight[k] = nil
        release()
        switch answer {
        case .image(let image): images[k] = image; return image
        case .none: misses.insert(missKey); return nil
        case .transient: return nil
        }
    }

    private func joined(_ running: Task<Answer, Never>) async -> NSImage? {
        if case .image(let image) = await running.value { return image }
        return nil
    }

    /// G61 S3-b — a page's source icons asked before a site was trusted answered 404 and were remembered as misses;
    /// when a source write lands on that page they are asked again (the row would otherwise keep the plain glyph until
    /// relaunch).
    func forget(entity: String) {
        let suffix = "|\(entity)"
        misses = misses.filter { !$0.hasSuffix(suffix) }
        images = images.filter { !$0.key.hasSuffix(suffix) }
    }

    /// An offscreen render (a PR screenshot) hands a saved site's answer in, so nothing is asked of a backend.
    func prime(_ image: NSImage, savedSite site: String, bank: String) {
        images[key(site, bank, saved: true)] = image
    }

    /// A bank switch forgets what is held for that bank (the list is per bank).
    func clear(bank: String) {
        let prefix = "\(bank)|"
        images = images.filter { !$0.key.hasPrefix(prefix) }
        misses = misses.filter { !$0.hasPrefix(prefix) }
    }
}

import Foundation
import Observation

/// Every way a file reaches Cicada (design §5.1). The seams part b and Track Z
/// use are here from day one: `.welcome`/`.home`/`.onboardingRow` (part b),
/// `.sleepRoom` (Track Z feeds the worm through `accept(urls:from:)`),
/// `.reminder` (part b's export reminders).
enum IntakeOrigin: Hashable {
    case welcome, home, windowDrop, dock, menuBar, sleepRoom
    case emptyState(AppTab)
    case feedPlus(ChatVendor?)
    case fileMenu
    case reminder(ChatVendor)
    case onboardingRow

    /// `.feedPlus` renders inside the `+` sheet; every other origin raises the
    /// window overlay (R-IA20).
    var host: IntakeHost {
        if case .feedPlus = self { return .feedPlus }
        return .overlay
    }
}

enum IntakeHost: Equatable { case overlay, feedPlus }

enum IntakeTarget: Hashable {
    case active
    case bank(String)
    case newBank(String)
}

struct IntakeProgress: Equatable {
    var total: Int
    var staged: Int?
}

enum IntakePhase: Equatable {
    case idle
    case reading([String])
    case preview(IntakePreview)
    case importing(IntakeProgress)
    case done(IntakeOutcome)
    case failed(String)
}

/// What one drop holds, aggregated over its files (design §5.2's preview).
struct IntakePreview: Equatable {
    static let maxTitles = 5000

    var chatFiles: [URL] = []
    var savedFiles: [URL] = []
    var vendor: String?
    var origin: String?
    var platform: String?
    var counts = IntakeCounts()
    var dateFrom: String?
    var dateTo: String?
    var delta = IntakeDelta()
    var titles: [IntakeTitle] = []
    var titlesTruncated = false
    var skipped: [IntakeIgnored] = []
    var warnings: [String] = []

    /// Import N = new + grew, plus saved items (design §5.2).
    var importCount: Int { delta.new + delta.grown + counts.items }

    /// "Into: New memory…" — nothing is in a bank that does not exist yet.
    func assumingEmptyBank() -> IntakePreview {
        var p = self
        p.delta = IntakeDelta(new: delta.new + delta.grown + delta.unchanged)
        return p
    }

    static func aggregate(_ files: [IntakeFileSniff], capped: Bool) -> IntakePhase {
        var p = IntakePreview()
        var vendors = Set<String>(), origins = Set<String>()
        var unreadable: [IntakeIgnored] = []
        for f in files {
            let name = f.url.lastPathComponent
            guard let s = f.sniff else {
                unreadable.append(IntakeIgnored(name: name, reason: f.error ?? Copy.intakeUnreadable))
                continue
            }
            p.skipped += s.ignored
            p.warnings += s.warnings
            guard s.recognized else {
                if let reason = s.reason { unreadable.append(IntakeIgnored(name: name, reason: reason)) }
                continue
            }
            if s.kind == "saved" {
                p.savedFiles.append(f.url)
                p.counts = p.counts + IntakeCounts(items: s.counts.items)
                p.platform = p.platform ?? s.platform
                continue
            }
            p.chatFiles.append(f.url)
            if let v = s.vendor { vendors.insert(v) }
            if let o = s.origin { origins.insert(o) }
            p.counts = p.counts + s.counts
            p.delta = p.delta + s.delta
            if let from = s.dateRange?.from { p.dateFrom = min(p.dateFrom ?? from, from) }
            if let to = s.dateRange?.to { p.dateTo = max(p.dateTo ?? to, to) }
            p.titles += s.titles
            p.titlesTruncated = p.titlesTruncated || s.titlesTruncated
        }
        if p.chatFiles.isEmpty && p.savedFiles.isEmpty {
            return .failed(unreadable.first?.reason
                            ?? p.skipped.first.map { Copy.intakeSkipped($0.name, $0.reason) }
                            ?? Copy.intakeNothingReadable)
        }
        p.skipped += unreadable
        p.vendor = vendors.count == 1 ? vendors.first : nil
        p.origin = origins.count == 1 ? origins.first : nil
        p.titles.sort { ($0.date ?? "") > ($1.date ?? "") }
        if p.titles.count > maxTitles {
            p.titles = Array(p.titles.prefix(maxTitles))
            p.titlesTruncated = true
        }
        if capped { p.warnings.append(Copy.intakeCapped(IntakeRouter.maxFiles)) }
        return .preview(p)
    }
}

/// What landed — the done card's data (design §5.2).
struct IntakeOutcome: Equatable {
    var vendor: String?
    var origin: String?
    var created = 0
    var updated = 0
    var unchanged = 0
    var savedCreated = 0
    var dateFrom: String?
    var dateTo: String?
    var bank: String?
    var bankIsActive = true
    var failures: [String] = []

    var total: Int { created + updated + savedCreated }
    /// G87: an import into a bank Sleep does not read says so, with a Switch.
    var inactiveBank: String? { bankIsActive ? nil : bank }

    mutating func add(created: Int, updated: Int, unchanged: Int, response r: IntakeImportResponse) {
        self.created += created
        self.updated += updated
        self.unchanged += unchanged
        bank = r.bank
        bankIsActive = bankIsActive && r.active
        vendor = vendor ?? r.vendor
        origin = origin ?? r.origin
        if let from = r.dateRange?.from { dateFrom = min(dateFrom ?? from, from) }
        if let to = r.dateRange?.to { dateTo = max(dateTo ?? to, to) }
    }
}

/// The one import seam (R-IA20) — testable with a fake.
protocol IntakeAPI: Sendable {
    func sniffIntake(fileURL: URL, bank: String?) async throws -> IntakeSniff
    func importIntake(fileURL: URL, bank: String?) async throws -> IntakeImportResponse
    func intakeJob(id: String) async throws -> IntakeJobStatus
    func uploadSaved(fileURL: URL) async throws -> UploadResponse
}

/// Track I T5 (design §5.1, spec decision 13) — every way a file arrives goes
/// through here: sniff → preview → import → a done card that never closes on
/// its own. Before it, the upload overlay and the `+` sheet each had their own
/// pipeline, their own folder walk and their own idea of the mascot flag
/// (D5, D6). It owns:
///
/// - `Store.intakeInFlight`, through a counter of REQUESTS in flight — a Bool
///   two overlapping intakes cleared under each other (F4), and a preview left
///   open is not an intake landing (R-IA20);
/// - the generation token `AddSourceSheet` introduced (G71 H1), hoisted: a late
///   sniff never lands on a newer preview;
/// - the folder walk (`expand`), app-side because the app reads user folders
///   and the backend parses bytes; skipping `user.json` and friends is the
///   backend's job, reported by name.
@MainActor
@Observable
final class IntakeRouter {
    /// `nonisolated`: read by the pure `expand` and `IntakePreview.aggregate`.
    nonisolated static let maxFiles = 512
    static let pollInterval: Duration = .seconds(1)
    /// Everything either parser reads: the chat side (`json`, `html`, `zip`) and
    /// `media_ingestor.parse_upload`'s saved-content formats (design §5.1 names
    /// `.plist` — Safari's exported `Bookmarks.plist`).
    nonisolated static let exportExtensions: Set<String> = ["json", "html", "htm", "zip", "csv", "txt", "xml",
                                                            "rss", "atom", "opml", "plist"]

    private(set) var phase: IntakePhase = .idle
    private(set) var host: IntakeHost = .overlay
    private(set) var isOverlayPresented = false
    private(set) var target: IntakeTarget = .active
    private(set) var inFlight = 0

    @ObservationIgnored private let api: any IntakeAPI
    @ObservationIgnored private let sleep: @Sendable (Duration) async throws -> Void
    @ObservationIgnored private var store: Store?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private var files: [URL] = []
    @ObservationIgnored private var capped = false
    /// The last sniff's preview, for the importing line's noun and the Into
    /// picker's "new memory" delta.
    private(set) var sniffedPreview: IntakePreview?

    init(api: any IntakeAPI = APIClient.shared,
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }) {
        self.api = api
        self.sleep = sleep
    }

    /// Strong, like `BrowserWatcher.store` — the app owns both for its lifetime.
    func attach(store: Store) { self.store = store }

    var isImporting: Bool { if case .importing = phase { return true }; return false }
    var previewVendor: String? { sniffedPreview?.vendor }

    // MARK: Entry points

    /// No file yet — ⌘⇧I, the menu-bar item, a reminder: open the panel idle.
    func present(from origin: IntakeOrigin) {
        host = origin.host
        if host == .overlay { isOverlayPresented = true }
        if case .reading = phase { cancel() }
        if case .failed = phase { phase = .idle }
    }

    /// Files arrived. Public on purpose: Track Z's Sleep-room worm calls this
    /// with `.sleepRoom` (design §12 cross-track seam).
    func accept(urls: [URL], from origin: IntakeOrigin) {
        guard !isImporting else {
            store?.toast = Copy.intakeBusy
            return
        }
        host = origin.host
        if host == .overlay { isOverlayPresented = true }
        let expanded = Self.expand(urls)
        files = expanded.files
        capped = expanded.capped
        target = .active
        guard !files.isEmpty else {
            generation &+= 1
            phase = .failed(Copy.intakeNothingReadable)
            return
        }
        sniff()
    }

    /// The Into picker (G87). An existing bank re-sniffs, so the delta is that
    /// bank's; a new memory assumes everything is new.
    func retarget(_ newTarget: IntakeTarget) {
        guard case .preview = phase else { target = newTarget; return }
        target = newTarget
        switch newTarget {
        case .newBank:
            if let base = sniffedPreview { phase = .preview(base.assumingEmptyBank()) }
        case .active, .bank:
            sniff()
        }
    }

    // MARK: Sniff

    private var targetSlug: String? {
        if case .bank(let slug) = target { return slug }
        return nil
    }

    private func sniff() {
        generation &+= 1
        let gen = generation
        let files = self.files
        let bank = targetSlug
        let capped = self.capped
        phase = .reading(files.map(\.lastPathComponent))
        task?.cancel()
        task = Task { [weak self] in
            guard let self else { return }
            var results: [IntakeFileSniff] = []
            for url in files {
                guard gen == self.generation else { return }
                do {
                    let s = try await self.tracked { try await self.api.sniffIntake(fileURL: url, bank: bank) }
                    results.append(IntakeFileSniff(url: url, sniff: s))
                } catch {
                    results.append(IntakeFileSniff(url: url, error: AddSourceSheet.friendlyError(error)))
                }
            }
            guard gen == self.generation else { return }
            let next = IntakePreview.aggregate(results, capped: capped)
            if case .preview(let p) = next { self.sniffedPreview = p }
            self.phase = next
        }
    }

    // MARK: Import

    /// Import what the preview showed. A second tap while importing is a no-op
    /// (the M4 double-tap guard). `createBank` is the Into picker's "New memory…"
    /// (`BanksViewModel.create`), injected so the router needs no view model.
    func confirm(createBank: @escaping (String) async -> String?) {
        guard case .preview(let preview) = phase else { return }
        generation &+= 1
        let gen = generation
        let target = self.target
        phase = .importing(IntakeProgress(total: preview.importCount, staged: nil))
        task = Task { [weak self] in
            guard let self else { return }
            var outcome = IntakeOutcome(vendor: preview.vendor, origin: preview.origin)
            var bank: String?
            switch target {
            case .active: bank = nil
            case .bank(let slug): bank = slug
            case .newBank(let name):
                guard let slug = await createBank(name) else {
                    self.phase = .failed(Copy.intakeCouldNotCreate(name))
                    return
                }
                bank = slug
            }
            for url in preview.chatFiles {
                do {
                    let r = try await self.tracked { try await self.api.importIntake(fileURL: url, bank: bank) }
                    if let job = r.job {
                        let status = try await self.follow(job, gen: gen)
                        outcome.add(created: status.created, updated: status.updated, unchanged: status.skipped, response: r)
                    } else {
                        outcome.add(created: r.episodesStaged, updated: r.episodesUpdated,
                                    unchanged: r.duplicatesSkipped, response: r)
                    }
                } catch {
                    outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
                }
            }
            for url in preview.savedFiles {
                do {
                    let r = try await self.tracked { try await self.api.uploadSaved(fileURL: url) }
                    outcome.savedCreated += r.episodesCreated
                    outcome.unchanged += r.duplicatesSkipped
                } catch {
                    outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
                }
            }
            await self.store?.refresh([.channels, .status, .sources, .sourcesOverview, .graph, .banks])
            guard gen == self.generation else { return }
            if outcome.total == 0, outcome.unchanged == 0, let first = outcome.failures.first {
                self.phase = .failed(first)
            } else {
                self.phase = .done(outcome)
            }
        }
    }

    /// Polls a background job until it reports done — whether or not the panel
    /// is visible (R-IA20). The count shown is only ever one the job reported.
    /// The WHOLE loop is one tracked request: tracking each poll alone would drop
    /// `Store.intakeInFlight` for the second between polls and make the Sleep
    /// page's worm flicker in and out of `.reading`.
    private func follow(_ job: IntakeJobRef, gen: Int) async throws -> IntakeJobStatus {
        try await tracked {
            var status = IntakeJobStatus(id: job.id, total: job.total)
            while !status.done {
                try await self.sleep(Self.pollInterval)
                status = try await self.api.intakeJob(id: job.id)
                if gen == self.generation, self.isImporting {
                    self.phase = .importing(IntakeProgress(total: status.total, staged: status.staged))
                }
            }
            if let error = status.error { throw IntakeRouterError.job(error) }
            return status
        }
    }

    /// Part b's Welcome Start path: import dropped files without opening the
    /// panel; the counter still owns the flag.
    func commit(urls: [URL], from origin: IntakeOrigin) async -> IntakeOutcome {
        var outcome = IntakeOutcome()
        for url in Self.expand(urls).files {
            do {
                let r = try await tracked { try await api.importIntake(fileURL: url, bank: nil) }
                if let job = r.job {
                    let status = try await follow(job, gen: -1)
                    outcome.add(created: status.created, updated: status.updated, unchanged: status.skipped, response: r)
                } else {
                    outcome.add(created: r.episodesStaged, updated: r.episodesUpdated, unchanged: r.duplicatesSkipped, response: r)
                }
            } catch {
                outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
            }
        }
        await store?.refresh([.channels, .status, .sources, .sourcesOverview, .graph, .banks])
        return outcome
    }

    // MARK: Leaving

    /// Esc / Cancel: stops a sniff in flight (the generation drops its answer).
    /// Nothing can be un-imported, so an import in flight is never cancelled.
    func cancel() {
        guard !isImporting else { return }
        generation &+= 1
        task?.cancel()
        phase = .idle
        sniffedPreview = nil
        // The Into picker reads `target`; a cancelled "New memory" must not
        // outlive the preview it was chosen for (final review, finding 3).
        target = .active
    }

    /// Close the overlay. An import keeps running and reopens where it was.
    func dismiss() {
        if !isImporting, case .done = phase { phase = .idle }
        if !isImporting { cancel() }
        isOverlayPresented = false
    }

    /// The done card's Done — the ONLY way it closes (design §5.2).
    func finish() {
        phase = .idle
        sniffedPreview = nil
        target = .active
        isOverlayPresented = false
    }

    // MARK: Plumbing

    private func tracked<T>(_ work: () async throws -> T) async rethrows -> T {
        inFlight += 1
        store?.intakeInFlight = true
        defer {
            inFlight -= 1
            store?.intakeInFlight = inFlight > 0
        }
        return try await work()
    }

    /// Folders walked, hidden files and `__MACOSX` skipped, export-shaped
    /// extensions kept, capped at `maxFiles` with a stated warning.
    nonisolated static func expand(_ urls: [URL], fileManager fm: FileManager = .default) -> (files: [URL], capped: Bool) {
        var out: [URL] = []
        func consider(_ url: URL) {
            guard !url.lastPathComponent.hasPrefix("."), !url.pathComponents.contains("__MACOSX") else { return }
            if exportExtensions.contains(url.pathExtension.lowercased()) { out.append(url) }
        }
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                let walker = fm.enumerator(at: url, includingPropertiesForKeys: nil,
                                           options: [.skipsHiddenFiles, .skipsPackageDescendants])
                while let next = walker?.nextObject() as? URL, out.count <= maxFiles { consider(next) }
            } else {
                consider(url)
            }
            if out.count > maxFiles { break }
        }
        out.sort { $0.path < $1.path }
        return (Array(out.prefix(maxFiles)), out.count > maxFiles)
    }
}

enum IntakeRouterError: Error, LocalizedError {
    case job(String)
    var errorDescription: String? { if case .job(let why) = self { return why }; return nil }
}

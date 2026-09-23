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

extension IntakeOrigin {
    /// A door that tells its own outcome — the Sleep room's worm (Track Z
    /// R-Z10, Z-B6). The router neither raises the overlay nor toasts for a
    /// refusal or a busy router there: the worm's line says it, once.
    var answersInPlace: Bool { self == .sleepRoom }
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

/// What no door may import, whatever the file is (Track Z R-Z10, design §7.4,
/// Z-B5). Named for the worm that asked for it; enforced at every
/// `IntakeRouter` door (`feedGuard`), because the capture rail is not a
/// Sleep-page rule: transcripts under `~/.claude/` are read by the Stop hook's
/// endpoint and nowhere else, Codex's home is Codex's, and `~/.cicada` holds
/// the api token, `secrets.env` and the remote connectors' database — none of
/// it an export, all of it sniffable. The three pickers outside the router
/// (the Add-source walkthrough, its saved-content picker, Settings'
/// local-folder picker) check only the chosen item (`refusedRoot(of:)`); a
/// watched folder that CONTAINS a refused root is still walked — open (final
/// review, finding 3).
enum FeedRefusal: String, Equatable, CaseIterable {
    case claudeSessions, codexSessions, cicadaHome, unreadable

    /// The panel's words — every door but the room, which speaks for itself
    /// in the worm's voice (Z-B18).
    var panelText: String {
        switch self {
        case .claudeSessions: Copy.intakeRefusedClaude
        case .codexSessions: Copy.intakeRefusedCodex
        case .cicadaHome: Copy.intakeRefusedCicada
        case .unreadable: Copy.intakeNothingReadable
        }
    }
}

/// `accept`'s answer (Z-B6), so a door that speaks for itself can.
enum IntakeAcceptance: Equatable {
    case accepted
    case refused(FeedRefusal)
    /// An import is still landing; nothing about this drop was read.
    case busy
}

/// The guard's verdict: refused, or the files `expand` found — walked once,
/// and only after every dropped URL cleared the refused roots.
enum IntakeAdmission: Equatable {
    case refused(FeedRefusal)
    case admitted(files: [URL], capped: Bool)
}

struct WelcomeDrop: Identifiable, Equatable {
    let id: String
    let preview: IntakePreview
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
    /// A drop target nearer the pointer than the window has the drag (the
    /// Sleep room, Z-B8): the window's veil steps aside so that target's own
    /// cue — the worm's open mouth, its outline — is not under the scrim.
    private(set) var nearerDrop: IntakeOrigin?

    @ObservationIgnored private let api: any IntakeAPI
    @ObservationIgnored private let sleep: @Sendable (Duration) async throws -> Void
    /// Where the refused roots are resolved from (Z-B5) — injected so
    /// `FeedGuardTests` runs on a temporary home, never the person's.
    @ObservationIgnored private let home: URL
    @ObservationIgnored private let env: [String: String]
    @ObservationIgnored private var store: Store?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private var files: [URL] = []
    @ObservationIgnored private var capped = false
    /// The last sniff's preview, for the importing line's noun and the Into
    /// picker's "new memory" delta.
    private(set) var sniffedPreview: IntakePreview?

    /// Track I part b (R-IB15) — `ContentView` sets this while the Welcome shows:
    /// every arrival (window, Dock, menu bar, File → Import) is sniffed and staged
    /// as a ticked row there, never raised as an overlay hidden underneath, and
    /// nothing imports until Start commits it. Raising it clears an earlier
    /// Welcome's leftovers and adopts a sniff already on the overlay: a Dock open
    /// on a cold launch reaches `accept` before the gate has resolved the bank.
    var welcomeActive = false {
        didSet {
            guard welcomeActive, !oldValue else { return }
            welcomeDrops = []
            welcomeDropError = nil
            let adoptable: Bool
            switch phase {
            case .reading, .preview: adoptable = host == .overlay
            default: adoptable = false
            }
            guard adoptable, !files.isEmpty else { return }
            // `files` were admitted by `feedGuard` when the overlay took them.
            let pending = files, wasCapped = capped
            cancel()                      // the generation drops the overlay's answer
            isOverlayPresented = false
            stageForWelcome(pending, capped: wasCapped)
        }
    }
    private(set) var welcomeDrops: [WelcomeDrop] = []
    private(set) var welcomeDropError: String?
    /// ⌘⇧I and the menu bar while the Welcome shows: it opens its own file panel.
    private(set) var welcomeChooseRequest = 0
    /// Track I part b (R-IB22) — a sniff that recognised one vendor's chat export
    /// reports the vendor, so the app clears that vendor's export wait: the
    /// export someone was waiting for has arrived, whatever door it came in by.
    /// A closure, not state — nothing observes it.
    @ObservationIgnored var onVendorSniffed: ((String) -> Void)?

    init(api: any IntakeAPI = APIClient.shared,
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
         home: URL = FileManager.default.homeDirectoryForCurrentUser,
         env: [String: String] = ProcessInfo.processInfo.environment) {
        self.api = api
        self.sleep = sleep
        self.home = home
        self.env = env
    }

    /// Strong, like `BrowserWatcher.store` — the app owns both for its lifetime.
    func attach(store: Store) { self.store = store }

    var isImporting: Bool { if case .importing = phase { return true }; return false }
    var previewVendor: String? { sniffedPreview?.vendor }

    // MARK: Entry points

    /// No file yet — ⌘⇧I, the menu-bar item, a reminder: open the panel idle.
    func present(from origin: IntakeOrigin) {
        if welcomeActive { welcomeChooseRequest &+= 1; return }
        host = origin.host
        if host == .overlay { isOverlayPresented = true }
        if case .reading = phase { cancel() }
        if case .failed = phase { phase = .idle }
    }

    /// Files arrived. Public on purpose: Track Z's Sleep-room worm calls this
    /// with `.sleepRoom` (design §12 cross-track seam). Every door passes the
    /// same guard (Z-B5); the answer lets a door that speaks for itself do so
    /// (Z-B6) and is discardable everywhere else.
    @discardableResult
    func accept(urls: [URL], from origin: IntakeOrigin) -> IntakeAcceptance {
        guard !isImporting else {
            if !origin.answersInPlace { store?.toast = Copy.intakeBusy }
            return .busy
        }
        switch Self.feedGuard(urls: urls, home: home, env: env) {
        case .refused(let refusal):
            // The Welcome's drop zone says it (R-IB15) — after the same guard as
            // every other door (Z-B5): staging comes after the guard, never
            // instead of it, so a folder dropped on the Welcome is never walked
            // into `~/.claude`, `~/.codex` or `~/.cicada` (I-b final review,
            // findings 6 and 7).
            if welcomeActive {
                welcomeDropError = refusal.panelText
                return .refused(refusal)
            }
            guard !origin.answersInPlace else { return .refused(refusal) }
            host = origin.host
            if host == .overlay { isOverlayPresented = true }
            // As the old empty-drop path did: a refused drop resets the Into
            // picker too (final review, finding 3 — no "New memory" outlives
            // the drop it was chosen for).
            target = .active
            generation &+= 1
            phase = .failed(refusal.panelText)
            return .refused(refusal)
        case .admitted(let found, let wasCapped):
            if welcomeActive {
                stageForWelcome(found, capped: wasCapped)
                return .accepted
            }
            host = origin.host
            if host == .overlay { isOverlayPresented = true }
            files = found
            capped = wasCapped
            target = .active
            sniff()
            return .accepted
        }
    }

    /// Z-B8 — the room has the drag; the veil yields until it lets go.
    func claimDrop(_ origin: IntakeOrigin) {
        if nearerDrop != origin { nearerDrop = origin }
    }

    /// Only the claimant releases, so a late exit from one target never
    /// clears another's claim.
    func releaseDrop(_ origin: IntakeOrigin) {
        if nearerDrop == origin { nearerDrop = nil }
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
            if case .preview(let p) = next {
                self.sniffedPreview = p
                self.reportVendor(p)
            }
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

    /// Imports dropped chat files without opening the panel; the counter still
    /// owns the flag. Delegates to `commit(_ preview:from:)` — identical for its
    /// chat-only callers.
    func commit(urls: [URL], from origin: IntakeOrigin) async -> IntakeOutcome {
        // The same door as `accept` (Z-B5): a refused root is never walked —
        // checked here, before the delegation, because `commit(_ preview:)`
        // trusts files a guarded door already admitted.
        switch Self.feedGuard(urls: urls, home: home, env: env) {
        case .refused(let refusal):
            var outcome = IntakeOutcome()
            outcome.failures.append(refusal.panelText)
            return outcome
        case .admitted(let found, _):
            return await commit(IntakePreview(chatFiles: found), from: origin)
        }
    }

    // MARK: Welcome staging (R-IB15)

    /// Sniffs files `feedGuard` already admitted and stages them as one row.
    /// It takes the admitted list and never walks a URL itself: a re-expansion
    /// here would be a second, unguarded walk of the drop (I-b final review,
    /// findings 6 and 7 — the Welcome is a door like any other).
    private func stageForWelcome(_ files: [URL], capped: Bool) {
        welcomeDropError = nil
        guard !files.isEmpty else { welcomeDropError = Copy.intakeNothingReadable; return }
        Task { [weak self] in
            guard let self else { return }
            var results: [IntakeFileSniff] = []
            for url in files {
                do {
                    let s = try await self.tracked { try await self.api.sniffIntake(fileURL: url, bank: nil) }
                    results.append(IntakeFileSniff(url: url, sniff: s))
                } catch {
                    results.append(IntakeFileSniff(url: url, error: AddSourceSheet.friendlyError(error)))
                }
            }
            switch IntakePreview.aggregate(results, capped: capped) {
            case .preview(let p):
                self.welcomeDrops.append(WelcomeDrop(id: UUID().uuidString, preview: p))
                self.reportVendor(p)
            case .failed(let reason): self.welcomeDropError = reason
            default: break
            }
        }
    }

    private func reportVendor(_ preview: IntakePreview) {
        if let vendor = preview.vendor { onVendorSniffed?(vendor) }
    }

    func removeWelcomeDrop(_ id: String) { welcomeDrops.removeAll { $0.id == id } }

    /// Start's path for a staged drop: commit it, then forget it — unless a file
    /// failed, so Getting started's Retry can commit it again (a re-commit of the
    /// files that did land reads as unchanged, G20).
    func commitWelcomeDrop(_ id: String) async -> IntakeOutcome? {
        guard let drop = welcomeDrops.first(where: { $0.id == id }) else { return nil }
        let outcome = await commit(drop.preview, from: .welcome)
        if outcome.failures.isEmpty { removeWelcomeDrop(id) }
        return outcome
    }

    /// Chat files through `/intake/import` (a background job followed to its end),
    /// saved files through `/sources/upload` — the route that previewed them
    /// (R-IA32) — then one Store refresh. The counter owns the flag throughout.
    func commit(_ preview: IntakePreview, from origin: IntakeOrigin) async -> IntakeOutcome {
        var outcome = IntakeOutcome(vendor: preview.vendor, origin: preview.origin)
        for url in preview.chatFiles {
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
        for url in preview.savedFiles {
            do {
                let r = try await tracked { try await api.uploadSaved(fileURL: url) }
                outcome.savedCreated += r.episodesCreated
                outcome.unchanged += r.duplicatesSkipped
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

    /// The door (design §7.4, Z-B5). Order matters: a dropped URL under a
    /// refused root is refused BEFORE `expand` walks it — listing the names in
    /// `~/.claude/projects` is already more than the capture rail allows. The
    /// walk of an innocent folder asks about every entry it meets: a folder
    /// under a refused root is pruned, never descended into (a visible
    /// `$CLAUDE_CONFIG_DIR` inside a dropped `~`), and a file under one (a
    /// symlink can point anywhere) is caught the same way; either refuses the
    /// whole drop. Then a drop with nothing export-shaped in it is refused by
    /// name. Both sides are compared resolved and component by component
    /// (`~/.claudette` is not `~/.claude`). Nothing is opened. `walk` is the
    /// test seam that lets `FeedGuardTests` prove a refused root is never
    /// walked; production always uses `expand`.
    ///
    /// Only a symlink is resolved during the walk (final review, finding 2).
    /// This runs on the main actor inside `accept`, and resolving every entry
    /// (a `realpath` per file) made a 20,600-entry folder walk 5.3× slower
    /// (0.08 s → 0.42 s, `swiftc -O`); resolving only links brings it to
    /// 0.14 s on the same tree, the rest being the prefetched link flag and
    /// the component compare. `FileManager`'s enumerator never
    /// descends a symlinked directory, so any other entry lives where its
    /// dropped folder resolves plus its path inside it — compared lexically.
    /// A symlink, an entry the walk did not spell under a dropped URL (the
    /// `walk` seam), or one whose kind is unknown is resolved as before.
    nonisolated static func feedGuard(
        urls: [URL], home: URL, env: [String: String],
        walk: (_ urls: [URL], _ prune: (URL) -> Bool) -> (files: [URL], capped: Bool)
            = { IntakeRouter.expand($0, prune: $1) }
    ) -> IntakeAdmission {
        let roots = refusedRoots(home: home, env: env)
        func refusal(components path: [String]) -> FeedRefusal? {
            roots.first { path.starts(with: $0.components) }?.refusal
        }
        func refusal(_ url: URL) -> FeedRefusal? { refusal(components: resolved(url).pathComponents) }
        if let why = urls.lazy.compactMap(refusal).first { return .refused(why) }
        // Each dropped URL under every spelling the walk may use for it — as
        // dropped, as `resolved` spells it, and as `realpath` does: the
        // enumerator hands back `/private/tmp/…` for a drop spelled `/tmp/…`,
        // and `resolvingSymlinksInPath` strips that `/private` again — each
        // mapped to where it resolves. The longest spelling wins, so a dropped
        // folder inside another dropped folder answers for its own entries.
        let bases = urls.flatMap { url -> [(spelled: [String], resolved: [String])] in
            let target = resolved(url).pathComponents
            return [url.pathComponents, target, realPath(url)?.pathComponents].compactMap { spelled in
                spelled.map { (spelled: $0, resolved: target) }
            }
        }.sorted { $0.spelled.count > $1.spelled.count }
        func walkedRefusal(_ url: URL) -> FeedRefusal? {
            let isLink = (try? url.resourceValues(forKeys: [.isSymbolicLinkKey]))?.isSymbolicLink ?? true
            let path = url.pathComponents
            guard !isLink, let base = bases.first(where: { path.starts(with: $0.spelled) }) else {
                return refusal(url)
            }
            return refusal(components: base.resolved + path.dropFirst(base.spelled.count))
        }
        var inner: FeedRefusal?
        let walked = walk(urls) { url in
            guard let why = walkedRefusal(url) else { return false }
            if inner == nil { inner = why }
            return true
        }
        // `inner` covers everything the walk met; the second look covers a
        // custom `walk` that ignores `prune` (defence in depth, one cached
        // lookup per kept file).
        if let why = inner ?? walked.files.lazy.compactMap(walkedRefusal).first { return .refused(why) }
        guard !walked.files.isEmpty else { return .refused(.unreadable) }
        return .admitted(files: walked.files, capped: walked.capped)
    }

    /// The roots alone, for a door that takes one chosen file or folder and
    /// never walks it (the Add-source walkthrough and saved-content picker,
    /// the local-folder picker — final review, finding 3): refused iff the
    /// choice itself resolves under a refused root.
    nonisolated static func refusedRoot(of urls: [URL], home: URL = FileManager.default.homeDirectoryForCurrentUser,
                                        env: [String: String] = ProcessInfo.processInfo.environment) -> FeedRefusal? {
        let roots = refusedRoots(home: home, env: env)
        return urls.lazy.compactMap { url in
            let path = resolved(url).pathComponents
            return roots.first { path.starts(with: $0.components) }?.refusal
        }.first
    }

    /// The three homes and their environment overrides, resolved once per call.
    nonisolated static func refusedRoots(home: URL, env: [String: String])
        -> [(components: [String], refusal: FeedRefusal)] {
        var roots: [(URL, FeedRefusal)] = [
            (home.appendingPathComponent(".claude"), .claudeSessions),
            (home.appendingPathComponent(".codex"), .codexSessions),
            (home.appendingPathComponent(".cicada"), .cicadaHome),
        ]
        let overrides: [(String, FeedRefusal)] = [("CLAUDE_CONFIG_DIR", .claudeSessions),
                                                  ("CODEX_HOME", .codexSessions),
                                                  ("CICADA_HOME", .cicadaHome)]
        for (key, refusal) in overrides {
            guard let value = env[key], !value.isEmpty else { continue }
            roots.append((URL(fileURLWithPath: (value as NSString).expandingTildeInPath), refusal))
        }
        return roots.map { (components: resolved($0.0).pathComponents, refusal: $0.1) }
    }

    nonisolated static func resolved(_ url: URL) -> URL { url.resolvingSymlinksInPath().standardizedFileURL }

    /// `realpath(3)`: the spelling `FileManager`'s enumerator uses for a
    /// dropped folder whose path runs through a symlink (`/tmp`, `/var`).
    nonisolated static func realPath(_ url: URL) -> URL? {
        guard let real = realpath(url.path, nil) else { return nil }
        defer { free(real) }
        return URL(fileURLWithPath: String(cString: real))
    }


    /// Folders walked, hidden files and `__MACOSX` skipped, export-shaped
    /// extensions kept, capped at `maxFiles` with a stated warning. `prune`
    /// (Z-B5) is asked about every entry the walk meets; `true` skips it and,
    /// for a folder, everything under it — so a refused root inside a dropped
    /// folder is never listed. It defaults to "never", which is today's walk.
    nonisolated static func expand(_ urls: [URL], fileManager fm: FileManager = .default,
                                   prune: (URL) -> Bool = { _ in false }) -> (files: [URL], capped: Bool) {
        var out: [URL] = []
        func consider(_ url: URL) {
            guard !url.lastPathComponent.hasPrefix("."), !url.pathComponents.contains("__MACOSX") else { return }
            if exportExtensions.contains(url.pathExtension.lowercased()) { out.append(url) }
        }
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                // `.isSymbolicLinkKey` prefetched: `feedGuard`'s prune asks it
                // of every entry (final review, finding 2).
                let walker = fm.enumerator(at: url, includingPropertiesForKeys: [.isSymbolicLinkKey],
                                           options: [.skipsHiddenFiles, .skipsPackageDescendants])
                while let next = walker?.nextObject() as? URL, out.count <= maxFiles {
                    if prune(next) { walker?.skipDescendants(); continue }
                    consider(next)
                }
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

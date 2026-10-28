import Foundation
import Observation

/// G218 (ruling 38, owner 2026-10-23) — activity traces: what was in front of the person on this Mac, with times, so
/// "the video I watched at 15:20" is findable later. Off by default; on only after the consent sheet.
///
/// **The app captures; the backend keeps.** This recorder is the only capturer: each tick it reads the app in front,
/// idle time, the locked screen and secure input (no permission), the focused window's title (Accessibility), an
/// allowed Chromium browser's front tab (Automation), and now and then a screenshot (Screen Recording) — of every
/// connected screen once the person agreed to the sheet that says so (`allScreensConsent`), each cut down to the apps the
/// policy may describe; of the front window before that — with its text read on this Mac (Vision). It applies `TracePolicy` *before* anything leaves it and posts
/// closed spans and frames to This Mac's backend, which re-applies the policy and seals them outside every bank. The
/// app writes nothing to disk: what waits to be posted waits in memory, capped, and is dropped rather than spilled.
///
/// **Nothing, not even a title,** while traces are off or paused, while the screen is locked or a password field has
/// focus, for an app or site the person excluded, a password manager, Cicada itself, or a private window. A browser
/// window is described (title, screenshot) only when its tab was read and is known not to be private; a chat or mail
/// app keeps its name and times only (no title, no screenshot) unless the person turned titles on for it.
///
/// **No prompts.** Every permission is read by preflight; asking happens only through the person's own click.
@MainActor
@Observable
final class TraceRecorder {
    enum State: Equatable {
        /// Traces are off (the default), or the backend has not answered yet.
        case off
        case recording
        case paused
        /// This app talks to a server: traces stay on the Mac that records them, and none is recorded here.
        case notThisMac
        case failed(String)
    }

    enum PauseChoice: Equatable { case hour, untilTomorrow, untilResumed }

    private(set) var state: State = .off
    private(set) var settings = TraceSettings()
    private(set) var status = TraceStoreStatus()
    private(set) var lists = TracePolicyLists()
    private(set) var consentVersion = 1
    /// The sheet version from which screenshots cover every connected screen; nil from an older backend.
    private(set) var allScreensConsent: Int?
    /// Screenshots cover every connected screen: the person agreed to the sheet that says so.
    var capturesAllScreens: Bool {
        guard let needed = allScreensConsent else { return false }
        return settings.consentVersion >= needed
    }
    /// Recording, with screenshots on, under the older sheet: the page offers the newer one (every screen).
    var offersAllScreens: Bool {
        guard let needed = allScreensConsent, settings.enabled, settings.screenshots else { return false }
        return settings.consentVersion < needed
    }
    /// Spans waiting to be posted (memory only).
    private(set) var pendingCount = 0
    var isRecording: Bool { state == .recording }
    /// The backend has answered at least once (`apply`): before that, `settings` are defaults, not the person's.
    private(set) var loaded = false
    /// G218 (owner 2026-10-26) — whether the Traces page belongs on the rail; nil until the backend has answered.
    /// Never on a Mac that talks to a server: traces stay on the Mac that records them.
    var pageShown: Bool? {
        if state == .notThisMac { return false }
        return loaded ? TracesPageVisibility.shown(settings: settings, status: status) : nil
    }

    @ObservationIgnored private let backend: any TraceBackend
    @ObservationIgnored private let workspace: any TraceWorkspace
    @ObservationIgnored private let idle: any TraceIdleProbe
    @ObservationIgnored private let titles: any TraceWindowTitles
    @ObservationIgnored private let tabs: any TraceBrowserTabs
    @ObservationIgnored private let capture: any TraceScreenCapture
    @ObservationIgnored private let recognizer: any TraceTextRecognizer
    @ObservationIgnored private let registry: any TraceBrowserRegistry
    @ObservationIgnored private let connection: () -> ServerConnection
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let ownBundleId: String?
    @ObservationIgnored private let tickInterval: Duration
    @ObservationIgnored let cadence: TraceFrameCadence

    /// Idle longer than this ends the span (ActivityWatch's AFK default is 3 min; the proposal's 2 min).
    nonisolated static let idleThreshold: TimeInterval = 120
    /// A span shorter than this is an alt-tab flicker, not a moment.
    nonisolated static let minSpan: TimeInterval = 2
    /// Spans are posted once a minute, or sooner when this many wait.
    nonisolated static let flushInterval: TimeInterval = 60
    nonisolated static let flushCount = 50
    /// At most this many spans wait in memory when the backend is away; the oldest go first.
    nonisolated static let pendingCap = 500
    /// At most this many frames wait for text recognition and posting (a moment is one frame per connected screen).
    nonisolated static let frameQueueCap = 8

    struct OpenSpan: Equatable {
        var id: String
        var start: Date
        var lastSeen: Date
        var bundleId: String
        var app: String
        var title: String?
        var url: String?
        var host: String?
        var pid: Int32
        /// A screenshot may describe it (not a browser whose tab is unverified, not a title-off app).
        var describable: Bool
        /// A browser (by name, or registered to open https: links): described only through a verified tab.
        var isBrowser: Bool
        var key: String { "\(bundleId)\u{1}\(title ?? "")\u{1}\(url ?? "")" }
    }

    @ObservationIgnored private var open: OpenSpan?
    @ObservationIgnored private var pending: [TraceSpan] = []
    @ObservationIgnored private var lastFlush: Date?
    @ObservationIgnored private var lastFrameAt: Date?
    @ObservationIgnored private var lastFrameSpanStart: Date?
    @ObservationIgnored private var frameQueue: [TraceFramePost] = []
    @ObservationIgnored private var framesRunning = false
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var activation: AnyObject?
    @ObservationIgnored private var ticking = false
    /// A pause the person asked for holds here at once, whatever the backend answers.
    @ObservationIgnored private var localPauseUntil: Date?
    @ObservationIgnored private var localPauseIndefinite = false

    init(backend: any TraceBackend, workspace: any TraceWorkspace, idle: any TraceIdleProbe,
         titles: any TraceWindowTitles, tabs: any TraceBrowserTabs, capture: any TraceScreenCapture,
         recognizer: any TraceTextRecognizer, registry: any TraceBrowserRegistry,
         connection: @escaping () -> ServerConnection = { .current },
         now: @escaping () -> Date = Date.init, ownBundleId: String? = Bundle.main.bundleIdentifier,
         tickInterval: Duration = .seconds(5), cadence: TraceFrameCadence = TraceFrameCadence()) {
        self.backend = backend
        self.workspace = workspace
        self.idle = idle
        self.titles = titles
        self.tabs = tabs
        self.capture = capture
        self.recognizer = recognizer
        self.registry = registry
        self.connection = connection
        self.now = now
        self.ownBundleId = ownBundleId
        self.tickInterval = tickInterval
        self.cadence = cadence
    }

    var policy: TracePolicy { TracePolicy(settings: settings, lists: lists, ownBundleId: ownBundleId) }

    // MARK: - The person's controls

    /// On launch: read the person's choices; record only if they turned traces on.
    func start() async {
        await reload()
    }

    func reload() async {
        guard TraceBackendGate.allows(connection()) else { disarm(); state = .notThisMac; return }
        do {
            apply(try await backend.traceSettings())
        } catch {
            // Fail closed: with no answer, nothing is recorded.
            disarm()
            if settings.enabled { state = .failed(Self.describe(error)) } else { state = .off }
        }
    }

    /// The consent sheet's Turn on.
    func turnOn() async throws {
        guard TraceBackendGate.allows(connection()) else { throw TraceBackendError.notThisMac }
        apply(try await backend.traceTurnOn(consentVersion: consentVersion))
    }

    func turnOff() async {
        closeOpen(at: now())
        await flush(force: true)
        disarm()
        if let answer = try? await backend.traceTurnOff() { apply(answer) } else { settings.enabled = false; state = .off }
    }

    func pause(_ choice: PauseChoice) async {
        let moment = now()
        closeOpen(at: moment)
        await flush(force: true)
        let until: String
        switch choice {
        case .hour:
            let end = moment.addingTimeInterval(3600)
            localPauseUntil = end
            until = TraceClock.stamp(end)
        case .untilTomorrow:
            let end = Calendar.current.startOfDay(for: moment).addingTimeInterval(86_400)
            localPauseUntil = Calendar.current.startOfDay(for: end)
            until = TraceClock.stamp(localPauseUntil ?? end)
        case .untilResumed:
            localPauseIndefinite = true
            until = TraceSettings.untilResumed
        }
        state = .paused
        if let answer = try? await backend.tracePause(until: until) { apply(answer) }
    }

    func resume() async {
        localPauseUntil = nil
        localPauseIndefinite = false
        if let answer = try? await backend.tracePause(until: nil) { apply(answer) } else if settings.enabled { arm() }
    }

    func update(_ patch: [String: TracePatchValue]) async throws {
        apply(try await backend.traceUpdate(patch))
    }

    /// "Forget the last 15 minutes": what waits here is dropped too, and the open span ends without being kept.
    func forget(minutes: Int = 15) async throws {
        let cutoff = now().addingTimeInterval(-TimeInterval(minutes * 60))
        open = nil
        pending.removeAll { (TraceClock.parse($0.end) ?? .distantFuture) > cutoff }
        frameQueue.removeAll { (TraceClock.parse($0.at) ?? .distantFuture) >= cutoff }
        pendingCount = pending.count
        try await backend.traceForget(minutes: minutes)
        await refreshStatus()
    }

    /// Every trace, screenshot, setting and the key, gone; traces are off afterwards.
    func wipe() async throws {
        disarm()
        open = nil
        pending.removeAll()
        frameQueue.removeAll()
        pendingCount = 0
        apply(try await backend.traceWipe())
    }

    func refreshStatus() async {
        if let answer = try? await backend.traceSettings() { apply(answer) }
    }

    // MARK: - State

    private func apply(_ answer: TraceSettingsAnswer) {
        settings = answer.settings
        status = answer.status
        lists = answer.policy
        consentVersion = answer.consentVersion
        allScreensConsent = answer.allScreensConsent
        loaded = true
        if !settings.enabled {
            disarm()
            state = .off
        } else if pausedNow() {
            closeOpen(at: now())
            state = .paused
            arm()   // the ticker notices the pause's end
        } else {
            state = .recording
            arm()
        }
    }

    private func pausedNow() -> Bool {
        let moment = now()
        if localPauseIndefinite { return true }
        if let until = localPauseUntil {
            if moment < until { return true }
            localPauseUntil = nil
        }
        return settings.isPaused(at: moment)
    }

    private func arm() {
        if activation == nil {
            activation = workspace.onActivation { [weak self] in
                guard let self else { return }
                Task { await self.tick() }
            }
        }
        guard ticker == nil else { return }
        // The first spans go out a minute after recording starts, then once a minute.
        if lastFlush == nil { lastFlush = now() }
        let interval = tickInterval
        ticker = Task { [weak self] in
            // The first look comes one interval in (or at the next app activation): nothing is read the instant
            // traces turn on or the app opens.
            while !Task.isCancelled {
                try? await Task.sleep(for: interval)
                guard !Task.isCancelled else { return }
                await self?.tick()
            }
        }
    }

    private func disarm() {
        ticker?.cancel()
        ticker = nil
        activation = nil
        open = nil
    }

    // MARK: - The tick

    /// One look at the screen. Public for tests; the ticker and app activations call it.
    func tick() async {
        guard !ticking else { return }
        ticking = true
        defer { ticking = false }
        let moment = now()
        guard settings.enabled, TraceBackendGate.allows(connection()) else { closeOpen(at: moment); return }
        if pausedNow() {
            closeOpen(at: moment)
            state = .paused
            return
        }
        if state == .paused { state = .recording }
        await observe(at: moment)
        await flush(force: false)
    }

    private func observe(at moment: Date) async {
        if idle.screenLocked() || idle.secureInput() { closeOpen(at: moment); return }
        let idleFor = idle.secondsSinceInput()
        if idleFor >= Self.idleThreshold { closeOpen(at: moment.addingTimeInterval(-idleFor)); return }
        guard let front = workspace.frontmost() else { closeOpen(at: moment); return }
        let policy = self.policy
        if policy.neverRecorded(front.bundleId) { closeOpen(at: moment); return }

        var title: String?
        var url: String?
        var host: String?
        var describable = policy.titleAllowed(front.bundleId)
        // Any app macOS registers to open https: links is a browser, listed or not (review of #456, B3): an unlisted
        // browser's private window is never described.
        let isBrowser = policy.isBrowser(front.bundleId) || registry.opensWebLinks(front.bundleId)
        if isBrowser {
            // A browser window is described only once its tab is read and known not to be private.
            describable = false
            if policy.urlBrowser(front.bundleId) != nil, tabs.granted(bundleId: front.bundleId),
               let tab = await tabs.frontTab(bundleId: front.bundleId) {
                if tab.isPrivate { closeOpen(at: moment); return }
                if let cleaned = policy.cleanURL(tab.url) {
                    if policy.hostExcluded(cleaned.host) { closeOpen(at: moment); return }
                    url = cleaned.url
                    host = cleaned.host
                    describable = policy.titleAllowed(front.bundleId)
                    if describable, !tab.title.isEmpty { title = TracePolicy.trimTitle(tab.title) }
                }
            }
        } else if describable, titles.trusted(), let raw = titles.focusedTitle(pid: front.pid), !raw.isEmpty {
            title = TracePolicy.trimTitle(raw)
        }
        // The front app may have changed while the tab was read: look again before keeping anything.
        guard workspace.frontmost()?.bundleId == front.bundleId else { return }

        let next = OpenSpan(id: Self.newId(), start: moment, lastSeen: moment, bundleId: front.bundleId,
                            app: front.name, title: title, url: url, host: host, pid: front.pid,
                            describable: describable, isBrowser: isBrowser)
        var isNew = false
        if var current = open, current.key == next.key {
            current.lastSeen = moment
            open = current
        } else {
            closeOpen(at: moment)
            open = next
            isNew = true
        }
        if let span = open { considerFrame(span, isNew: isNew, at: moment) }
    }

    private func closeOpen(at moment: Date) {
        guard let span = open else { return }
        open = nil
        let end = max(span.start, moment)
        guard end.timeIntervalSince(span.start) >= Self.minSpan else { return }
        pending.append(TraceSpan(id: span.id, start: TraceClock.stamp(span.start), end: TraceClock.stamp(end),
                                 bundleId: span.bundleId, app: span.app, title: span.title, url: span.url,
                                 browser: span.isBrowser ? true : nil))
        if pending.count > Self.pendingCap { pending.removeFirst(pending.count - Self.pendingCap) }
        pendingCount = pending.count
    }

    /// Posts the closed spans once a minute (or when many wait). Never spills to disk: on failure they wait here.
    func flush(force: Bool) async {
        let moment = now()
        guard !pending.isEmpty else { return }
        if !force, pending.count < Self.flushCount,
           moment.timeIntervalSince(lastFlush ?? .distantPast) < Self.flushInterval { return }
        guard TraceBackendGate.allows(connection()) else { pending.removeAll(); pendingCount = 0; return }
        let batch = pending
        lastFlush = moment
        do {
            _ = try await backend.traceSync(batch)
            pending.removeFirst(min(batch.count, pending.count))
        } catch APIError.httpError(409, _) {
            // Off or paused on the backend's side: what waits here is not kept.
            pending.removeAll()
            await refreshStatus()
        } catch {
            // The backend is away: keep them in memory (capped) and try again next minute.
        }
        pendingCount = pending.count
    }

    // MARK: - Screenshots

    private func considerFrame(_ span: OpenSpan, isNew: Bool, at moment: Date) {
        // The cadence first: the Screen Recording preflight is a TCC lookup (~7 ms measured on the main actor, 2026-10-28),
        // asked only when a frame is due — not on every five-second tick.
        guard settings.screenshots, span.describable,
              cadence.shouldCapture(now: moment, spanStartedAt: span.start, spanIsNew: isNew, lastFrameAt: lastFrameAt,
                                    lastFrameSpanStart: lastFrameSpanStart),
              capture.hasAccess() else { return }
        lastFrameAt = moment
        lastFrameSpanStart = span.start
        let capture = self.capture
        let maxSide = cadence.maxSide
        let allScreens = capturesAllScreens
        let registry = self.registry
        let shown = TraceScreens.shown(policy) { registry.opensWebLinks($0) }
        Task { [weak self] in
            let frames: [TraceCapturedFrame]
            if allScreens {
                frames = (try? await capture.captureScreens(frontPid: span.pid, keepFrontWindow: span.isBrowser,
                                                            maxSide: maxSide, shown: shown)) ?? []
            } else if let frame = try? await capture.captureFrontWindow(pid: span.pid, maxSide: maxSide) {
                frames = [frame]
            } else {
                frames = []
            }
            guard !frames.isEmpty, let self, await self.stillShows(span) else { return }
            for frame in frames { await self.enqueue(frame, span: span, at: moment) }
        }
    }

    /// After a capture: is what was vetted still what is in front? The same app, and for a browser the same page in a
    /// window still known not to be private — otherwise the frame may show another window (an incognito one brought
    /// forward in between) and is dropped (review of #456, B2).
    func stillShows(_ span: OpenSpan) async -> Bool {
        guard let front = workspace.frontmost(), front.pid == span.pid, front.bundleId == span.bundleId else {
            return false
        }
        guard span.isBrowser else { return true }
        guard let expected = span.url, let tab = await tabs.frontTab(bundleId: span.bundleId), !tab.isPrivate,
              let cleaned = policy.cleanURL(tab.url) else { return false }
        return cleaned.url == expected
    }

    private func enqueue(_ frame: TraceCapturedFrame, span: OpenSpan, at moment: Date) async {
        // Paused or turned off while the frame was taken: it is not kept.
        guard settings.enabled, settings.screenshots, !pausedNow() else { return }
        let post = TraceFramePost(id: Self.newId(), at: TraceClock.stamp(moment), bundleId: span.bundleId,
                                  app: span.app, host: span.host ?? "", spanId: span.id, width: frame.width,
                                  height: frame.height, image: frame.jpeg.base64EncodedString(), text: "",
                                  browser: span.isBrowser, display: frame.display, displays: frame.displays)
        frameQueue.append(post)
        if frameQueue.count > Self.frameQueueCap { frameQueue.removeFirst(frameQueue.count - Self.frameQueueCap) }
        await drainFrames()
    }

    /// Text recognition runs here, after capture and off the tick (the capture path is file I/O and a post only).
    private func drainFrames() async {
        guard !framesRunning else { return }
        framesRunning = true
        defer { framesRunning = false }
        while !frameQueue.isEmpty {
            var post = frameQueue.removeFirst()
            guard let data = Data(base64Encoded: post.image) else { continue }
            let recognizer = self.recognizer
            post.text = await Task.detached(priority: .utility) { await recognizer.recognize(jpeg: data) }.value
            guard settings.enabled, settings.screenshots, !pausedNow() else { continue }
            try? await backend.traceAddFrame(post)
        }
    }

    /// For tests: frames waiting for recognition.
    var queuedFrames: Int { frameQueue.count }

    // MARK: - Helpers

    nonisolated static func newId() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }

    nonisolated static func describe(_ error: Error) -> String {
        if case APIError.httpError(_, let message) = error { return message }
        return error.localizedDescription
    }
}

extension TracePolicy {
    /// The browsers known before the backend's list arrives (the recorder records nothing before it does, so this is a
    /// floor). The full list is the backend's (`trace_policy.KNOWN_BROWSERS`, served as `known_browsers`).
    static let floorBrowsers: Set<String> = [
        "com.google.Chrome", "com.google.Chrome.beta", "com.google.Chrome.dev", "com.google.Chrome.canary",
        "com.brave.Browser", "com.microsoft.edgemac", "com.vivaldi.Vivaldi", "com.apple.Safari",
        "com.apple.SafariTechnologyPreview", "org.mozilla.firefox", "company.thebrowser.Browser",
    ]

    /// A browser: its windows are described only when the tab was read and is known not to be private.
    func isBrowser(_ bundleId: String) -> Bool {
        Self.floorBrowsers.contains(bundleId) || lists.knownBrowsers.contains(bundleId)
    }
}

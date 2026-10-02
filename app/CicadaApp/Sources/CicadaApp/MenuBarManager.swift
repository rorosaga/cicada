import SwiftUI
import AppKit

/// Owns the menu-bar `NSStatusItem`, the bookworm sprite animation, and the
/// dropdown. Driven by ``StatusSnapshot``s pushed in from the App's poll loop
/// (every 30s + immediately after quick actions) and by the live 1s sleep hook
/// (``applySleep(_:)``). All UI work happens on the main actor.
/// The status item is a single colour sprite (G107) — no text title; the
/// inbox count is drawn into the frame.
@MainActor
@Observable
final class MenuBarManager: NSObject {
    private(set) var state: BookwormState = .awake

    /// F-10's *Show in menu bar* (R-HO16): the status item stays built — its sprite, badge and menu keep updating — and
    /// only its visibility follows the switch, so turning it back on shows the current state at once.
    private(set) var isVisible = true

    func setVisible(_ visible: Bool) {
        isVisible = visible
        statusItem?.isVisible = visible
        restartAnimation()
    }

    /// A new skin can have different frame holds. Redraw immediately and restart its chained timer at its key frame.
    func mascotChanged() {
        frameStep = 0
        restartAnimation()
    }

    /// One point per art pixel, at the standard status-item image height.
    nonisolated static let spritePointSize: CGFloat = 18

    nonisolated static func animates(_ state: BookwormState, reduceMotion: Bool) -> Bool {
        !reduceMotion && (BookwormArt.clip(state, look: .idle, set: .small)?.1.order.count ?? 0) > 1
    }

    nonisolated static func animationRuns(isVisible: Bool, displaysAsleep: Bool, reduceMotion: Bool) -> Bool {
        isVisible && !displaysAsleep && !reduceMotion
    }

    nonisolated static func accessibilityLabel(for state: BookwormState) -> String {
        "Cicada — \(state.title), \(state.detail)"
    }

    private var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }

    private var statusItem: NSStatusItem?
    private var frameTimer: Timer?
    private var reduceMotionObserver: NSObjectProtocol?
    private var digestExpiryTask: Task<Void, Never>?
    private var frameStep = 0
    private var displaysAsleep = false
    private var displayObservers: [NSObjectProtocol] = []
    private var currentSnapshot: StatusSnapshot?
    /// Sleep page v5 — what the run item and the header say (`SleepDoor`): "Consolidate now — all 287", and while a run
    /// is paused "Paused — 98 of 287 filed" with "Continue on the Sleep page…", which opens the page and never continues.
    var sleepDoor: (@MainActor () -> SleepDoor)?
    private var justFinishedAt: Date?

    // Quick-action closures injected by the App.
    private var onOpenApp: (() -> Void)?
    private var onRunSleep: (() async -> Void)?
    private var onSaveClipboardURL: (() async -> Void)?
    /// Track I T5 (R-IA26) — "Import a file…" opens the one intake.
    private var onImportFile: (() -> Void)?
    /// Track I part b (R-IB22) — the export waits of the active memory, as the
    /// menu's lines. Set by the app; a closure, not state to observe, so it is
    /// read when the menu is built or opened and never re-renders anything.
    @ObservationIgnored var exportWaitLines: () -> [String] = { [] }
    /// Tags the reminder lines so a menu open can swap them without a rebuild.
    static let exportWaitTag = 9_101

    // MARK: - Setup

    func setup(
        onOpenApp: @escaping () -> Void,
        onRunSleep: @escaping () async -> Void,
        onSaveClipboardURL: @escaping () async -> Void,
        onImportFile: @escaping () -> Void
    ) {
        self.onOpenApp = onOpenApp
        self.onRunSleep = onRunSleep
        self.onSaveClipboardURL = onSaveClipboardURL
        self.onImportFile = onImportFile

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem?.button?.imagePosition = .imageOnly
        statusItem?.isVisible = isVisible
        transition(to: .awake)
        rebuildMenu()

        // Re-evaluate the timer when the user toggles Reduce Motion (R7).
        // NOT `NotificationCenter.default`: AppKit posts this one to the
        // workspace's own centre (SDK `NSAccessibility.h`: "Notification posted
        // to the NSWorkspace notification center"), so an observer on the
        // default centre never fires. The token is kept (the block-based API
        // is not `@discardableResult`) for the manager's app-long lifetime.
        reduceMotionObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { guard let self else { return }; self.restartAnimation() }
        }
        let center = NSWorkspace.shared.notificationCenter
        displayObservers = [
            center.addObserver(forName: NSWorkspace.screensDidSleepNotification, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.displaysAsleep = true; self?.restartAnimation() }
            },
            center.addObserver(forName: NSWorkspace.screensDidWakeNotification, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.displaysAsleep = false; self?.restartAnimation() }
            },
        ]

    }

    // MARK: - State input

    /// Called by the App's poll loop every 30s and immediately after actions.
    /// Recomputes ``deriveBookwormState`` and re-renders; the dropdown is always
    /// rebuilt because counts/times may move without a state-case change.
    func apply(snapshot: StatusSnapshot, justFinishedAt: Date?) {
        currentSnapshot = snapshot
        self.justFinishedAt = justFinishedAt
        let newState = deriveBookwormState(snapshot, justFinishedAt: justFinishedAt)
        if newState.caseName != state.caseName {
            transition(to: newState)
        } else {
            // Same animation, but the badge/stage overlay or detail may differ.
            state = newState
            renderCurrentFrame()
        }
        rebuildMenu()
        scheduleDigestExpiry(for: newState, snapshot: snapshot)
    }

    /// `digesting` is the one state that expires on a clock rather than on new
    /// data (`deriveBookwormState` drops it 6s after the cycle finished). Push
    /// models don't guarantee another status event inside that window, so
    /// re-derive once ourselves — otherwise the worm chews forever.
    private func scheduleDigestExpiry(for newState: BookwormState, snapshot: StatusSnapshot) {
        digestExpiryTask?.cancel()
        digestExpiryTask = nil
        guard case .digesting = newState, let finished = justFinishedAt else { return }
        let remaining = 6.1 - Date().timeIntervalSince(finished)
        guard remaining > 0 else { return }
        digestExpiryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(remaining))
            guard !Task.isCancelled, let self else { return }
            // Same snapshot, later clock: `digesting` has aged out by now.
            self.apply(snapshot: snapshot, justFinishedAt: self.justFinishedAt)
        }
    }

    /// The ``Store`` owns sleep running→idle edge detection; it tells us when a
    /// cycle finished so `digesting` fires exactly once from one authority.
    func noteCycleFinished(at date: Date = Date()) {
        justFinishedAt = date
    }

    /// Patches only the sleep portion of the current snapshot and re-derives.
    /// Wired to ``SleepViewModel.onStatusChanged`` so the 1..5 stage dots advance
    /// within ~1s during a running cycle without waiting for the 30s poll.
    func applySleep(_ sleep: SleepStatusResponse) {
        var snap = currentSnapshot ?? Self.unknownSnapshot
        snap.sleep = StatusSnapshot.Sleep(
            status: sleep.status,
            stage: sleep.stage,
            totalStages: sleep.totalStages,
            cycleId: sleep.cycleId,
            error: sleep.error
        )
        // NOTE: the running -> idle edge is NOT computed here. The Store is the
        // single owner of `justFinishedAt` (it sees both `/status` refreshes and
        // live `sleep` SSE events) and hands it to us via `apply` /
        // `noteCycleFinished(at:)`. Two independent edge detectors used to
        // double-fire `digesting`.
        apply(snapshot: snap, justFinishedAt: justFinishedAt)
    }

    private static let unknownSnapshot = StatusSnapshot(
        sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
        inbox: .init(total: 0, byKind: [:]),
        episodes: .init(unprocessed: 0, lastIngestedAt: nil),
        lastSleepAt: nil,
        nextSleepAt: nil
    )

    // MARK: - Animation

    private func transition(to newState: BookwormState) {
        state = newState
        frameStep = 0
        restartAnimation()
    }

    private func restartAnimation() {
        frameTimer?.invalidate()
        frameTimer = nil
        if reduceMotion { frameStep = 0 }
        renderCurrentFrame()
        scheduleNextFrame()
    }

    private func scheduleNextFrame() {
        guard Self.animationRuns(isVisible: isVisible, displaysAsleep: displaysAsleep, reduceMotion: reduceMotion),
              let (_, clip) = BookwormArt.clip(state, look: .idle, set: .small), clip.order.count > 1 else { return }
        let profile = SpritePlaybackProfile.of(reduceMotion: reduceMotion, lowPower: SceneStore.shared.lowPower)
        let seconds = clip.seconds[frameStep % clip.seconds.count] * profile.slowdown
        let timer = Timer(timeInterval: seconds, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        timer.tolerance = seconds * CicadaMotion.spriteTimerTolerance
        frameTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    private func tick() {
        frameTimer = nil
        guard Self.animationRuns(isVisible: isVisible, displaysAsleep: displaysAsleep, reduceMotion: reduceMotion),
              let (_, clip) = BookwormArt.clip(state, look: .idle, set: .small), !clip.order.isEmpty else { return }
        frameStep = (frameStep + 1) % clip.order.count
        renderCurrentFrame()
        scheduleNextFrame()
    }

    private func renderCurrentFrame() {
        guard let button = statusItem?.button else { return }
        let image = BookwormRenderer.smallImage(state: state, frameStep: frameStep, pointSize: Self.spritePointSize)
        let label = Self.accessibilityLabel(for: state)
        image.accessibilityDescription = label
        button.image = image
        button.setAccessibilityLabel(label)
        button.imagePosition = .imageOnly
        button.title = ""
    }

    // MARK: - Dropdown

    private func rebuildMenu() {
        let menu = NSMenu()

        // Status header (disabled): "<icon> <title> — <detail>".
        let door = sleepDoor?()
        let header = NSMenuItem(title: door?.menuHeader ?? "\(state.title) — \(state.detail)", action: nil,
                                keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)

        menu.addItem(NSMenuItem.separator())

        // Inbox count.
        let inboxTotal = currentSnapshot?.inbox.total ?? 0
        let inboxTitle = inboxTotal == 0 ? "Inbox: empty" : "Inbox: \(inboxTotal) item\(inboxTotal == 1 ? "" : "s")"
        let inboxItem = NSMenuItem(title: inboxTitle, action: nil, keyEquivalent: "")
        inboxItem.isEnabled = false
        menu.addItem(inboxItem)

        // Last / next sleep.
        let lastItem = NSMenuItem(title: "Last sleep: \(relativeLastSleep())", action: nil, keyEquivalent: "")
        lastItem.isEnabled = false
        menu.addItem(lastItem)

        let nextItem = NSMenuItem(title: "Next sleep: \(nextSleepDescription())", action: nil, keyEquivalent: "")
        nextItem.isEnabled = false
        menu.addItem(nextItem)
        // R-IB22 — the text twin of an export reminder, permission or not.
        insertExportWaitItems(in: menu, at: menu.items.count)

        menu.addItem(NSMenuItem.separator())

        // Quick actions.
        let isRunning = currentSnapshot?.sleep.status == "running"
        let runItem = NSMenuItem(title: door?.menuItemTitle ?? Copy.consolidateNow, action: #selector(runSleepAction),
                                 keyEquivalent: "r")
        runItem.target = self
        runItem.isEnabled = !isRunning || door?.isPaused == true
        menu.addItem(runItem)

        let saveItem = NSMenuItem(title: "Save clipboard URL", action: #selector(saveClipboardAction), keyEquivalent: "s")
        saveItem.target = self
        menu.addItem(saveItem)

        // Track I T5 (R-IA26): the one intake from the menu bar; the status
        // button as a drag target waits on design §14 item 5.
        let importItem = NSMenuItem(title: Copy.intakeMenuBarItem, action: #selector(importFileAction), keyEquivalent: "i")
        importItem.target = self
        menu.addItem(importItem)

        let openItem = NSMenuItem(title: "Open Cicada", action: #selector(openApp), keyEquivalent: "o")
        openItem.target = self
        menu.addItem(openItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit Cicada", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        menu.delegate = self
        statusItem?.menu = menu
    }

    /// Swaps the tagged reminder lines for the current ones, right after "Next sleep".
    fileprivate func refreshExportWaitItems(in menu: NSMenu) {
        for item in menu.items where item.tag == Self.exportWaitTag { menu.removeItem(item) }
        let anchor = menu.items.firstIndex { $0.title.hasPrefix("Next sleep:") }
        insertExportWaitItems(in: menu, at: anchor.map { $0 + 1 } ?? 0)
    }

    private func insertExportWaitItems(in menu: NSMenu, at index: Int) {
        for (offset, line) in exportWaitLines().enumerated() {
            let item = NSMenuItem(title: line, action: nil, keyEquivalent: "")
            item.isEnabled = false
            item.tag = Self.exportWaitTag
            menu.insertItem(item, at: index + offset)
        }
    }

    private func relativeLastSleep() -> String {
        guard let date = StatusSnapshot.parseDate(currentSnapshot?.lastSleepAt) else { return "never" }
        let fmt = RelativeDateTimeFormatter()
        fmt.unitsStyle = .full
        return fmt.localizedString(for: date, relativeTo: Date())
    }

    private func nextSleepDescription() -> String {
        guard let date = StatusSnapshot.parseDate(currentSnapshot?.nextSleepAt) else { return "not scheduled" }
        let cal = Calendar.current
        let timeFmt = DateFormatter()
        timeFmt.dateFormat = "h:mm a"
        let time = timeFmt.string(from: date)
        if cal.isDateInToday(date) { return "today \(time)" }
        if cal.isDateInTomorrow(date) { return "tomorrow \(time)" }
        let dayFmt = DateFormatter()
        dayFmt.dateFormat = "EEE h:mm a"
        return dayFmt.string(from: date)
    }

    // MARK: - Actions

    @objc private func openApp() {
        onOpenApp?()
    }

    @objc private func runSleepAction() {
        guard let onRunSleep else { return }
        Task { await onRunSleep() }
    }

    @objc private func saveClipboardAction() {
        guard let onSaveClipboardURL else { return }
        Task { await onSaveClipboardURL() }
    }

    @objc private func importFileAction() {
        onImportFile?()
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }

    /// Reads a URL off the clipboard and posts it to the media/sources ingest
    /// endpoint. The endpoint ships in a later wave, so a 404 surfaces a
    /// transient "coming soon" header in the menu rather than crashing.
    func saveClipboardURL() async {
        guard let raw = AppPasteboard.board.string(forType: .string),
              let url = Self.firstURL(in: raw) else {
            flashHeader("Clipboard has no URL")
            return
        }
        do {
            try await APIClient.shared.saveSource(url: url)
            flashHeader("Saved \(url)")
            await refreshAfterAction()
        } catch let APIError.httpError(code, _) where code == 404 {
            flashHeader("Save URL — coming soon")
        } catch {
            flashHeader("Save failed")
        }
    }

    /// One immediate poll + apply, used after a quick action so the icon/badge
    /// reacts without waiting for the 30s loop.
    func refreshAfterAction() async {
        if let snap = await StatusService.shared.fetch() {
            apply(snapshot: snap, justFinishedAt: justFinishedAt)
        }
    }

    /// Briefly swap the disabled header line to convey a transient message, then
    /// restore the real header on the next rebuild.
    private func flashHeader(_ message: String) {
        guard let menu = statusItem?.menu, let header = menu.items.first else { return }
        header.title = "Cicada: \(message)"
    }

    private static func firstURL(in text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        // Accept a bare http(s) URL on the clipboard.
        if let url = URL(string: trimmed), let scheme = url.scheme,
           scheme == "http" || scheme == "https", url.host != nil {
            return trimmed
        }
        // Otherwise scan for the first http(s) substring.
        if let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) {
            let range = NSRange(trimmed.startIndex..., in: trimmed)
            if let match = detector.firstMatch(in: trimmed, range: range),
               let u = match.url, let scheme = u.scheme,
               scheme == "http" || scheme == "https" {
                return u.absoluteString
            }
        }
        return nil
    }
}

#if DEBUG
extension MenuBarManager {
    /// Tiny harness so a frame can be eyeballed without launching the menu bar.
    /// Returns rendered colour images for each state at frame 0 (used in
    /// previews / manual inspection; costs nothing in release builds).
    /// Overlays are already baked into the frame (R2), so nothing is merged.
    static func debugRenderAllStates() -> [(String, NSImage)] {
        let states: [BookwormState] = [
            .awake, .sleeping(stage: 3), .digesting, .happy, .curious(count: 7), .hungry, .reading, .error,
        ]
        return states.map { st in
            (st.caseName, BookwormRenderer.smallImage(state: st, frameStep: 0, pointSize: spritePointSize))
        }
    }
}
#endif

extension MenuBarManager: NSMenuDelegate {
    /// "requested 2 hours ago" must be true when the menu opens, not when it was
    /// last rebuilt — AppKit calls this just before showing the menu.
    nonisolated func menuNeedsUpdate(_ menu: NSMenu) {
        MainActor.assumeIsolated { self.refreshExportWaitItems(in: menu) }
    }
}

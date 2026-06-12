import SwiftUI
import AppKit

/// Owns the menu-bar `NSStatusItem`, the bookworm sprite animation, and the
/// dropdown. Driven by ``StatusSnapshot``s pushed in from the App's poll loop
/// (every 30s + immediately after quick actions) and by the live 1s sleep hook
/// (``applySleep(_:)``). All UI work happens on the main actor.
@MainActor
@Observable
final class MenuBarManager: NSObject {
    private(set) var state: BookwormState = .awake

    private var statusItem: NSStatusItem?
    private var frameTimer: Timer?
    private var frameIndex = 0
    private var currentSnapshot: StatusSnapshot?
    private var justFinishedAt: Date?

    // Cache of rendered template images keyed by (case, frame, badge, stage).
    private var imageCache: [String: NSImage] = [:]

    // Quick-action closures injected by the App.
    private var onOpenApp: (() -> Void)?
    private var onRunSleep: (() async -> Void)?
    private var onSaveClipboardURL: (() async -> Void)?

    // MARK: - Setup

    func setup(
        onOpenApp: @escaping () -> Void,
        onRunSleep: @escaping () async -> Void,
        onSaveClipboardURL: @escaping () async -> Void
    ) {
        self.onOpenApp = onOpenApp
        self.onRunSleep = onRunSleep
        self.onSaveClipboardURL = onSaveClipboardURL

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem?.button?.imagePosition = .imageLeading
        transition(to: .awake)
        rebuildMenu()
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
        // Track the running -> idle edge locally so digesting fires even when the
        // 30s poll hasn't run yet.
        let wasRunning = currentSnapshot?.sleep.status == "running"
        if wasRunning, sleep.status != "running", (sleep.error ?? "").isEmpty {
            justFinishedAt = Date()
        }
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
        frameTimer?.invalidate()
        frameTimer = nil
        frameIndex = 0
        renderCurrentFrame()

        let (frames, interval) = BookwormSprites.frames(for: newState)
        // A single-frame animation never needs a timer (keeps CPU at zero for
        // static states); multi-frame ones tick at the state's interval.
        guard frames.count > 1 else { return }
        let timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        timer.tolerance = interval * 0.3   // let the OS coalesce wakeups -> cheaper
        RunLoop.main.add(timer, forMode: .common)
        frameTimer = timer
    }

    private func tick() {
        let (frames, _) = BookwormSprites.frames(for: state)
        guard !frames.isEmpty else { return }
        frameIndex = (frameIndex + 1) % frames.count
        renderCurrentFrame()
    }

    private func renderCurrentFrame() {
        guard let button = statusItem?.button else { return }
        let (frames, _) = BookwormSprites.frames(for: state)
        guard !frames.isEmpty else { return }
        let idx = frameIndex % frames.count
        let base = frames[idx]

        // Compute overlays from the live snapshot.
        var overlays: [[String]] = []
        var badge = 0
        var stage = 0
        switch state {
        case .sleeping(let st):
            stage = st
            overlays.append(BookwormSprites.stageDots(st))
            // Cycle the zZz overlay in lockstep with the base frame.
            overlays.append(BookwormSprites.zzzFrames[idx % BookwormSprites.zzzFrames.count])
        case .curious(let count):
            badge = min(99, count)
            // The numeric badge is drawn as menu-bar text alongside the icon
            // (see rebuildButtonTitle); the corner overlay keeps a compact
            // visual cue on the sprite itself.
            overlays.append(BookwormSprites.badgeOverlay(badge))
        default:
            break
        }

        let key = "\(state.caseName)|\(idx)|\(badge)|\(stage)"
        let image: NSImage
        if let cached = imageCache[key] {
            image = cached
        } else {
            image = BookwormRenderer.image(grid: base, overlays: overlays, pointSize: 18)
            imageCache[key] = image
        }
        button.image = image
        button.imagePosition = .imageLeading

        // Numeric badge text alongside the icon for `curious` (per spec §1.3).
        if case .curious(let count) = state {
            let shown = min(99, count)
            button.title = " \(shown)"
        } else {
            button.title = ""
        }
    }

    // MARK: - Dropdown

    private func rebuildMenu() {
        let menu = NSMenu()

        // Status header (disabled): "<icon> <title> — <detail>".
        let header = NSMenuItem(title: "\(state.title) — \(state.detail)", action: nil, keyEquivalent: "")
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

        menu.addItem(NSMenuItem.separator())

        // Quick actions.
        let isRunning = currentSnapshot?.sleep.status == "running"
        let runItem = NSMenuItem(title: "Run sleep cycle now", action: #selector(runSleepAction), keyEquivalent: "r")
        runItem.target = self
        runItem.isEnabled = !isRunning
        menu.addItem(runItem)

        let saveItem = NSMenuItem(title: "Save clipboard URL", action: #selector(saveClipboardAction), keyEquivalent: "s")
        saveItem.target = self
        menu.addItem(saveItem)

        let openItem = NSMenuItem(title: "Open Cicada", action: #selector(openApp), keyEquivalent: "o")
        openItem.target = self
        menu.addItem(openItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit Cicada", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem?.menu = menu
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

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }

    /// Reads a URL off the clipboard and posts it to the media/sources ingest
    /// endpoint. The endpoint ships in a later wave, so a 404 surfaces a
    /// transient "coming soon" header in the menu rather than crashing.
    func saveClipboardURL() async {
        guard let raw = NSPasteboard.general.string(forType: .string),
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
    /// Returns rendered template images for each state at frame 0 (used in
    /// previews / manual inspection; costs nothing in release builds).
    static func debugRenderAllStates() -> [(String, NSImage)] {
        let states: [BookwormState] = [
            .awake, .sleeping(stage: 3), .digesting, .happy, .curious(count: 7), .hungry,
        ]
        return states.map { st in
            let (frames, _) = BookwormSprites.frames(for: st)
            var overlays: [[String]] = []
            if case .sleeping(let s) = st {
                overlays = [BookwormSprites.stageDots(s), BookwormSprites.zzzFrames[0]]
            }
            if case .curious(let c) = st {
                overlays = [BookwormSprites.badgeOverlay(c)]
            }
            return (st.caseName, BookwormRenderer.image(grid: frames[0], overlays: overlays, pointSize: 18))
        }
    }
}
#endif

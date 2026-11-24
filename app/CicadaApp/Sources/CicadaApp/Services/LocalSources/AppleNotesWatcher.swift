import AppKit
import Foundation
import Observation

/// Apple Notes keeps up on its own once the person connected it (2026-10-23). Before, Notes was read only when someone
/// pressed Refresh, while its Sources row said Connected and "2 h ago" over a source that took in nothing new. The app
/// reads Notes (the `~/Library` rail) through `AppleNotesReader`, so the one Automation prompt names Cicada.
///
/// Never read before the person's own first sync (Connect / Refresh, onboarding's tick). After that: on launch, after a
/// bank switch and every two hours — and only while Notes is already open, because `tell application "Notes"` would
/// launch Notes in the background. G245 (track C1): also when the person opens Notes or brings it to the front
/// (`NSWorkspace`'s launch and activation notices — a notice, never a poll), after a short settle and no sooner than
/// `floor` after the last read, so switching to Notes over and over reads once. The read is the same one, so a locked
/// note's body is still never asked for. Cicada never launches Notes. Disconnect stops all of it and deletes nothing.
@MainActor
@Observable
final class AppleNotesWatcher {
    enum Status: Equatable {
        case off, idle, syncing
        case synced(at: Date)
        case failed(String)
    }

    /// The `/sources/channels` id.
    nonisolated static let channel = "notes"
    nonisolated static let enabledKey = "cicada.notes.enabled"
    nonisolated static let notesBundleId = "com.apple.Notes"

    /// The app's one watcher. Onboarding's drivers and the Sources page's Refresh reach it through `ChannelActions`,
    /// which holds no environment, so it is shared rather than injected; tests make their own.
    static let shared = AppleNotesWatcher()

    private(set) var enabled: Bool
    private(set) var status: Status = .off

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let read: () async throws -> NoteSyncResult
    @ObservationIgnored private let notesRunning: () -> Bool
    @ObservationIgnored private let period: Duration
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let center: NotificationCenter
    @ObservationIgnored private let floor: TimeInterval
    @ObservationIgnored private let settle: Duration
    @ObservationIgnored private let bundleOf: @Sendable (Notification) -> String?
    @ObservationIgnored private var observers: [NSObjectProtocol] = []
    /// When the last read started, whoever asked for it (the two-hour timer, a bank switch, the person, Notes coming
    /// forward): the floor on a read caused by Notes coming forward counts from it.
    @ObservationIgnored private var lastReadStart: Date?
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    /// Bumped by every Disconnect, so a read that started before one never undoes it.
    @ObservationIgnored private var disconnects = 0

    /// No sooner than this after the last read does Notes coming to the front read again.
    nonisolated static let defaultFloor: TimeInterval = 15 * 60

    init(defaults: UserDefaults = .standard, period: Duration = .seconds(2 * 60 * 60),
         now: @escaping () -> Date = Date.init,
         center: NotificationCenter = NSWorkspace.shared.notificationCenter,
         floor: TimeInterval = AppleNotesWatcher.defaultFloor, settle: Duration = .seconds(3),
         bundleOf: @escaping @Sendable (Notification) -> String? = AppleNotesWatcher.bundleId(of:),
         notesRunning: @escaping () -> Bool = AppleNotesWatcher.isNotesRunning,
         read: @escaping () async throws -> NoteSyncResult = { try await AppleNotesReader.syncNow() }) {
        self.defaults = defaults; self.period = period; self.now = now
        self.center = center; self.floor = floor; self.settle = settle; self.bundleOf = bundleOf
        self.notesRunning = notesRunning; self.read = read
        self.enabled = defaults.bool(forKey: Self.enabledKey)
        self.status = enabled ? .idle : .off
    }

    /// The application a workspace launch or activation notice is about.
    nonisolated static func bundleId(of note: Notification) -> String? {
        (note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier
    }

    nonisolated static func isNotesRunning() -> Bool {
        NSWorkspace.shared.runningApplications.contains { $0.bundleIdentifier == notesBundleId }
    }

    /// On launch: keep up only if the person connected before.
    func start() {
        guard enabled else { status = .off; return }
        arm()
        Task { await syncIfOpen() }
    }

    /// The person's own read (Connect, Refresh, onboarding's tick): reads now even with Notes closed — they asked —
    /// and from then on keeps up. A refusal (Automation off) leaves it off and is thrown in the reader's own words.
    /// Only this path turns Notes on; a Disconnect pressed while it reads wins (review of #448).
    @discardableResult
    func syncNow() async throws -> NoteSyncResult {
        let generation = disconnects
        status = .syncing
        lastReadStart = now()
        do {
            let result = try await read()
            guard generation == disconnects else { status = .off; return result }   // disconnected meanwhile
            if !enabled {
                enabled = true
                defaults.set(true, forKey: Self.enabledKey)
            }
            arm()
            status = .synced(at: now())
            return result
        } catch {
            status = enabled && generation == disconnects ? .failed(error.localizedDescription) : .off
            throw error
        }
    }

    func disconnect() {
        disconnects += 1
        enabled = false
        defaults.set(false, forKey: Self.enabledKey)
        periodic?.cancel()
        periodic = nil
        stopObserving()
        status = .off
    }

    /// A bank switch: the new memory gets the notes too (a demo bank answers 409, said as a failure).
    func bankChanged() async { await syncIfOpen() }

    /// The unattended read: only while on, one at a time, and only with Notes already open. It never turns Notes on:
    /// a Disconnect that lands while it reads leaves it off, unarmed, its status untouched by the late answer.
    func syncIfOpen() async {
        guard enabled, !inFlight, notesRunning() else { return }
        inFlight = true
        defer { inFlight = false }
        let generation = disconnects
        status = .syncing
        lastReadStart = now()
        do {
            _ = try await read()
            guard enabled, generation == disconnects else { return }
            status = .synced(at: now())
        } catch {
            guard enabled, generation == disconnects else { return }
            status = .failed(error.localizedDescription)
        }
    }

    /// Notes was opened or came to the front (`NSWorkspace`'s notices; tests call it with a bundle id). Another app's
    /// notice is ignored; so is one inside `floor` of the last read. After `settle` (a launching Notes is not ready to
    /// answer at once) it is the same unattended read as the timer's — which still reads only with Notes open.
    func workspaceEvent(bundleId: String?) async {
        guard enabled, bundleId == Self.notesBundleId else { return }
        if let last = lastReadStart, now().timeIntervalSince(last) < floor { return }
        let generation = disconnects
        try? await Task.sleep(for: settle)
        guard enabled, generation == disconnects else { return }
        if let last = lastReadStart, now().timeIntervalSince(last) < floor { return }   // a read began while it settled
        await syncIfOpen()
    }

    /// Whether the two-hour timer is set (tests: a Disconnect during a read leaves it unset).
    var isArmed: Bool { periodic != nil }

    private func observe() {
        guard observers.isEmpty else { return }
        for name in [NSWorkspace.didLaunchApplicationNotification, NSWorkspace.didActivateApplicationNotification] {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                let bundleId = self?.bundleOf(note)
                Task { @MainActor in await self?.workspaceEvent(bundleId: bundleId) }
            })
        }
    }

    private func stopObserving() {
        observers.forEach { center.removeObserver($0) }
        observers = []
    }

    private func arm() {
        observe()
        guard periodic == nil else { return }
        periodic = Task { [weak self, period] in
            while !Task.isCancelled {
                try? await Task.sleep(for: period)
                guard !Task.isCancelled else { return }
                await self?.syncIfOpen()
            }
        }
    }
}

import AppKit
import Foundation
import Observation

/// Apple Notes keeps up on its own once the person connected it (2026-10-23). Before, Notes was read only when someone
/// pressed Refresh, while its Sources row said Connected and "2 h ago" over a source that took in nothing new. The app
/// reads Notes (the `~/Library` rail) through `AppleNotesReader`, so the one Automation prompt names Cicada.
///
/// Never read before the person's own first sync (Connect / Refresh, onboarding's tick). After that: on launch, after a
/// bank switch and every two hours — and only while Notes is already open, because `tell application "Notes"` would
/// launch Notes in the background. Disconnect stops all of it and deletes nothing.
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
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    /// Bumped by every Disconnect, so a read that started before one never undoes it.
    @ObservationIgnored private var disconnects = 0

    init(defaults: UserDefaults = .standard, period: Duration = .seconds(2 * 60 * 60),
         now: @escaping () -> Date = Date.init,
         notesRunning: @escaping () -> Bool = AppleNotesWatcher.isNotesRunning,
         read: @escaping () async throws -> NoteSyncResult = { try await AppleNotesReader.syncNow() }) {
        self.defaults = defaults; self.period = period; self.now = now
        self.notesRunning = notesRunning; self.read = read
        self.enabled = defaults.bool(forKey: Self.enabledKey)
        self.status = enabled ? .idle : .off
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
        do {
            _ = try await read()
            guard enabled, generation == disconnects else { return }
            status = .synced(at: now())
        } catch {
            guard enabled, generation == disconnects else { return }
            status = .failed(error.localizedDescription)
        }
    }

    /// Whether the two-hour timer is set (tests: a Disconnect during a read leaves it unset).
    var isArmed: Bool { periodic != nil }

    private func arm() {
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

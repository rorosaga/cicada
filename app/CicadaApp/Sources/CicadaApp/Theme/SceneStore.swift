import AppKit
import Observation

/// Round-4 D4 (R-FA6, C7) — the clock's current scene, observable, so Home's band and the Welcome's hero repaint when
/// the sun crosses a line. It holds the CLOCK only — the sky's `phase` (C7) and, since round-4 T-Home (R-HO1), the
/// painting's `time` (day · afternoon · night) — plus the power state a living painting needs (Low Power turns it
/// gentle, R-HO7). The person's Scene choice stays in `@AppStorage` and `HeroScenePreference.time(clock:)` resolves
/// the two. It looks again at the next boundary or within the hour,
/// whichever is first, and at once on a time-zone change or a wake — `ThemeStore.observeSystemAppearance`'s shape:
/// started once at app scope, never from `init`, so a test's store never listens to the real system.
@MainActor
@Observable
final class SceneStore {
    static let shared = SceneStore()

    private(set) var phase: CicadaTheme.SkyPhase
    /// Round-4 T-Home (R-HO1) — the clock's painting: day, the afternoon's golden hour, or night.
    private(set) var time: SceneTime
    /// Low Power Mode turns every living painting gentle and halves its frame rate (DR-66, R-HO7).
    private(set) var lowPower: Bool

    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let timeZone: () -> TimeZone
    @ObservationIgnored private let table: [String: GeoPoint]
    @ObservationIgnored private let readLowPower: () -> Bool
    @ObservationIgnored private var tick: Task<Void, Never>?
    @ObservationIgnored private var observers: [(NotificationCenter, NSObjectProtocol)] = []

    init(now: @escaping () -> Date = Date.init, timeZone: @escaping () -> TimeZone = { .autoupdatingCurrent },
         table: [String: GeoPoint] = TimeZoneCoordinates.bundled,
         lowPower: @escaping () -> Bool = { ProcessInfo.processInfo.isLowPowerModeEnabled }) {
        self.now = now
        self.timeZone = timeZone
        self.table = table
        readLowPower = lowPower
        let at = now(), zone = timeZone()
        phase = SceneClock.phase(at: at, timeZone: zone, table: table)
        time = SceneClock.time(at: at, timeZone: zone, table: table)
        self.lowPower = lowPower()
    }

    func start() {
        guard observers.isEmpty else { return }
        let local = NotificationCenter.default
        observers.append((local, local.addObserver(forName: .NSSystemTimeZoneDidChange, object: nil, queue: .main) { [weak self] _ in
            NSTimeZone.resetSystemTimeZone()
            MainActor.assumeIsolated { self?.refresh() }
        }))
        let workspace = NSWorkspace.shared.notificationCenter
        observers.append((workspace, workspace.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }))
        observers.append((local, local.addObserver(forName: .NSProcessInfoPowerStateDidChange, object: nil,
                                                   queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refreshPower() }
        }))
        schedule()
    }

    func refresh() {
        let at = now(), zone = timeZone()
        let nextPhase = SceneClock.phase(at: at, timeZone: zone, table: table)
        if nextPhase != phase { phase = nextPhase }
        let nextTime = SceneClock.time(at: at, timeZone: zone, table: table)
        if nextTime != time { time = nextTime }
        schedule()
    }

    /// R-HO7 — re-read Low Power Mode; only a real change is published, so an idle notification repaints nothing.
    func refreshPower() {
        let next = readLowPower()
        if next != lowPower { lowPower = next }
    }

    /// Seconds until the next look: the next crossing, capped at an hour, never under a second.
    func delayUntilNextCheck() -> TimeInterval {
        let current = now()
        let boundary = SceneClock.nextBoundary(after: current, timeZone: timeZone(), table: table)
        return min(max(boundary.timeIntervalSince(current), 1), SceneClock.maxRecheck)
    }

    private func schedule() {
        tick?.cancel()
        let delay = delayUntilNextCheck()
        tick = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            self?.refresh()
        }
    }
}

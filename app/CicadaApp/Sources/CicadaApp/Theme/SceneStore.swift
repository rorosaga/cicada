import AppKit
import Observation

/// Round-4 D4 (R-FA6, C7) — the clock's current scene, observable, so Home's band and the Welcome's hero repaint when
/// the sun crosses a line. It holds the CLOCK only; the person's Scene choice stays in `@AppStorage` and
/// `HeroScenePreference.scene(clock:)` resolves the two. It looks again at the next boundary or within the hour,
/// whichever is first, and at once on a time-zone change or a wake — `ThemeStore.observeSystemAppearance`'s shape:
/// started once at app scope, never from `init`, so a test's store never listens to the real system.
@MainActor
@Observable
final class SceneStore {
    static let shared = SceneStore()

    private(set) var phase: CicadaTheme.SkyPhase

    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let timeZone: () -> TimeZone
    @ObservationIgnored private let table: [String: GeoPoint]
    @ObservationIgnored private var tick: Task<Void, Never>?
    @ObservationIgnored private var observers: [(NotificationCenter, NSObjectProtocol)] = []

    init(now: @escaping () -> Date = Date.init, timeZone: @escaping () -> TimeZone = { .autoupdatingCurrent },
         table: [String: GeoPoint] = TimeZoneCoordinates.bundled) {
        self.now = now
        self.timeZone = timeZone
        self.table = table
        phase = SceneClock.phase(at: now(), timeZone: timeZone(), table: table)
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
        schedule()
    }

    func refresh() {
        let next = SceneClock.phase(at: now(), timeZone: timeZone(), table: table)
        if next != phase { phase = next }
        schedule()
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

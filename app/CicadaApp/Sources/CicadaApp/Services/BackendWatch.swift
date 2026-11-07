import Foundation

/// Production blocker (tester report 2026-11-06) — the app and its backend, told apart in words.
///
/// A backend that dies under a running app used to leave no sign: nothing listening, nothing restarting it, and the
/// pages read the silence as an empty memory. This file is the pure half of the answer: what one look at the backend
/// found (`BackendReading`), what the person is told (`BackendReach`, only after the look has held long enough to be
/// true), the bounded restart of a backend this app started (`BackendRestartPolicy`), and the one line the shell shows
/// (`BackendBanner`). `BackendWatch` drives them; the Store carries the result so every page reads one predicate.

/// What the person can act on, and nothing finer.
enum BackendReach: Equatable, Sendable {
    /// Answering — or merely slow. A slow answer (Sleep busy, a heavy route) is never "down" (ruling 66).
    case up
    /// Nothing listening, or silent past `BackendSilence`'s bound.
    case notAnswering
    /// The port answers, and what answers is not Cicada.
    case portHeld
    /// A Cicada answers and does not accept this app's key.
    case tokenRefused
}

/// One look at the backend's `/healthz`.
enum BackendReading: Equatable, Sendable {
    /// Cicada. `fullAccess` is false when the answer is the token-less one (its paths and counts withheld).
    case cicada(fullAccess: Bool)
    /// Something answered, and it is not Cicada.
    case foreign
    /// Nothing listening.
    case noAnswer
    /// A listener that did not answer in time, or whose answer broke off.
    case slow

    /// The look as `BackendSilence` and the updater's probe name it — one vocabulary for "is it hung".
    var silenceAnswer: SleepProbe.Answer {
        switch self {
        case .noAnswer: .noAnswer
        case .slow: .slow
        case .cicada, .foreign: .idle
        }
    }

    /// A failed request, read the way `SleepProbe.classify` reads it, with one addition: a connection that was made and
    /// then answered with something that is not HTTP is a stranger on the port.
    static func classify(error: Error) -> BackendReading {
        if let api = error as? APIError {
            switch api {
            case .httpError, .decodingError: return .foreign
            case .serverUnreachable: return .slow
            }
        }
        if let url = error as? URLError,
           [.cannotParseResponse, .badServerResponse, .secureConnectionFailed, .serverCertificateUntrusted,
            .clientCertificateRejected].contains(url.code) { return .foreign }
        switch SleepProbe.classify(statusCode: nil, body: nil, error: error) {
        case .noAnswer: return .noAnswer
        default: return .slow
        }
    }
}

/// Turns looks into what the person is told. Pure: the clock is passed in.
///
/// A look is not a fact. The backend takes seconds to start, a restart takes seconds more, and a single odd answer is
/// not worth a sentence — so "not answering" waits `grace` seconds from the last real answer (or from launch), and
/// "port held" and "key refused" wait for two looks in a row. Nothing is shown the moment the app opens.
struct BackendReachTracker: Equatable {
    static let grace: TimeInterval = 20
    static let confirmations = 2

    private(set) var reach: BackendReach = .up
    private var lastAnswer: Date
    private var pending: BackendReach?
    private var streak = 0

    init(now: Date) { lastAnswer = now }

    /// The event stream is open: the backend is answering, whatever the last look said.
    mutating func answered(now: Date) {
        lastAnswer = now
        pending = nil
        streak = 0
        reach = .up
    }

    /// `hung` is `BackendSilence`'s verdict — three looks ten minutes apart over two hours — and the only thing that
    /// turns a slow listener into "not answering".
    @discardableResult
    mutating func observe(_ reading: BackendReading, now: Date, hung: Bool = false) -> BackendReach {
        switch reading {
        case .cicada(fullAccess: true):
            answered(now: now)
        case .cicada(fullAccess: false):
            lastAnswer = now
            confirm(.tokenRefused)
        case .foreign:
            lastAnswer = now
            confirm(.portHeld)
        case .noAnswer:
            pending = nil
            streak = 0
            if now.timeIntervalSince(lastAnswer) >= Self.grace { reach = .notAnswering }
        case .slow:
            pending = nil
            streak = 0
            reach = hung ? .notAnswering : .up
        }
        return reach
    }

    private mutating func confirm(_ kind: BackendReach) {
        streak = pending == kind ? streak + 1 : 1
        pending = kind
        if streak >= Self.confirmations { reach = kind }
    }
}

/// When a backend this app started dies, how soon to start it again, and when to stop trying.
///
/// Bounded and backing off, so a backend that fails at start is not hammered: five tries over roughly two minutes, then
/// it stays down until the person asks (`BackendProcess.restartNow`). A child that ran for `healthyRun` or longer was
/// working, so what ended it was not a start failure and the count begins again.
struct BackendRestartPolicy: Equatable {
    enum Decision: Equatable { case restart(after: TimeInterval), giveUp }

    static let delays: [TimeInterval] = [2, 5, 15, 30, 60]
    static let healthyRun: TimeInterval = 60

    private(set) var failures = 0

    mutating func childEnded(ranFor: TimeInterval) -> Decision {
        if ranFor >= Self.healthyRun { failures = 0 }
        guard failures < Self.delays.count else { return .giveUp }
        defer { failures += 1 }
        return .restart(after: Self.delays[failures])
    }
}

/// The one line the shell shows while the backend is not answering, and the one thing that helps.
struct BackendBanner: Equatable {
    let line: String
    /// nil while the app is already restarting it: nothing to click.
    let action: String?

    static func make(reach: BackendReach, retrying: Bool, onServer: Bool, port: Int) -> BackendBanner? {
        switch reach {
        case .up:
            return nil
        case .notAnswering:
            if onServer { return BackendBanner(line: Copy.Reach.serverSilent, action: Copy.Reach.tryAgain) }
            if retrying { return BackendBanner(line: Copy.Reach.restarting, action: nil) }
            return BackendBanner(line: Copy.Reach.stopped, action: Copy.Reach.restart)
        case .portHeld:
            return BackendBanner(line: Copy.Reach.portHeld(port), action: Copy.Reach.tryAgain)
        case .tokenRefused:
            return BackendBanner(line: onServer ? Copy.Reach.serverKeyRefused : Copy.Reach.keyRefused,
                                 action: onServer ? Copy.Reach.tryAgain : Copy.Reach.restart)
        }
    }
}

/// Watches the backend while the event stream is closed, and tells the Store what it found.
///
/// **Why only while the stream is closed.** The stream pings every 15 s, so an open stream is the best proof the
/// backend is answering and costs nothing; `/healthz` counts the bank's folders, so asking it on a timer from a healthy
/// app would tax a large memory for no news. The look is taken only in the gap, every `interval`, and stops the moment
/// the stream is back. Slow is not down: a silent-but-listening backend is judged by `BackendSilence`, the bound the
/// updater already uses (ruling 66), not a second one.
@MainActor
@Observable
final class BackendWatch {
    private(set) var reach: BackendReach = .up
    /// True while the app is already restarting a backend it started.
    var retrying: Bool { isRetrying() }
    let port: Int
    let onServer: Bool

    @ObservationIgnored private var tracker: BackendReachTracker
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private let probe: () async -> BackendReading
    @ObservationIgnored private let noteSilence: (SleepProbe.Answer) -> Bool
    @ObservationIgnored private let publish: (BackendReach) -> Void
    @ObservationIgnored private let isRetrying: () -> Bool
    @ObservationIgnored private let restart: () async -> Void
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let interval: Duration

    init(port: Int, onServer: Bool,
         probe: @escaping () async -> BackendReading,
         noteSilence: @escaping (SleepProbe.Answer) -> Bool,
         publish: @escaping (BackendReach) -> Void,
         isRetrying: @escaping () -> Bool,
         restart: @escaping () async -> Void,
         now: @escaping () -> Date = Date.init,
         interval: Duration = .seconds(4)) {
        self.port = port
        self.onServer = onServer
        self.probe = probe
        self.noteSilence = noteSilence
        self.publish = publish
        self.isRetrying = isRetrying
        self.restart = restart
        self.now = now
        self.interval = interval
        tracker = BackendReachTracker(now: now())
    }

    var banner: BackendBanner? {
        BackendBanner.make(reach: reach, retrying: retrying, onServer: onServer, port: port)
    }

    /// The event stream opened (`true`) or dropped (`false`). Called from the app's one `store.isConnected` observer.
    func connectionChanged(_ connected: Bool) {
        task?.cancel()
        task = nil
        if connected {
            _ = noteSilence(.idle)   // a real answer ends any silent series
            tracker.answered(now: now())
            set(.up)
            return
        }
        task = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.step()
                try? await Task.sleep(for: self.interval)
            }
        }
    }

    /// One look.
    func step() async {
        let reading = await probe()
        guard !Task.isCancelled else { return }
        let hung = noteSilence(reading.silenceAnswer)
        set(tracker.observe(reading, now: now(), hung: hung))
    }

    /// The banner's button: the one action that helps, then a look at once.
    func fix() async {
        await restart()
        await step()
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func set(_ next: BackendReach) {
        guard next != reach else { return }
        reach = next
        publish(next)
    }
}

extension BackendWatch {
    /// The look the app takes of its own backend: `/healthz`, which is open and tells Cicada from a stranger by its
    /// shape, and which gives its paths and counts only to a caller whose key it accepts. A key the cache holds may
    /// be one a restarted backend replaced, so a token-less answer is asked once more after the cache is dropped.
    static func liveProbe(api: APIClient = .shared, timeout: TimeInterval = 5) -> () async -> BackendReading {
        {
            do {
                var health = try await api.fetchHealth(timeout: timeout)
                if health.version != nil, health.memoryRoot == nil {
                    APIClient.invalidateToken()
                    health = try await api.fetchHealth(timeout: timeout)
                }
                guard health.version != nil else { return .foreign }
                return .cicada(fullAccess: health.memoryRoot != nil)
            } catch {
                return BackendReading.classify(error: error)
            }
        }
    }
}

import AppKit
import Foundation
import Observation

// G181 phase 3 — the person's devices (`GET /devices`), where memory came from, and the connection this app uses.
// None of this is a Store domain: `/devices` lives outside every bank (`$CICADA_HOME/devices`), so it is read on
// demand and kept in memory (`DeviceDirectory`), like the remote connectors (R-R33).

/// One device the person issued a token for: ids, names and times only — never a token or its hash.
struct DeviceRecord: Codable, Hashable, Identifiable, Sendable {
    let id: String
    let name: String
    let createdAt: String
    var revokedAt: String? = nil
    /// When its token last reached the server (stamped at most once a minute) — "last seen".
    var lastUsedAt: String? = nil
    var useCount: Int = 0
    var active: Bool = true
    /// The device whose token asked: this Mac, when the app is a server's client.
    var current: Bool = false

    enum CodingKeys: String, CodingKey { case id, name, createdAt, revokedAt, lastUsedAt, useCount, active, current }

    init(id: String, name: String, createdAt: String, revokedAt: String? = nil, lastUsedAt: String? = nil,
         useCount: Int = 0, active: Bool = true, current: Bool = false) {
        self.id = id; self.name = name; self.createdAt = createdAt; self.revokedAt = revokedAt
        self.lastUsedAt = lastUsedAt; self.useCount = useCount; self.active = active; self.current = current
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        createdAt = (try? c.decode(String.self, forKey: .createdAt)) ?? ""
        revokedAt = (try? c.decodeIfPresent(String.self, forKey: .revokedAt)) ?? nil
        lastUsedAt = (try? c.decodeIfPresent(String.self, forKey: .lastUsedAt)) ?? nil
        useCount = (try? c.decode(Int.self, forKey: .useCount)) ?? 0
        active = (try? c.decode(Bool.self, forKey: .active)) ?? (revokedAt == nil)
        // An older server (phase 2) never sends it.
        current = (try? c.decode(Bool.self, forKey: .current)) ?? false
    }
}

struct DeviceList: Codable, Sendable { let devices: [DeviceRecord] }

/// `POST /devices`: the record and its token — the one answer that ever holds it.
struct DeviceCreated: Codable, Identifiable, Sendable {
    let device: DeviceRecord
    let token: String
    var id: String { device.id }
}

/// What the Devices page and the directory ask the backend; `APIClient` is the live one, tests hand in a double.
protocol DevicesAPI: Sendable {
    func fetchDevices() async throws -> [DeviceRecord]
    func createDevice(name: String) async throws -> DeviceCreated
    func revokeDevice(id: String) async throws -> DeviceRecord
    func fetchHealth() async throws -> HealthSnapshot
    func outboxCount() async -> Int
    func flushOutbox() async -> ReaderOutbox.FlushResult
    /// D3 (G202): what waits on this Mac — the readers' outbox and the hooks' spool — for the server in use (`here`)
    /// and for one this Mac no longer uses (`elsewhere`).
    func waitingCaptures() async -> CaptureWait
}

/// What waits on this Mac to be sent (D3, G202), counted by the server it was meant for.
struct CaptureWait: Equatable, Sendable {
    var here = 0
    var elsewhere = 0
}

extension DevicesAPI {
    func waitingCaptures() async -> CaptureWait { CaptureWait(here: await outboxCount()) }
}

extension APIClient: DevicesAPI {
    /// `GET /devices` — the master token on this Mac, or this device's own token on a server (read-only there).
    func fetchDevices() async throws -> [DeviceRecord] {
        let list: DeviceList = try await getDevicesList()
        return list.devices
    }

    func outboxCount() async -> Int { await outbox.count() }

    func waitingCaptures() async -> CaptureWait {
        let base: String? = connection.isServer ? baseURL : nil
        let app = await outbox.waiting(for: base)
        let hooks = HookSpool.waiting(cicadaHome: cicadaHome, base: base)
        return CaptureWait(here: app.here + hooks.here, elsewhere: app.elsewhere + hooks.elsewhere)
    }
}

// MARK: - Where it came from

/// One quiet word for where a conversation, a save or a claim came from (G181 phase 3): the device's name, "this Mac"
/// for this app's own device, or — when this app is a server's client — "this server" for what the server's own
/// machine wrote. On This Mac, what this Mac wrote says nothing (it is everything, and saying so everywhere is noise).
enum DeviceOrigin {
    static func label(device: String?, connection: ServerConnection, names: [String: String],
                      myDevice: String?) -> String? {
        let id = device?.trimmingCharacters(in: .whitespaces) ?? ""
        if id.isEmpty { return connection.isServer ? Copy.Devices.thisServer : nil }
        if let myDevice, id == myDevice { return Copy.Devices.thisDevice }
        return names[id] ?? Copy.Devices.aDevice
    }

    /// The parenthetical the bank picker shows on a server: "on home-server.example.net".
    static func bankHost(_ connection: ServerConnection) -> String? {
        connection.host.map(Copy.Devices.onServer)
    }
}

/// The devices this app knows by name, read once per session on demand and refreshed by the Devices page — not a Store
/// domain (it lives outside every bank), so it says so and caches in memory.
@Observable
@MainActor
final class DeviceDirectory {
    static let shared = DeviceDirectory(api: APIClient.shared, connection: APIClient.shared.connection,
                                        myDevice: APIClient.shared.connection.isServer
                                            ? ServerConnection.deviceId(fromToken: ServerConnection.deviceToken()) : nil)

    private(set) var names: [String: String] = [:]
    private(set) var loaded = false
    let connection: ServerConnection
    /// This app's own device id, from its token (server mode only).
    let myDevice: String?
    @ObservationIgnored private let api: any DevicesAPI
    @ObservationIgnored private var loading: Task<Void, Never>?

    init(api: any DevicesAPI, connection: ServerConnection, myDevice: String?) {
        self.api = api
        self.connection = connection
        self.myDevice = myDevice
    }

    func label(for device: String?) -> String? {
        DeviceOrigin.label(device: device, connection: connection, names: names, myDevice: myDevice)
    }

    /// Ask once; a surface that shows a device id calls this on appear. A failure leaves "a device" in place of a name.
    func ensureLoaded() {
        guard !loaded, loading == nil else { return }
        loading = Task { @MainActor in
            if let rows = try? await api.fetchDevices() { self.update(rows) }
            self.loaded = true
            self.loading = nil
        }
    }

    func update(_ rows: [DeviceRecord]) {
        names = Dictionary(rows.map { ($0.id, $0.name) }, uniquingKeysWith: { first, _ in first })
        loaded = true
    }
}

// MARK: - The Devices page

@Observable
@MainActor
final class DevicesPageModel {
    let connection: ServerConnection
    @ObservationIgnored private let api: any DevicesAPI
    @ObservationIgnored private let directory: DeviceDirectory?
    @ObservationIgnored private let now: () -> Date

    private(set) var devices: [DeviceRecord] = []
    private(set) var loadFailed = false
    private(set) var reachable: Bool?
    private(set) var lastCheckedAt: Date?
    private(set) var lastReachableAt: Date?
    private(set) var waiting = 0
    /// Captures waiting on this Mac for a server it no longer uses (D1/D2/D3, G202): kept, sent only there.
    private(set) var waitingElsewhere = 0
    private(set) var problem: String?
    var created: DeviceCreated?

    init(api: any DevicesAPI, connection: ServerConnection, directory: DeviceDirectory? = nil,
         now: @escaping () -> Date = { Date() }) {
        self.api = api
        self.connection = connection
        self.directory = directory
        self.now = now
    }

    /// On This Mac the app holds the master token, so it may add and revoke; a server's client only reads (ruling 28.1:
    /// issuing and revoking are acts of the person on the server).
    var canManage: Bool { !connection.isServer }

    /// The running connection, named only when it is not this Mac: on This Mac the choice above it already says so
    /// (DR-38), and a server picked but not yet used must not read as the one in use.
    var connectionLine: String? {
        switch connection.mode {
        case .thisMac: nil
        case .server(let url): Copy.Devices.connectionServer(url.host ?? url.absoluteString)
        case .invalid: Copy.Devices.connectionInvalid
        }
    }

    /// "Reachable · checked 2 minutes ago" — recomputed by the view each minute so "ago" is true when read.
    func statusLine(at date: Date, locale: Locale = .autoupdatingCurrent) -> String? {
        guard connection.isServer, let reachable else { return nil }
        let rel = { (d: Date) in DevicesText.relative(d, now: date, locale: locale) }
        if reachable, let checked = lastCheckedAt { return Copy.Devices.reachable(rel(checked)) }
        return Copy.Devices.unreachable(lastReachableAt.map(rel))
    }

    /// The connection's answer, the devices and what waits — each failure kept apart, nothing blanks.
    func refresh() async {
        let checked = now()
        let health = try? await api.fetchHealth()
        lastCheckedAt = checked
        reachable = health != nil
        if health != nil { lastReachableAt = checked }
        do {
            let rows = try await api.fetchDevices()
            devices = rows
            loadFailed = false
            directory?.update(rows)
        } catch {
            loadFailed = true
        }
        await countWaiting()
    }

    private func countWaiting() async {
        let wait = await api.waitingCaptures()
        waiting = connection.isServer ? wait.here : 0
        waitingElsewhere = wait.elsewhere
    }

    func add(name: String) async {
        problem = nil
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canManage, !clean.isEmpty else { return }
        do {
            created = try await api.createDevice(name: clean)
            await refresh()
        } catch {
            problem = error.localizedDescription
        }
    }

    func revoke(_ device: DeviceRecord) async {
        problem = nil
        guard canManage else { return }
        do {
            _ = try await api.revokeDevice(id: device.id)
            await refresh()
        } catch {
            problem = error.localizedDescription
        }
    }

    func sendNow() async {
        _ = await api.flushOutbox()
        await countWaiting()
    }

    func detail(_ device: DeviceRecord, at date: Date, locale: Locale = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        if let made = DevicesText.date(device.createdAt) {
            parts.append(Copy.Devices.added(DevicesText.day(made, locale: locale)))
        }
        if let revoked = device.revokedAt.flatMap(DevicesText.date) {
            parts.append(Copy.Devices.revokedOn(DevicesText.day(revoked, locale: locale)))
        } else if let seen = device.lastUsedAt.flatMap(DevicesText.date) {
            parts.append(Copy.Devices.lastSeen(DevicesText.relative(seen, now: date, locale: locale)))
        } else {
            parts.append(Copy.Devices.neverSeen)
        }
        return parts.joined(separator: " · ")
    }
}

enum DevicesText {
    static func date(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: iso) { return d }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: iso)
    }

    static func relative(_ date: Date, now: Date, locale: Locale) -> String {
        if abs(now.timeIntervalSince(date)) < 60 { return "just now" }
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .full
        f.locale = locale
        return f.localizedString(for: date, relativeTo: now)
    }

    static func day(_ date: Date, locale: Locale) -> String {
        let f = DateFormatter()
        f.locale = locale
        f.setLocalizedDateFormatFromTemplate("d MMM yyyy")
        return f.string(from: date)
    }
}

// MARK: - Settings → Devices & access: choosing a server

/// What a candidate server said before anything is saved.
enum ServerCheck: Equatable {
    case ok(deviceName: String?)
    case unreachable
    case badToken
    case notDeviceToken
    case notCicada
    case failed(Int)
    case badAddress(String)

    var message: String {
        switch self {
        case .ok: ""
        case .unreachable: Copy.Devices.checkUnreachable
        case .badToken: Copy.Devices.checkBadToken
        case .notDeviceToken: Copy.Devices.checkNotDevice
        case .notCicada: Copy.Devices.checkNotCicada
        case .failed(let code): Copy.Devices.checkFailed(code)
        case .badAddress(let why): why
        }
    }
}

enum ServerProbe {
    /// `GET /healthz` (open) proves it is a Cicada backend; `GET /devices` with the token proves the token and names
    /// this device (`current`). A phase-2 server refuses that read (403), so `GET /banks` proves the token instead.
    static func check(base: URL, token: String, session: URLSession = ServerProbe.session) async -> ServerCheck {
        guard ServerConnection.looksLikeDeviceToken(token) else { return .notDeviceToken }
        func get(_ path: String, auth: Bool) async -> (Int, Data)? {
            var request = URLRequest(url: base.appendingPathComponent(String(path.dropFirst())))
            request.timeoutInterval = 6
            if auth {
                request.setValue("Bearer \(token.trimmingCharacters(in: .whitespacesAndNewlines))",
                                 forHTTPHeaderField: "Authorization")
            }
            guard let (data, response) = try? await session.data(for: request),
                  let http = response as? HTTPURLResponse else { return nil }
            return (http.statusCode, data)
        }
        guard let (healthCode, healthData) = await get("/healthz", auth: false) else { return .unreachable }
        guard healthCode == 200,
              let object = try? JSONSerialization.jsonObject(with: healthData) as? [String: Any],
              object["version"] != nil || object["memoryRoot"] != nil else { return .notCicada }
        guard let (code, data) = await get("/devices", auth: true) else { return .unreachable }
        switch code {
        case 200:
            let rows = (try? JSONDecoder().decode(DeviceList.self, from: data))?.devices ?? []
            return .ok(deviceName: rows.first(where: \.current)?.name)
        case 401: return .badToken
        case 403:
            guard let (banks, _) = await get("/banks", auth: true) else { return .unreachable }
            if banks == 200 { return .ok(deviceName: nil) }
            return banks == 401 ? .badToken : .failed(banks)
        default: return .failed(code)
        }
    }

    static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.httpCookieStorage = nil
        return URLSession(configuration: config)
    }()
}

@Observable
@MainActor
final class ConnectionSettingsModel {
    enum Choice: String, CaseIterable, Identifiable {
        case thisMac, server
        var id: String { rawValue }
        var label: String { self == .thisMac ? Copy.Devices.thisMac : Copy.Devices.aServer }
    }

    /// What the app runs with now (decided at launch).
    let running: ServerConnection
    @ObservationIgnored private let cicadaHome: URL
    @ObservationIgnored private let environment: [String: String]
    @ObservationIgnored private let probe: (URL, String) async -> ServerCheck

    var choice: Choice
    var address: String
    var token = ""
    private(set) var checking = false
    private(set) var result: ServerCheck?
    /// What is on disk now — differs from `running` once the person saved a change.
    private(set) var saved: ServerConnection
    private(set) var tokenSaved: Bool

    init(running: ServerConnection = .current, cicadaHome: URL = CicadaRuntime.current.cicadaHome,
         environment: [String: String] = ProcessInfo.processInfo.environment,
         probe: @escaping (URL, String) async -> ServerCheck = { await ServerProbe.check(base: $0, token: $1) }) {
        self.running = running
        self.cicadaHome = cicadaHome
        self.environment = environment
        self.probe = probe
        let onDisk = ServerConnection.resolve(environment: environment, cicadaHome: cicadaHome, includingPending: true)
        saved = onDisk
        choice = onDisk.isServer ? .server : .thisMac
        address = onDisk.serverURL?.absoluteString
            ?? ServerConnection.readText(cicadaHome.appendingPathComponent(ServerConnection.apiBaseFile))?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        tokenSaved = ServerConnection.deviceToken(environment: environment, cicadaHome: cicadaHome) != nil
    }

    /// The environment decides and the app cannot change it.
    var lockedByEnvironment: Bool { running.source == .environment }
    var needsRestart: Bool { saved != running }

    var pendingLine: String? {
        guard needsRestart else { return nil }
        if let host = saved.host { return Copy.Devices.pendingServer(host) }
        return saved.isServer ? nil : Copy.Devices.pendingThisMac
    }

    /// Check the address and token against the server; save both only when it answers as a Cicada server that accepts
    /// the token. Nothing is written on a failed check.
    func checkAndUse() async {
        result = nil
        let url: URL
        switch ServerConnection.validate(address) {
        case .success(let ok): url = ok
        case .failure(let error): result = .badAddress(error.errorDescription ?? ""); return
        }
        let pasted = token.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidate = pasted.isEmpty ? (ServerConnection.deviceToken(environment: environment,
                                                                        cicadaHome: cicadaHome) ?? "") : pasted
        checking = true
        let answer = await probe(url, candidate)
        checking = false
        result = answer
        guard case .ok = answer else { return }
        do {
            try ServerConnection.save(base: url, token: pasted.isEmpty ? nil : pasted, cicadaHome: cicadaHome)
            token = ""
            tokenSaved = true
            saved = ServerConnection.resolve(environment: environment, cicadaHome: cicadaHome, includingPending: true)
            address = saved.serverURL?.absoluteString ?? address
        } catch {
            result = .failed(-1)
        }
    }

    func useThisMac() {
        result = nil
        do {
            try ServerConnection.forget(cicadaHome: cicadaHome)
            saved = ServerConnection.resolve(environment: environment, cicadaHome: cicadaHome, includingPending: true)
            choice = .thisMac
        } catch {
            result = .failed(-1)
        }
    }
}

/// Close and open Cicada again, so the new connection is used everywhere at once. A bundle only; a `swift run` build
/// says so in words (`Copy.Devices.restartByHand`).
enum AppRelaunch {
    static var canRelaunch: Bool { Bundle.main.bundlePath.hasSuffix(".app") }

    @MainActor
    static func relaunch() {
        guard canRelaunch else { return }
        let path = Bundle.main.bundlePath
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        // `$0` is the bundle path, never interpolated into the script.
        task.arguments = ["-c", "sleep 1; /usr/bin/open -n \"$0\"", path]
        try? task.run()
        NSApp.terminate(nil)
    }
}

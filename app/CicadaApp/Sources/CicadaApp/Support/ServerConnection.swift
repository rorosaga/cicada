import CryptoKit
import Foundation

/// G181 phase 3 — where this app's memory lives: *This Mac* (its own backend on loopback, as always) or *A server* the
/// person runs elsewhere and reaches over an overlay of their own (a tailnet name, an SSH tunnel). Decided once at
/// launch, like `CicadaRuntime`; a change in Settings → General is written to disk and takes effect when Cicada opens
/// again, so the Store, its disk cache, the event stream and every reader switch together, never half-way.
///
/// One setting for the whole Mac, shared with the hooks, the stdio MCP server and the `cicada` command
/// (`runtime_layout._raw_base`, `hook_client.raw_base`): `CICADA_API_BASE` in the environment, else the address the
/// person saved here in `$CICADA_HOME/api_base` (0600). The token is this device's own, issued on the server
/// (`cicada device add`): `CICADA_API_TOKEN`, else `$CICADA_HOME/device_token` (0600) — #311's location, never the
/// login keychain and never the server's master token (ruling 28.1).
///
/// The address rule is #311's client rule, restated: https for any host; plain http only to a loopback address (an SSH
/// tunnel's local end); no user, password, query or fragment. An address that breaks it is `invalid` — still "a
/// server", so nothing falls back silently to this Mac's bank: every request goes to an address that cannot resolve
/// and Settings says which rule it broke.
struct ServerConnection: Equatable, Sendable {
    enum Mode: Equatable, Sendable {
        case thisMac
        case server(URL)
        case invalid(reason: String)
    }

    /// Where the address came from: the person's choice in the app, or the environment (which the app cannot change).
    enum Source: Equatable, Sendable { case none, file, environment }

    static let apiBaseFile = "api_base"
    static let deviceTokenFile = "device_token"
    static let baseEnv = "CICADA_API_BASE"
    static let tokenEnv = "CICADA_API_TOKEN"
    static let deviceTokenPrefix = "cic_dev_"
    /// RFC 2606: a name that never resolves. An invalid address sends every request here — never to this Mac.
    static let unreachableBase = "https://address-not-valid.invalid"

    let mode: Mode
    let source: Source

    var isServer: Bool { if case .thisMac = mode { false } else { true } }
    var serverURL: URL? { if case .server(let url) = mode { url } else { nil } }
    var invalidReason: String? { if case .invalid(let reason) = mode { reason } else { nil } }
    /// The host the person will recognise ("home-server.example.ts.net"), for the bank picker and Settings.
    var host: String? { serverURL?.host }

    /// The base every `APIClient` request is built on.
    func baseURL(local: String) -> String {
        switch mode {
        case .thisMac: local
        case .server(let url): url.absoluteString
        case .invalid: Self.unreachableBase
        }
    }

    /// "" on This Mac (every key and folder exactly as before); "-server-<6 bytes of the address's hash>" on a server.
    var scopeSuffix: String {
        switch mode {
        case .thisMac: return ""
        case .server(let url):
            let digest = SHA256.hash(data: Data(url.absoluteString.utf8))
            return "-server-" + digest.prefix(6).map { String(format: "%02x", $0) }.joined()
        case .invalid: return "-server-invalid"
        }
    }

    /// The Store's disk cache is per connection: a server's graph never paints under This Mac's, or the reverse.
    var cacheFolderName: String { "cache" + scopeSuffix }

    /// What this app remembers about what it already sent (a reader's cursor, a file's last-synced signature, a
    /// folder's manifest, a picture it fetched) belongs to the backend it sent it to: keyed per connection, so switching
    /// to a server sends the server everything it has not had, and switching back changes nothing on This Mac.
    func scoped(_ key: String) -> String { key + scopeSuffix }

    // MARK: The address rule

    enum AddressError: Error, Equatable, LocalizedError {
        case notAURL, notHTTP, carriesExtras, needsHTTPS

        var errorDescription: String? {
            switch self {
            case .notAURL: Copy.Devices.addressNotURL
            case .notHTTP: Copy.Devices.addressNotHTTP
            case .carriesExtras: Copy.Devices.addressExtras
            case .needsHTTPS: Copy.Devices.addressNeedsHTTPS
            }
        }
    }

    private static let loopbackHosts: Set<String> = ["127.0.0.1", "localhost", "::1"]

    /// `runtime_layout.api_base`'s rule. Returns the normalised address (no trailing slash).
    static func validate(_ raw: String) -> Result<URL, AddressError> {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let parts = URLComponents(string: trimmed) else { return .failure(.notAURL) }
        guard let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme) else { return .failure(.notHTTP) }
        guard let host = parts.host, !host.isEmpty else { return .failure(.notHTTP) }
        if let port = parts.port, !(1...65535).contains(port) { return .failure(.notAURL) }
        if parts.user != nil || parts.password != nil || parts.query != nil || parts.fragment != nil {
            return .failure(.carriesExtras)
        }
        let bareHost = host.trimmingCharacters(in: CharacterSet(charactersIn: "[]")).lowercased()
        if scheme == "http" && !loopbackHosts.contains(bareHost) { return .failure(.needsHTTPS) }
        var clean = URLComponents()
        clean.scheme = scheme
        clean.host = parts.host
        clean.port = parts.port
        var path = parts.path
        while path.hasSuffix("/") { path.removeLast() }
        clean.path = path
        guard let url = clean.url else { return .failure(.notAURL) }
        return .success(url)
    }

    // MARK: Resolution

    static let current: ServerConnection = resolve()

    static func resolve(environment: [String: String] = ProcessInfo.processInfo.environment,
                        cicadaHome: URL = CicadaRuntime.current.cicadaHome,
                        readFile: (URL) -> String? = { try? String(contentsOf: $0, encoding: .utf8) }) -> ServerConnection {
        let fromEnv = (environment[baseEnv] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let raw: String
        let source: Source
        if !fromEnv.isEmpty {
            raw = fromEnv
            source = .environment
        } else if let saved = readFile(cicadaHome.appendingPathComponent(apiBaseFile))?
            .trimmingCharacters(in: .whitespacesAndNewlines), !saved.isEmpty {
            raw = saved
            source = .file
        } else {
            return ServerConnection(mode: .thisMac, source: .none)
        }
        switch validate(raw) {
        case .success(let url): return ServerConnection(mode: .server(url), source: source)
        case .failure(let error):
            return ServerConnection(mode: .invalid(reason: error.errorDescription ?? ""), source: source)
        }
    }

    // MARK: The device token

    static func looksLikeDeviceToken(_ token: String) -> Bool {
        let t = token.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.hasPrefix(deviceTokenPrefix) && t.count > deviceTokenPrefix.count + 9
    }

    /// The id inside a device token (`cic_dev_<id>_<secret>`) — how this app knows which row of `/devices` is itself.
    static func deviceId(fromToken token: String?) -> String? {
        guard let token, looksLikeDeviceToken(token) else { return nil }
        let rest = token.trimmingCharacters(in: .whitespacesAndNewlines).dropFirst(deviceTokenPrefix.count)
        let id = rest.prefix(8)
        guard id.count == 8, rest.dropFirst(8).first == "_",
              id.allSatisfy({ $0.isASCII && ($0.isLowercase || $0.isNumber) }) else { return nil }
        return String(id)
    }

    /// This device's token: `CICADA_API_TOKEN`, else `$CICADA_HOME/device_token`.
    static func deviceToken(environment: [String: String] = ProcessInfo.processInfo.environment,
                            cicadaHome: URL = CicadaRuntime.current.cicadaHome,
                            readFile: (URL) -> String? = { try? String(contentsOf: $0, encoding: .utf8) }) -> String? {
        if let env = environment[tokenEnv]?.trimmingCharacters(in: .whitespacesAndNewlines), !env.isEmpty { return env }
        guard let raw = readFile(cicadaHome.appendingPathComponent(deviceTokenFile))?
            .trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        return raw
    }

    // MARK: Saving the person's choice

    /// Writes the address (and the token, when the person pasted one) — each 0600, the folder 0700. Only on the
    /// person's click in Settings → General; nothing else in the app writes either file.
    static func save(base: URL, token: String?, cicadaHome: URL = CicadaRuntime.current.cicadaHome) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: cicadaHome, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        if let token = token?.trimmingCharacters(in: .whitespacesAndNewlines), !token.isEmpty {
            try writePrivate(token + "\n", to: cicadaHome.appendingPathComponent(deviceTokenFile))
        }
        try writePrivate(base.absoluteString + "\n", to: cicadaHome.appendingPathComponent(apiBaseFile))
    }

    /// *This Mac* again: the address goes; the device token stays, so choosing the server again needs no new one.
    static func forget(cicadaHome: URL = CicadaRuntime.current.cicadaHome) throws {
        let file = cicadaHome.appendingPathComponent(apiBaseFile)
        if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
    }

    private static func writePrivate(_ text: String, to url: URL) throws {
        let fm = FileManager.default
        let staging = url.deletingLastPathComponent().appendingPathComponent(".\(url.lastPathComponent).tmp")
        try? fm.removeItem(at: staging)
        guard fm.createFile(atPath: staging.path, contents: Data(text.utf8), attributes: [.posixPermissions: 0o600]) else {
            throw CocoaError(.fileWriteUnknown)
        }
        if fm.fileExists(atPath: url.path) {
            _ = try fm.replaceItemAt(url, withItemAt: staging)
        } else {
            try fm.moveItem(at: staging, to: url)
        }
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}

/// What a request the app could not deliver became, said in words (never an `APIError` case: those are switched on
/// exhaustively across the app).
enum ServerLinkError: Error, Equatable, LocalizedError {
    /// A reader's bytes are kept here and go to the server when it answers again (`ReaderOutbox`).
    case queuedOffline
    /// A demo never reaches a server (`demo_guard`; research §4 phase 3).
    case demoStaysLocal

    var errorDescription: String? {
        switch self {
        case .queuedOffline: Copy.Devices.queuedOffline
        case .demoStaysLocal: Copy.Devices.demoStaysLocal
        }
    }
}

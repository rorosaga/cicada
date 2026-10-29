import Foundation

// G217 / G212 / G213 — the connection model's wire, decoded leniently (a backend a field ahead or behind never blanks a
// page). None of these is a Store domain: `/providers` is static per release (fetched once, kept in memory),
// `/devices/status` changes by the minute (polled while visible), and agent tokens are machine-global, outside every
// bank. Each says so where it is read (CLAUDE.md, Sync: "a read that is not a Store domain says so").

/// `GET /providers` — one umbrella per provider (its logo slug, its products' ways in, the plans and keys that can run
/// Sleep). `api/services/agent_catalog.py` is the one table.
struct ProvidersResponse: Decodable, Equatable {
    var providers: [ProviderUmbrella] = []

    enum CodingKeys: String, CodingKey { case providers }
    init(providers: [ProviderUmbrella] = []) { self.providers = providers }
    init(from decoder: Decoder) throws {
        providers = try decoder.container(keyedBy: CodingKeys.self).lenient(.providers, [])
    }
}

struct ProviderUmbrella: Decodable, Equatable, Identifiable {
    let id: String
    var label: String
    var logo: String?
    var tier: Int = 1
    var ways: [ProviderWay] = []
    var intelligence: [ProviderIntelligence] = []
    var later: [String] = []

    init(id: String, label: String, logo: String?, tier: Int = 1, ways: [ProviderWay] = [],
         intelligence: [ProviderIntelligence] = [], later: [String] = []) {
        self.id = id; self.label = label; self.logo = logo; self.tier = tier
        self.ways = ways; self.intelligence = intelligence; self.later = later
    }

    enum CodingKeys: String, CodingKey { case id, label, logo, tier, ways, intelligence, later }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(.label, id)
        logo = c.lenient(.logo)
        tier = c.lenient(.tier, 1)
        ways = c.lenient(.ways, [])
        intelligence = c.lenient(.intelligence, [])
        later = c.lenient(.later, [])
    }
}

struct ProviderWay: Decodable, Equatable, Identifiable {
    let id: String
    var label: String
    var connects: [String] = []
    var tier: Int = 1
    var setup: [String] = []
    var note: String?
    /// The name this way goes by through the remote connector and its account's export, when that is another product
    /// than the local app (ruling 39: Claude Desktop here, claude.ai on the web and phone); nil = one name for all.
    var remoteLabel: String?

    init(id: String, label: String, connects: [String] = [], tier: Int = 1, setup: [String] = [], note: String? = nil,
         remoteLabel: String? = nil) {
        self.id = id; self.label = label; self.connects = connects; self.tier = tier; self.setup = setup; self.note = note
        self.remoteLabel = remoteLabel
    }

    enum CodingKeys: String, CodingKey { case id, label, connects, tier, setup, note, remoteLabel }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(.label, id)
        connects = c.lenient(.connects, [])
        tier = c.lenient(.tier, 1)
        setup = c.lenient(.setup, [])
        note = c.lenient(.note)
        remoteLabel = c.lenient(.remoteLabel)
    }
}

/// One way a provider can run Sleep: `kind` is `plan`, `key` or `local`; `connection` is the `/connections` id.
struct ProviderIntelligence: Decodable, Equatable, Identifiable {
    let connection: String
    var label: String
    var kind: String
    var note: String?
    var id: String { connection }

    init(connection: String, label: String, kind: String, note: String? = nil) {
        self.connection = connection; self.label = label; self.kind = kind; self.note = note
    }

    enum CodingKeys: String, CodingKey { case connection, label, kind, note }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        connection = try c.decode(String.self, forKey: .connection)
        label = c.lenient(.label, connection)
        kind = c.lenient(.kind, "key")
        note = c.lenient(.note)
    }
}

/// `GET /devices/status` (G212): this server first, by its own Computer Name, then each active device by the name the
/// person gave it.
struct DeviceStatusResponse: Decodable, Equatable {
    var devices: [DeviceStatusRow] = []
    enum CodingKeys: String, CodingKey { case devices }
    init(devices: [DeviceStatusRow] = []) { self.devices = devices }
    init(from decoder: Decoder) throws {
        devices = try decoder.container(keyedBy: CodingKeys.self).lenient(.devices, [])
    }
}

struct DeviceStatusRow: Decodable, Equatable, Identifiable {
    /// Nil for the server itself (it holds no device token).
    var deviceId: String?
    var name: String
    var role: String = "device"
    var current = false
    var connected = false
    /// `local`, `tailscale`, `ssh` or `lan` — read from the device's own requests; nil when it never reached here.
    var how: String?
    var lastSeenAt: String?
    var queue = 0
    /// 2026-10-29 (additive; nil from an older backend): `capture` (sends captures only) or `full`.
    var kind: String?
    /// 2026-10-29 (additive): the token works only with a proof of the device's own key; false = not yet key-bound.
    var keyBound: Bool?
    /// Review 2026-10-29 (additive): when its token was locked to its key.
    var keyBoundAt: String?
    var id: String { deviceId ?? "server" }
    var isServer: Bool { role == "server" }

    init(deviceId: String?, name: String, role: String = "device", current: Bool = false, connected: Bool = false,
         how: String? = nil, lastSeenAt: String? = nil, queue: Int = 0, kind: String? = nil, keyBound: Bool? = nil) {
        self.deviceId = deviceId; self.name = name; self.role = role; self.current = current
        self.connected = connected; self.how = how; self.lastSeenAt = lastSeenAt; self.queue = queue
        self.kind = kind; self.keyBound = keyBound
    }

    enum CodingKeys: String, CodingKey {
        case id, name, role, current, connected, how, lastSeenAt, queue, kind, keyBound, keyBoundAt
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        deviceId = c.lenient(.id)
        name = c.lenient(.name, "")
        role = c.lenient(.role, "device")
        current = c.lenient(.current, false)
        connected = c.lenient(.connected, false)
        how = c.lenient(.how)
        lastSeenAt = c.lenient(.lastSeenAt)
        queue = c.lenient(.queue, 0)
        kind = c.lenient(.kind)
        keyBound = c.lenient(.keyBound)
        keyBoundAt = c.lenient(.keyBoundAt)
    }
}

/// `GET /devices/reach` (G212, 2026-10-29): where this Mac stands on the person's own overlay, the one next step, and
/// — with `check=true` — whether its served address answers the way a phone would see it.
struct DeviceReach: Decodable, Equatable {
    /// `missing` | `not-running` | `logged-out` | `stopped` | `running`.
    var tailscale: String = "missing"
    /// `install` | `open` | `sign-in` | `turn-on` | `serve` | `unfunnel` | `ready` (`reach.GUIDE_STEPS`).
    var step: String = "install"
    /// The exact command the step is. On `serve` a click may run it (owner 2026-10-29, "Yes, one click"); on
    /// `unfunnel` it is only copied (a funnel command is never run).
    var command: String?
    /// The served address a QR carries (`ready` only).
    var url: String?
    var dnsName: String?
    var check: ReachCheck?
    /// `ready` only: the off for that one tailnet mapping, shown before a click may run it.
    var stopCommand: String?

    enum CodingKeys: String, CodingKey { case tailscale, step, command, url, dnsName, check, stopCommand }
    init(tailscale: String = "missing", step: String = "install", command: String? = nil, url: String? = nil,
         dnsName: String? = nil, check: ReachCheck? = nil, stopCommand: String? = nil) {
        self.tailscale = tailscale; self.step = step; self.command = command; self.url = url
        self.dnsName = dnsName; self.check = check; self.stopCommand = stopCommand
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tailscale = c.lenient(.tailscale, "missing")
        step = c.lenient(.step, "install")
        command = c.lenient(.command)
        url = c.lenient(.url)
        dnsName = c.lenient(.dnsName)
        check = c.lenient(.check)
        stopCommand = c.lenient(.stopCommand)
    }
}

struct ReachCheck: Decodable, Equatable {
    var ok = false
    /// `dns` | `overlay` | `backend` | `not-cicada` | `other-cicada` (`reach.CHECK_FAILURES`), nil when it passed.
    var failed: String?
    var ms: Int?
}

/// What a click asks of `POST /devices/reach/serve`: the action only, never a command.
enum DeviceReachAction: String {
    case serve, stop
}

/// `POST /devices/reach/serve`'s answer: whether the one command ran, its sentence when it did not, what ran, and the
/// fresh reach state.
struct DeviceReachServe: Decodable, Equatable {
    var ok = false
    var message: String?
    var ran: String?
    var reach: DeviceReach?

    enum CodingKeys: String, CodingKey { case ok, message, ran, reach }
    init(ok: Bool = false, message: String? = nil, ran: String? = nil, reach: DeviceReach? = nil) {
        self.ok = ok; self.message = message; self.ran = ran; self.reach = reach
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.lenient(.ok, false)
        message = c.lenient(.message)
        ran = c.lenient(.ran)
        reach = c.lenient(.reach)
    }
}

/// `POST /devices/pairing` and `GET /devices/pairing/{id}` (G212).
struct PairingCreated: Decodable, Equatable {
    var pairing: PairingState
    var code: String
    var qr: PairingQR
    /// #432 (additive): how this machine is reached for pairing — the `tailscale serve` command the person would run
    /// when the QR carries no address. Absent on an older backend, which keeps today's wording.
    var reach: PairingReach? = nil
}

struct PairingReach: Decodable, Equatable {
    var serveCommand: String?
    /// `missing` | `stopped` | … — the serve command is offered only where Tailscale is installed.
    var tailscale: String?

    /// The command to show: only when Tailscale is on this machine (a command for a tool not installed helps no one).
    var shownServeCommand: String? { tailscale == "missing" ? nil : serveCommand }
}

/// #432: what a pairing code mints — a phone's capture-only token, or another computer's full device token.
enum PairingKind: String, CaseIterable, Identifiable {
    case capture, full
    var id: String { rawValue }
}

struct PairingQR: Codable, Equatable {
    var v: Int
    var url: String?
    var code: String
}

struct PairingState: Decodable, Equatable {
    var id: String
    /// `waiting`, `paired`, `cancelled` or `expired`.
    var state: String
    var expiresAt: String?
    var deviceId: String?
}

struct PairingAnswer: Decodable, Equatable {
    var pairing: PairingState
    var device: DeviceRecord?
}

/// `GET /agent-api/tokens` rows and `POST /agent-api/tokens` (G213): an agent that cannot use MCP, by its token.
struct AgentToken: Decodable, Equatable, Identifiable {
    var id: String
    var name: String
    var scopes: [String] = []
    var expiresAt: String?
    var lastUsedAt: String?
    var state: String = "active"
}

struct AgentTokenCreated: Decodable, Equatable {
    var agent: AgentToken
    /// The one paragraph the person pastes to the agent — shown once, never stored by the app.
    var prompt: String
}

enum ConnectionModelText {
    /// The connection word a device row prints: how it reached this server.
    static func how(_ raw: String?) -> String? {
        switch raw {
        case "local": "this machine"
        case "tailscale": "Tailscale"
        case "ssh": "SSH"
        case "lan": "local network"
        default: nil
        }
    }

    /// The backend's detail out of an `APIError.httpError` body (`{"detail": "…"}`), else nil.
    static func detail(_ error: Error) -> (code: Int, text: String?)? {
        guard case let APIError.httpError(code, body) = error else { return nil }
        let text = (try? JSONSerialization.jsonObject(with: Data(body.utf8)) as? [String: Any])?["detail"] as? String
        return (code, text)
    }
}

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

    init(id: String, label: String, connects: [String] = [], tier: Int = 1, setup: [String] = [], note: String? = nil) {
        self.id = id; self.label = label; self.connects = connects; self.tier = tier; self.setup = setup; self.note = note
    }

    enum CodingKeys: String, CodingKey { case id, label, connects, tier, setup, note }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(.label, id)
        connects = c.lenient(.connects, [])
        tier = c.lenient(.tier, 1)
        setup = c.lenient(.setup, [])
        note = c.lenient(.note)
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
    var id: String { deviceId ?? "server" }
    var isServer: Bool { role == "server" }

    init(deviceId: String?, name: String, role: String = "device", current: Bool = false, connected: Bool = false,
         how: String? = nil, lastSeenAt: String? = nil, queue: Int = 0) {
        self.deviceId = deviceId; self.name = name; self.role = role; self.current = current
        self.connected = connected; self.how = how; self.lastSeenAt = lastSeenAt; self.queue = queue
    }

    enum CodingKeys: String, CodingKey { case id, name, role, current, connected, how, lastSeenAt, queue }
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

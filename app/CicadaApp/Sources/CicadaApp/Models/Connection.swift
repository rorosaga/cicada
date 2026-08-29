import Foundation

/// Mirror of api/models/schemas.py::ConnectionStatus (G50). Tolerant decoding:
/// every field but `id`/`label` is optional so an older backend still decodes.
struct ConnectionStatus: Identifiable, Codable, Hashable {
    let id: String
    let label: String
    let kind: String            // subscription | usage | local
    let available: Bool
    let connected: Bool
    let plan: String?
    let planLabel: String?
    let tier: String?
    let account: String?
    let priceUsdMonth: Double?
    let priceNote: String?
    let billing: String         // subscription | usage | free
    let engineRole: String?
    let detail: String?
    let login: LoginHint?

    enum CodingKeys: String, CodingKey {
        case id, label, kind, available, connected, plan, planLabel, tier, account
        case priceUsdMonth, priceNote, billing, engineRole, detail, login
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "usage"
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? false
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        plan = try c.decodeIfPresent(String.self, forKey: .plan)
        planLabel = try c.decodeIfPresent(String.self, forKey: .planLabel)
        tier = try c.decodeIfPresent(String.self, forKey: .tier)
        account = try c.decodeIfPresent(String.self, forKey: .account)
        priceUsdMonth = try c.decodeIfPresent(Double.self, forKey: .priceUsdMonth)
        priceNote = try c.decodeIfPresent(String.self, forKey: .priceNote)
        billing = try c.decodeIfPresent(String.self, forKey: .billing) ?? "usage"
        engineRole = try c.decodeIfPresent(String.self, forKey: .engineRole)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        login = try c.decodeIfPresent(LoginHint.self, forKey: .login)
    }

    var isSubscription: Bool { billing == "subscription" }
    var isKeyBased: Bool { login?.mode == "key" }

    /// "Claude Max 20x · $200/mo", "OpenAI API key · usage-based", "Ollama · free, local".
    var priceLine: String {
        switch billing {
        case "subscription":
            if let usd = priceUsdMonth { return "\(planLabel ?? label) · $\(Int(usd))/mo" }
            return planLabel ?? label
        case "free": return "\(planLabel ?? label) · free, local"
        default: return connected ? "\(label) · usage-based" : label
        }
    }
}

struct LoginHint: Codable, Hashable {
    let mode: String   // terminal | device-code | key | none
    let command: String?
}

struct LoginSession: Codable, Hashable {
    let sessionId: String
    let connectionId: String
    let mode: String
    let state: String  // pending | done | failed
    let command: String?
    let code: String?
    let url: String?
    let rawOutput: String
    let detail: String?

    enum CodingKeys: String, CodingKey {
        case sessionId, connectionId, mode, state, command, code, url, rawOutput, detail
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionId = try c.decode(String.self, forKey: .sessionId)
        connectionId = try c.decode(String.self, forKey: .connectionId)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "none"
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "pending"
        command = try c.decodeIfPresent(String.self, forKey: .command)
        code = try c.decodeIfPresent(String.self, forKey: .code)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        rawOutput = try c.decodeIfPresent(String.self, forKey: .rawOutput) ?? ""
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
    }
}

struct ConnectionsResponse: Codable {
    let connections: [ConnectionStatus]
}

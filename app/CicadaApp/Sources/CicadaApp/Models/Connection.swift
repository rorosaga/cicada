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
    /// G63: why this card says "Connected", authored server-side next to the
    /// probe that decided it. `nil` when not connected.
    let how: String?
    /// What this connection currently does for Cicada ("Sleep extraction",
    /// "Ask", … for the selected engine; "Standby" for the rest).
    let powers: [String]
    let login: LoginHint?

    enum CodingKeys: String, CodingKey {
        case id, label, kind, available, connected, plan, planLabel, tier, account
        case priceUsdMonth, priceNote, billing, engineRole, detail, how, powers, login
    }

    /// Memberwise init — declaring `init(from:)` below suppresses the
    /// synthesized one, and the optimistic mutations (§5.4) need to build a
    /// patched copy of a row (new tier, or `connected: false`) before the
    /// server's own version arrives.
    init(id: String, label: String, kind: String, available: Bool, connected: Bool,
         plan: String?, planLabel: String?, tier: String?, account: String?,
         priceUsdMonth: Double?, priceNote: String?, billing: String,
         engineRole: String?, detail: String?, how: String? = nil,
         powers: [String] = [], login: LoginHint?) {
        self.id = id; self.label = label; self.kind = kind
        self.available = available; self.connected = connected
        self.plan = plan; self.planLabel = planLabel; self.tier = tier
        self.account = account; self.priceUsdMonth = priceUsdMonth
        self.priceNote = priceNote; self.billing = billing
        self.engineRole = engineRole; self.detail = detail
        self.how = how; self.powers = powers; self.login = login
    }

    /// A copy with only the named fields replaced. `nil` arguments mean
    /// "keep what's there"; the double-optionals carry "set this to nil"
    /// through (`.some(nil)`).
    func patching(connected: Bool? = nil, tier: String?? = nil, planLabel: String?? = nil,
                  priceUsdMonth: Double?? = nil, priceNote: String?? = nil) -> ConnectionStatus {
        ConnectionStatus(
            id: id, label: label, kind: kind, available: available,
            connected: connected ?? self.connected,
            plan: plan,
            planLabel: planLabel ?? self.planLabel,
            tier: tier ?? self.tier,
            account: account,
            priceUsdMonth: priceUsdMonth ?? self.priceUsdMonth,
            priceNote: priceNote ?? self.priceNote,
            billing: billing, engineRole: engineRole, detail: detail,
            how: how, powers: powers, login: login
        )
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
        how = try c.decodeIfPresent(String.self, forKey: .how)
        powers = try c.decodeIfPresent([String].self, forKey: .powers) ?? []
        login = try c.decodeIfPresent(LoginHint.self, forKey: .login)
    }

    var isSubscription: Bool { billing == "subscription" }
    var isKeyBased: Bool { login?.mode == "key" }

    /// "Sleep extraction · Ask · clarification wording", or nil when this
    /// connection isn't powering anything.
    var powersLine: String? {
        powers.isEmpty ? nil : powers.joined(separator: " · ")
    }

    /// The Max tier picker is a **cost-estimate** control, and only Claude
    /// Max is tiered — showing it anywhere else implied it changed behaviour.
    var showsTierPicker: Bool {
        connected && isSubscription && id == "claude-plan" && plan == "max"
    }

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

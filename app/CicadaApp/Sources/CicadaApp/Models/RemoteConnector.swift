import Foundation

// G135 — the remote connector, as the app sees it. Wire types decode the
// camelCase `/remote/*` payloads; everything the page DECIDES is a pure
// function below, tested in `RemoteConnectorTests`.

/// One connector as `GET /remote/connectors` lists it. Never carries the token
/// or its hash — the token exists only in `RemoteConnectorCreated`, the one
/// response that minted it (R-R3).
struct RemoteConnector: Codable, Identifiable, Equatable {
    let id: String
    let label: String
    let app: String
    let scopes: [String]
    let createdAt: String
    var expiresAt: String? = nil
    var revokedAt: String? = nil
    var lastUsedAt: String? = nil
    var lastClient: String? = nil
    let state: String

    var isActive: Bool { state == "active" }
    var remoteApp: RemoteApp { RemoteApp(rawValue: app) ?? .other }
    var grantedScopes: [RemoteScope] { RemoteScope.allCases.filter { scopes.contains($0.rawValue) } }
}

/// The shown-once payload (create or rotate). Identifiable so a rotate can
/// drive `.sheet(item:)`.
struct RemoteConnectorCreated: Codable, Equatable, Identifiable {
    let connector: RemoteConnector
    let token: String
    var link: String? = nil
    var mcpUrl: String? = nil
    var id: String { connector.id + "·" + String(token.suffix(6)) }
}

struct RemoteStatus: Codable, Equatable {
    let enabled: Bool
    let port: Int
    let listenerUp: Bool
    var listenerError: String? = nil
    var publicBaseUrl: String? = nil
    var detectedUrl: String? = nil
    var effectiveUrl: String? = nil
    let tailscale: String
    let ngrokInstalled: Bool
    var reachable: Bool? = nil
    let funnelCommand: String
    let ngrokCommand: String
}

/// What a connector may do, in plain verbs (R-R22). Order is the backend's
/// `catalog.SCOPES`, pinned by `api/tests/fixtures/remote_catalog.json`.
enum RemoteScope: String, CaseIterable, Identifiable, Hashable {
    case search, read, record, sources, answer, ask

    var id: String { rawValue }

    var title: String {
        switch self {
        case .search: "Search"
        case .read: "Read"
        case .record: "Record"
        case .sources: "Raw conversations"
        case .answer: "Answer questions"
        case .ask: "Ask"
        }
    }

    var detail: String {
        switch self {
        case .search: "Find things in your memory."
        case .read: "Open full pages and Cicada's questions."
        case .record: "Save notes, links and facts, marked as from this app."
        case .sources: "Read what you said, word for word."
        case .answer: "Record your answers to Cicada's questions as yours."
        case .ask: "Let Cicada write answers for it. Uses your plan."
        }
    }

    /// The word in the "Can …" sentence — the same words the backend primer
    /// uses (`handshake._REMOTE_VERBS`).
    var verb: String {
        switch self {
        case .search: "search"
        case .read: "read"
        case .record: "record"
        case .sources: "read raw conversations"
        case .answer: "answer questions"
        case .ask: "ask"
        }
    }

    var isDefault: Bool { self == .search || self == .read || self == .record }

    static var defaults: Set<RemoteScope> { Set(allCases.filter(\.isDefault)) }

    static func summary(_ scopes: Set<RemoteScope>) -> String {
        let verbs = allCases.filter(scopes.contains).map(\.verb)
        guard !verbs.isEmpty else { return "Can't delete or rewrite." }
        let joined = verbs.count == 1 ? verbs[0] : verbs.dropLast().joined(separator: ", ") + " and " + verbs.last!
        return "Can \(joined). Can't delete or rewrite."
    }
}

enum RemoteExpiry: CaseIterable, Identifiable, Hashable {
    case sevenDays, thirtyDays, ninetyDays, never

    var id: Self { self }
    var days: Int? {
        switch self {
        case .sevenDays: 7
        case .thirtyDays: 30
        case .ninetyDays: 90
        case .never: nil
        }
    }
    var title: String {
        switch self {
        case .sevenDays: "7 days"
        case .thirtyDays: "30 days"
        case .ninetyDays: "90 days"
        case .never: "No expiry"
        }
    }
}

struct RemoteSetupStep: Equatable {
    let text: String
    var snippet: String? = nil
}

/// The nine apps of the New connector grid (R-R26). `harness` is the id their
/// episodes and commits carry — and the key `OriginIconography` marks them by,
/// so the grid, the Sources card and the contributor strip draw one picture.
enum RemoteApp: String, CaseIterable, Identifiable {
    case claude
    case chatgpt
    case perplexity
    case claudeCode = "claude-code"
    case codex
    case cursor
    case vscode
    case geminiCLI = "gemini-cli"
    case other

    var id: String { rawValue }

    var name: String {
        switch self {
        case .claude: "Claude"
        case .chatgpt: "ChatGPT"
        case .perplexity: "Perplexity"
        case .claudeCode: "Claude Code"
        case .codex: "Codex"
        case .cursor: "Cursor"
        case .vscode: "VS Code"
        case .geminiCLI: "Gemini CLI"
        case .other: "Other app"
        }
    }

    var harness: String {
        switch self {
        case .claude: "claude-web"
        case .chatgpt: "chatgpt"
        case .perplexity: "perplexity"
        case .claudeCode: "claude-code-remote"
        case .codex: "codex-remote"
        case .cursor: "cursor"
        case .vscode: "vscode"
        case .geminiCLI: "gemini-cli"
        case .other: "remote-app"
        }
    }

    var delivery: String {
        switch self {
        case .claude, .chatgpt, .perplexity: "link"
        case .other: "both"
        default: "header"
        }
    }

    var usesLink: Bool { delivery != "header" }
    var usesHeader: Bool { delivery != "link" }
    var logoName: String? { OriginIconography.logoName(for: harness) }
    var symbol: String { OriginIconography.symbol(for: harness) }

    /// The honest limit under the steps (R4 §2: verified vendor docs; what is
    /// unverified is said to be).
    var note: String? {
        switch self {
        case .claude: "Free plans allow one custom connector. Tip: set the saving tools to “Needs approval”."
        case .chatgpt: "Works on the web with Plus, Pro, Business, Enterprise and Edu. Phone support for custom apps isn't documented yet."
        case .perplexity: "Paid plans only."
        default: nil
        }
    }

    /// At most three steps, each copyable where there is something to type.
    /// `mcpURL` and `token` are safe to interpolate unquoted: the backend
    /// normalises the URL to `https://host[:port]` and the token alphabet is
    /// base64url.
    func steps(link: String, mcpURL: String, token: String) -> [RemoteSetupStep] {
        switch self {
        case .claude:
            return [
                .init(text: "Open claude.ai → Settings → Connectors → Add custom connector."),
                .init(text: "Name it Cicada, paste this link and leave sign-in off.", snippet: link),
                .init(text: "That's it — it shows up in the Claude app on your phone too."),
            ]
        case .chatgpt:
            return [
                .init(text: "In ChatGPT on the web: Settings → Security and login → turn on Developer mode."),
                .init(text: "Add a new app with the + button, paste this link and choose no authentication.", snippet: link),
                .init(text: "ChatGPT asks you before it saves anything."),
            ]
        case .perplexity:
            return [
                .init(text: "Open Settings → Connectors → + Custom connector → Remote."),
                .init(text: "Paste this link, choose no authentication and Streamable HTTP.", snippet: link),
            ]
        case .claudeCode:
            return [
                .init(text: "Run this once in a terminal:",
                      snippet: "claude mcp add --transport http --scope user cicada-remote \(mcpURL) --header \"Authorization: Bearer \(token)\""),
                .init(text: "Check it with claude mcp list."),
            ]
        case .codex:
            return [
                .init(text: "Keep the token where Codex can read it:", snippet: "export CICADA_TOKEN=\(token)"),
                .init(text: "Add this to ~/.codex/config.toml:",
                      snippet: "[mcp_servers.cicada-remote]\nurl = \"\(mcpURL)\"\nbearer_token_env_var = \"CICADA_TOKEN\""),
            ]
        case .cursor:
            return [
                .init(text: "Keep the token where Cursor can read it:", snippet: "export CICADA_TOKEN=\(token)"),
                .init(text: "Add this to ~/.cursor/mcp.json:",
                      snippet: "{\n  \"mcpServers\": {\n    \"cicada-remote\": {\n      \"url\": \"\(mcpURL)\",\n      \"headers\": { \"Authorization\": \"Bearer ${env:CICADA_TOKEN}\" }\n    }\n  }\n}"),
            ]
        case .vscode:
            return [
                .init(text: "Add this to .vscode/mcp.json:",
                      snippet: "{\n  \"servers\": {\n    \"cicada-remote\": {\n      \"type\": \"http\",\n      \"url\": \"\(mcpURL)\",\n      \"headers\": { \"Authorization\": \"Bearer ${input:cicada-token}\" }\n    }\n  },\n  \"inputs\": [\n    { \"type\": \"promptString\", \"id\": \"cicada-token\", \"description\": \"Cicada token\", \"password\": true }\n  ]\n}"),
                .init(text: "VS Code asks for the token the first time — paste this:", snippet: token),
            ]
        case .geminiCLI:
            return [
                .init(text: "Run this once in a terminal:",
                      snippet: "gemini mcp add --transport http --header \"Authorization: Bearer \(token)\" cicada-remote \(mcpURL)"),
                .init(text: "Check it with /mcp list inside Gemini CLI."),
            ]
        case .other:
            return [
                .init(text: "Apps that take a link: paste this one.", snippet: link),
                .init(text: "Apps that take an address and a header: use this address…", snippet: mcpURL),
                .init(text: "…with the header Authorization: Bearer and this token.", snippet: token),
            ]
        }
    }
}

enum RemoteConnectorText {
    static func date(_ iso: String?) -> Date? {
        guard let iso else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: iso)
    }

    static func expiry(_ c: RemoteConnector, now: Date = .now) -> String {
        if c.state == "revoked" { return "Revoked" }
        if c.state == "expired" { return "Expired" }
        guard let end = date(c.expiresAt) else { return "No expiry" }
        let days = Int((end.timeIntervalSince(now) / 86_400).rounded())
        switch days {
        case ..<1: return "Expires today"
        case 1: return "Expires in 1 day"
        default: return "Expires in \(days) days"
        }
    }

    static func lastUsed(_ c: RemoteConnector, now: Date = .now, locale: Locale = .autoupdatingCurrent) -> String {
        guard let used = date(c.lastUsedAt) else { return "Never used" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        formatter.locale = locale
        let when = formatter.localizedString(for: used, relativeTo: now)
        if let client = c.lastClient, !client.isEmpty { return "Last used \(when) by \(client)" }
        return "Last used \(when)"
    }
}

/// What the Reach card says (R-R32). `.off` hides the card.
enum RemoteReach: Equatable {
    case off
    case problem(String)
    case reachable(String)
    case checking(String)
    case unreachable(String)
    case setUp(message: String, command: String?)

    static func of(_ s: RemoteStatus) -> RemoteReach {
        guard s.enabled else { return .off }
        if let error = s.listenerError { return .problem("Cicada couldn't open its door: \(error).") }
        if let url = s.effectiveUrl {
            switch s.reachable {
            case .some(true): return .reachable(url)
            case .some(false): return .unreachable(url)
            case .none: return .checking(url)
            }
        }
        switch s.tailscale {
        case "no-funnel":
            return .setUp(message: "Tailscale is installed. Run this once in Terminal to open a door to Cicada only:",
                          command: s.funnelCommand)
        case "stopped":
            return .setUp(message: "Tailscale is installed but not running. Open Tailscale, then run this once in Terminal:",
                          command: s.funnelCommand)
        default:
            if s.ngrokInstalled {
                return .setUp(message: "Run this in Terminal. ngrok can see what passes through it; Tailscale can't.",
                              command: s.ngrokCommand)
            }
            return .setUp(message: "Install Tailscale (free) to give this Mac a private address, then come back here.",
                          command: nil)
        }
    }
}

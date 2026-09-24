import Foundation

/// R-AG1 — the ten agents Settings → Agents offers, in the order the owner named them, pinned to the backend's
/// `agent_live.LIVE_AGENTS` by `api/tests/fixtures/agent_catalog.json`. `featured` (the first nine) is what phase
/// B's onboarding shows; Gemini CLI stays for installs that already registered it.
struct AgentCatalogEntry: Identifiable, Equatable {
    enum Kind: Equatable {
        /// Copy and send a prompt; `runsItself` = it runs a command (vs. edits its own settings, R-AG3).
        case prompt(runsItself: Bool)
        case deeplink
        /// R-AG2: the Claude app (config merge) first, claude.ai (remote) as Advanced.
        case claude
        case remote(RemoteApp)
    }

    let id: String
    let name: String
    /// A bundled mark name (through `LogoImage`, so `claude-code` gets its badge); nil = `symbol`.
    let mark: String?
    let symbol: String
    let kind: Kind
    /// The `GET /agents/setup` harness ids this pill reads.
    let setupHarnesses: [String]
    let featured: Bool
}

enum AgentCatalog {
    static let all: [AgentCatalogEntry] = [
        .init(id: "claude-code", name: "Claude Code", mark: "claude-code", symbol: "terminal",
              kind: .prompt(runsItself: true), setupHarnesses: ["claude-code"], featured: true),
        .init(id: "codex", name: "Codex", mark: "codex", symbol: "terminal",
              kind: .prompt(runsItself: true), setupHarnesses: ["codex"], featured: true),
        .init(id: "claude", name: "Claude", mark: "claude", symbol: "bubble.left.and.bubble.right",
              kind: .claude, setupHarnesses: ["claude-desktop", "claude"], featured: true),
        .init(id: "chatgpt", name: "ChatGPT", mark: "chatgpt", symbol: "bubble.left.and.bubble.right",
              kind: .remote(.chatgpt), setupHarnesses: ["chatgpt"], featured: true),
        .init(id: "cursor", name: "Cursor", mark: "cursor", symbol: "cursorarrow",
              kind: .deeplink, setupHarnesses: ["cursor"], featured: true),
        .init(id: "opencode", name: "OpenCode", mark: "opencode", symbol: "terminal",
              kind: .prompt(runsItself: false), setupHarnesses: ["opencode"], featured: true),
        .init(id: "hermes", name: "Hermes", mark: "hermes", symbol: "terminal",
              kind: .prompt(runsItself: false), setupHarnesses: ["hermes"], featured: true),
        .init(id: "openclaw", name: "OpenClaw", mark: "openclaw", symbol: "terminal",
              kind: .prompt(runsItself: false), setupHarnesses: ["openclaw"], featured: true),
        .init(id: "grok", name: "Grok", mark: nil, symbol: "bubble.left.and.bubble.right",
              kind: .remote(.grok), setupHarnesses: ["grok"], featured: true),
        .init(id: "gemini-cli", name: "Gemini CLI", mark: "gemini-cli", symbol: "terminal",
              kind: .prompt(runsItself: true), setupHarnesses: ["gemini-cli"], featured: false),
    ]

    static var featured: [AgentCatalogEntry] { all.filter(\.featured) }
    static var setupHarnesses: Set<String> { Set(all.flatMap(\.setupHarnesses)) }

    /// A pill id, or a setup id that belongs to a pill (`claude-desktop` → Claude).
    static func entry(for id: String) -> AgentCatalogEntry? {
        all.first { $0.id == id } ?? all.first { $0.setupHarnesses.contains(id) }
    }
}

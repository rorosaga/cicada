import SwiftUI

/// Round-4 D5 (R-FA15) — the one-click paths on an agent's row, decided purely: Connect for me (Cicada runs the
/// wiring commands after the click, the Found row's Turn on), Copy setup prompt (the agent runs them itself),
/// Open in Cursor (the catalog's own deeplink), Set up Claude (a config merge the app performs).
enum AgentQuickAction: Equatable {
    case connectForMe([AgentWiringStep])
    case copyPrompt(String)
    case openCursor
    case setUpClaude
}

enum AgentQuickSetup {
    /// What an agent's open row offers (Round 4: `AgentSteps` turns these into numbered steps, R-AG17). Connect for me only while the backend says the agent is installed, has
    /// steps, and is not already fully wired (a wired agent re-running `mcp add` fails, R-IA15). Copy setup prompt
    /// only for the harnesses `GET /agents/setup` answers (`AgentCatalog.setupHarnesses`, R-AG1) and only a `kind: prompt` answer with text — against today's backend (a 404) there
    /// is no `setup`, so nothing new shows. Cursor and Claude desktop need nothing off the wire: their paths are
    /// computed by the app itself (R-FA15).
    static func actions(catalogId: String, setup: AgentSetupPrompt?, wiring: AgentWiring?) -> [AgentQuickAction] {
        var out: [AgentQuickAction] = []
        if let wiring, wiring.id == catalogId, wiring.installed, !wiring.connect.isEmpty,
           !(wiring.recall == "on" && wiring.autosave == "on") {
            out.append(.connectForMe(wiring.connect))
        }
        if AgentCatalog.setupHarnesses.contains(catalogId), setup?.kind == "prompt",
           let prompt = setup?.prompt, !prompt.isEmpty {
            out.append(.copyPrompt(prompt))
        }
        if catalogId == "cursor" { out.append(.openCursor) }
        if catalogId == "claude-desktop" { out.append(.setUpClaude) }
        return out
    }

    /// The caption each Set up Claude outcome reads as — plain words, never the file's path (the row's manual
    /// step below already names it).
    static func caption(_ outcome: ClaudeDesktopConfig.Outcome) -> String {
        switch outcome {
        case .done: Copy.agentClaudeDone
        case .alreadySetUp: Copy.agentClaudeAlready
        case .claudeNotSetUp: Copy.agentClaudeNotSetUp
        case .leftUntouched: Copy.agentClaudeUnreadable
        case .failed(let why): why
        }
    }
}

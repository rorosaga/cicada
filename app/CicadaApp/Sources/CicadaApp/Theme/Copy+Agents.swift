import Foundation

/// Round 4 C8 — every sentence of Settings → Agents' selector and numbered steps (and of phase B's onboarding,
/// which reuses the same two components). One extension so the words the table tests pin
/// (`AgentStepsTests`) live in one place; plain words for a non-technical reader, no prices, no counts of tokens.
extension Copy {
    static let agentsYourAgents = "Your agents"
    static func agentsConnectedSummary(_ n: Int) -> String {
        n == 0 ? "Connect as many as you like" : "\(n) connected · connect as many as you like"
    }
    static func agentConnectTitle(_ name: String) -> String { "Connect \(name)" }
    static let agentFoundOnMac = "Found on this Mac."
    static let agentNotFoundOnMac = "Not found on this Mac yet — you can still copy the setup."
    static let agentRunsInCloud = "Runs in the cloud and reaches this Mac through From anywhere."
    static let agentConnectedBadge = "Connected"
    static func agentStepSend(_ name: String) -> String { "Copy and send this to \(name)" }
    static func agentStepSendRuns(_ name: String) -> String { "\(name) runs the setup itself and asks you to approve one command." }
    static func agentStepSendConfig(_ name: String) -> String { "\(name) adds Cicada to its own settings and asks before changing anything." }
    static let agentStepPreparing = "Getting the setup ready…"
    static let agentStepOpenCursor = "Open in Cursor"
    static let agentStepCursorHow = "Cursor asks you to confirm. Then open a new chat."
    static let agentStepClaudeApp = "Set up the Claude app on this Mac"
    static let agentStepClaudeAppHow = "One click adds Cicada to Claude's settings. Then quit and reopen Claude."
    static let agentStepClaudeWeb = "Use it on claude.ai and your phone too"
    static func agentStepReach(_ name: String) -> String { "Let \(name) reach this Mac" }
    static func agentStepLink(_ name: String) -> String { "Create a link for \(name)" }
    static let agentStepAdvanced = "Advanced"
    static let agentStepConfirm = "Confirm"
    static func agentStepConfirmHow(_ name: String) -> String { "Cicada sees \(name) connect — this turns green by itself." }
    static func agentWaiting(_ name: String) -> String { "Waiting for \(name)…" }
    static let agentConnectedNow = "Connected just now"
    static func agentConnectedAgo(_ relative: String) -> String { "Connected \(relative)" }
    static let agentConnectedPlain = "Connected"
    static let agentNoAutosave = "Saves when you or it asks — it has no automatic save."
    static let agentCreateLink = "Create a link"
    static let agentOpenFromAnywhere = "Open From anywhere"
    static let agentNeedsReach = "Turn on From anywhere first. It needs a tunnel you run."
    static let agentsFooter = "Connect or disconnect agents any time in Settings → Agents"
    static let agentsDoItByHand = "Do it by hand"
}

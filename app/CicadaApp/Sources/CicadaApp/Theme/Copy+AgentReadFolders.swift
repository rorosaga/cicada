import Foundation

/// Ruling 84 (2026-11-26) — the folders Cicada's own agent may read, in Settings → Privacy & data. The agent is the person's
/// own harness, working an open question in their files; this list is theirs to change, so the words say what is read and what
/// never is. The reason beside each folder is the backend's sentence (one place for the app and the shell). Provider-neutral:
/// no model or plan is named (owner 2026-09-30).
extension Copy {
    enum AgentReadFolders {
        static let groupHeader = "Folders its agent may read"
        /// Once, under the header: what the agent does and the one limit that holds for every folder.
        static let lead = "To answer a question, Cicada's agent looks through the folders switched on here. It reads documents only, never keys, settings or code."
        static let loading = "Reading the list…"
        static let unavailable = "This list couldn't be read. It loads again when the backend answers."
        static let saveFailed = "That change wasn't saved. Try again."
        static let addFolder = "Add a folder…"
        static let addHelp = "Choose a folder of your own. Only its documents are read."
        static let panelMessage = "Choose a folder for Cicada's agent to read."
        static let panelPrompt = "Add"
        static let removeFolder = "Remove from the list"
        static func switchLabel(_ name: String) -> String { "Let the agent read \(name)" }
        /// "macOS keeps Documents, Desktop and Downloads closed to a read Cicada starts by itself." Names come from the backend.
        static func protectedNote(_ names: [String]) -> String? {
            guard let last = names.last else { return nil }
            let list = names.count == 1 ? last : names.dropLast().joined(separator: ", ") + " and " + last
            return "macOS keeps \(list) closed to a read Cicada starts by itself, so they stay unread."
        }
    }
}

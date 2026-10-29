import Foundation

// G227 follow-up (owner 2026-10-29) — merge two pages, split one, undo either. Provider-neutral: the suggestion is
// "Cicada's read", never a model's name.
extension Copy.Graph {
    static let historyMerged = "merged another page into this one"
    static let historySplit = "split this page in two"
    static let historyUndidJoin = "undid a merge or split"
    static let historyUndo = "Undo"
    static let historyUndoHelp = "Put the pages back as they were before this change"
    static func historyUndone(_ kind: String) -> String { kind == "split" ? "Split undone" : "Merge undone" }
}

extension Copy {
    enum PageJoin {
        // The page menu
        static let mergeMenu = "Merge into another page…"

        // Merge
        static func mergeTitle(_ name: String) -> String { "Merge \(name) into…" }
        static let mergeSearch = "Find the page that stays"
        static let mergeNoMatch = "No page by that name"
        static func mergeExplain(_ from: String, _ into: String) -> String {
            "\(from) folds into \(into): its beliefs, sources, aliases and links move there, and links to \(from) "
                + "open \(into). You can undo it from the page's history."
        }
        static let mergeAction = "Merge"
        static func merged(_ into: String) -> String { "Merged into \(into)" }

        // Separating is the person's agent's job (owner 2026-10-29): the page hands it a ready sentence.
        static let separateMenu = "Separate with your agent…"
        static func separatePrompt(_ name: String, _ id: String) -> String {
            "In Cicada, the page \"\(name)\" (`\(id)`) seems to mix two different things that share the name. "
                + "Use cicada_split_page with preview to show me which sentences are about the other thing, and split it "
                + "only after I say yes."
        }
        static let separateCopied = "Copied — paste it to your agent"
        static let loading = "Reading the page…"
        static let failed = "The page could not be read."
        static let cancel = "Cancel"
    }
}

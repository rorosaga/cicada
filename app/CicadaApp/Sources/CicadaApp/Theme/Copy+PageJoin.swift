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
        static let splitMenu = "Split this page…"

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

        // Split
        static func splitTitle(_ name: String) -> String { "Split \(name)" }
        static let splitExplain = "Tick what is about the other thing. It moves to a new page with the same name; "
            + "the two are kept apart from now on, and you can undo it from the page's history."
        static let splitSuggest = "Suggest what to move"
        static let splitSuggesting = "Reading the page…"
        static let splitSuggestNone = "Nothing here reads as another thing — tick what moves yourself."
        static let newName = "New page's name"
        static let newType = "It is a"
        static let sentences = "Sentences"
        static let beliefs = "Beliefs"
        static let sources = "Where to check"
        static let conversations = "Conversations"
        static let links = "Pages that link here"
        static let linkNew = "the new page"
        static let linkStay = "this page"
        static let linkAsk = "say which"
        static func linkRests(_ n: Int) -> String { n == 1 ? "rests on 1 conversation" : "rests on \(n) conversations" }
        static let splitAction = "Split"
        static func split(_ name: String) -> String { "Split off a new \(name)" }
        static let nothingPicked = "Tick at least one sentence or belief"
        static let loading = "Reading the page…"
        static let failed = "The page could not be read."
        static let cancel = "Cancel"
    }
}

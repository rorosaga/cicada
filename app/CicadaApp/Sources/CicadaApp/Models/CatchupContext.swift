import Foundation

/// Item 1 of app-fixes-1109 — *Answer* opens the chat, and the question arrives with a short account of what the card
/// is about, drawn only from what the inbox item already carries (no model call): for a possible duplicate, what each
/// page says, side by side; for another kind, the page's lead sentence. Nil when the record has nothing to add.
enum CatchupContext {
    static func summary(for item: InboxItem) -> String? {
        let mine = clean(item.subject?.summary)
        if item.kind == .mergeSuggestion {
            // Ruling 83: a mention that could be several pages is asked once and the answers name the candidates; one
            // page's summary beside a question about all of them would favour it, and its id is no copy.
            if (item.sameTitle?.count ?? 0) >= 2 { return nil }
            let other = clean(item.otherSubject?.summary)
            let a = item.entityDisplayName ?? item.entityName
            let b = item.mergeTargetDisplayName ?? item.mergeTargetHint ?? ""
            switch (mine, other) {
            case let (x?, y?): return Copy.Catchup.contextBoth(a, x, b, y)
            case let (x?, nil): return Copy.Catchup.contextOne(a, x)
            case let (nil, y?): return Copy.Catchup.contextOne(b, y)
            default: return nil
            }
        }
        if let mine { return Copy.Catchup.contextOne(item.displayName, mine) }
        return nil
    }

    private static func clean(_ text: String?) -> String? {
        let line = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return line.isEmpty ? nil : line
    }
}

import Foundation

/// G191 — the "What made you save this?" panel and its Settings switch. The reason labels themselves come from the
/// backend (`GET /sources/saved-why/options`), so the words the panel shows are the words the record keeps.
extension Copy {
    enum SaveWhy {
        static let question = "What made you save this?"
        static let somethingElse = "Something else…"
        static let placeholder = "In a few words — Return to save"
        static let hint = "Tap one or more. Esc or a click elsewhere skips it."
        static let savingHint = "Saving your answer…"
        static let dontAsk = "Don’t ask for this site"
        static func forProject(_ name: String) -> String { "For \(name)" }
        static func subject(title: String, host: String?) -> String {
            let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
            switch (name.isEmpty, host) {
            case (false, let host?): return "\(name) · \(host)"
            case (false, nil): return name
            case (true, let host?): return host
            case (true, nil): return "A new bookmark"
            }
        }

        // MARK: Settings → Integrations → Browsers
        static let switchTitle = "Ask why when I bookmark something"
        static let switchDetail = "When you bookmark a page in a browser Cicada watches, a small question drops from the top of the screen: what made you save it? One tap answers; the answer is kept with the bookmark and the time you saved it. Never after an import or a reorganised bookmark bar."
        static func mutedLine(_ count: Int) -> String {
            count == 1 ? "1 site is never asked about." : "\(count) sites are never asked about."
        }
        static let unmuteAll = "Ask about every site again"
    }
}

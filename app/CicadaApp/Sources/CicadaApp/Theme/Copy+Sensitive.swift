import Foundation

/// G235 — what may be sensitive, and which engine read it. Naming the engine is the point here, and it is the person's own
/// choice, passed in as data. Nothing here ever carries the text itself: the server sends kinds and titles.
extension Copy {
    enum Sensitive {
        static let remove = "Remove"
        static let leave = "Leave it"
        static let review = "Review"
        static let confirm = "Remove this from memory?"
        static let failed = "That didn't go through. Try again."
        /// Plainly, once: what Remove does and what it cannot.
        static let effect = "Remove takes it out of memory. History keeps an older copy, and what was read can't be unread."

        static func kind(_ raw: String) -> String {
            switch raw {
            case "password": "A password"
            case "key": "A key"
            case "card": "A card number"
            case "bank": "A bank account"
            case "id": "An ID number"
            default: "Something sensitive"
            }
        }

        /// "A password, a card number": one row, every kind it holds.
        static func kinds(_ raw: [String]) -> String {
            let words = raw.map(kind)
            guard let first = words.first else { return kind("") }
            return ([first] + words.dropFirst().map { $0.prefix(1).lowercased() + $0.dropFirst() }).joined(separator: ", ")
        }

        /// What became of it, per kind: "A password held back from Claude plan · An ID number read by Claude plan".
        /// Ruling 60: a confident hit is held back, an unsure one read. An older read names no engine it never recorded.
        static func fate(kinds raw: [String], heldKinds: [String], readBy: [String], heldFrom: [String], earlier: Bool) -> String {
            let held = raw.filter(heldKinds.contains)
            let rest = raw.filter { !heldKinds.contains($0) }
            var parts: [String] = []
            if !held.isEmpty {
                let from = heldFrom.isEmpty ? "held back" : "held back from \(heldFrom.joined(separator: ", "))"
                parts.append("\(kinds(held)) \(from)")
            }
            if !rest.isEmpty {
                let by = !readBy.isEmpty ? "read by \(readBy.joined(separator: ", "))"
                    : earlier ? "read by an earlier Sleep" : nil
                parts.append(by.map { "\(kinds(rest)) \($0)" } ?? kinds(rest))
            }
            return parts.joined(separator: " · ")
        }

        static func runLine(conversations n: Int, kinds raw: [String], _ locale: Locale = .autoupdatingCurrent) -> String {
            let count = UsageFormat.count(n, locale: locale)
            let noun = n == 1 ? "conversation" : "conversations"
            let what = raw.count == 1 ? kind(raw[0]).lowercased() : "something sensitive"
            return "\(count) \(noun) may hold \(what)"
        }

        /// What the count is: long hex and base64 runs and one-time codes count too, so it "looked like" one.
        static func replaced(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            let count = UsageFormat.count(n, locale: locale)
            return "\(count) \(n == 1 ? "conversation" : "conversations") had what looked like a key or code replaced before it was stored."
        }

        static func allRows(_ n: Int) -> String { "All \(UsageFormat.count(n))" }
    }
}

import Foundation

/// The one ranker (round-3 design §1.2) — Settings search, the ⌘K palette's
/// local tier and every in-page filter rank with it, so one name can never be
/// ranked two ways. Pure. Fields are normalised once, when an index is built,
/// never per keystroke.
///
/// Per token, per field, the best tier wins: exact 0, field prefix 1,
/// word-start prefix 2, initials 3 ("cc" → "Claude Code"), substring 4. A
/// document matches only when EVERY token matches some field (AND). Score =
/// Σ over tokens of (5 − tier) × field weight.
///
/// Built here by Track O (G139, R-O13) because Settings search cannot ship
/// without a ranker; the palette track (S-ui) ranks with the same file — if
/// both branches add it, the second to merge keeps `dev`'s and adapts its
/// caller.
enum QuickMatch {
    enum Tier: Int, Comparable {
        case exact = 0, prefix, wordStart, initials, substring
        static func < (a: Tier, b: Tier) -> Bool { a.rawValue < b.rawValue }
    }

    static let titleWeight = 1.0
    static let aliasWeight = 0.9
    static let keywordWeight = 0.7
    static let detailWeight = 0.4

    struct Field: Hashable {
        let text: String
        let normalized: String
        let weight: Double
        init(_ text: String, weight: Double) {
            self.text = text
            self.normalized = QuickMatch.normalize(text)
            self.weight = weight
        }
    }

    struct Match: Equatable {
        let score: Double
        /// Character offsets into the first field's text that matched, for
        /// bolding. Empty when folding changed the length (offsets would lie).
        let titleRanges: [Range<Int>]
    }

    /// Case- and diacritic-folded, whitespace collapsed to single spaces — so
    /// "ZÜR" finds "Zürich" and a double space in a query is not a token.
    static func normalize(_ s: String) -> String {
        s.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
            .split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    static func tokens(_ query: String) -> [String] {
        normalize(query).split(separator: " ").map(String.init)
    }

    /// The best tier `token` reaches in `field` (both already normalised),
    /// with the matched character range (empty for initials, which match
    /// scattered letters and so have nothing contiguous to bold).
    static func tier(of token: String, in field: String) -> (Tier, Range<Int>)? {
        guard !token.isEmpty, !field.isEmpty else { return nil }
        let t = Array(token), f = Array(field)
        if f == t { return (.exact, 0..<f.count) }
        if f.starts(with: t) { return (.prefix, 0..<t.count) }
        let starts = f.indices.filter { i in
            (f[i].isLetter || f[i].isNumber) && (i == 0 || !(f[i - 1].isLetter || f[i - 1].isNumber))
        }
        for s in starts where s + t.count <= f.count && Array(f[s..<(s + t.count)]) == t {
            return (.wordStart, s..<(s + t.count))
        }
        if t.count >= 2, String(starts.map { f[$0] }).hasPrefix(token) { return (.initials, 0..<0) }
        if t.count <= f.count {
            for s in 0...(f.count - t.count) where Array(f[s..<(s + t.count)]) == t {
                return (.substring, s..<(s + t.count))
            }
        }
        return nil
    }

    static func match(_ tokens: [String], fields: [Field]) -> Match? {
        guard !tokens.isEmpty, !fields.isEmpty else { return nil }
        var score = 0.0
        var ranges: [Range<Int>] = []
        for token in tokens {
            var best: (value: Double, field: Int, range: Range<Int>)?
            for (index, field) in fields.enumerated() {
                guard let (tier, range) = tier(of: token, in: field.normalized) else { continue }
                let value = Double(5 - tier.rawValue) * field.weight
                if best == nil || value > best!.value { best = (value, index, range) }
            }
            guard let best else { return nil }
            score += best.value
            if best.field == 0, !best.range.isEmpty { ranges.append(best.range) }
        }
        let stable = fields[0].normalized.count == fields[0].text.count
        return Match(score: score, titleRanges: stable ? ranges : [])
    }
}

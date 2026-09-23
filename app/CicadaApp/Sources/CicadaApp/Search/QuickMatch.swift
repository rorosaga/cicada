import Foundation

/// The one ranker (G136; round-3 design §1.2). The ⌘K palette's instant tier,
/// the graph typeahead (G123), Clusters, the Feed, a source's conversations and
/// the Inbox all rank and bold through this file, so no two surfaces can
/// disagree about one name.
///
/// **Folding is the server's rule, not Foundation's** (plan R-SU1). The design
/// sketched `folding(options: [.caseInsensitive, .diacriticInsensitive])`; the
/// server's twin (`api/services/text_fold.py`, G136 R21) was amended at its
/// final review to NFD + combining marks dropped + lowercase, because a full
/// case fold rewrites "ß" as "ss" while FTS5's `unicode61` indexes it as
/// written — the exact stored spelling then hit one tier and missed the other.
/// Marks are dropped BEFORE lowercasing, as Python's `fold` does, so "İ" folds
/// to "i" on both sides.
///
/// **Tiers** (per token, per field, the best wins): whole field 0, field
/// prefix 1, word-start prefix 2, initials 3 ("cc" → "Claude Code"),
/// substring 4. The server ranks tiers 0–2 with the same weights (G136 R7);
/// 3 and 4 have no index behind them there, which is why this tier exists.
/// A one-character token matches only at a field or word start (R-SU2).
/// **Score** = Σ over tokens of `(5 − tier) × weight`, every token required
/// (AND). **Ranges** are ORIGINAL Unicode scalars — the unit
/// `ExcerptText.attributed(_:bold:)` and the server's `snippetOffsets` use —
/// so a bold run lands on the same characters whichever tier found the row.
///
/// Fields are folded once, when an index is built, never per keystroke
/// (`QuickIndex`, `ClusterSearchIndex`).
enum QuickMatch {
    /// Design §1.2's weights; the server's `search_service` uses the same four.
    enum Weight {
        static let name = 1.0
        static let alias = 0.9
        static let keyword = 0.7
        static let body = 0.4
    }

    enum Tier: Int, Comparable, Sendable {
        case exact = 0, prefix, wordStart, initials, substring
        static func < (lhs: Tier, rhs: Tier) -> Bool { lhs.rawValue < rhs.rawValue }
        var points: Double { Double(5 - rawValue) }
    }

    /// `text_fold.MAX_TOKENS` — past eight words a query is a paragraph.
    static let maxTokens = 8

    /// One field, folded once.
    struct Folded: Sendable, Equatable {
        /// NFD, combining marks dropped, lowercased; whitespace runs collapsed
        /// to one space and both ends trimmed.
        var scalars: [UInt32] = []
        /// `back[i]` is the index, in the ORIGINAL scalars, `scalars[i]` came from.
        var back: [Int] = []
        /// Folded offsets where a word starts (R-SU3: letters and numbers are
        /// word characters, everything else separates — `unicode61`'s split).
        var wordStarts: [Int] = []
        /// Presence mask of `scalars`: a token whose mask is not a subset
        /// cannot match at any tier, which rejects most documents in one AND.
        var mask: UInt64 = 0
    }

    struct Field: Sendable {
        let folded: Folded
        let weight: Double
        init(_ text: String, weight: Double) {
            self.folded = QuickMatch.fold(text)
            self.weight = weight
        }
    }

    struct Token: Sendable, Equatable {
        let scalars: [UInt32]
        let mask: UInt64
    }

    struct Hit: Equatable {
        let tier: Tier
        /// Folded `[start, end)` runs the token covered.
        let runs: [Range<Int>]
    }

    struct Match: Sendable, Equatable {
        let score: Double
        /// Field index → merged `[start, end)` ranges in ORIGINAL scalars.
        let ranges: [Int: [[Int]]]
        func ranges(inField index: Int) -> [[Int]] { ranges[index] ?? [] }
    }

    // MARK: Folding

    static func fold(_ text: String) -> Folded {
        var out = Folded()
        let count = text.unicodeScalars.count
        out.scalars.reserveCapacity(count)
        out.back.reserveCapacity(count)
        var pendingSpace: Int? = nil
        var previousIsWord = false
        func emit(_ value: UInt32, from index: Int) {
            let isWord = isWordScalar(value)
            if isWord && !previousIsWord { out.wordStarts.append(out.scalars.count) }
            previousIsWord = isWord
            out.scalars.append(value)
            out.back.append(index)
            out.mask |= bit(value)
        }
        for (index, scalar) in text.unicodeScalars.enumerated() {
            if scalar.properties.isWhitespace {
                if !out.scalars.isEmpty, pendingSpace == nil { pendingSpace = index }
                continue
            }
            if let space = pendingSpace {
                emit(0x20, from: space)
                pendingSpace = nil
            }
            if scalar.isASCII {
                let value = scalar.value
                emit((65...90).contains(value) ? value + 32 : value, from: index)
                continue
            }
            for piece in String(scalar).decomposedStringWithCanonicalMapping.unicodeScalars
            where piece.properties.canonicalCombiningClass == .notReordered {
                for lower in piece.properties.lowercaseMapping.unicodeScalars {
                    emit(lower.value, from: index)
                }
            }
        }
        return out
    }

    static func isWordScalar(_ value: UInt32) -> Bool {
        if value < 128 {
            return (48...57).contains(value) || (97...122).contains(value) || (65...90).contains(value)
        }
        guard let scalar = Unicode.Scalar(value) else { return false }
        return scalar.properties.isAlphabetic || scalar.properties.numericType != nil
    }

    static func bit(_ value: UInt32) -> UInt64 { 1 << UInt64(value % 64) }

    // MARK: Matching

    static func tokens(_ query: String) -> [Token] {
        var seen = Set<[UInt32]>()
        var out: [Token] = []
        for part in query.split(whereSeparator: { $0.isWhitespace }) {
            let folded = fold(String(part))
            guard !folded.scalars.isEmpty, seen.insert(folded.scalars).inserted else { continue }
            out.append(Token(scalars: folded.scalars, mask: folded.mask))
            if out.count == maxTokens { break }
        }
        return out
    }

    static func hit(_ token: Token, in field: Folded) -> Hit? {
        let t = token.scalars, s = field.scalars
        guard !t.isEmpty, t.count <= s.count, token.mask & ~field.mask == 0 else { return nil }
        if t == s { return Hit(tier: .exact, runs: [0..<t.count]) }
        if s.starts(with: t) { return Hit(tier: .prefix, runs: [0..<t.count]) }
        for start in field.wordStarts where start > 0 && start + t.count <= s.count {
            if s[start..<(start + t.count)].elementsEqual(t) {
                return Hit(tier: .wordStart, runs: [start..<(start + t.count)])
            }
        }
        guard t.count >= 2 else { return nil }   // R-SU2
        if field.wordStarts.count >= t.count, zip(field.wordStarts, t).allSatisfy({ s[$0.0] == $0.1 }) {
            return Hit(tier: .initials, runs: field.wordStarts.prefix(t.count).map { $0..<($0 + 1) })
        }
        let first = t[0]
        var index = 0
        while index <= s.count - t.count {
            if s[index] == first, s[index..<(index + t.count)].elementsEqual(t) {
                return Hit(tier: .substring, runs: [index..<(index + t.count)])
            }
            index += 1
        }
        return nil
    }

    static func match(_ tokens: [Token], fields: [Field]) -> Match? {
        guard !tokens.isEmpty else { return nil }
        var score = 0.0
        var runs: [Int: [Range<Int>]] = [:]
        for token in tokens {
            var best: (points: Double, field: Int, hit: Hit)?
            for (index, field) in fields.enumerated() {
                guard let hit = hit(token, in: field.folded) else { continue }
                let points = hit.tier.points * field.weight
                if best == nil || points > best!.points { best = (points, index, hit) }
            }
            guard let best else { return nil }
            score += best.points
            runs[best.field, default: []] += best.hit.runs
        }
        var ranges: [Int: [[Int]]] = [:]
        for (index, folded) in runs { ranges[index] = originalRanges(folded, in: fields[index].folded) }
        return Match(score: score, ranges: ranges)
    }

    /// Folded runs → merged ranges in the ORIGINAL scalars: `[a, b)` covers
    /// `[back[a], back[b-1] + 1)`, so "u" + U+0308 folded to one "u" is bolded whole.
    static func originalRanges(_ runs: [Range<Int>], in folded: Folded) -> [[Int]] {
        let mapped = runs.compactMap { run -> (Int, Int)? in
            guard !run.isEmpty, run.upperBound <= folded.back.count else { return nil }
            return (folded.back[run.lowerBound], folded.back[run.upperBound - 1] + 1)
        }.sorted { $0.0 < $1.0 }
        var merged: [[Int]] = []
        for (start, end) in mapped {
            if let last = merged.last, start <= last[1] {
                merged[merged.count - 1][1] = max(last[1], end)
            } else {
                merged.append([start, end])
            }
        }
        return merged
    }

    // MARK: Conveniences

    /// Best first: score, then `tieBreak` (higher first), then `name`
    /// ascending — G123's typeahead order, which `GraphViewModel.rankNames`
    /// now delegates to (R-SU4). Items that miss any token are dropped.
    static func rank<Item>(_ items: [Item], query: String, limit: Int? = nil,
                           fields: (Item) -> [Field], tieBreak: (Item) -> Double,
                           name: (Item) -> String) -> [(item: Item, match: Match)] {
        let tokens = tokens(query)
        guard !tokens.isEmpty else { return [] }
        var scored: [(item: Item, match: Match, tie: Double, name: String)] = []
        for item in items {
            guard let found = match(tokens, fields: fields(item)) else { continue }
            scored.append((item, found, tieBreak(item), name(item)))
        }
        scored.sort { a, b in
            if a.match.score != b.match.score { return a.match.score > b.match.score }
            if a.tie != b.tie { return a.tie > b.tie }
            return a.name < b.name
        }
        let cut = limit.map { Array(scored.prefix($0)) } ?? scored
        return cut.map { (item: $0.item, match: $0.match) }
    }

    /// For a list that keeps its own order (R-SU20): does every token match
    /// somewhere? An empty query keeps everything.
    static func matches(_ query: String, fields: [Field]) -> Bool {
        let tokens = tokens(query)
        return tokens.isEmpty || match(tokens, fields: fields) != nil
    }
}

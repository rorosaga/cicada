import Foundation

/// DR-18 / DR-56 (R-DL2, R-DL3) — the words a person or an agent wrote, without the markup they wrote them in. The
/// owner's live check of #94 found `**bold**`, list dashes and `user:` / `assistant:` labels inside the Inbox's quote
/// and the Reader's turns: `ExcerptText.clean` knew line prefixes and wikilinks only, and ran on each piece AFTER the
/// mention split, so a `**` that straddled the split could never be paired.
///
/// Two rules keep a cited span exact (G118 — spans, not copies):
/// 1. **Deletion only.** Every change removes scalars from the raw text, or swaps one scalar for one (a list marker
///    drawn "•" in the Reader). Nothing is inserted, so a raw offset maps to the clean text by subtracting what was
///    removed before it (`Stripped.map`). The server's offsets are never re-derived, searched for or guessed.
/// 2. **Markup, not words.** Emphasis is stripped, not rendered: DR-18 says a quote has no bold and no italic, and
///    semibold is already the found-by-name mention's signal (R-DI11). Only CommonMark-flanked pairs count, so `2**3`,
///    `**kwargs` and `a * b` stay as written; `_` is never emphasis (snake_case, `__init__`).
///
/// A role label is the writers' turn marker (`evidence._TURN_RE`, `_SPEAKER_RE`; the words are
/// `EvidenceSpeaker.markerWords`) and goes only at a line start. Display only: the Reader's roles still come from the
/// server's `turns[]` (R-PB3), never from this pattern.
extension ExcerptText {
    struct Stripped: Equatable {
        let text: String
        /// Raw scalar ranges removed, ascending and disjoint.
        let deleted: [Range<Int>]

        /// A raw scalar offset in the clean text. An offset inside a removed run lands where the run was, so a span
        /// that began on `**` begins on the word after it.
        func map(_ offset: Int) -> Int {
            var shift = 0
            for run in deleted {
                if run.upperBound <= offset {
                    shift += run.count
                } else {
                    if run.lowerBound < offset { shift += offset - run.lowerBound }
                    break
                }
            }
            return offset - shift
        }

        func map(_ range: Range<Int>) -> Range<Int> {
            let lower = map(range.lowerBound)
            return lower..<max(lower, map(range.upperBound))
        }
    }

    /// `keepLines: false` is a quote's (the focus card, "Where this came from", a chip's preview): list markers and
    /// numbering go. `true` is the Reader's, which keeps a turn's lines: a bullet is drawn "•" and numbering stays,
    /// because a numbered list's order is words, not markup.
    static func stripMarkup(_ raw: String, keepLines: Bool) -> Stripped {
        let s = Array(raw.unicodeScalars)
        var drop = [Bool](repeating: false, count: s.count)
        var dot = [Bool](repeating: false, count: s.count)
        var start = 0
        while start <= s.count {
            var end = start
            while end < s.count, s[end] != "\n" { end += 1 }
            let words = MarkupScan.linePrefix(s, start, end, keepLines: keepLines, drop: &drop, dot: &dot)
            MarkupScan.inline(s, words, end, drop: &drop)
            start = end + 1
        }
        var text = String.UnicodeScalarView()
        var deleted: [Range<Int>] = []
        for k in s.indices {
            guard drop[k] else {
                text.append(dot[k] ? "•" : s[k])
                continue
            }
            if let last = deleted.last, last.upperBound == k {
                deleted[deleted.count - 1] = last.lowerBound..<(k + 1)
            } else {
                deleted.append(k..<(k + 1))
            }
        }
        return Stripped(text: String(text), deleted: deleted)
    }

    /// R-DL2 — one quote's three parts cleaned TOGETHER: the join is stripped once and split again at the mapped
    /// boundaries, so a marker that straddles the span is paired and the span stays exact. The one door for
    /// `QuoteBlock` and the focus card's quote.
    static func quoteParts(before: String, span: String, after: String) -> (before: String, span: String, after: String) {
        let head = before.unicodeScalars.count
        let tail = head + span.unicodeScalars.count
        let stripped = stripMarkup(before + span + after, keepLines: false)
        let text = ScalarText(stripped.text)
        let lower = min(stripped.map(head), text.count)
        let upper = min(max(stripped.map(tail), lower), text.count)
        return (text.slice(0, lower), text.slice(lower, upper), text.slice(upper, text.count))
    }
}

/// The scanner behind `stripMarkup`, in scalar offsets. One place for the rules.
enum MarkupScan {
    /// The writers' turn markers (`evidence._TURN_RE` and `_SPEAKER_RE`), plus the one space after.
    private static let roleMarker = try? NSRegularExpression(
        pattern: #"^(?:(?:user|human|assistant|ai|system|unknown)\s*:|speaker:[^:\n]{1,64}:|(?:video|media)\s*\[\d{1,2}(?::\d{2}){1,2}\]\s*:) ?"#,
        options: [.caseInsensitive])

    static func roleMarkerLength(_ s: [Unicode.Scalar], _ from: Int, _ end: Int) -> Int? {
        guard from < end, let roleMarker else { return nil }
        var view = String.UnicodeScalarView()
        view.append(contentsOf: s[from..<end])
        let line = String(view)
        guard let match = roleMarker.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)),
              let range = Range(match.range, in: line) else { return nil }
        return line.unicodeScalars.distance(from: line.unicodeScalars.startIndex, to: range.upperBound)
    }

    static func mark(_ drop: inout [Bool], _ from: Int, _ to: Int) {
        for k in from..<to { drop[k] = true }
    }

    static func isDigit(_ c: Unicode.Scalar) -> Bool { c.value >= 48 && c.value <= 57 }

    /// Marks one line's prefix markup (a role label, then a heading, a quote marker, a bullet or a number); returns
    /// where its words begin.
    static func linePrefix(_ s: [Unicode.Scalar], _ start: Int, _ end: Int, keepLines: Bool,
                           drop: inout [Bool], dot: inout [Bool]) -> Int {
        var p = start
        while p < end, s[p] == " " || s[p] == "\t" { p += 1 }
        if let n = roleMarkerLength(s, p, end) {
            mark(&drop, p, p + n)
            p += n
        }
        var q = p
        while q < end, s[q] == "#", q - p < 6 { q += 1 }
        if q > p, q < end, s[q] == " " {
            while q < end, s[q] == " " { q += 1 }
            mark(&drop, p, q)
            return q
        }
        if p < end, s[p] == ">" {
            q = p + 1
            if q < end, s[q] == " " { q += 1 }
            mark(&drop, p, q)
            return q
        }
        if p + 1 < end, s[p] == "-" || s[p] == "*" || s[p] == "+", s[p + 1] == " " {
            if keepLines {
                dot[p] = true
                return p + 1
            }
            q = p + 1
            while q < end, s[q] == " " { q += 1 }
            mark(&drop, p, q)
            return q
        }
        q = p
        while q < end, isDigit(s[q]) { q += 1 }
        if !keepLines, q > p, q + 1 < end, s[q] == ".", s[q + 1] == " " {
            var r = q + 1
            while r < end, s[r] == " " { r += 1 }
            mark(&drop, p, r)
            return r
        }
        return p
    }

    /// `code`, **strong** and *emphasis* on one line, CommonMark-flanked; only the markers are removed.
    static func inline(_ s: [Unicode.Scalar], _ from: Int, _ end: Int, drop: inout [Bool]) {
        func alnum(_ i: Int) -> Bool { i >= 0 && i < s.count && CharacterSet.alphanumerics.contains(s[i]) }
        func blank(_ i: Int) -> Bool { i < from || i >= end || s[i] == " " || s[i] == "\t" }
        var code = Set<Int>()
        var i = from
        while i < end {
            guard s[i] == "`", i + 1 < end, s[i + 1] != "`",
                  let j = (i + 1..<end).first(where: { s[$0] == "`" }) else { i += 1; continue }
            drop[i] = true
            drop[j] = true
            code.formUnion(i...j)
            i = j + 1
        }
        i = from
        while i + 1 < end {
            let opens = s[i] == "*" && s[i + 1] == "*" && !drop[i] && !code.contains(i)
                && !alnum(i - 1) && (i == from || s[i - 1] != "*") && !blank(i + 2)
            guard opens, let c = (i + 3..<max(i + 3, end - 1)).first(where: { j in
                s[j] == "*" && s[j + 1] == "*" && !code.contains(j) && !blank(j - 1)
                    && !alnum(j + 2) && (j + 2 >= end || s[j + 2] != "*")
            }) else { i += 1; continue }
            for k in [i, i + 1, c, c + 1] { drop[k] = true }
            i = c + 2
        }
        i = from
        while i + 1 < end {
            let opens = s[i] == "*" && s[i + 1] != "*" && !drop[i] && !code.contains(i)
                && (i == from || s[i - 1] != "*") && !alnum(i - 1) && !blank(i + 1)
            guard opens, let c = (i + 2..<max(i + 2, end)).first(where: { j in
                s[j] == "*" && !drop[j] && !code.contains(j) && s[j - 1] != "*"
                    && (j + 1 >= end || s[j + 1] != "*") && !blank(j - 1) && !alnum(j + 1)
            }) else { i += 1; continue }
            drop[i] = true
            drop[c] = true
            i = c + 1
        }
    }
}

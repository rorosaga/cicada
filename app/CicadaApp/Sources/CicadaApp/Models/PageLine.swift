import Foundation

/// The one door for **page text shown as a plain line** (owner 2026-11-23: *"fix when the text in search and appwide
/// makes links appear as [[example]]? it should always be rendered"*; DESIGN_RULES §9, 2026-11-23 "A link never shows as
/// brackets").
///
/// Page text in the bank is markdown: `[[Name]]`, `[[page-id]]`, `[[page-id|shown words]]`, `![[transclusion]]`, `**bold**`,
/// `_em_`, `` `code` `` and `[text](url)`. The entity article draws those; every other surface that shows a page's
/// words, a claim's, a question's or a search snippet as a `Text` goes through here, so none of them shows a bracket:
///
/// * a link reads as **the page's own name** (`PageLinkIndex`: an id, else exactly one page whose name or alias it is;
///   the words it was written under never show, the same rule the article's chip follows);
/// * an unknown or ambiguous one reads as its written words — the `|` words if it has some, else the ref, a slug
///   spelled as words ("alpha-project-notes" → "Alpha Project Notes");
/// * a link a snippet cut in half (`…favourite of [[Rodri`, `odrigo Sagastegui]] is`) reads as the words it still has;
/// * emphasis markers and code ticks are dropped, a `[text](url)` link reads as its text.
///
/// What it is not: the MCP tools, the CLI and `/v1` return page text as stored (an agent reads the brackets on purpose),
/// and the article keeps its own renderer. Display only — nothing that is sent changes.
///
/// **Offsets.** A search hit carries scalar offsets into the raw snippet for the words that matched. The cut here
/// replaces and deletes scalars, so the result carries a map (`Cleaned.map`): a range that touches a link covers the
/// whole name it became, so highlighting still marks what matched.
///
/// **Cost.** Pure and linear in the line; a line with no `[`, `*`, `_` or backtick is returned as it is, and a name is
/// a dictionary lookup (`PageLinkIndex` is built once per graph snapshot), so a 4,000-row list costs nothing per row
/// that is not on screen.
enum PageLine {
    /// The line as words, and how a raw scalar range lands in it.
    struct Cleaned: Equatable {
        let text: String
        /// Raw scalar runs and where each went: contiguous, ascending, covering the raw text.
        fileprivate let runs: [Run]
        fileprivate let stripped: ExcerptText.Stripped?

        func map(_ range: Range<Int>) -> Range<Int> {
            let lower = mapOffset(range.lowerBound, upper: false)
            let upper = max(lower, mapOffset(range.upperBound, upper: true))
            guard let stripped else { return lower..<upper }
            return stripped.map(lower..<upper)
        }

        /// A raw offset in the intermediate text (links resolved, markers still in). Inside a replaced run the start
        /// lands on the name's start and the end on its end.
        private func mapOffset(_ offset: Int, upper: Bool) -> Int {
            for run in runs {
                let inside = upper ? (run.raw.lowerBound < offset && offset <= run.raw.upperBound)
                                   : (run.raw.lowerBound <= offset && offset < run.raw.upperBound)
                guard inside else { continue }
                if run.identity { return run.out.lowerBound + (offset - run.raw.lowerBound) }
                return upper ? run.out.upperBound : run.out.lowerBound
            }
            return runs.last?.out.upperBound ?? 0
        }
    }

    fileprivate struct Run: Equatable {
        let raw: Range<Int>
        let out: Range<Int>
        let identity: Bool
    }

    /// `excerpt: true` is a conversation passage's (a search snippet): a turn's role label, a heading's hashes and a
    /// list marker at a line start go too (`ExcerptText.stripMarkup`). A page's own sentence never gets that.
    static func cleaned(_ raw: String, links: PageLinkIndex = .empty, excerpt: Bool = false) -> Cleaned {
        let plain = !excerpt && !raw.contains(where: { "[]*_`\n".contains($0) })
        if plain {
            let count = raw.unicodeScalars.count
            return Cleaned(text: raw, runs: [Run(raw: 0..<count, out: 0..<count, identity: true)], stripped: nil)
        }
        let (middle, runs) = resolveLinks(raw, links: links)
        let stripped = ExcerptText.stripMarkup(middle, keepLines: false, lines: excerpt, underscores: true)
        return Cleaned(text: stripped.text, runs: runs, stripped: stripped)
    }

    /// The line as words: links as names, markers gone. Newlines read as spaces (one line); a run of spaces is not
    /// collapsed, so a range into the raw text stays honest.
    static func plain(_ raw: String, links: PageLinkIndex = .empty, excerpt: Bool = false) -> String {
        cleaned(raw, links: links, excerpt: excerpt).text
    }

    /// `plain`, with the matched runs semibold (`ExcerptText.attributed`), the server's raw offsets mapped through the
    /// cut. A range that is stale or off the end is ignored, never trapped on.
    static func attributed(_ raw: String, bold offsets: [[Int]] = [], links: PageLinkIndex = .empty,
                           excerpt: Bool = false) -> AttributedString {
        let cleaned = cleaned(raw, links: links, excerpt: excerpt)
        guard !offsets.isEmpty else { return AttributedString(cleaned.text) }
        let rawCount = raw.unicodeScalars.count
        let mapped: [[Int]] = offsets.compactMap { pair in
            guard pair.count == 2, pair[0] >= 0, pair[0] < pair[1], pair[1] <= rawCount else { return nil }
            let range = cleaned.map(pair[0]..<pair[1])
            return range.isEmpty ? nil : [range.lowerBound, range.upperBound]
        }
        return ExcerptText.attributed(cleaned.text, bold: mapped)
    }

    /// Only the links of `raw` as words (no emphasis, no line rules): for a caller that has cleaned the rest itself, such
    /// as a conversation quote (`ExcerptText.clean`), where `_` is never emphasis (DR-18).
    static func resolvingLinks(_ raw: String, links: PageLinkIndex = .empty) -> String {
        guard raw.contains(where: { "[]".contains($0) }) else { return raw }
        return resolveLinks(raw, links: links).0
    }

    /// The first line of a page's text, as words — a link is resolved before the line is cut, so a cut never lands
    /// inside one. Nil when nothing is left.
    static func firstLine(_ raw: String, links: PageLinkIndex = .empty) -> String? {
        let line = raw.split(whereSeparator: \.isNewline).lazy
            .map { plain(String($0), links: links).trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty }
        return line
    }

    /// Whether a string still carries a link's brackets — the check `PageLineTests` and the source lint stand on.
    static func hasBrackets(_ text: String) -> Bool { text.contains("[[") || text.contains("]]") }

    // MARK: - Links

    /// Pass one: every `[[…]]`, `![[…]]` and `[text](url)` becomes its words, newlines become spaces (one scalar for
    /// one), and a half link at an edge loses its brackets. Returns the new text and the run map.
    private static func resolveLinks(_ raw: String, links: PageLinkIndex) -> (String, [Run]) {
        let s = Array(raw.unicodeScalars)
        var out = String.UnicodeScalarView()
        var outCount = 0
        var runs: [Run] = []

        func emit(_ text: String, raw range: Range<Int>, identity: Bool) {
            let scalars = text.unicodeScalars
            let n = scalars.count
            out.append(contentsOf: scalars)
            if identity, let last = runs.last, last.identity, last.raw.upperBound == range.lowerBound {
                runs[runs.count - 1] = Run(raw: last.raw.lowerBound..<range.upperBound,
                                           out: last.out.lowerBound..<(outCount + n), identity: true)
            } else {
                runs.append(Run(raw: range, out: outCount..<(outCount + n), identity: identity))
            }
            outCount += n
        }
        func scalarString(_ range: Range<Int>) -> String {
            var view = String.UnicodeScalarView()
            view.append(contentsOf: s[range])
            return String(view)
        }

        // A stray `]]` before any `[[` is the tail of a link the snippet cut: what is before it reads as words (the
        // part after a `|` if it has one), the brackets go. Only a short run with no bracket of its own: `a[b[0]]` is code.
        var i = 0
        if let close = indexOfPair(s, "]", from: 0), close <= 120,
           indexOfPair(s, "[", from: 0).map({ $0 > close }) ?? true,
           !s[0..<close].contains(where: { $0 == "\n" || $0 == "[" }) {
            emit(cutWords(scalarString(0..<close)), raw: 0..<(close + 2), identity: false)
            i = close + 2
        }
        var plainStart = i
        func flushPlain(to end: Int) {
            guard plainStart < end else { return }
            // Newlines read as spaces: one scalar for one, so a range into the raw text is unmoved.
            let text = scalarString(plainStart..<end).replacingOccurrences(of: "\n", with: " ")
            emit(text, raw: plainStart..<end, identity: true)
        }
        while i < s.count {
            // `![[x]]` and `[[x]]`
            let embed = s[i] == "!" && i + 2 < s.count && s[i + 1] == "[" && s[i + 2] == "["
            let open = embed ? i + 1 : i
            if i + 1 < s.count, s[open] == "[", open + 1 < s.count, s[open + 1] == "[", !indexesCode(s, before: open) {
                if let close = closeOfLink(s, after: open + 2) {
                    flushPlain(to: i)
                    emit(linkWords(scalarString((open + 2)..<close), links: links), raw: i..<(close + 2), identity: false)
                    i = close + 2
                    plainStart = i
                    continue
                }
                // No `]]` after it: the cut end of a link when the rest of the line has no bracket of its own — its
                // brackets go, its words stay (after a `|` when the display words were reached, else the ref as far
                // as it goes). Anything else is a stray `[[`: just those two scalars go.
                flushPlain(to: i)
                let end = lineEnd(s, from: open + 2)
                let rest = s[(open + 2)..<end]
                if !rest.contains(where: { $0 == "[" || $0 == "]" }) {
                    emit(cutWords(scalarString((open + 2)..<end)), raw: i..<end, identity: false)
                    i = end
                } else {
                    emit("", raw: i..<(open + 2), identity: false)
                    i = open + 2
                }
                plainStart = i
                continue
            }
            // `[text](url)` and `![alt](url)`
            let image = s[i] == "!" && i + 1 < s.count && s[i + 1] == "["
            let bracket = image ? i + 1 : i
            if s[bracket] == "[", bracket == 0 || !CharacterSet.alphanumerics.contains(s[bracket - 1]),
               let (textEnd, urlEnd) = markdownLink(s, from: bracket) {
                flushPlain(to: i)
                emit(scalarString((bracket + 1)..<textEnd), raw: i..<urlEnd, identity: false)
                i = urlEnd
                plainStart = i
                continue
            }
            i += 1
        }
        flushPlain(to: s.count)
        if runs.isEmpty { runs = [Run(raw: 0..<0, out: 0..<0, identity: true)] }
        return (String(out), runs)
    }

    /// `df[["a"]]`, `grid[[0, 1]]`, `m[i][[j]]` — a `[[` glued to the word, call or index before it is code, not a link.
    static func indexesCode(_ s: [Unicode.Scalar], before open: Int) -> Bool {
        guard open > 0 else { return false }
        let p = s[open - 1]
        return CharacterSet.alphanumerics.contains(p) || p == ")" || p == "]" || p == "_" || p == "."
    }

    /// What a closed link reads as: the page's own name when the ref means one page, else the written words.
    private static func linkWords(_ inner: String, links: PageLinkIndex) -> String {
        let parts = inner.split(separator: "|", maxSplits: 1, omittingEmptySubsequences: false)
        let ref = parts[0].trimmingCharacters(in: .whitespaces)
        let shown = parts.count > 1 ? parts[1].trimmingCharacters(in: .whitespaces) : ""
        if let target = links.resolve(ref), !target.name.isEmpty { return target.name }
        if !shown.isEmpty { return shown }
        return humanised(ref)
    }

    /// A slug reads as its page's name ("alpha-project-notes" → "Alpha Project Notes"); anything else as written.
    static func humanised(_ name: String) -> String {
        guard name.range(of: #"^[a-z0-9]+(?:-[a-z0-9]+)+$"#, options: .regularExpression) != nil else { return name }
        return name.split(separator: "-").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
    }

    /// The words of a cut link: after a `|` when it has one, else the ref as far as it goes (a slug as words).
    private static func cutWords(_ text: String) -> String {
        guard let bar = text.lastIndex(of: "|") else { return humanised(text.trimmingCharacters(in: .whitespaces)) }
        return String(text[text.index(after: bar)...]).trimmingCharacters(in: .whitespaces)
    }

    private static func lineEnd(_ s: [Unicode.Scalar], from: Int) -> Int {
        var j = from
        while j < s.count, s[j] != "\n" { j += 1 }
        return j
    }

    /// Where the first `cc` pair (`]]` or `[[`) starts at or after `from`.
    private static func indexOfPair(_ s: [Unicode.Scalar], _ c: Unicode.Scalar, from: Int) -> Int? {
        var j = from
        while j + 1 < s.count {
            if s[j] == c, s[j + 1] == c { return j }
            j += 1
        }
        return nil
    }

    /// The `]]` that closes a link opened before `from`: on the same line, with no `[` or `]` between.
    private static func closeOfLink(_ s: [Unicode.Scalar], after from: Int) -> Int? {
        var j = from
        while j < s.count {
            if s[j] == "\n" || s[j] == "[" { return nil }
            if s[j] == "]" { return j + 1 < s.count && s[j + 1] == "]" && j > from ? j : nil }
            j += 1
        }
        return nil
    }

    /// `[text](url)` starting at `from`: the end of the text and the end of the whole link.
    private static func markdownLink(_ s: [Unicode.Scalar], from: Int) -> (Int, Int)? {
        var j = from + 1
        while j < s.count, s[j] != "]", s[j] != "[", s[j] != "\n" { j += 1 }
        guard j < s.count, s[j] == "]", j + 1 < s.count, s[j + 1] == "(", j > from + 1 else { return nil }
        var k = j + 2
        while k < s.count, s[k] != ")", s[k] != "\n", s[k] != " " { k += 1 }
        guard k < s.count, s[k] == ")" else { return nil }
        return (j, k + 1)
    }
}

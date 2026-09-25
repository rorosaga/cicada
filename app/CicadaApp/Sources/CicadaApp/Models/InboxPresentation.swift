import Foundation

/// The pure half of the G115 card, kept out of the views so it is testable:
/// the cause line, the age phrase (same wording as the server's
/// `inbox_questions.humanize_age`), the bolded excerpt, and the collapse rule.
enum InboxAge {
    /// The instant an ISO date or timestamp names; `nil` if unparseable. A bare day is UTC midnight.
    static func date(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime]
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        return full.date(from: iso) ?? fractional.date(from: iso) ?? dayOnly.date(from: String(iso.prefix(10)))
    }

    /// Whole days between an ISO date/timestamp and `now`; `nil` if unparseable.
    static func days(since iso: String?, now: Date) -> Int? {
        guard let then = date(iso) else { return nil }
        return max(0, Int(now.timeIntervalSince(then) / 86_400))
    }

    /// Word-for-word `inbox_questions.humanize_age` — including the branch
    /// boundaries (the week branch starts at 14 days, the month branch at 60),
    /// so a card and an MCP blurb never disagree about the same item's age.
    /// The rounding rule is part of that parity: Python's `round()` is
    /// round-half-to-EVEN, so 75 days is "2 months ago" there and would be
    /// "3 months ago" under Swift's default `.rounded()` (half away from zero).
    /// `.toNearestOrEven` keeps the two surfaces in step.
    static func phrase(days: Int?) -> String {
        guard let days else { return "unknown" }
        if days == 0 { return "today" }
        if days == 1 { return "yesterday" }
        if days < 14 { return "\(days) days ago" }
        if days < 60 {
            let weeks = Int((Double(days) / 7).rounded(.toNearestOrEven))
            return weeks == 1 ? "a week ago" : "\(weeks) weeks ago"
        }
        if days < 365 {
            let months = Int((Double(days) / 30).rounded(.toNearestOrEven))
            return months == 1 ? "a month ago" : "\(months) months ago"
        }
        let years = Int((Double(days) / 365).rounded(.toNearestOrEven))
        return years == 1 ? "a year ago" : "\(years) years ago"
    }
}

enum ExcerptText {
    /// The excerpt with each `[start, end)` scalar range bolded. Ranges that
    /// fall outside the text are ignored — a stale offset must never crash
    /// the card (the server recomputes offsets on every read; the cache may
    /// hold an older excerpt for a moment).
    static func attributed(_ excerpt: String, bold offsets: [[Int]]) -> AttributedString {
        var out = AttributedString(excerpt)
        let scalars = excerpt.unicodeScalars
        let count = scalars.count
        for pair in offsets where pair.count == 2 {
            let (s, e) = (pair[0], pair[1])
            guard s >= 0, e > s, e <= count else { continue }
            let lower = scalars.index(scalars.startIndex, offsetBy: s)
            let upper = scalars.index(scalars.startIndex, offsetBy: e)
            guard let aLower = AttributedString.Index(lower, within: out),
                  let aUpper = AttributedString.Index(upper, within: out) else { continue }
            out[aLower..<aUpper].inlinePresentationIntent = .stronglyEmphasized
        }
        return out
    }
}

/// The owner's second defect (2026-09-03): merge/clarification items over media
/// rendered every URL inline. More than `threshold` non-blank lines collapse to
/// the first `visible` plus a "Show all N" toggle — four lines are not worth
/// the toggle, five are.
struct CollapsedLines {
    static let visible = 3
    static let threshold = 4

    let lines: [String]

    init(_ text: String) {
        lines = text.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    var needsCollapse: Bool { lines.count > Self.threshold }
    var head: [String] { needsCollapse ? Array(lines.prefix(Self.visible)) : lines }
    var hidden: Int { needsCollapse ? lines.count - Self.visible : 0 }
}

extension InboxItem {
    /// A cause that actually resolved to an episode.
    var hasCause: Bool { (cause?.tier ?? "none") != "none" }

    /// Index of the `(Recommended)` option in `options`, if any.
    var recommendedIndex: Int? {
        options.firstIndex(where: \.recommended)
    }
}

/// R-DI5 / DR-42 — what the Undo row says for an answer: the full form in the list, the short
/// one while the Reader is open ("Answered · Undo"). Words, never the action's wire name.
enum UndoLabel {
    /// R-DL5 — `names` shows a picked option that is a page's id as that page's name, as the card did.
    static func of(_ r: QuestionResolution, item: InboxItem, names: EntityNames = .empty) -> (full: String, short: String) {
        let typed = r.answer?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        switch r.action {
        case "resolve":
            if r.optionKey == "remind_later" { return (Copy.Inbox.notNow, Copy.Inbox.notNow) }
            if !typed.isEmpty { return (Copy.Inbox.answered(typed), Copy.Inbox.answered) }
            if let key = r.optionKey, let option = item.options.first(where: { $0.key == key }) {
                return (Copy.Inbox.answered(names.display(option.label)), Copy.Inbox.answered)
            }
            return (Copy.Inbox.answered, Copy.Inbox.answered)
        case "answer":
            return (typed.isEmpty ? Copy.Inbox.answered : Copy.Inbox.answered(typed), Copy.Inbox.answered)
        case "defer", "remind_later":
            return (Copy.Inbox.notNow, Copy.Inbox.notNow)
        case "dismiss":
            let words = item.informational ? Copy.Inbox.gotIt : Copy.Inbox.dismissed
            return (words, words)
        case "skip": return (Copy.Inbox.skipped, Copy.Inbox.skipped)
        case "reject": return (Copy.Inbox.keptSeparate, Copy.Inbox.kept)
        case "merge": return (Copy.Inbox.merged, Copy.Inbox.merged)
        case "keep_active": return (Copy.Inbox.kept, Copy.Inbox.kept)
        case "archive": return (Copy.Inbox.archived, Copy.Inbox.archived)
        default: return (Copy.Inbox.answered, Copy.Inbox.answered)
        }
    }
}

extension InboxAge {
    /// DR-58 / R-DI12 — an age for a row or an option tag: "today", "5d", "3w", "6mo", "2y". The
    /// same branch boundaries and half-even rounding as `phrase(days:)`, so "3w" beside "3 weeks ago"
    /// on the same card never disagree.
    static func compact(days: Int) -> String {
        if days <= 0 { return "today" }
        if days < 14 { return "\(days)d" }
        if days < 60 { return "\(Int((Double(days) / 7).rounded(.toNearestOrEven)))w" }
        if days < 365 { return "\(Int((Double(days) / 30).rounded(.toNearestOrEven)))mo" }
        return "\(Int((Double(days) / 365).rounded(.toNearestOrEven)))y"
    }
}

/// DR-58 — a row's age: compact, measured from the conversation that raised it, with the absolute
/// day in `.help`. A question with no source keeps G125's "—", and its reason (DR-55).
enum InboxRowAge {
    static func of(_ item: InboxItem, now: Date, locale: Locale = .autoupdatingCurrent,
                   timeZone: TimeZone = .autoupdatingCurrent) -> (text: String, help: String) {
        guard item.hasCause, let cause = item.cause,
              let then = cause.timestamp.flatMap({ ReaderTime.instant($0, timeZone: timeZone) })
                ?? cause.episodeId.flatMap({ ReaderTime.episodeDate($0, timeZone: timeZone) }) else {
            return ("—", Copy.Inbox.noSourceAge)
        }
        let days = max(0, Int(now.timeIntervalSince(then) / 86_400))
        let day = ReaderTime.day(timestamp: cause.timestamp, episode: cause.episodeId ?? "",
                                 locale: locale, timeZone: timeZone) ?? ""
        return (InboxAge.compact(days: days), day)
    }
}

/// DR-54 / R-DI12 — a source named the way a person would: the app, the conversation's title, the
/// day. Ids and slugs never reach body weight; the episode id lives in `.help` only. Replaces the
/// pre-DS-2 cause line, which printed the raw harness slug.
enum InboxSourceLine {
    /// G115 / DR-55 — served exactly as written, never louder than a real source line.
    static let noSource = "[ no source recorded ]"

    static func app(_ cause: InboxCause) -> String? {
        if let agent = EvidenceSpeaker.agentName(harness: cause.harness, origin: cause.origin) { return agent }
        guard let origin = cause.origin?.trimmingCharacters(in: .whitespaces), !origin.isEmpty,
              origin != "unknown", origin != "mcp" else { return nil }
        return OriginIconography.label(for: origin)
    }

    /// The origin whose real mark sits beside the line (DR-52) — the same precedence as `app`.
    static func markOrigin(_ item: InboxItem) -> String? {
        guard item.hasCause, let cause = item.cause else { return nil }
        if let agent = EvidenceSpeaker.agentOrigin(harness: cause.harness, origin: cause.origin) { return agent }
        guard let origin = cause.origin, !origin.isEmpty, origin != "unknown", origin != "mcp" else { return nil }
        return origin
    }

    private static func day(_ cause: InboxCause, _ locale: Locale, _ timeZone: TimeZone) -> String? {
        ReaderTime.day(timestamp: cause.timestamp, episode: cause.episodeId ?? "", locale: locale,
                       timeZone: timeZone, withYear: false)
    }

    private static func title(_ cause: InboxCause) -> String? {
        let t = cause.conversationTitle?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? nil : t
    }

    /// The card's line: "Claude Code · Index choice · Aug 25" / "a Claude Code conversation · Aug 25".
    static func full(_ item: InboxItem, locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> String {
        guard item.hasCause, let cause = item.cause else { return noSource }
        var parts: [String] = []
        if let title = title(cause) {
            if let app = app(cause) { parts.append(app) }
            parts.append(title)
        } else {
            parts.append(app(cause).map(Copy.Inbox.aConversation) ?? Copy.Inbox.aConversationPlain)
        }
        if let d = day(cause, locale, timeZone) { parts.append(d) }
        return parts.joined(separator: " · ")
    }

    /// The row's slot (§5.3): "Claude Code · Aug 25" — the title is the card's to say.
    static func row(_ item: InboxItem, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent) -> String {
        guard item.hasCause, let cause = item.cause else { return noSource }
        var parts = [app(cause) ?? title(cause) ?? Copy.Inbox.aConversationPlain]
        if let d = day(cause, locale, timeZone) { parts.append(d) }
        return parts.joined(separator: " · ")
    }

    /// DR-54 — the id, reachable only through `.help` ("Episode ep_…").
    static func help(_ item: InboxItem) -> String? {
        guard item.hasCause, let ep = item.cause?.episodeId, !ep.isEmpty else { return nil }
        return "Episode \(ep)"
    }
}

extension ExcerptText {
    /// DR-56 / R-DI22 — clean text for a quote: heading hashes, bullets and quote markers at a line's
    /// start go, `[[a|b]]` reads "b", `[[slug-name]]` reads "Slug Name", and every whitespace run is
    /// one space. It runs on each segment AFTER the split, so the mention's scalar offsets never
    /// move, and it never trims a segment's edges — that would glue "Discussed" to "swapping".
    /// `atLineStart: false` is for a segment that begins mid-line (the span, the text after it): its
    /// first line is not a line start, so a "- " there is a minus, not a bullet. A link the mention
    /// split in two leaves a stray `[[`, `[[target|` or `]]` at a segment's edge; those go too.
    static func clean(_ text: String, atLineStart: Bool = true) -> String {
        let linePrefix = try? NSRegularExpression(pattern: #"^\s*(?:#{1,6}\s+|[-*+]\s+|>\s?|\d+\.\s+)"#)
        let lines = text.components(separatedBy: "\n").enumerated().map { index, line -> String in
            guard let linePrefix, index > 0 || atLineStart else { return line }
            let ns = line as NSString
            return linePrefix.stringByReplacingMatches(in: line, range: NSRange(location: 0, length: ns.length),
                                                       withTemplate: "")
        }
        var joined = lines.joined(separator: " ")
        if let link = try? NSRegularExpression(pattern: #"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]"#) {
            let ns = joined as NSString
            var out = ""
            var last = 0
            for m in link.matches(in: joined, range: NSRange(location: 0, length: ns.length)) {
                out += ns.substring(with: NSRange(location: last, length: m.range.location - last))
                if m.range(at: 2).location != NSNotFound {
                    out += ns.substring(with: m.range(at: 2)).trimmingCharacters(in: .whitespaces)
                } else {
                    out += humanised(ns.substring(with: m.range(at: 1)).trimmingCharacters(in: .whitespaces))
                }
                last = m.range.location + m.range.length
            }
            out += ns.substring(from: last)
            joined = out
        }
        joined = joined.replacingOccurrences(of: #"\[\[(?:[^\[\]|]*\|)?|\]\]"#, with: "", options: .regularExpression)
        return joined.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
    }

    /// A slug reads as its page's name ("alpha-project-notes" → "Alpha Project Notes").
    private static func humanised(_ name: String) -> String {
        guard name.range(of: #"^[a-z0-9]+(?:-[a-z0-9]+)+$"#, options: .regularExpression) != nil else { return name }
        return name.split(separator: "-").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
    }
}

/// §5.3 item 3 / R-DI11 — the focus card's quote: the cause excerpt split at its first mention,
/// each piece cleaned (DR-56). An asserted G118 span is washed and underlined (DR-18); a mention
/// found by name is semibold and unwashed (DR-57, G118 §4.9) — the words were found, not quoted.
enum QuoteSegments {
    static func of(_ item: InboxItem) -> [CitedSpan.Segment]? {
        guard item.hasCause, let cause = item.cause, !cause.excerpt.isEmpty else { return nil }
        let raw = QuoteBlock.parts(excerpt: cause.excerpt, mentionOffsets: cause.mentionOffsets)
        // R-DL2 — markup and role labels leave the WHOLE excerpt first, the mention mapped through the cut, so a
        // `**` around it is paired and the wash covers exactly the words; `clean` then does wikilinks and spacing.
        let parts = ExcerptText.quoteParts(before: raw.before, span: raw.span, after: raw.after)
        let mark: CitedSpan.Mark = cause.spanKind == "asserted" ? .current : .mention
        let pieces: [(String, CitedSpan.Mark)] = [(parts.before, .plain), (parts.span, mark), (parts.after, .plain)]
        // Only `before` opens on a real line start; the span and the rest begin mid-line (R-DI22).
        let segments = pieces.enumerated()
            .map { i, piece in CitedSpan.Segment(text: ExcerptText.clean(piece.0, atLineStart: i == 0), mark: piece.1) }
            .filter { !$0.text.isEmpty }
        return segments.isEmpty ? nil : segments
    }

    /// Whether the card says "Found by searching the conversation" under the quote.
    static func isDerived(_ item: InboxItem) -> Bool {
        guard item.hasCause, let cause = item.cause else { return false }
        return cause.spanKind != "asserted" && !cause.mentionOffsets.isEmpty
    }
}

/// G115 §7 — the extractor's side of the question, stated before the person answers. Never on an
/// informational card: there is nothing to grade (the mock's `hasGuess && !vInfo`).
enum InboxGuess {
    static func text(_ item: InboxItem) -> String? {
        guard !item.informational,
              let model = item.extractorModel ?? (item.extractorConfidence.map { _ in "Cicada" }) else { return nil }
        return item.extractorConfidence.map { String(format: "%@'s guess at %.2f", model, $0) } ?? "\(model)'s guess"
    }
}

/// G61 — the hint's "Open source ↗" target: its first URL, or nothing to open.
enum HintLink {
    static func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
        return detector.firstMatch(in: text, range: NSRange(text.startIndex..., in: text))?.url
    }

    /// The hint as the person reads it (round-4 final review, finding 3). The server keeps a Contacts card's ref in
    /// the sentence — "Their card in your Contacts (addressbook://<id>) is where to check this" — so `firstURL` can
    /// find it for the button; drawn word for word it put a raw Contacts id in the Inbox, which the entity card
    /// already hides (DR-54). Only a parenthesised `addressbook://` ref is removed; every other hint is unchanged.
    static func displayText(_ hint: String) -> String {
        hint.replacingOccurrences(of: #"\s*\(addressbook://[^)\s]*\)"#, with: "", options: .regularExpression)
    }

    /// True when the link opens a card in the Mac's Contacts app — the button then says so.
    static func isContacts(_ url: URL) -> Bool { url.scheme?.lowercased() == "addressbook" }
}

/// A typed answer, in the wire shape each item was built for: a G60 question object answers through
/// `resolve` (the backend closes every option claim and records the person's words; a clarification
/// takes `resolve` as an alias of `answer`); a legacy clarification through `answer`. Both shapes
/// shipped before DS-2 (the Other… field and the legacy Answer row), and both keep working.
enum FreeTextSubmit {
    static func resolution(for item: InboxItem, text: String) -> QuestionResolution? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        if item.question != nil || !item.options.isEmpty {
            return QuestionResolution(action: "resolve", answer: t,
                                      optionKey: item.options.contains { $0.key == "neither" } ? "neither" : nil)
        }
        return QuestionResolution(action: "answer", answer: t)
    }
}

/// DR-43 / R-DI15 — which body the focus card draws. Order matters: G98's informational flag
/// outranks the options it lists; options outrank the legacy shapes they replaced.
enum FocusCardVariant: Equatable {
    case informational, options, merge, legacyDecay, freeText, dismissOnly

    static func of(_ item: InboxItem) -> FocusCardVariant {
        if item.informational { return .informational }
        if !item.options.isEmpty { return .options }
        if item.kind == .mergeSuggestion || item.requiredInput == .merge { return .merge }
        if item.kind == .decay { return .legacyDecay }
        if item.allowOther || item.requiredInput == .freetext || item.question != nil { return .freeText }
        return .dismissOnly
    }
}

/// The merge's direction in words: "Tool Example A (CLI) → tool-example-a".
enum MergeDirection {
    static func line(survivorIsMention: Bool, mention: String, existing: String) -> String? {
        let (from, to) = survivorIsMention ? (existing, mention) : (mention, existing)
        guard !from.isEmpty, !to.isEmpty else { return nil }
        return "\(from) → \(to)"
    }
}

import Foundation

/// What an opened page change says and draws, pure so `RunPageChangeModelTests` holds every rule without a view (owner
/// 2026-11-24: "pages render normally, not as raw markdown, because it's harder to read what the actual changes were —
/// and I don't get why a page was modified, what influenced this change?").
///
/// The backend computes the change (`SleepPageChange`); this is how it reads: why first (what is not already said by the
/// card the chip sits under), then facts as sentences with what moved in words, then the page's own text in blocks with
/// the changed words marked, then the few other things that moved.
enum RunPageChangeModel {
    typealias Step = SleepConsolidated.Step

    // MARK: Why

    /// The card the opened chip sits under, so the panel never says again what the card already said.
    struct Parent: Equatable {
        var conversation: String? = nil
        var step: Step? = nil
        static let none = Parent()
    }

    /// What else changed the page than the card it sits under says: the other conversations of the run that fed it, or
    /// — only when no conversation fed it (the backend's rule) — the other steps.
    struct Why: Equatable {
        var conversations: [SleepConsolidated.Conversation] = []
        var steps: [Step] = []
        var isEmpty: Bool { conversations.isEmpty && steps.isEmpty }
    }

    static func why(_ change: SleepPageChange, parent: Parent) -> Why {
        let page = change.page
        if !page.episodes.isEmpty {
            let rows = page.episodes.compactMap { id in change.conversations.first { $0.id == id }?.conversation }
            return Why(conversations: rows.filter { $0.id != parent.conversation })
        }
        return Why(steps: RunItemsModel.otherSteps(page, parent: parent.step))
    }

    /// The conversation to show beside a fact: the one its own evidence names, unless it is the card's own.
    static func factConversation(_ fact: SleepPageChange.Fact, in change: SleepPageChange, parent: Parent)
        -> SleepConsolidated.Conversation? {
        guard let id = fact.conversation, id != parent.conversation,
              !why(change, parent: parent).conversations.contains(where: { $0.id == id }) else { return nil }
        return change.conversation(id)
    }

    // MARK: Sections

    /// How many parts the opened change draws (why, each group of facts, text, the page's own record): with more than one
    /// each is named by a quiet label, and the line over it stays silent; with one the line over it says what it holds.
    static func sectionCount(_ change: SleepPageChange, parent: Parent) -> Int {
        let f = change.facts
        return (why(change, parent: parent).isEmpty ? 0 : 1)
            + [f.added, f.changed, f.withdrawn].filter { !$0.isEmpty }.count
            + (change.prose.hasChange ? 1 : 0)
            + (!change.other.isEmpty || change.otherDetails > 0 ? 1 : 0)
    }

    // MARK: The line over it

    /// "1 new fact · 1 fact changed · 1 passage edited": what is in the change, said once. Nil when nothing is.
    static func summary(_ change: SleepPageChange, locale: Locale = .autoupdatingCurrent) -> String? {
        let facts = change.facts
        func n(_ key: String, _ fallback: Int) -> Int { facts.counts[key] ?? fallback }
        let prose = change.prose.counts
        return Copy.RunChange.summary(
            added: n("added", facts.added.count), changed: n("changed", facts.changed.count),
            withdrawn: n("withdrawn", facts.withdrawn.count),
            passagesAdded: prose["added"] ?? 0, passagesEdited: prose["edited"] ?? 0, passagesRemoved: prose["removed"] ?? 0,
            other: change.other.count + change.otherDetails, locale)
    }

    // MARK: What moved in a fact

    /// What changed in one fact, in words (never the field's name, a claim id or a value as stored): "Confidence 80% → 60%
    /// · Ended Sep 30". A reworded fact says so once, however many of its parts moved.
    static func factWords(_ fact: SleepPageChange.Fact, locale: Locale = .autoupdatingCurrent) -> String? {
        var words: [String] = []
        for change in fact.changes {
            guard let word = fieldWords(change, locale: locale), !words.contains(word) else { continue }
            words.append(word)
        }
        return words.isEmpty ? nil : words.joined(separator: " · ")
    }

    static func fieldWords(_ c: SleepPageChange.FieldChange, locale: Locale = .autoupdatingCurrent) -> String? {
        func day(_ iso: String) -> String { EntityDates.shortDay(iso, locale: locale) ?? iso }
        switch c.field {
        case "text", "subject", "predicate", "object":
            return Copy.RunChange.reworded
        case "valid_from":
            return c.after.map { Copy.RunChange.startsOn(day($0)) }
        case "valid_to":
            return c.after.map { Copy.RunChange.endedOn(day($0)) } ?? Copy.RunChange.reopened
        case "expected_end":
            return c.after.map { Copy.RunChange.expectedToEnd(day($0)) } ?? Copy.RunChange.noExpectedEnd
        case "superseded_by":
            return c.after == nil ? Copy.RunChange.stoppedReplaced : Copy.RunChange.replaced
        case "supersedes":
            return c.after == nil ? nil : Copy.RunChange.replacesOne
        case "status":
            return c.after.map { Copy.RunChange.status(Copy.RunChange.statusWord($0).lowercased()) }
        case "target":
            return Copy.RunChange.aboutAnotherPage
        case "context":
            return c.after.map { Copy.RunChange.movedTo(ClaimContext.displayName($0).lowercased()) }
        case "source_trust":
            return c.after.map { Copy.RunChange.trust((SourceTrust(rawValue: $0)?.label ?? $0).lowercasedFirst) }
        case "observer":
            return c.after.map { Copy.RunChange.heldBy(Observer(wire: $0).label) }
        case "epistemic":
            return c.after.map { Copy.RunChange.readAs(epistemicWords($0)) }
        case "confidence":
            guard let after = c.after.flatMap(percent) else { return nil }
            return Copy.RunChange.confidence(c.before.flatMap(percent), after)
        case "sources":
            if !c.added.isEmpty { return Copy.RunChange.moreConversations(c.added.count, locale) }
            if !c.removed.isEmpty { return Copy.RunChange.fewerConversations(c.removed.count, locale) }
            return nil
        default:
            return Copy.RunChange.detailsChanged
        }
    }

    /// "0.8" → "80%".
    static func percent(_ raw: String) -> String? {
        guard let value = Double(raw) else { return nil }
        return "\(Int((value * 100).rounded()))%"
    }

    private static func epistemicWords(_ raw: String) -> String {
        switch raw {
        case "explicit": "stated outright"
        case "deductive": "reasoned from other facts"
        case "inductive": "a pattern across conversations"
        case "abductive": "a best guess"
        default: raw
        }
    }

    // MARK: What moved on the page

    /// One page-level change as lines of words: a new alias, a status move.
    static func otherLines(_ c: SleepPageChange.FieldChange) -> [String] {
        switch c.field {
        case "status":
            guard let after = c.after else { return [] }
            let to = Copy.RunChange.statusWord(after)
            return [c.before.map { Copy.RunChange.statusMoved(from: Copy.RunChange.statusWord($0), to: to) } ?? to]
        case "name":
            guard let after = c.after else { return [] }
            return [c.before.map { Copy.RunChange.renamed(from: $0, to: after) } ?? after]
        case "type":
            guard let after = c.after else { return [] }
            return [c.before.map { Copy.RunChange.retyped(from: $0, to: after) } ?? after]
        case "decay_class":
            return c.after.map { [Copy.RunChange.keptAs(decayWords($0))] } ?? []
        case "aliases":
            return lines(c, add: Copy.RunChange.addedAlias, remove: Copy.RunChange.removedAlias)
        case "tags":
            return lines(c, add: Copy.RunChange.addedTag, remove: Copy.RunChange.removedTag)
        case "sources":
            return lines(c, add: Copy.RunChange.addedSource, remove: Copy.RunChange.removedSource)
        default:
            return []
        }
    }

    private static func lines(_ c: SleepPageChange.FieldChange, add: ([String]) -> String, remove: ([String]) -> String)
        -> [String] {
        (c.added.isEmpty ? [] : [add(c.added)]) + (c.removed.isEmpty ? [] : [remove(c.removed)])
    }

    private static func decayWords(_ raw: String) -> String {
        switch raw {
        case "evergreen": "never fading"
        case "durable": "lasting"
        case "active": "active"
        case "volatile": "short-lived"
        default: raw
        }
    }

    // MARK: The page's text

    /// One thing the text section draws, in the page's own order: a heading a block sits under (said once, in a quiet
    /// line, when the heading itself is not drawn) or a block.
    enum ProseItem: Equatable, Identifiable {
        case under(String, id: Int)
        case block(SleepPageChange.Block, id: Int)

        var id: Int {
            switch self {
            case .under(_, let id), .block(_, let id): id
            }
        }
    }

    /// The blocks with a quiet "under <heading>" line before the first block of each section whose heading is not drawn.
    static func proseItems(_ blocks: [SleepPageChange.Block]) -> [ProseItem] {
        var items: [ProseItem] = []
        var current: String?
        for block in blocks {
            if block.level > 0 {
                current = plain(block.markdown)
            } else if let heading = block.heading.map(plain), !heading.isEmpty, heading != current {
                items.append(.under(heading, id: items.count))
                current = heading
            }
            items.append(.block(block, id: items.count))
        }
        return items
    }

    /// A heading's inline markdown as the words a person reads.
    static func plain(_ markdown: String) -> String {
        var text = markdown.trimmingCharacters(in: .whitespaces)
        while text.hasPrefix("#") { text.removeFirst() }
        return String(WikiInline.attributed(text.trimmingCharacters(in: .whitespaces)).characters)
    }

    /// The blocks of a section the card draws before "Show all".
    static let blocksShown = 8
    /// The facts of a group the card draws before "Show all" (DR-81: at most five rows).
    static let factsShown = 5

    /// The block as the article's rows, with the changed words marked: an edited paragraph shows its new words washed and
    /// its old words struck through in place; a removed block is struck through whole; an added or context block is the
    /// page's own text. `marked` is false for a page's first or last text (a created or removed page is whole text, with
    /// nothing to wash).
    static func rows(_ block: SleepPageChange.Block, marked: Bool = true) -> [WikiRow] {
        var rows = WikiArticle.build(block.markdown, dropping: []).rows
        // A heading with nothing under it in this block (the article drops an empty section): the block is that heading.
        if rows.isEmpty, block.level > 0 {
            let title = WikiInline.attributed(plain(block.markdown))
            rows = [WikiRow(id: 0, kind: .heading(level: block.level), text: title, source: 0..<block.markdown.count)]
        }
        guard marked, !rows.isEmpty else { return rows }
        switch block.op {
        case .removed:
            rows = rows.map { row in
                var text = row.text
                text[ProseMark.self] = .removed
                return WikiRow(id: row.id, kind: row.kind, text: text, source: row.source, links: row.links)
            }
        case .edited:
            if rows.count == 1, let text = edited(block.segments, base: rows[0].text) {
                rows[0] = WikiRow(id: rows[0].id, kind: rows[0].kind, text: text, source: rows[0].source, links: rows[0].links)
            }
        case .added, .context:
            break
        }
        return rows
    }

    /// An edited paragraph's words: the new text with the added words washed, the removed words struck through where they
    /// stood. `base` is the paragraph as the article renders it; segments that tile it exactly are marked in it (so every
    /// link and emphasis is the article's own); a paragraph the segments cannot tile (a link whose mention adds words, an
    /// emphasis cut across two segments) is drawn from the segments alone, which still shows every change.
    static func edited(_ segments: [SleepPageChange.Segment], base: AttributedString) -> AttributedString? {
        guard segments.contains(where: { $0.op != .equal }) else { return nil }
        let segs = strippingBlockSyntax(segments)
        if let tiled = tile(segs, in: base) { return tiled }
        var out = AttributedString()
        for (n, seg) in segs.enumerated() {
            var part = WikiInline.attributed(seg.text)
            switch seg.op {
            case .equal: break
            case .added: part[ProseMark.self] = .added
            case .removed: part[ProseMark.self] = .removed
            }
            out += part
            if seg.op == .removed { out += gap(after: seg, next: n + 1 < segs.count ? segs[n + 1] : nil) }
        }
        return out
    }

    /// One plain space between struck-through words and the words that replaced them, when neither side has one: the old
    /// and the new would otherwise read as a single word.
    private static func gap(after removed: SleepPageChange.Segment, next: SleepPageChange.Segment?) -> AttributedString {
        guard let next, next.op == .added, let last = removed.text.last, let first = next.text.first,
              !last.isWhitespace, !first.isWhitespace else { return AttributedString() }
        return AttributedString(" ")
    }

    private static func tile(_ segments: [SleepPageChange.Segment], in base: AttributedString) -> AttributedString? {
        var out = AttributedString()
        var cursor = base.startIndex
        for (n, seg) in segments.enumerated() {
            if seg.op == .removed {
                var part = WikiInline.attributed(seg.text)
                part[ProseMark.self] = .removed
                out += part
                out += gap(after: seg, next: n + 1 < segments.count ? segments[n + 1] : nil)
                continue
            }
            let length = WikiInline.attributed(seg.text).characters.count
            guard base[cursor...].characters.count >= length else { return nil }
            let end = base.index(cursor, offsetByCharacters: length)
            var part = AttributedString(base[cursor..<end])
            if seg.op == .added { part[ProseMark.self] = .added }
            out += part
            cursor = end
        }
        // The rest of the paragraph may only be the whitespace its own trimming dropped.
        return String(base[cursor...].characters).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? out : nil
    }

    /// The leading `- `, `1. `, `## ` or `> ` of the paragraph's first segment: the article draws it as its own marker.
    private static let blockSyntax = try! NSRegularExpression(pattern: #"^(?:#{1,6}[ \t]+|(?:[-*+]|\d+[.)])[ \t]+|>[ \t]?)"#)

    static func strippingBlockSyntax(_ segments: [SleepPageChange.Segment]) -> [SleepPageChange.Segment] {
        guard let first = segments.first else { return segments }
        let ns = first.text as NSString
        guard let match = blockSyntax.firstMatch(in: first.text, range: NSRange(location: 0, length: ns.length)) else {
            return segments
        }
        var out = segments
        out[0].text = ns.substring(from: match.range.upperBound)
        return out
    }
}

import Foundation

/// Ruling 48 — the entity page's blocks in words. Pure, so every line the page draws is pinned by a test
/// (`PagesV2Tests`); the views only lay them out.
enum PageWords {
    // MARK: Where to check (DR-79)

    /// The rows the box draws: links and notes the page trusts or the person added — never a waiting proposal, which
    /// is the one Review line (ruling 36 D5).
    static func rows(_ sources: PageBlocks.Sources?) -> [PageBlocks.Source] {
        (sources?.items ?? []).filter { $0.state != "proposed" }
    }

    /// How many proposals wait: the server's count (every source, not only the first twelve it sends).
    static func proposals(_ sources: PageBlocks.Sources?) -> Int {
        sources?.proposed ?? (sources?.items ?? []).filter { $0.state == "proposed" }.count
    }

    /// A row's state on its trailing edge, in words (DR-79): "checked yesterday", "looks stale · last checked Aug 1",
    /// "the page changed", "not reachable", "not checked yet". Dates are relative at read (DR-58).
    static func state(_ source: PageBlocks.Source, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let when = ISODay(source.checkedAt).map { RelativeDay.phrase($0, today: today, locale: locale).lowercasedFirst }
        switch source.state {
        case "checked": return when.map(Copy.Pages.checked) ?? Copy.Pages.checked(Copy.Pages.notChecked)
        case "stale": return [Copy.Pages.stale, when.map(Copy.Pages.lastChecked)].compactMap { $0 }
            .joined(separator: " · ")
        case "changed": return Copy.Pages.changed
        case "dead": return Copy.Pages.dead
        case "unconfirmed": return Copy.Pages.unconfirmed
        case "proposed": return Copy.Pages.suggestedBy
        default: return Copy.Pages.notChecked
        }
    }

    /// A row's words: the site in tertiary, the link's own words in primary ink (the 2026-10-26 mention view). The
    /// title is the label when it says more than the site does; else the URL's path, else nothing.
    static func mention(_ source: PageBlocks.Source) -> (site: String?, title: String) {
        let words = LinkWords.of(ref: source.ref, label: source.label, linkKind: source.linkKind)
        guard let site = source.site, !site.isEmpty else { return (nil, words.label) }
        if words.label.caseInsensitiveCompare(site) != .orderedSame { return (site, words.label) }
        let path = URL(string: source.ref)?.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) ?? ""
        // A site's own home page: the site once, in primary ink (never "example.org example.org").
        return path.isEmpty ? (nil, site) : (site, path)
    }

    // MARK: Ongoing (ruling 48 (4))

    /// "Since Oct 1" for what is happening, "planned for Dec 1" for a milestone (DR-58: relative words at read).
    static func ongoingMeta(_ item: PageBlocks.Ongoing, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        if let target = ISODay(item.target) {
            parts.append(Copy.Pages.planned(RelativeDay.phrase(target, today: today, locale: locale)))
        } else if let since = ISODay(item.since) {
            parts.append(Copy.Pages.since(RelativeDay.absolute(since, today: today, locale: locale)))
        }
        if item.verbatim == true { parts.append(Copy.Pages.inYourWords) }
        return parts.joined(separator: " · ")
    }

    // MARK: References (DR-80)

    /// One reference's lead: "You, in Claude Code", "You, in Messages · with Bob Example", "Looked up", or the page's
    /// name for another page of the bank.
    static func refWho(_ ref: PageBlocks.Citations.Ref) -> String {
        switch ref.kind {
        case "web": return Copy.Pages.lookedUp
        case "page": return Copy.Pages.fromPage
        default:
            let place = ProvenanceSummary.placeName(harness: ref.harness, origin: ref.origin)
            let you = Copy.Pages.you(in: place.prefix(1).uppercased() + place.dropFirst())
            return ref.correspondent.map { "\(you) · \(Copy.Pages.with($0))" } ?? you
        }
    }

    /// The reference's day or range: "Oct 9", "Jun 4 – Yesterday" (DR-58).
    static func refWhen(first: String?, last: String?, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String? {
        let a = ISODay(first), b = ISODay(last)
        switch (a, b) {
        case let (a?, b?) where a != b:
            return "\(RelativeDay.absolute(a, today: today, locale: locale)) – "
                + RelativeDay.phrase(b, today: today, locale: locale).lowercasedFirst
        case let (a?, _): return RelativeDay.phrase(a, today: today, locale: locale)
        case let (nil, b?): return RelativeDay.phrase(b, today: today, locale: locale)
        default: return nil
        }
    }

    /// References' closing line: "9 conversations and 2 web pages in all".
    static func closing(_ c: PageBlocks.Citations) -> String {
        var parts: [String] = []
        if c.conversations > 0 { parts.append(Copy.Pages.conversations(c.conversations)) }
        if c.web > 0 { parts.append(Copy.Pages.webPages(c.web)) }
        if c.pages > 0 { parts.append(Copy.Pages.otherPages(c.pages)) }
        return Copy.Pages.inAll(parts)
    }

    // MARK: Belief sentences (DR-80)

    /// A belief as a sentence: an inference is worded as one ("It seems that …"), and what ended says until when
    /// ("… (until March 2025)") — never a list, never an Earlier section.
    static func sentence(_ belief: PageBlocks.Citations.Belief, locale: Locale = .autoupdatingCurrent) -> String {
        var text = belief.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if belief.inferred {
            let first = text.split(separator: " ", maxSplits: 1).first.map(String.init) ?? ""
            let lowered = commonOpeners.contains(first.lowercased()) ? text.lowercasedFirst : text
            text = "\(Copy.Pages.itSeems) \(lowered)"
        }
        if let until = ISODay(belief.until) {
            let month = RelativeDay.fullMonthYear(until, locale: locale)
            let body = text.hasSuffix(".") ? String(text.dropLast()) : text
            text = "\(body) (\(Copy.Pages.until(month)))."
        }
        return text
    }

    /// The link past the belief sentences: "3 more in Perspectives", "More in Perspectives" when the page's ledger
    /// holds an uncounted rest, nothing when every belief is shown.
    static func moreBeliefs(shown: Int, total: Int?) -> String? {
        guard let total else { return Copy.Pages.morePerspectives }
        return total > shown ? Copy.Pages.moreBeliefs(total - shown) : nil
    }

    /// Words that start a sentence without naming anyone — lowered after "It seems that"; a name keeps its capital.
    static let commonOpeners: Set<String> = ["the", "a", "an", "this", "that", "these", "those", "they", "he", "she",
                                             "it", "his", "her", "their", "its", "there", "some", "most", "many"]

    // MARK: The popover (DR-80, DR-57 amended)

    /// The popover's lead: who and how — "You said", "<agent> replied", "Looked up", "From the page", "From this
    /// conversation" (a line written from the conversation with no quote located), "Inferred" (a belief the agent
    /// only inferred).
    static func popoverKind(_ d: PageCitationDetail, inferred: Bool = false) -> String {
        if inferred { return Copy.Pages.inferred }
        if d.kind == "web" { return Copy.Pages.lookedUp }
        let kind = EvidenceKind(wire: d.evidenceKind)
        switch kind {
        case .reasoning, .unknown: return d.kind == "page" ? Copy.Pages.fromPage : Copy.Pages.fromConversation
        default:
            let agent = d.correspondent ?? EvidenceSpeaker.agentName(harness: d.harness, origin: d.origin)
            return EvidenceLabel.speaker(kind: kind, agent: agent, source: d.origin, origin: d.origin)
        }
    }
}

extension String {
    /// "Yesterday" → "yesterday", for a relative day inside a sentence.
    var lowercasedFirst: String { prefix(1).lowercased() + dropFirst() }
}

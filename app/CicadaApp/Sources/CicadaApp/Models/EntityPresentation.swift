import SwiftUI

/// The entity card's decisions, pure (Direction D, DS-3a; DESIGN_RULES §10 Entity card). The views render these;
/// `EntityHeaderTests`, `EntityContentTests` and `EntityTabsContentTests` pin them.

/// R-DG16 — the brief's order.
enum EntityCardTab: Hashable, CaseIterable {
    case content, perspectives, history, timeline

    var label: String {
        switch self {
        case .content: Copy.Graph.tabContent
        case .perspectives: Copy.Graph.tabPerspectives
        case .history: Copy.Graph.tabHistory
        case .timeline: Copy.Graph.tabTimeline
        }
    }
}

/// One belief's slot: a predicate in a context. It was the card's own nested timeline key; the tabs' counts and the
/// Timeline tab need it outside the view.
struct BeliefKey: Hashable, Identifiable {
    let predicate: String
    let context: String
    var id: String { "\(predicate)|\(context)" }

    init(predicate: String, context: String) {
        self.predicate = predicate
        self.context = context
    }

    init(_ claim: Claim) { self.init(predicate: claim.predicate, context: claim.context) }
}

enum EntityHeaderWords {
    /// R-DG14 — the mock's four steps; 0.85 and up is "very confident".
    static func confidence(_ value: Double) -> String {
        switch value {
        case 0.85...: "very confident"
        case 0.6..<0.85: "fairly confident"
        case 0.4..<0.6: "unsure"
        default: "doubtful"
        }
    }

    static func statusLine(status: EntityStatus, confidence: Double) -> String {
        "\(status.word) · \(self.confidence(confidence))"
    }

    /// The number lives here, in `.help`, and never as a bare "%" (DR-59).
    static func statusHelp(status: EntityStatus, confidence: Double) -> String {
        let base = Copy.Graph.confidenceOutOf100(Int((confidence * 100).rounded()))
        return status == .decaying ? base + Copy.Graph.fadingReason : base
    }

    /// R-DG15 — the page's `## Summary` (never the agentic-write placeholder, R-FX11). A graph-node stub's
    /// markdown IS its server preview, so it stands in until the page lands; a full page with no Summary has none.
    static func summary(markdown: String, isStub: Bool) -> String? {
        if let text = EntityProse.section(named: "## Summary", in: markdown), !EntityProse.isPlaceholderSummary(text) {
            return text
        }
        guard isStub else { return nil }
        let preview = EntityProse.stripClaimsFence(markdown)
        return preview.isEmpty ? nil : preview
    }
}

enum EntityTabs {
    /// R-DG16 — a count only once it is known: current beliefs, commits in hand, contested beliefs.
    static func tabs(claims: [Claim]?, historyCount: Int?) -> [TextTab<EntityCardTab>] {
        [
            TextTab(id: .content, label: EntityCardTab.content.label),
            TextTab(id: .perspectives, label: EntityCardTab.perspectives.label, count: claims.map { $0.filter(\.isValid).count }),
            TextTab(id: .history, label: EntityCardTab.history.label, count: historyCount),
            TextTab(id: .timeline, label: EntityCardTab.timeline.label, count: claims.map { contested($0).count }),
        ]
    }

    /// The full page carries its history; an empty embedded list is "not fetched yet" until a fetch says 0
    /// (`HistoryTabState`'s rule — a count must never say 0 while the tab says "Reading git history…").
    static func historyCount(embedded: [EntityHistoryEntry], fetched: [EntityHistoryEntry]?) -> Int? {
        if let fetched { return fetched.count }
        return embedded.isEmpty ? nil : embedded.count
    }

    /// (predicate, context) slots with two or more claims over time, current and superseded.
    static func contested(_ claims: [Claim]) -> [BeliefKey] {
        Dictionary(grouping: claims, by: { BeliefKey($0) })
            .filter { $0.value.count >= 2 }
            .keys
            .sorted { $0.id < $1.id }
    }
}

/// DR-58 — an absolute day for `.help` and the Details grid. A stored day is a calendar day, so it is shown in
/// UTC and never slips a day west of Greenwich; a timestamp is shown where the reader is.
enum EntityDates {
    static func day(_ iso: String?, locale: Locale = .autoupdatingCurrent) -> String? {
        format(iso, locale: locale, year: true)
    }

    static func shortDay(_ iso: String?, locale: Locale = .autoupdatingCurrent) -> String? {
        format(iso, locale: locale, year: false)
    }

    private static func format(_ iso: String?, locale: Locale, year: Bool) -> String? {
        guard let iso, let date = InboxAge.date(iso) else { return nil }
        let zone: TimeZone = iso.count == 10 ? .gmt : .autoupdatingCurrent
        let style = Date.FormatStyle(locale: locale, timeZone: zone).month(.abbreviated).day()
        return date.formatted(year ? style.year() : style)
    }
}

/// R-DG18 — one G61 source in words. The voices mirror `fact_sources.voiced_hint`, so the card and a conflict's
/// hint never disagree about who added a source.
enum FactSourceWords {
    struct Line: Equatable {
        let ref: String
        let isLink: Bool
        let forFact: String
        let readBy: String?
        let addedBy: String
        /// The app whose mark stands beside `addedBy` (DR-52).
        let addedByOrigin: String?
        let note: String?
        /// The ref in full (a long one is truncated on screen) and, for an agent, its raw id (DR-54).
        let help: String
    }

    static func line(_ s: EntitySource, locale: Locale = .autoupdatingCurrent) -> Line {
        let who = addedBy(s.addedBy)
        let words = EntityDates.shortDay(s.addedAt, locale: locale).map { "\(who.words) · \($0)" } ?? who.words
        let rawShown = who.origin != nil || who.words != Copy.Graph.foundByAnAgent
        // G154 (R-SR16) — a Contacts card is named as one; its `addressbook://` id is only ever in the tooltip.
        let shown = s.ref.hasPrefix("addressbook://") ? Copy.contactsCardRef : s.ref
        return Line(ref: shown, isLink: s.url != nil, forFact: forFact(s.predicate),
                    readBy: readBy(access: s.access, kind: s.kind), addedBy: words, addedByOrigin: who.origin,
                    note: note(accepted: s.accepted, onlyMe: s.onlyMe),
                    help: rawShown ? s.ref : "\(s.ref)\n\(Copy.Graph.addedByRaw(s.addedBy))")
    }

    static func forFact(_ predicate: String?) -> String {
        let p = (predicate ?? "").trimmingCharacters(in: .whitespaces)
        guard !p.isEmpty else { return Copy.Graph.forAnyFact }
        return Copy.Graph.forFact(p.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " "))
    }

    /// The stated access wins (a stated `unknown` says nothing); unstated, only the kind can speak.
    static func readBy(access: String?, kind: String) -> String? {
        if let stated = access?.trimmingCharacters(in: .whitespaces).lowercased(), !stated.isEmpty {
            switch stated {
            case "public": return Copy.Graph.publicPage
            case "signed_in": return Copy.Graph.needsSignIn
            case "local": return Copy.Graph.fileOnThisMac
            default: return nil
            }
        }
        switch kind {
        case "path", "repo": return Copy.Graph.fileOnThisMac
        case "app": return Copy.Graph.anApp
        default: return nil
        }
    }

    static func addedBy(_ raw: String) -> (words: String, origin: String?) {
        let who = raw.trimmingCharacters(in: .whitespaces)
        if who.isEmpty || who == "user" { return (Copy.Graph.addedByYou, nil) }
        if who == ContributorIdentity.systemAuthor { return (Copy.Graph.foundByCicada, nil) }
        if who != "unknown", OriginIconography.logoName(for: who) != nil || OriginIconography.appBundleId(for: who) != nil {
            return (Copy.Graph.addedBy(OriginIconography.label(for: who)), who)
        }
        return (Copy.Graph.foundByAnAgent, nil)
    }

    static func note(accepted: Bool?, onlyMe: Bool?) -> String? {
        if onlyMe == true { return Copy.Graph.onlyYouKnow }
        if accepted == true { return Copy.Graph.youChoseThis }
        return nil
    }
}

/// R-DG19 — the first visible question about this page, in the Inbox's own order.
enum EntityOpenQuestion {
    static func first(in items: [InboxItem], entityId: String) -> InboxItem? {
        items.first { $0.entityId == entityId }
    }
}

/// R-DG21 — a repository in words (`git_service`'s statuses), never a raw id (DR-54).
enum RepoWords {
    static func status(_ status: String) -> String {
        switch status {
        case "ok": "On this Mac"
        case "other_device": "On another Mac"
        case "missing": "Not found on this Mac"
        case "not_a_repo": "Not a git folder"
        case "git_unavailable": "git isn't installed"
        case "timeout": "git didn't answer"
        default: "Can't tell right now"
        }
    }

    /// Neutral tags, never semantic fills (DR-7).
    static func tags(branch: String?, dirty: Int?, ahead: Int?, behind: Int?) -> [String] {
        var out: [String] = []
        if let branch, !branch.isEmpty { out.append(branch) }
        if let dirty, dirty > 0 { out.append(Copy.Graph.changedFiles(dirty)) }
        if let ahead, ahead > 0 { out.append(Copy.Graph.ahead(ahead)) }
        if let behind, behind > 0 { out.append(Copy.Graph.behind(behind)) }
        return out
    }
}

/// R-DG21 — the Details disclosure.
enum DetailsWords {
    /// DR-39 — collapsed by default, remembered per viewer.
    static let openKey = "cicada.entity.detailsOpen"

    /// G66 — how fast it fades, as a person says it.
    static func fades(_ decay: DecayClass) -> String {
        switch decay {
        case .evergreen: "Never"
        case .durable: "Slowly"
        case .active: "If it stops coming up"
        case .volatile: "Quickly — it's expected to change"
        }
    }

    /// DR-58 — the day, then the age phrase the inbox uses.
    static func lastMentioned(_ iso: String, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        guard let day = EntityDates.day(iso, locale: locale) else { return "—" }
        return "\(day) · \(InboxAge.phrase(days: InboxAge.days(since: iso, now: now)))"
    }

    /// `related:` holds ids or names; a link opens only when one matches a page in the graph.
    static func relatedTarget(_ related: String, in entities: [Entity]) -> String? {
        let key = related.trimmingCharacters(in: .whitespaces)
        if entities.contains(where: { $0.id == key }) { return key }
        return entities.first { $0.name.caseInsensitiveCompare(key) == .orderedSame }?.id
    }
}

/// R-DG22 — what a belief row does not print, and its age.
enum BeliefWords {
    static func help(_ claim: Claim) -> String {
        var parts = [claim.observer.label]
        if claim.context != "general" { parts.append(ClaimContext.displayName(claim.context)) }
        let kind = ContributorIdentity.kind(author: claim.authoredBy, serverKind: claim.authorKind)
        // Round-4 C3 (R-FA14) — "Claude Code · Opus 5.5 · high effort at 0.85"
        // when the write's turn carried a model; byte-for-byte today's otherwise.
        let author = [ContributorIdentity.displayName(author: claim.authoredBy, kind: kind),
                      ModelNames.line(model: claim.authorModel, effort: claim.authorEffort)]
            .compactMap { $0 }.joined(separator: " · ")
        parts.append(Copy.Graph.writtenBy(author, confidence: claim.confidence))
        return parts.joined(separator: " · ")
    }

    static func age(_ claim: Claim, now: Date, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String)? {
        guard let days = InboxAge.days(since: claim.validFrom, now: now),
              let since = EntityDates.day(claim.validFrom, locale: locale) else { return nil }
        var help = Copy.Graph.trueSince(since)
        if let noted = EntityDates.day(claim.recordedAt, locale: locale) { help += Copy.Graph.notedOn(noted) }
        return (InboxAge.compact(days: days), help)
    }
}

/// R-DG23 — the Timeline tab's rows: the contested beliefs, and first the one a belief's clock asked for when it is
/// not one of them (a clock on an uncontested belief still opens its own timeline — the sheet it replaced did).
enum TimelineKeys {
    static func rows(claims: [Claim], requested: BeliefKey?) -> [BeliefKey] {
        let contested = EntityTabs.contested(claims)
        guard let requested, !contested.contains(requested) else { return contested }
        return [requested] + contested
    }

    /// "2 beliefs since Jan 5" — the row's count and its first day (DR-58: an absolute day, no year in a row).
    static func summary(_ key: BeliefKey, claims: [Claim], locale: Locale = .autoupdatingCurrent) -> String {
        let group = claims.filter { BeliefKey($0) == key }
        let first = group.map(\.validFrom).filter { !$0.isEmpty }.min()
        return Copy.Graph.beliefsSince(group.count, EntityDates.shortDay(first, locale: locale))
    }

    static func heading(contested: Int) -> String { contested > 0 ? Copy.Graph.contestedBeliefs : Copy.Graph.thisBelief }
}

/// R-DG24 — where "Show in conversation" goes: the Reader when every session a commit carries maps to one episode
/// in this bank; otherwise the chooser, whose Resume may still work for a session with no episode here.
enum HistoryConversation {
    enum Action: Equatable {
        case none
        case open(episode: String)
        case choose
    }

    static func action(sessions: [String], openEpisode: [String: String]) -> Action {
        guard !sessions.isEmpty else { return .none }
        let episodes = sessions.compactMap { openEpisode[$0] }
        if episodes.count == sessions.count, let first = episodes.first, Set(episodes).count == 1 {
            return .open(episode: first)
        }
        return .choose
    }
}

/// R-DG24 — a history row says its change in words; the per-kind hue it replaced spent data colour on a change
/// kind (P-c: hue is for data identity).
enum HistoryWords {
    static func change(_ type: HistoryChangeType) -> String {
        switch type {
        case .created: "Created"
        case .updated: "Updated"
        case .statusChange: "Status changed"
        case .confidenceChange: "Confidence changed"
        case .relationAdded: "Link added"
        }
    }
}

/// §3b — who believes what: current beliefs grouped by observer, Cicada, then the person, then outside sources.
/// It was the card's own `observerGroups` / `divergences`; pure so the order and the one-line disagreement are pinned.
enum PerspectiveGroups {
    struct Group: Identifiable {
        let observer: Observer
        let claims: [Claim]
        var id: String { observer.id }
    }

    struct Divergence: Identifiable, Equatable {
        let key: BeliefKey
        /// "Cicada: sqlite-vec · You: csv-storage"
        let line: String
        var id: String { key.id }
    }

    static func rank(_ observer: Observer) -> Int {
        switch observer {
        case .agent: 0
        case .rodrigo: 1
        case .external: 2
        }
    }

    static func of(_ claims: [Claim]) -> [Group] {
        Dictionary(grouping: claims.filter(\.isValid), by: \.observer)
            .map { Group(observer: $0.key, claims: $0.value) }
            .sorted { rank($0.observer) != rank($1.observer) ? rank($0.observer) < rank($1.observer)
                                                             : $0.observer.label < $1.observer.label }
    }

    static func heading(_ group: Group) -> String { "\(group.observer.label) · \(UsageFormat.count(group.claims.count))" }

    /// Keys where two or more observers hold different current values.
    static func divergences(_ claims: [Claim]) -> [Divergence] {
        Dictionary(grouping: claims.filter(\.isValid), by: { BeliefKey($0) })
            .compactMap { key, group -> Divergence? in
                guard Set(group.map(\.observer)).count >= 2, Set(group.map(\.object)).count >= 2 else { return nil }
                let ordered = group.sorted { rank($0.observer) < rank($1.observer) }
                return Divergence(key: key, line: ordered.map { "\($0.observer.label): \($0.object)" }.joined(separator: " · "))
            }
            .sorted { $0.id < $1.id }
    }
}

enum BeliefTimelineWords {
    /// DR-54 — the replacing claim's id belongs in `.help`.
    static func superseded(by id: String?) -> (text: String, help: String?) {
        (Copy.Graph.supersededByNewer, id.map { "Claim \($0)" })
    }
}

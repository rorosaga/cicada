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

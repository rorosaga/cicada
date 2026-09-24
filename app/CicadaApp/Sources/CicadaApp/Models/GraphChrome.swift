import SwiftUI

/// The Graph page's chrome, pure (Direction D, DS-3a; DESIGN_RULES §10 Graph). The views in
/// `Views/Graph/` render these and decide nothing, so every rule is a row in `GraphChromeTests`.
enum GraphChrome {
    /// R-DG4 — "filtered" whenever a filter differs from `GraphFilter()`. The observer lens is visible in
    /// its own tabs and Show logos is paint, so neither counts.
    static func isFiltered(_ filter: GraphFilter) -> Bool {
        let base = GraphFilter()
        return filter.types != base.types || filter.statuses != base.statuses
            || filter.minConfidence > 0 || filter.minDegree != base.minDegree
            || !filter.contexts.isEmpty || !filter.tags.isEmpty
    }

    static func legendLabel(_ filter: GraphFilter) -> String {
        isFiltered(filter) ? Copy.Graph.legendFiltered : Copy.Graph.legend
    }

    /// Up to three context hues on the Legend button — the hues the edges wear (DR-8).
    static func legendDotContexts(_ roster: [String]) -> [String] { Array(roster.prefix(3)) }

    struct TypeRow: Equatable, Identifiable {
        let type: EntityType
        let count: Int
        let isOn: Bool
        var id: String { type.rawValue }
    }

    /// Every type the graph holds, busiest first, plus any type the filter switched off (so it can come
    /// back). Hubs and satellites are views of pages, not pages, and do not count.
    static func typeRows(nodes: [GraphNode], filter: GraphFilter) -> [TypeRow] {
        var counts: [EntityType: Int] = [:]
        for node in nodes where !node.isFacet && !node.isHub { counts[node.type, default: 0] += 1 }
        return EntityType.selectableCases
            .filter { (counts[$0] ?? 0) > 0 || !filter.types.contains($0) }
            .map { TypeRow(type: $0, count: counts[$0] ?? 0, isOn: filter.types.contains($0)) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.type.label < $1.type.label }
    }

    struct ContextRow: Equatable, Identifiable {
        let context: String
        let links: Int
        let isOn: Bool
        var id: String { context }
    }

    /// R-DG4 — today's semantics, kept: an empty set is every context, and a click shows ONLY the contexts
    /// clicked ("show me only the engineering subgraph" is one tap).
    static func contextRows(roster: [String], edges: [GraphEdge], filter: GraphFilter) -> [ContextRow] {
        var links: [String: Int] = [:]
        for edge in edges { if let c = edge.context { links[c, default: 0] += 1 } }
        return roster.map {
            ContextRow(context: $0, links: links[$0] ?? 0, isOn: filter.contexts.isEmpty || filter.contexts.contains($0))
        }
    }

    static func linksLabel(_ n: Int) -> String { "\(UsageFormat.count(n)) \(n == 1 ? "link" : "links")" }

    struct StatusRow: Equatable, Identifiable {
        let status: EntityStatus
        let label: String
        let hint: String?
        let isOn: Bool
        var id: String { status.rawValue }
    }

    static func statusRows(_ filter: GraphFilter) -> [StatusRow] {
        EntityStatus.allCases.map { status in
            let on = filter.statuses.contains(status)
            let hint: String? = switch status {
            case .decaying: on ? Copy.Graph.dashed : nil
            case .archived, .dropped: on ? nil : Copy.Graph.hiddenByDefault
            case .active: nil
            }
            return StatusRow(status: status, label: status.word, hint: hint, isOn: on)
        }
    }

    /// DR-59 — the slider's value in words, never a bare "%".
    static func minConfidenceLabel(_ value: Double) -> String {
        let n = Int((value * 100).rounded())
        return n <= 0 ? Copy.Graph.anyConfidence : Copy.Graph.orMore(n)
    }

    /// R-DG3 — the whose-beliefs lens; nil is All, the wires are `GraphViewModel.setObserver`'s.
    static let observerTabs: [TextTab<String>] = [
        TextTab(id: nil, label: Copy.Graph.all),
        TextTab(id: "agent", label: "Cicada"),
        TextTab(id: "__owner__", label: Copy.you),
        TextTab(id: "external", label: Copy.Graph.external),
    ]
}

extension EntityStatus {
    /// The status as a person says it — "Fading", not "decaying" (R-DG14, R-DG4).
    var word: String {
        switch self {
        case .active: "Active"
        case .decaying: "Fading"
        case .archived: "Archived"
        case .dropped: "Dropped"
        }
    }
}

/// R-DG3 — where the one floating group puts things, from the canvas's width in units (DR-70).
enum GraphChromeLayout {
    /// The approved mock's breakpoint for the whose-beliefs tabs.
    static let tabsInGroupMinWidth: CGFloat = 640
    /// The widest group ("Legend · filtered" with three hues, a spacer, − + fit and pan, ≈ 303, measured) plus its 16-unit
    /// inset on each side; narrower than this, the group would clip. `testTheWidestGroupFitsItsFloor` renders it.
    static let groupMinWidth: CGFloat = 340

    enum Group: Equatable { case full, compact, hidden }

    static func group(canvasWidth: CGFloat, scale: CGFloat, hasObserverTabs: Bool) -> Group {
        let units = canvasWidth / max(scale, 0.1)
        if units < groupMinWidth { return .hidden }
        return hasObserverTabs && units >= tabsInGroupMinWidth ? .full : .compact
    }

    /// The tabs sit at the top of the Legend panel whenever they are not in the group.
    static func tabsInPanel(_ group: Group, hasObserverTabs: Bool) -> Bool { hasObserverTabs && group != .full }
}

/// DR-28 / R-DG7 / R-DG8 — what Esc, a click on empty canvas and the column's × close.
enum GraphDismiss {
    enum Action: Equatable { case closeFind, closeLegend, closePanels, closeReader, closeEntity, closeEntityAndReader, none }

    struct State: Equatable {
        var findOpen = false
        var legendOpen = false
        var readerOpen = false
        var entityOpen = false
    }

    /// One thing per press, topmost first: find, the Legend, the Reader, the column. A keyboard path.
    static func escape(_ s: State) -> Action {
        if s.findOpen { return .closeFind }
        if s.legendOpen { return .closeLegend }
        if s.readerOpen { return .closeReader }
        if s.entityOpen { return .closeEntity }
        return .none
    }

    /// R-DG8 — an outside click dismisses a floating panel first, like a popover's; only then does it close
    /// the column, with its Reader (R-DG7). A Reader open with no column was opened elsewhere and stays (R-DI8).
    static func backgroundClick(_ s: State) -> Action {
        if s.findOpen || s.legendOpen { return .closePanels }
        if s.entityOpen { return s.readerOpen ? .closeEntityAndReader : .closeEntity }
        return .none
    }

    /// R-DG7 — the column's ×: the whole detail, as the mock's `closeEntity` and the Inbox's × do.
    static func close(_ s: State) -> Action { s.readerOpen ? .closeEntityAndReader : .closeEntity }
}

/// R-DG5 — find on the canvas.
enum GraphFind {
    enum Escape: Equatable { case clear, close }
    static func escape(textIsEmpty: Bool) -> Escape { textIsEmpty ? .close : .clear }
    /// The mock lists six; the palette (⌘K) is where "everything" lives.
    static let hitLimit = 6
}

/// R-DG12 — the canvas and the entity column. The canvas is the flexible column (the list's role in §5.3), so
/// the Graph does not reuse `ColumnLayout`, whose flexible column is the detail. Widths are units (÷ uiScale,
/// DR-70), and the two always sum to the page, so nothing is ever pushed off-window (DR-31).
enum GraphColumns {
    /// DR-27's floor for the detail column.
    static let entityMin: CGFloat = 440
    /// The approved mock: 560 with nothing beside it, 480 beside the Reader (440 once the page is narrower).
    static let entityMax: CGFloat = 560
    static let entityMaxBesideReader: CGFloat = 480

    struct Plan: Equatable {
        var canvas: CGFloat
        var entity: CGFloat
    }

    static func plan(pageWidth: CGFloat, scale: CGFloat, entityOpen: Bool, readerOpen: Bool) -> Plan {
        let page = max(pageWidth, 0)
        guard entityOpen else { return Plan(canvas: page, entity: 0) }
        let s = max(scale, 0.1)
        let units = page / s
        let ceiling = readerOpen ? entityMaxBesideReader : entityMax
        let entityUnits = min(min(max(units / 2, entityMin), ceiling), units)
        let entity = min((entityUnits * s).rounded(), page)
        return Plan(canvas: page - entity, entity: entity)
    }
}

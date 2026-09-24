import Foundation

/// F-12 (G146 plan R-PE16) — one cell of the person card's facts strip: a label, a value, and the compressed provenance
/// line under it. A cell exists only when there is something true to put in it — never a placeholder.
struct PersonFact: Equatable, Identifiable {
    enum Kind: String { case worksAt, role, knownSince, lastMentioned, conversations, contacts }

    let kind: Kind
    let label: String
    let value: String
    /// The page the value names, when it names one — the cell opens it.
    var valueEntity: String? = nil
    var valueType: EntityType? = nil
    var line: String? = nil
    /// Origins whose real marks lead the line (≤ 4; DR-52).
    var marks: [String] = []

    var id: String { kind.rawValue }
}

enum PersonFacts {
    static let worksAt: Set<String> = ["works-at"]
    /// R-PE16 — the predicate vocabulary has no `role` yet; the first of these a current belief uses.
    static let role = ["role", "has-role", "job-title", "is-a"]
    static let maxMarks = 4

    static func cells(entity: Entity, claims: [Claim], provenance: EntityProvenance?, names: EntityNames,
                      typeOf: @escaping (String) -> EntityType?, picture: EntityPictureRef?, docs: EvidenceDocIndex,
                      today: ISODay, locale: Locale = .autoupdatingCurrent,
                      timeZone: TimeZone = .autoupdatingCurrent) -> [PersonFact] {
        var cells: [PersonFact] = []
        let current = claims.filter(\.isValid).sorted { $0.validFrom > $1.validFrom }
        func valueCell(_ kind: PersonFact.Kind, _ label: String, _ claim: Claim) -> PersonFact {
            let page = names.name(for: claim.object) != nil ? claim.object : nil
            return PersonFact(kind: kind, label: label, value: names.display(claim.object), valueEntity: page,
                              valueType: page.flatMap(typeOf),
                              line: evidenceLine(claim, docs: docs, locale: locale, timeZone: timeZone))
        }
        if let claim = current.first(where: { worksAt.contains($0.predicate) }) {
            cells.append(valueCell(.worksAt, Copy.People.worksAt, claim))
        }
        if let claim = role.lazy.compactMap({ predicate in current.first { $0.predicate == predicate } }).first {
            cells.append(valueCell(.role, Copy.People.role, claim))
        }
        let conversations = (provenance?.conversations ?? []).sorted { ($0.timestamp ?? "") < ($1.timestamp ?? "") }
        if let created = ISODay(entity.created), created <= today {
            let first = conversations.first
            cells.append(PersonFact(kind: .knownSince, label: Copy.People.knownSince,
                                    value: "\(RelativeDay.absolute(created, today: today, locale: locale)) · \(Copy.People.span(days: today - created))",
                                    line: first.flatMap(app).map(Copy.People.firstIn),
                                    marks: first.flatMap(origin).map { [$0] } ?? []))
        }
        if let last = ISODay(entity.lastReferenced) {
            let latest = conversations.last
            let line = [latest.flatMap(app), clock(latest?.timestamp, locale: locale, timeZone: timeZone)].compactMap { $0 }
            cells.append(PersonFact(kind: .lastMentioned, label: Copy.People.lastMentioned,
                                    value: RelativeDay.phrase(last, today: today, locale: locale),
                                    line: line.isEmpty ? nil : line.joined(separator: " · "),
                                    marks: latest.flatMap(origin).map { [$0] } ?? []))
        }
        if !conversations.isEmpty {
            var seen = Set<String>()
            let marks = conversations.compactMap(origin).filter { seen.insert($0).inserted }.prefix(maxMarks)
            let pages = provenance?.pages.count ?? 0
            cells.append(PersonFact(kind: .conversations, label: Copy.People.conversations,
                                    value: UsageFormat.count(conversations.count),
                                    line: pages > 0 ? Copy.People.pages(pages) : nil, marks: Array(marks)))
        }
        if picture?.source == .contacts {
            cells.append(PersonFact(kind: .contacts, label: Copy.People.contacts, value: Copy.People.matched,
                                    line: Copy.People.photoMatched))
        }
        return cells
    }

    /// "You said · Mar 12" — the belief's first evidence chip, in the chip's own words (DR-57).
    static func evidenceLine(_ claim: Claim, docs: EvidenceDocIndex, locale: Locale, timeZone: TimeZone) -> String? {
        guard let chip = EvidenceChipModel.chips(evidence: claim.evidence, sourceEpisodes: claim.sourceEpisodes,
                                                 subjectId: claim.subject).first else { return nil }
        return EvidenceLabel.chipText(chip, meta: docs.meta(chip.episode), locale: locale, timeZone: timeZone)
    }

    /// A conversation's app, as a person names it (DR-54).
    static func app(_ c: ProvenanceConversation) -> String? {
        EvidenceSpeaker.agentName(harness: c.harness, origin: c.origin) ?? origin(c).map(OriginIconography.label(for:))
    }

    static func origin(_ c: ProvenanceConversation) -> String? {
        for raw in [c.harness, c.origin] {
            if let value = raw?.trimmingCharacters(in: .whitespaces), !value.isEmpty, value != "unknown", value != "mcp" {
                return value
            }
        }
        return nil
    }

    /// A conversation's time of day, only when it has one (a day-only stamp says nothing about the clock).
    static func clock(_ iso: String?, locale: Locale, timeZone: TimeZone) -> String? {
        guard let iso, iso.contains("T"), let date = InboxAge.date(iso) else { return nil }
        return date.formatted(Date.FormatStyle(locale: locale, timeZone: timeZone).hour().minute())
    }
}

/// F-12 (G146 plan R-PE18) — who wrote a belief, as the person card signs it: "Written by Claude Code · Opus 5.5 · high
/// effort · Sep 24". The model is the captured turn's (round-4 C3, TODO ruling 11) — never a guess; an app with no
/// capture says so; a legacy write with no author signs nothing.
enum SignedLine {
    /// `bare` rather than `none`, so `?? .bare` is never read as `Optional.none`.
    enum Mark: Equatable { case origin(String), logo(String), bare }

    static func who(_ claim: Claim) -> String? {
        switch ContributorIdentity.kind(author: claim.authoredBy, serverKind: claim.authorKind) {
        case "user": return Copy.People.you
        case "system": return Copy.People.cicada
        case "harness":
            return ModelNames.agentLine(agent: OriginIconography.label(for: claim.authoredBy), harness: claim.authoredBy,
                                        model: claim.authorModel, effort: claim.authorEffort)
        case "model": return "\(Copy.People.sleep) · \(ModelNames.display(claim.authoredBy))"
        default: return nil
        }
    }

    /// When it was written, else when it became true — the calendar day only, so it never slips across a time zone.
    static func day(_ claim: Claim, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let raw = [claim.recordedAt, claim.validFrom].compactMap({ $0 }).first(where: { !$0.isEmpty }) else {
            return nil
        }
        return EntityDates.shortDay(String(raw.prefix(10)), locale: locale)
    }

    static func text(_ claim: Claim, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let who = who(claim) else { return nil }
        return [Copy.People.writtenBy(who), day(claim, locale: locale)].compactMap { $0 }.joined(separator: " · ")
    }

    static func mark(_ claim: Claim) -> Mark {
        switch ContributorIdentity.kind(author: claim.authoredBy, serverKind: claim.authorKind) {
        case "harness": return .origin(claim.authoredBy)
        case "model": return ContributorIdentity.logoName(provider: claim.authorProvider).map(Mark.logo) ?? .bare
        default: return .bare
        }
    }
}

/// F-12 — "What Cicada believes · N, newest first": current beliefs by when they were written, else when they became
/// true; four, then "Show N more".
enum PersonBeliefs {
    static let collapsed = 4

    static func ordered(_ claims: [Claim]) -> [Claim] {
        claims.filter(\.isValid).sorted { key($0) > key($1) }
    }

    private static func key(_ claim: Claim) -> String {
        [claim.recordedAt, claim.validFrom].compactMap { $0 }.first { !$0.isEmpty } ?? ""
    }
}

/// One neighbour on "How you know <name>" (R-PE17): where it sits in the map's unit box and what links it.
struct PersonMapNode: Equatable, Identifiable {
    let id: String
    let name: String
    let type: EntityType
    let label: String
    let isOwner: Bool
    let x: Double
    let y: Double
}

struct PersonMap: Equatable {
    let nodes: [PersonMapNode]
    /// Every neighbour, for the sentence — the map draws at most `PersonMapLayout.limit`.
    let total: Int
}

/// R-PE17 — C-09's radial map, pure: the graph's own edges around the person, the owner first at the top, then the
/// busiest pages clockwise. Hubs and facets are views of pages, never neighbours.
enum PersonMapLayout {
    static let limit = 6
    static let radius = 0.38

    static func make(personId: String, nodes: [GraphNode], edges: [GraphEdge], limit: Int = limit) -> PersonMap {
        let pages = pageIndex(nodes)
        let (order, labels) = neighbours(personId, edges: edges, pages: pages)
        let ranked = rank(order, pages: pages)
        let picked = Array(ranked.prefix(limit))
        let placed = picked.enumerated().compactMap { index, id -> PersonMapNode? in
            guard let node = pages[id] else { return nil }
            let angle = -Double.pi / 2 + 2 * Double.pi * Double(index) / Double(picked.count)
            return PersonMapNode(id: id, name: node.name, type: node.type, label: labels[id] ?? "", isOwner: node.isOwner,
                                 x: round3(0.5 + radius * cos(angle)), y: round3(0.5 + radius * sin(angle)))
        }
        return PersonMap(nodes: placed, total: order.count)
    }

    /// R-PE19 — the projects a person is linked to, busiest first: where "What's happening" looks.
    static func projects(personId: String, nodes: [GraphNode], edges: [GraphEdge], limit: Int = 2) -> [String] {
        let pages = pageIndex(nodes)
        let (order, _) = neighbours(personId, edges: edges, pages: pages)
        return Array(rank(order.filter { pages[$0]?.type == .project }, pages: pages).prefix(limit))
    }

    private static func pageIndex(_ nodes: [GraphNode]) -> [String: GraphNode] {
        Dictionary(nodes.filter { !$0.isFacet && !$0.isHub }.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
    }

    private static func neighbours(_ personId: String, edges: [GraphEdge],
                                   pages: [String: GraphNode]) -> (order: [String], labels: [String: String]) {
        var order: [String] = []
        var labels: [String: String] = [:]
        for edge in edges where edge.label != "member of" {
            let other: String
            if edge.source == personId { other = edge.target } else if edge.target == personId { other = edge.source } else { continue }
            guard other != personId, pages[other] != nil, labels[other] == nil else { continue }
            labels[other] = edge.label
            order.append(other)
        }
        return (order, labels)
    }

    private static func rank(_ ids: [String], pages: [String: GraphNode]) -> [String] {
        ids.sorted { a, b in
            let (na, nb) = (pages[a], pages[b])
            let (oa, ob) = (na?.isOwner ?? false, nb?.isOwner ?? false)
            if oa != ob { return oa }
            let (da, db) = (na?.degree ?? 0, nb?.degree ?? 0)
            if da != db { return da > db }
            return (na?.name ?? a).localizedCaseInsensitiveCompare(nb?.name ?? b) == .orderedAscending
        }
    }

    private static func round3(_ value: Double) -> Double { (value * 1000).rounded() / 1000 }
}

/// One row of "What's happening" (R-PE19), in the Projects band's grammar: a planned milestone (a hollow diamond), an
/// ongoing thread (a span), or something that happened (a dot).
struct PersonHappening: Equatable, Identifiable {
    enum Mark: Equatable { case planned, ongoing, done }

    let id: String
    let mark: Mark
    let day: ISODay
    let text: String
    let projectId: String
    /// Where it was heard — its mark leads the source line; nil for a plan.
    let origin: String?
}

/// R-PE19 — from the timelines the Projects page already fetched, never a new endpoint: each timeline the person takes
/// part in (any item names them) gives its next planned milestone, and every happening naming the person gives a row;
/// planned soonest first, then ongoing, then done — newest first, each item once. `ProjectItem` carries its state in
/// `state` (`ongoing` | `done` | `dropped` for a `happening`; a `moment` is `said`, a `created` item has none) — there is
/// no `status` on an item; only a happening is a row, and a dropped one is not "happening".
enum PersonHappenings {
    static let limit = 3

    static func rows(personId: String, timelines: [ProjectTimeline], limit: Int = limit) -> [PersonHappening] {
        var planned: [PersonHappening] = []
        var ongoing: [PersonHappening] = []
        var done: [PersonHappening] = []
        var seen = Set<String>()
        for timeline in timelines {
            let mine = timeline.items.filter { $0.participants.contains { $0.id == personId } }
            guard !mine.isEmpty else { continue }
            if let next = timeline.now.next, next.status == "planned", let target = ISODay(next.target) {
                planned.append(PersonHappening(id: "next:\(timeline.project.id):\(next.slug)", mark: .planned, day: target,
                                               text: next.name, projectId: timeline.project.id, origin: nil))
            }
            for item in mine where item.kind == "happening" && ["ongoing", "done"].contains(item.state ?? "")
                && seen.insert(item.id).inserted {
                guard let day = ISODay(item.day) else { continue }
                let row = PersonHappening(id: item.id, mark: item.state == "ongoing" ? .ongoing : .done, day: day,
                                          text: item.text, projectId: item.project ?? timeline.project.id,
                                          origin: item.conversation?.harness ?? item.conversation?.origin)
                if row.mark == .ongoing { ongoing.append(row) } else { done.append(row) }
            }
        }
        planned.sort { $0.day < $1.day }
        ongoing.sort { $0.day > $1.day }
        done.sort { $0.day > $1.day }
        return Array((planned + ongoing + done).prefix(limit))
    }
}

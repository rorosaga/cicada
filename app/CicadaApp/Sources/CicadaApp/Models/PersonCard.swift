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

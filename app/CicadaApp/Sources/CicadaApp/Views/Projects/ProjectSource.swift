import Foundation

/// R-PP16 — where a row on the Projects page came from, said once, and where the Reader opens (DR-31, DR-54, DR-55,
/// DR-57; G118: spans, not copies). Pure: Task 4's source lines and the band's ⏎ read the same answers.
enum ProjectSource {
    enum Line: Equatable {
        /// A conversation: its origin's real mark, "<App> · <title>" (DR-54).
        case conversation(origin: String, app: String, title: String)
        /// The person's own Log entry — a companion note (R-PJ18).
        case note
        /// Written in the app with no sentence behind it: DR-57's sixth label, as a source line, never a chip (§7).
        case setByYou
        /// A `## History` bullet (§6.1 layer 5).
        case pageHistory
        /// A span whose conversation the payload does not name: the chip alone says who spoke.
        case chipOnly
        /// Nothing at all — `[ no source recorded ]`, served exactly as written (G115, DR-55).
        case none
    }

    static func line(_ item: ProjectItem) -> Line {
        if item.kind == "history" { return .pageHistory }
        if let conversation = item.conversation {
            if conversation.origin == "companion_app" { return .note }
            let origin = conversation.harness ?? conversation.origin ?? ""
            return .conversation(origin: origin, app: OriginIconography.label(for: origin), title: conversation.title)
        }
        if let claim = item.claim, claim.origin == "companion_app", claim.evidence.allSatisfy({ !$0.isSpan }) {
            return .setByYou
        }
        return item.quote == nil ? .none : .chipOnly
    }

    /// A milestone's line reads its slot's head claim: the person set or moved it in the app, or a sentence said it.
    static func line(_ m: ProjectMilestone, conversations: [ProjectConversation]) -> Line {
        guard let head = m.chain.first else { return .none }
        if head.origin == "companion_app", head.evidence.allSatisfy({ !$0.isSpan }) { return .setByYou }
        guard let span = head.evidence.first(where: \.isSpan) else { return .none }
        if let c = conversations.first(where: { $0.episodeId == span.episode }) {
            let origin = c.harness ?? c.origin ?? ""
            return .conversation(origin: origin, app: OriginIconography.label(for: origin), title: c.title)
        }
        return .chipOnly
    }

    /// The evidence entry a row's chip shows: the claim's own span on the quoted episode (it carries the hash), else the
    /// quote's offsets. A stale quote has none — its words moved, and a chip would wash words that are no longer there.
    static func evidence(_ item: ProjectItem) -> Evidence? {
        guard let quote = item.quote, quote.status != "stale" else { return nil }
        if let own = item.claim?.evidence.first(where: { $0.episode == quote.episode && $0.isSpan }) { return own }
        guard let start = quote.start, let end = quote.end, end > start else { return nil }
        return Evidence(episode: quote.episode, start: start, end: end,
                        kind: quote.status == "derived" ? .derived : EvidenceKind(wire: quote.kind))
    }

    static func target(_ item: ProjectItem, projectId: String) -> ReaderTarget? {
        guard let quote = item.quote, !quote.episode.isEmpty else { return nil }
        let subject = item.claim?.subject ?? item.project ?? projectId
        let title = item.conversation?.title
        let harness = item.conversation?.harness
        if quote.status == "stale" {
            return ReaderTarget(episode: quote.episode, focus: .stale, subjectId: subject, knownTitle: title,
                                knownHarness: harness)
        }
        if let own = item.claim?.evidence.first(where: { $0.episode == quote.episode && $0.isSpan }) {
            return ReaderTarget.evidence(own, subjectId: subject, knownTitle: title, knownHarness: harness)
        }
        if let start = quote.start, let end = quote.end, end > start {
            let derived = quote.kind == "derived" || quote.status == "derived"
            return ReaderTarget(episode: quote.episode, focus: .span(start: start, end: end, hash: nil, derived: derived),
                                subjectId: subject, knownTitle: title, knownHarness: harness)
        }
        return ReaderTarget(episode: quote.episode, focus: .none, subjectId: subject, knownTitle: title,
                            knownHarness: harness)
    }

    static func target(_ m: ProjectMilestone, projectId: String) -> ReaderTarget? {
        guard let head = m.chain.first, let span = head.evidence.first(where: \.isSpan) else { return nil }
        return ReaderTarget.evidence(span, subjectId: head.subject.isEmpty ? projectId : head.subject)
    }

    /// The band's ⏎ and a section row's "Show in conversation ›": the selected key's words.
    static func target(for key: ProjectKey, in t: ProjectTimeline, projectId: String) -> ReaderTarget? {
        switch key {
        case .item(let id), .thread(let id):
            return t.items.first { $0.id == id }.flatMap { target($0, projectId: projectId) }
        case .milestone(let slug):
            return t.milestones.first { $0.slug == slug }.flatMap { target($0, projectId: projectId) }
        }
    }

    /// Every conversation the payload names, by episode — so an assistant chip says "Claude Code replied", not "The
    /// agent replied" (`EvidenceDocIndex`'s reason: no fetch per chip).
    static func docIndex(_ t: ProjectTimeline) -> EvidenceDocIndex {
        var byEpisode: [String: EvidenceDocMeta] = [:]
        for c in t.conversations + t.items.compactMap(\.conversation) {
            byEpisode[c.episodeId] = EvidenceDocMeta(title: c.title.isEmpty ? nil : c.title, harness: c.harness,
                                                     origin: c.origin)
        }
        return EvidenceDocIndex(byEpisode: byEpisode)
    }
}

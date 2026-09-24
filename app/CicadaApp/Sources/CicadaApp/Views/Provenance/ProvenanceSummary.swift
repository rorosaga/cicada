import Foundation

/// "Where this came from", as sentences (design §4.5, §4.10
/// `ProvenanceSummaryTests`). Pure over the `/provenance` payload, so the
/// section is a renderer and every sentence it can say is pinned by a test —
/// including the honest ones: no conversation links, no exact quotes, too
/// many conversations to break down.
enum ProvenanceSummary {
    /// The card shows this many conversation rows before "Show all".
    static let visibleConversations = 5
    /// The writers sentence names this many before "and N others".
    static let namedWriters = 3

    // MARK: Conversations

    /// "From 3 conversations: 2 in Claude Code and 1 in ChatGPT."
    ///
    /// The breakdown is only given when every conversation is in the payload
    /// (the server ships at most 50 rows, R-PB7); past that it would be a
    /// breakdown of a sample, so the sentence says only the honest total.
    static func conversationsSentence(_ p: EntityProvenance) -> String {
        let total = max(p.totals.conversations, p.conversations.count)
        guard total > 0 else { return Copy.Provenance.noConversations }
        let lead = "From \(Copy.Provenance.conversations(total))"
        guard p.conversations.count == total else { return lead + "." }
        let groups = groupCounts(p.conversations)
        if groups.count == 1, let only = groups.first { return "\(lead) in \(only.name)." }
        let parts = groups.map { "\(UsageFormat.count($0.count)) in \($0.name)" }
        return "\(lead): \(list(parts))."
    }

    /// Where a conversation happened, as a person would say it: the agent's
    /// product name, else the capture channel's label, else "other places".
    static func placeName(harness: String?, origin: String?) -> String {
        if let agent = EvidenceSpeaker.agentName(harness: harness, origin: origin) { return agent }
        if let origin, !origin.isEmpty, origin != "unknown" { return OriginIconography.label(for: origin) }
        return "other places"
    }

    static func groupCounts(_ rows: [ProvenanceConversation]) -> [(name: String, count: Int)] {
        var counts: [String: Int] = [:]
        for row in rows { counts[placeName(harness: row.harness, origin: row.origin), default: 0] += 1 }
        return counts.map { (name: $0.key, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.name < $1.name }
    }

    // MARK: Writers

    /// "Written by Claude (claude-sonnet-4-5) and you." — who authored the
    /// beliefs, never who spoke in the conversation (conversation `model` is
    /// reserved-null, §4.9). `unknown` is left to its chip ("Before
    /// provenance"); nil when nobody can be named.
    static func writersSentence(_ p: EntityProvenance) -> String? {
        let names = p.contributors
            .filter { $0.kind != "unknown" && ($0.claims + $0.commits) > 0 }
            .map { sentenceName($0) }
        guard !names.isEmpty else { return nil }
        var shown = Array(names.prefix(namedWriters))
        if names.count > namedWriters {
            let others = names.count - namedWriters
            shown.append(others == 1 ? "1 other" : "\(UsageFormat.count(others)) others")
        }
        return "Written by \(list(shown))."
    }

    /// A contributor's name mid-sentence: "you", "Cicada", an app's name, or
    /// a model with its vendor first and its exact id in parentheses — the id
    /// is its own honest name and is never hidden (`ContributorIdentity`).
    static func sentenceName(_ c: ProvenanceContributor) -> String {
        switch c.kind {
        case "user": return "you"
        case "system": return "Cicada"
        default: return chipName(c)
        }
    }

    /// The chip's name: `ContributorIdentity.displayName`, with a model's
    /// vendor in front when the provider has one ("Claude (claude-sonnet-4-5)").
    static func chipName(_ c: ProvenanceContributor) -> String {
        let name = ContributorIdentity.displayName(author: c.author, kind: c.kind)
        guard c.kind == "model", let vendor = ContributorIdentity.vendorName(provider: c.provider) else { return name }
        return "\(vendor) (\(name))"
    }

    /// "12 beliefs · 3 edits" — two nouns, never one number meaning two things
    /// (the Sources v2 rule). An author with only edits shows only edits.
    static func chipCount(_ c: ProvenanceContributor) -> String {
        var parts: [String] = []
        if c.claims > 0 { parts.append(Copy.Provenance.beliefs(c.claims)) }
        if c.commits > 0 { parts.append(Copy.Provenance.edits(c.commits)) }
        return parts.joined(separator: " · ")
    }

    // MARK: Models (round-4 C4, D1)

    /// A harness chip shows this many models before ", +N more".
    static let namedModels = 2

    /// A harness contributor's models, most beliefs first, then by id so the
    /// order never flickers between reads.
    private static func sortedModels(_ c: ProvenanceContributor) -> [ContributorModel] {
        c.models.filter { !$0.model.isEmpty }
            .sorted { $0.beliefs != $1.beliefs ? $0.beliefs > $1.beliefs : $0.model < $1.model }
    }

    /// The third line of a harness chip (R-FA14): "Opus 5.5 · high effort,
    /// Sonnet 5", then ", +N more". With no models, an app that never tells
    /// says so; a capturing harness (writes from before D1) and every other
    /// kind say nothing — never a guess.
    static func modelsLine(_ c: ProvenanceContributor) -> String? {
        guard c.kind == "harness" else { return nil }
        let models = sortedModels(c)
        guard !models.isEmpty else {
            let h = c.author.trimmingCharacters(in: .whitespaces)
            guard !h.isEmpty, h != "unknown", h != "mcp", h != "agent",
                  !ModelNames.capturingHarnesses.contains(h) else { return nil }
            return Copy.Provenance.modelNotShared
        }
        var line = models.prefix(namedModels)
            .compactMap { ModelNames.line(model: $0.model, effort: $0.effort) }
            .joined(separator: ", ")
        if models.count > namedModels { line += ", " + Copy.Provenance.moreEvidence(models.count - namedModels) }
        return line
    }

    /// The chip's hover, one line per model: "Opus 5.5 · high effort — 2
    /// beliefs". Empty when the contributor carries no models.
    static func modelsHelp(_ c: ProvenanceContributor) -> [String] {
        guard c.kind == "harness" else { return [] }
        return sortedModels(c).compactMap { m in
            ModelNames.line(model: m.model, effort: m.effort).map { "\($0) — \(Copy.Provenance.beliefs(m.beliefs))" }
        }
    }

    // MARK: Coverage

    /// "9 of 18 beliefs here have an exact quote." — stated, never implied:
    /// most live claims predate exact quotes (no backfill, slice 1), and the
    /// section must not suggest every memory has a snippet.
    static func coverage(_ totals: ProvenanceTotals) -> String {
        guard totals.claims > 0 else { return Copy.Provenance.noBeliefs }
        let verb = totals.claims == 1 ? "belief here has" : "beliefs here have"
        return "\(UsageFormat.count(totals.withSpan)) of \(UsageFormat.count(totals.claims)) \(verb) an exact quote."
    }

    /// Why the rest have none, when any are legacy.
    static func legacyNote(_ totals: ProvenanceTotals) -> String? {
        guard totals.legacy > 0 else { return nil }
        let subject = totals.legacy == 1 ? "1 was" : "\(UsageFormat.count(totals.legacy)) were"
        return "\(subject) noted before Cicada kept exact quotes."
    }

    /// The "Also" line: page spans by page, then the inferred count.
    static func alsoItems(_ p: EntityProvenance) -> [String] {
        var items = p.pages.map { page in
            "\(Copy.Provenance.fromThePage) \(page.name.isEmpty ? page.entityId : page.name) · "
                + Copy.Provenance.beliefs(page.claimCount)
        }
        if p.inferredCount > 0 {
            items.append("\(Copy.Provenance.inferredByCicada) · \(Copy.Provenance.beliefs(p.inferredCount))")
        }
        return items
    }

    // MARK: Helpers

    /// "a", "a and b", "a, b and c".
    static func list(_ items: [String]) -> String {
        switch items.count {
        case 0: return ""
        case 1: return items[0]
        default: return items.dropLast().joined(separator: ", ") + " and " + items[items.count - 1]
        }
    }

    /// conversation id → its newest episode, for "Open conversation" on a
    /// history row (plan R-PU5 — the one place a conversation id meets an
    /// episode id the Reader can open).
    static func episodeByConversation(_ p: EntityProvenance?) -> [String: String] {
        var out: [String: String] = [:]
        for row in p?.conversations ?? [] where row.available {
            if let id = row.conversationId { out[id] = row.episodeId }
        }
        return out
    }
}

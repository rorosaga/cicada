import SwiftUI

// The evidence chip's decisions, pure and tested (design §4.2, §4.10
// `EvidenceChipLabelTests`): which chips a claim gets, what each one says,
// and where it opens. `EvidenceChip` renders these and nothing else.

// MARK: - What the chip knows about a document without fetching it

/// A document's header fields, when some payload the surface already holds
/// carried them — the entity card's `/provenance` conversations, an inbox
/// cause. `/span` carries no title or harness, and fetching `/text` per chip
/// just to name the agent would be N whole documents per card, so a chip
/// with no entry here says "The agent replied" and stays honest.
struct EvidenceDocMeta: Hashable {
    var title: String?
    var harness: String?
    var origin: String?
}

struct EvidenceDocIndex: Hashable {
    var byEpisode: [String: EvidenceDocMeta] = [:]

    static let empty = EvidenceDocIndex()

    func meta(_ episode: String) -> EvidenceDocMeta? { byEpisode[episode] }

    /// Every episode of every conversation row, keyed to that row's header.
    static func from(_ provenance: EntityProvenance?) -> EvidenceDocIndex {
        guard let provenance else { return .empty }
        var out: [String: EvidenceDocMeta] = [:]
        for row in provenance.conversations {
            let meta = EvidenceDocMeta(title: row.title.isEmpty ? nil : row.title,
                                       harness: row.harness, origin: row.origin)
            for ep in Set(row.episodeIds + [row.episodeId]) { out[ep] = meta }
        }
        return EvidenceDocIndex(byEpisode: out)
    }
}

private struct EvidenceDocIndexKey: EnvironmentKey {
    static let defaultValue = EvidenceDocIndex.empty
}

extension EnvironmentValues {
    /// Set by a surface that already knows its documents (the entity card sets
    /// it from `/provenance`), read by every `EvidenceChip` below it.
    var evidenceDocIndex: EvidenceDocIndex {
        get { self[EvidenceDocIndexKey.self] }
        set { self[EvidenceDocIndexKey.self] = newValue }
    }
}

// MARK: - Which chips

struct EvidenceChipModel: Hashable, Identifiable {
    enum Source: Hashable {
        /// A stored evidence entry — a span, or the contributor's own reasoning.
        case stored(Evidence)
        /// A legacy claim with no evidence: the conversation it lists in
        /// `source_episodes`, where the server will look for the subject's
        /// name (R-PB9). Always labelled `derived`, never "You said" (§4.9).
        case mention(episode: String, subjectId: String)
    }

    let source: Source

    var id: String {
        switch source {
        case let .stored(ev): "s|\(ev.episode)|\(ev.start)|\(ev.end)|\(ev.kind.rawValue)"
        case let .mention(ep, subject): "m|\(ep)|\(subject)"
        }
    }

    var episode: String {
        switch source {
        case let .stored(ev): ev.episode
        case let .mention(ep, _): ep
        }
    }

    /// What the chip is labelled as. `unknown` renders like `reasoning`.
    var kind: EvidenceKind {
        switch source {
        case let .stored(ev): ev.kind == .unknown ? .reasoning : ev.kind
        case .mention: .derived
        }
    }

    /// Where a click goes, or nil when there is nothing to open (reasoning
    /// that names no document).
    func target(subjectId: String?, meta: EvidenceDocMeta?) -> ReaderTarget? {
        switch source {
        case let .stored(ev):
            return ReaderTarget.evidence(ev, subjectId: subjectId, knownTitle: meta?.title,
                                         knownHarness: meta?.harness)
        case let .mention(ep, subject):
            return ReaderTarget(episode: ep, focus: .mention(entityId: subject), subjectId: subject,
                                knownTitle: meta?.title, knownHarness: meta?.harness)
        }
    }

    /// Legacy claims list every conversation they were reinforced in; three
    /// derived chips is enough to show the pattern without a wall of them.
    static let legacyCap = 3

    /// A claim's chips: one per stored evidence entry (duplicates folded), or,
    /// for a legacy claim with none, one derived chip per `ep_*` episode it
    /// lists, capped (§4.2). Before this, only the first episode showed, as an
    /// inert monospaced id (`EpisodePill`, A9).
    static func chips(evidence: [Evidence], sourceEpisodes: [String], subjectId: String) -> [EvidenceChipModel] {
        if !evidence.isEmpty {
            var seen = Set<String>()
            return evidence.compactMap { ev in
                let chip = EvidenceChipModel(source: .stored(ev))
                return seen.insert(chip.id).inserted ? chip : nil
            }
        }
        guard !subjectId.isEmpty else { return [] }
        var seen = Set<String>()
        return sourceEpisodes
            .filter { $0.hasPrefix("ep_") && seen.insert($0).inserted }
            .prefix(legacyCap)
            .map { EvidenceChipModel(source: .mention(episode: $0, subjectId: subjectId)) }
    }
}

// MARK: - What the chip says

enum EvidenceLabel {
    /// More than this many chips on one claim fold behind "+N more" (§4.2).
    static let visibleLimit = 3

    /// The speaker half of the label — the carrier of meaning; colour never
    /// carries it alone (§4.2, K13). `derived` is never "You said".
    static func speaker(kind: EvidenceKind, agent: String?, speakerName: String? = nil) -> String {
        switch kind {
        case .user: Copy.Provenance.youSaid
        case .assistant: agent.map(Copy.Provenance.replied) ?? Copy.Provenance.theAgentReplied
        case .page: Copy.Provenance.fromThePage
        case .media: Copy.Provenance.inTheVideo
        case .speaker: EvidenceSpeaker.named(speakerName).map(Copy.Provenance.said) ?? Copy.Provenance.someoneElseSaid
        case .derived: Copy.Provenance.mentionedHere
        case .reasoning, .unknown: Copy.Provenance.inferredLabel
        }
    }

    static func agent(_ meta: EvidenceDocMeta?) -> String? {
        EvidenceSpeaker.agentName(harness: meta?.harness, origin: meta?.origin)
    }

    /// "You said · Sep 3" — the date from the episode id (`ep_YYYY-MM-DD_nnn`);
    /// a page has no date to give.
    static func chipText(_ chip: EvidenceChipModel, meta: EvidenceDocMeta?,
                         locale: Locale = .autoupdatingCurrent,
                         timeZone: TimeZone = .autoupdatingCurrent) -> String {
        let label = speaker(kind: chip.kind, agent: agent(meta))
        guard let day = ReaderTime.day(timestamp: nil, episode: chip.episode, locale: locale,
                                       timeZone: timeZone, withYear: false) else { return label }
        return "\(label) · \(day)"
    }

    /// The VoiceOver label (§4.3): "You said, September 3, in Index choice.
    /// Opens the conversation."
    static func accessibility(_ chip: EvidenceChipModel, meta: EvidenceDocMeta?, opens: Bool,
                              locale: Locale = .autoupdatingCurrent,
                              timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts = [speaker(kind: chip.kind, agent: agent(meta))]
        if let date = ReaderTime.episodeDate(chip.episode, timeZone: timeZone) {
            var style = Date.FormatStyle().day().month(.wide)
            style.locale = locale
            style.timeZone = timeZone
            parts.append(date.formatted(style))
        }
        var sentence = parts.joined(separator: ", ")
        if let title = meta?.title, !title.isEmpty { sentence += ", in \(title)" }
        sentence += "."
        if opens { sentence += " \(Copy.Provenance.opensTheConversation)" }
        return sentence
    }

    /// The observer colour of the quote's left rule (§4.2): the same tokens
    /// `ObserverBadge` uses for you, the agent and an outside source — never a
    /// nature token, which may not encode data (R-M2, K13).
    static func ruleColor(_ kind: EvidenceKind) -> Color {
        switch kind {
        case .user: CicadaTheme.info
        case .assistant: CicadaTheme.accent
        case .page, .media, .speaker: CicadaTheme.mediaPink
        case .reasoning, .derived, .unknown: CicadaTheme.textTertiary
        }
    }

    static func symbol(_ kind: EvidenceKind) -> String {
        switch kind {
        case .user: "person.fill"
        case .assistant: "bubble.left.fill"
        case .page: "doc.richtext"
        case .media: "play.rectangle"
        case .speaker: "person.2"
        case .reasoning, .unknown: "lightbulb"
        case .derived: "text.magnifyingglass"
        }
    }
}

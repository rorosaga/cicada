import Foundation

// G227 follow-up (owner 2026-10-29) — the wire shapes of `page_joins` and the split sheet's pure rules.

/// `POST /entities/{id}/merge | split | history/{sha}/undo`.
struct PageJoinAnswer: Decodable, Equatable, Sendable {
    var kind: String
    var entityId: String
    var otherId: String?
    var commit: String?
    var restored: [String] = []
    var repointed: [String] = []
}

/// `GET /entities/{id}/split-plan` — what the split sheet shows.
struct SplitPlan: Decodable, Equatable, Sendable {
    struct Sentence: Decodable, Equatable, Sendable, Identifiable {
        var n: Int
        var section: String
        var text: String
        var suggested: Bool
        var reason: String?
        var id: Int { n }
    }
    struct Belief: Decodable, Equatable, Sendable, Identifiable {
        var id: String
        var text: String
        var episodes: [String]
        var current: Bool
    }
    struct Source: Decodable, Equatable, Sendable, Identifiable {
        var ref: String
        var label: String?
        var id: String { ref }
    }
    struct Conversation: Decodable, Equatable, Sendable, Identifiable {
        var id: String
        var title: String?
        var date: String?
    }
    struct Reference: Decodable, Equatable, Sendable, Identifiable {
        var pageId: String
        var name: String
        var episodes: [String]
        var id: String { pageId }
    }

    var entityId: String
    var name: String
    var type: String
    var newId: String
    var newName: String
    var sentences: [Sentence]
    var claims: [Belief]
    var sources: [Source]
    var conversations: [Conversation]
    var references: [Reference]
    var suggested: Bool = false
}

/// Which page another page's link meant — `page_join.reference_choice`, the same rule on both sides: the new page
/// when every conversation it rests on moves, this page when every one stays, else the person says.
enum SplitLinkChoice: String, Equatable, Sendable {
    case new, stay, ask

    static func from(episodes: [String], moved: Set<String>, staying: Set<String>) -> SplitLinkChoice {
        let eps = Set(episodes.filter { !$0.isEmpty })
        guard !eps.isEmpty else { return .ask }
        if eps.isSubset(of: moved), eps.isDisjoint(with: staying) { return .new }
        if eps.isSubset(of: staying), eps.isDisjoint(with: moved) { return .stay }
        return .ask
    }
}

/// What the person ticked: the request body of `POST /entities/{id}/split`.
struct SplitSelection: Equatable, Sendable {
    var sentences: Set<Int> = []
    var claims: Set<String> = []
    var sources: Set<String> = []
    var episodes: Set<String> = []
    /// Only the links the person said something about; an unsaid one follows its evidence on the server.
    var references: [String: SplitLinkChoice] = [:]
    var name: String = ""
    var type: String = ""

    /// The plan's own suggestions, pre-ticked — never applied until the person presses Split.
    static func starting(from plan: SplitPlan) -> SplitSelection {
        SplitSelection(sentences: Set(plan.sentences.filter(\.suggested).map(\.n)), name: plan.newName,
                       type: plan.type)
    }

    var isEmpty: Bool { sentences.isEmpty && claims.isEmpty }

    /// The link's choice as shown: the person's word, else what its evidence says once these conversations move.
    func choice(for ref: SplitPlan.Reference, plan: SplitPlan) -> SplitLinkChoice {
        if let said = references[ref.pageId] { return said }
        let all = Set(plan.conversations.map(\.id))
        return SplitLinkChoice.from(episodes: ref.episodes, moved: episodes, staying: all.subtracting(episodes))
    }

    var body: [String: Any] {
        var out: [String: Any] = [
            "sentences": sentences.sorted(), "claims": claims.sorted(), "sources": sources.sorted(),
            "episodes": episodes.sorted(),
            "references": references.filter { $0.value != .ask }.mapValues(\.rawValue),
        ]
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { out["name"] = trimmed }
        if !type.isEmpty { out["type"] = type }
        return out
    }
}

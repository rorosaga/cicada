import Foundation

/// G61 S3-a — a page holds many sources, and the person manages them on the card: change what a source is for,
/// how it is read, link it to the page that knows more about it, take an agent's, remove one. Everything here is pure
/// (the view and `EntitySourceWrite` only call it), so the painted list, the request body and the tests can never
/// disagree — the `ProjectWrite` / `EntityPictureWrite` rule: paint only what the server will answer.

/// One edit to one source, keyed by the entry's CURRENT `(ref, predicate)` (never an index).
enum SourceChange: Equatable {
    case remove
    /// "Use this source" — the person takes an agent's entry (`accepted`).
    case useThis
    /// `public` | `signed_in` — what opening it needs.
    case access(String)
    /// The fact it is for; empty makes it cover the page as a whole.
    case fact(String)
    case link(String)
    case unlink

    /// The entry after the change; `nil` when it is gone. A new fact changes the entry's identity (`id`).
    func apply(to source: EntitySource) -> EntitySource? {
        var next = source
        switch self {
        case .remove: return nil
        case .useThis: next.accepted = true
        case .access(let value): next.access = value
        case .fact(let value):
            let fact = value.trimmingCharacters(in: .whitespacesAndNewlines)
            next.predicate = fact.isEmpty ? nil : SourceGroups.slug(fact)
        case .link(let id): next.entity = id
        case .unlink: next.entity = nil
        }
        return next
    }

    /// The `POST /entities/{id}/sources/change` body. An unlink sends an explicit `null` (absent means "leave it").
    func body(for source: EntitySource) -> [String: Any] {
        var body: [String: Any] = ["ref": source.ref]
        if let predicate = source.predicate { body["predicate"] = predicate }
        switch self {
        case .remove: body["action"] = "remove"
        case .useThis: body["action"] = "update"; body["accepted"] = true
        case .access(let value): body["action"] = "update"; body["access"] = value
        case .fact(let value):
            body["action"] = "update"
            body["newPredicate"] = SourceGroups.slug(value.trimmingCharacters(in: .whitespacesAndNewlines))
        case .link(let id): body["action"] = "update"; body["entity"] = id
        case .unlink: body["action"] = "update"; body["entity"] = NSNull()
        }
        return body
    }

    /// The sentence after a change that lands, when one is owed. A removal says what it means: Cicada keeps it out.
    var doneMessage: String? {
        self == .remove ? Copy.Graph.sourceRemoved : nil
    }
}

extension EntitySource {
    /// An entry somebody else added and the person has not taken: the one "Use this source" is offered on.
    var canBeTaken: Bool {
        let who = addedBy.trimmingCharacters(in: .whitespaces)
        return !who.isEmpty && who != "user" && accepted != true
    }

    /// Only a `url` reads as one word of "how it is read"; a note is words, so it is never linked from the card's ↗.
    var hasLink: Bool { entity?.isEmpty == false }
}

enum SourceList {
    /// The list after `change` on the entry with this `id`; every other entry, and their order, unchanged.
    static func applying(_ change: SourceChange, toId id: String, in sources: [EntitySource]) -> [EntitySource] {
        sources.compactMap { $0.id == id ? change.apply(to: $0) : $0 }
    }
}

/// One fact's sources, in words — the card groups by predicate because a page holds many per fact.
struct SourceGroup: Equatable, Identifiable {
    /// nil is "the page as a whole".
    let predicate: String?
    let title: String
    let rows: [EntitySource]
    var id: String { predicate ?? "" }
}

enum SourceGroups {
    /// Groups in the order each predicate first appears (file order), rows keeping theirs; sources for the page as a
    /// whole come last, whatever their place in the file, so the facts a person asked about lead.
    static func groups(_ sources: [EntitySource]) -> [SourceGroup] {
        var order: [String] = []
        var rows: [String: [EntitySource]] = [:]
        for source in sources {
            let key = (source.predicate ?? "").trimmingCharacters(in: .whitespaces).lowercased()
            if rows[key] == nil { order.append(key) }
            rows[key, default: []].append(source)
        }
        let facts = order.filter { !$0.isEmpty }
        let keys = order.contains("") ? facts + [""] : facts
        return keys.map { key in SourceGroup(predicate: key.isEmpty ? nil : key, title: title(key), rows: rows[key] ?? []) }
    }

    /// "works-at" → "Works at"; `website` → "Official site"; none → "Anything".
    static func title(_ predicate: String?) -> String {
        let p = (predicate ?? "").trimmingCharacters(in: .whitespaces).lowercased()
        if p.isEmpty { return Copy.Graph.sourcesAnything }
        if p == "website" { return Copy.Graph.sourcesOfficialSite }
        let words = p.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
        return words.prefix(1).uppercased() + words.dropFirst()
    }

    /// The server slugs a predicate the way `id_utils.sanitize_id` does: lower-case words joined by hyphens.
    static func slug(_ text: String) -> String {
        let lowered = text.lowercased()
        let mapped = lowered.map { $0.isLetter || $0.isNumber ? String($0) : "-" }.joined()
        return mapped.split(separator: "-").joined(separator: "-")
    }
}

/// The pages a source may be linked to: not the page it is on, no facet satellites, hubs or repos (a repo node decodes as `unknown`).
enum SourceLinkCandidates {
    static func matching(_ query: String, nodes: [GraphNode], excluding entityId: String, limit: Int = 6) -> [GraphNode] {
        let pool = nodes.filter { !$0.isFacet && !$0.isHub && $0.type != .unknown && $0.id != entityId && $0.status != .dropped }
        return QuickMatch.rank(pool, query: query, limit: limit,
                               fields: { [QuickMatch.Field($0.name, weight: QuickMatch.Weight.name)] },
                               tieBreak: { $0.confidence }, name: { $0.name }).map(\.item)
    }
}

/// A failed source write in the person's words: the server's own sentence for a 400/409 (written for them); a 404's
/// detail names ids (DR-54), so it reads as one plain sentence.
enum SourceWriteFailure {
    static func message(_ error: (any Error)?) -> String {
        guard let api = error as? APIError else { return Copy.Graph.sourceSaveFailed }
        switch api {
        case .httpError(let code, let body) where [400, 409].contains(code):
            return ProjectWriteFailure.detail(body) ?? Copy.Graph.sourceSaveFailed
        case .serverUnreachable: return Copy.Graph.sourceBackendDown
        default: return Copy.Graph.sourceSaveFailed
        }
    }
}

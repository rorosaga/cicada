import Foundation

/// Owner ruling 2026-10-16 — one question a check settled (`GET /inbox/settled`, `SettledCheck` in
/// `api/models/schemas.py`): the answer, the citation it rests on (the page and its quote, on that belief only — never a
/// tracked source) and who settled it. `hasPage` says the subject has a page, so the citation can be promoted to a
/// tracked source with the person's own add-source route ("Track this source").
struct SettledCheck: Decodable, Identifiable, Equatable, Sendable {
    let id: String
    let kind: String
    let question: String
    let entityId: String
    let entityName: String
    let answer: String
    let predicate: String
    let ref: String
    let host: String
    let quote: String
    let settledAt: String
    let settledBy: String
    let settledByKind: String
    let scope: String
    let claimId: String
    let episode: String
    let held: Bool
    let hasPage: Bool
    /// Ruling 29: `check` (a web lookup or the person's own agent) or `sleep` — Sleep answered it from the person's
    /// own words in a conversation, or assumed it ("Settled by Sleep"). `reason` is the server's words for its rule.
    let group: String
    let rule: String
    let reason: String

    enum CodingKeys: String, CodingKey {
        case id, kind, question, entityId, entityName, answer, predicate, ref, host, quote, settledAt, settledBy, settledByKind
        case scope, claimId, episode, held, hasPage, group, rule, reason
    }

    init(id: String, kind: String = "clarification", question: String = "", entityId: String = "",
         entityName: String = "", answer: String = "", predicate: String = "description", ref: String = "", host: String = "", quote: String = "",
         settledAt: String = "", settledBy: String = "", settledByKind: String = "sleep", scope: String = "public",
         claimId: String = "", episode: String = "", held: Bool = false, hasPage: Bool = true,
         group: String = "check", rule: String = "", reason: String = "") {
        self.id = id; self.kind = kind; self.question = question; self.entityId = entityId
        self.entityName = entityName; self.answer = answer; self.predicate = predicate; self.ref = ref; self.host = host; self.quote = quote
        self.settledAt = settledAt; self.settledBy = settledBy; self.settledByKind = settledByKind
        self.scope = scope; self.claimId = claimId; self.episode = episode; self.held = held; self.hasPage = hasPage
        self.group = group; self.rule = rule; self.reason = reason
    }

    /// Forgiving, like the inbox's own decoder: a field a newer server adds or an older one lacks never costs the row.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func s(_ k: CodingKeys) -> String { (try? c.decodeIfPresent(String.self, forKey: k)) ?? "" }
        id = try c.decode(String.self, forKey: .id)
        kind = s(.kind); question = s(.question); entityId = s(.entityId); entityName = s(.entityName)
        answer = s(.answer); predicate = s(.predicate); ref = s(.ref); host = s(.host); quote = s(.quote); settledAt = s(.settledAt)
        settledBy = s(.settledBy); settledByKind = s(.settledByKind)
        scope = s(.scope).isEmpty ? "public" : s(.scope)
        claimId = s(.claimId); episode = s(.episode)
        held = (try? c.decodeIfPresent(Bool.self, forKey: .held)) ?? false
        hasPage = (try? c.decodeIfPresent(Bool.self, forKey: .hasPage)) ?? false
        group = s(.group).isEmpty ? "check" : s(.group)
        rule = s(.rule); reason = s(.reason)
    }

    /// Settled by Sleep (ruling 29), not by a check.
    var bySleep: Bool { group == "sleep" }

    /// A public citation the person may make a tracked source: a page they can open, on a subject with a page. A
    /// repository answer cites a commit, which is no place to re-check.
    var canTrack: Bool { !bySleep && hasPage && scope == "public" && ref.lowercased().hasPrefix("http") }
}

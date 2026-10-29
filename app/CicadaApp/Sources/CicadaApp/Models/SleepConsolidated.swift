import Foundation

/// Which consolidation a dropdown reads: a run (its batch commits) or one plain cycle's commit.
enum SleepConsolidatedKey: Hashable {
    case run(String)
    case commit(String)

    var path: String {
        switch self {
        case .run(let id):
            "/sleep/runs/\(id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id)/items"
        case .commit(let hash):
            "/sleep/history/\(hash.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? hash)/items"
        }
    }
}

/// `GET /sleep/runs/{id}/items` or `GET /sleep/history/{commit}/items` (owner 2026-10-26, the run card's dropdown):
/// the conversations one consolidation read, the pages it made and changed, the questions it raised and settled, from
/// its commits' own file lists. Not a Store domain: `SleepViewModel` keeps it in memory beside the run's detail,
/// revalidates it with the route's ETag and drops it on a bank switch. Each list is capped by the server (`truncated`);
/// `counts` are whole.
struct SleepConsolidated: Codable, Equatable {
    struct Conversation: Codable, Equatable, Identifiable {
        var id: String
        var title: String?
        var origin: String
        var timestamp: String?

        init(id: String, title: String? = nil, origin: String = "unknown", timestamp: String? = nil) {
            self.id = id; self.title = title; self.origin = origin; self.timestamp = timestamp
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            title = (try? c.decodeIfPresent(String.self, forKey: .title)) ?? nil
            origin = ((try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil) ?? "unknown"
            timestamp = (try? c.decodeIfPresent(String.self, forKey: .timestamp)) ?? nil
        }
    }

    struct Page: Codable, Equatable, Identifiable {
        var id: String
        var name: String?
        var type: String?
        /// Merged or removed since: the row shows its id and opens nothing.
        var gone: Bool
        /// G227 (items-2) — the name to show when another page shares this title.
        var displayName: String? = nil

        init(id: String, name: String? = nil, type: String? = nil, gone: Bool = false, displayName: String? = nil) {
            self.id = id; self.name = name; self.type = type; self.gone = gone; self.displayName = displayName
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? nil
            type = (try? c.decodeIfPresent(String.self, forKey: .type)) ?? nil
            gone = ((try? c.decodeIfPresent(Bool.self, forKey: .gone)) ?? nil) ?? false
            displayName = (try? c.decodeIfPresent(String.self, forKey: .displayName)) ?? nil
        }
    }

    struct Question: Codable, Equatable, Identifiable {
        var id: String
        var title: String?
        var kind: String?
        var entityId: String?
        var status: String?

        init(id: String, title: String? = nil, kind: String? = nil, entityId: String? = nil, status: String? = nil) {
            self.id = id; self.title = title; self.kind = kind; self.entityId = entityId; self.status = status
        }
    }

    var commits: [String]
    var conversations: [Conversation]
    var created: [Page]
    var updated: [Page]
    var questionsRaised: [Question]
    var questionsSettled: [Question]
    var counts: [String: Int]
    var truncated: Bool

    init(commits: [String] = [], conversations: [Conversation] = [], created: [Page] = [], updated: [Page] = [],
         questionsRaised: [Question] = [], questionsSettled: [Question] = [], counts: [String: Int] = [:],
         truncated: Bool = false) {
        self.commits = commits; self.conversations = conversations; self.created = created; self.updated = updated
        self.questionsRaised = questionsRaised; self.questionsSettled = questionsSettled; self.counts = counts
        self.truncated = truncated
    }

    /// Tolerant like every Sleep wire type: a missing list is empty, never a failed decode.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func list<T: Decodable>(_ key: CodingKeys) -> [T] { ((try? c.decodeIfPresent([T].self, forKey: key)) ?? nil) ?? [] }
        commits = list(.commits); conversations = list(.conversations); created = list(.created)
        updated = list(.updated); questionsRaised = list(.questionsRaised); questionsSettled = list(.questionsSettled)
        counts = ((try? c.decodeIfPresent([String: Int].self, forKey: .counts)) ?? nil) ?? [:]
        truncated = ((try? c.decodeIfPresent(Bool.self, forKey: .truncated)) ?? nil) ?? false
    }

    enum CodingKeys: String, CodingKey {
        case commits, conversations, created, updated, questionsRaised, questionsSettled, counts, truncated
    }

    /// The count of one group: the server's whole count, else the list's length.
    func count(_ key: String, _ fallback: Int) -> Int { counts[key] ?? fallback }
}

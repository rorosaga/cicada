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
        /// items-5 (2026-11-24) — the Waiting row's own facts, so the card draws the mark the Queue's card draws: the
        /// device that posted it (nil: this server's, or an older backend), a saved link's site key, a meeting's call
        /// app, and the ids of the pages (of the lists below) this conversation fed. All empty from an older backend.
        var device: String? = nil
        var site: String? = nil
        var meeting: EpisodeMeetingBrief? = nil
        var pages: [String] = []

        init(id: String, title: String? = nil, origin: String = "unknown", timestamp: String? = nil,
             device: String? = nil, site: String? = nil, meeting: EpisodeMeetingBrief? = nil, pages: [String] = []) {
            self.id = id; self.title = title; self.origin = origin; self.timestamp = timestamp
            self.device = device; self.site = site; self.meeting = meeting; self.pages = pages
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            title = (try? c.decodeIfPresent(String.self, forKey: .title)) ?? nil
            origin = ((try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil) ?? "unknown"
            timestamp = (try? c.decodeIfPresent(String.self, forKey: .timestamp)) ?? nil
            device = (try? c.decodeIfPresent(String.self, forKey: .device)) ?? nil
            site = (try? c.decodeIfPresent(String.self, forKey: .site)) ?? nil
            meeting = (try? c.decodeIfPresent(EpisodeMeetingBrief.self, forKey: .meeting)) ?? nil
            pages = ((try? c.decodeIfPresent([String].self, forKey: .pages)) ?? nil) ?? []
        }
    }

    /// What a consolidation did to a page (items-5). A page is in exactly one list, by its final state in the run.
    enum Change: String, Codable, CaseIterable, Equatable {
        case created, updated, archived, removed
    }

    struct Page: Codable, Equatable, Identifiable {
        var id: String
        var name: String?
        var type: String?
        /// Merged or removed since: the row shows its id and opens nothing.
        var gone: Bool
        /// G227 (items-2) — the name to show when another page shares this title.
        var displayName: String? = nil
        /// G227 — the qualifier alone (the run card says it inside the page's own `Tag`).
        var qualifier: String? = nil
        /// items-3 (owner 2026-11-23) — the consolidation's commits that changed this page, oldest first: its "Show
        /// change" diffs the first one's parent to the last. Empty from an older backend.
        var commits: [String] = []
        /// items-5 — what the run did to it, and the ids of THIS run's conversations that fed it. Nil / empty from an
        /// older backend: the list a page sits in then says what it did (`SleepConsolidated.pages`).
        var change: Change? = nil
        var episodes: [String] = []

        init(id: String, name: String? = nil, type: String? = nil, gone: Bool = false, displayName: String? = nil,
             qualifier: String? = nil, commits: [String] = [], change: Change? = nil, episodes: [String] = []) {
            self.id = id; self.name = name; self.type = type; self.gone = gone; self.displayName = displayName
            self.qualifier = qualifier; self.commits = commits; self.change = change; self.episodes = episodes
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? nil
            type = (try? c.decodeIfPresent(String.self, forKey: .type)) ?? nil
            gone = ((try? c.decodeIfPresent(Bool.self, forKey: .gone)) ?? nil) ?? false
            displayName = (try? c.decodeIfPresent(String.self, forKey: .displayName)) ?? nil
            qualifier = (try? c.decodeIfPresent(String.self, forKey: .qualifier)) ?? nil
            commits = ((try? c.decodeIfPresent([String].self, forKey: .commits)) ?? nil) ?? []
            change = ((try? c.decodeIfPresent(String.self, forKey: .change)) ?? nil).flatMap(Change.init(rawValue:))
            episodes = ((try? c.decodeIfPresent([String].self, forKey: .episodes)) ?? nil) ?? []
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
    /// items-5 — pages the run archived (decay's, or a status change) and pages it removed (a merged-away file).
    var archived: [Page] = []
    var removed: [Page] = []
    var questionsRaised: [Question]
    var questionsSettled: [Question]
    var counts: [String: Int]
    var truncated: Bool

    init(commits: [String] = [], conversations: [Conversation] = [], created: [Page] = [], updated: [Page] = [],
         archived: [Page] = [], removed: [Page] = [],
         questionsRaised: [Question] = [], questionsSettled: [Question] = [], counts: [String: Int] = [:],
         truncated: Bool = false) {
        self.commits = commits; self.conversations = conversations; self.created = created; self.updated = updated
        self.archived = archived; self.removed = removed
        self.questionsRaised = questionsRaised; self.questionsSettled = questionsSettled; self.counts = counts
        self.truncated = truncated
    }

    /// Tolerant like every Sleep wire type: a missing list is empty, never a failed decode.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func list<T: Decodable>(_ key: CodingKeys) -> [T] { ((try? c.decodeIfPresent([T].self, forKey: key)) ?? nil) ?? [] }
        commits = list(.commits); conversations = list(.conversations); created = list(.created)
        updated = list(.updated); archived = list(.archived); removed = list(.removed); questionsRaised = list(.questionsRaised); questionsSettled = list(.questionsSettled)
        counts = ((try? c.decodeIfPresent([String: Int].self, forKey: .counts)) ?? nil) ?? [:]
        truncated = ((try? c.decodeIfPresent(Bool.self, forKey: .truncated)) ?? nil) ?? false
    }

    enum CodingKeys: String, CodingKey {
        case commits, conversations, created, updated, archived, removed, questionsRaised, questionsSettled, counts, truncated
    }

    /// Every listed page with the change it carries: the list it sits in says it when the page does not (an older
    /// backend), in reading order (new, updated, archived, removed).
    var pages: [Page] {
        func tag(_ list: [Page], _ change: Change) -> [Page] {
            list.map { var p = $0; p.change = p.change ?? change; return p }
        }
        return tag(created, .created) + tag(updated, .updated) + tag(archived, .archived) + tag(removed, .removed)
    }

    /// The count of one group: the server's whole count, else the list's length.
    func count(_ key: String, _ fallback: Int) -> Int { counts[key] ?? fallback }
}

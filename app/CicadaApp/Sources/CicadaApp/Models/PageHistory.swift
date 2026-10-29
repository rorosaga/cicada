import Foundation

// Part B of the entity-page redesign (ruling 48 parts 5, 6 and 14; DR-77; 2026-10-29): the History tab's rows, a
// place's map state and "In short". The wire is `page_history`, `place_coordinates` and `page_blocks.summary`.

/// What one commit changed in one page (`page_history.summarize`): DR-77's "+N beliefs" and up to four changed lines.
struct HistorySummary: Codable, Equatable {
    struct Line: Codable, Equatable {
        var sign: String
        var text: String
    }

    var plusClaims: Int = 0
    var endedClaims: Int = 0
    var removedClaims: Int = 0
    var changedClaims: Int = 0
    var fields: [String] = []
    var proseAdded: Int = 0
    var proseRemoved: Int = 0
    var lines: [Line] = []

    enum CodingKeys: String, CodingKey {
        case plusClaims, endedClaims, removedClaims, changedClaims, fields, proseAdded, proseRemoved, lines
    }

    init(plusClaims: Int = 0, endedClaims: Int = 0, removedClaims: Int = 0, changedClaims: Int = 0,
         fields: [String] = [], proseAdded: Int = 0, proseRemoved: Int = 0, lines: [Line] = []) {
        self.plusClaims = plusClaims; self.endedClaims = endedClaims; self.removedClaims = removedClaims
        self.changedClaims = changedClaims; self.fields = fields; self.proseAdded = proseAdded
        self.proseRemoved = proseRemoved; self.lines = lines
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        plusClaims = (try? c.decodeIfPresent(Int.self, forKey: .plusClaims)) ?? 0
        endedClaims = (try? c.decodeIfPresent(Int.self, forKey: .endedClaims)) ?? 0
        removedClaims = (try? c.decodeIfPresent(Int.self, forKey: .removedClaims)) ?? 0
        changedClaims = (try? c.decodeIfPresent(Int.self, forKey: .changedClaims)) ?? 0
        fields = (try? c.decodeIfPresent([String].self, forKey: .fields)) ?? []
        proseAdded = (try? c.decodeIfPresent(Int.self, forKey: .proseAdded)) ?? 0
        proseRemoved = (try? c.decodeIfPresent(Int.self, forKey: .proseRemoved)) ?? 0
        lines = (try? c.decodeIfPresent([Line].self, forKey: .lines)) ?? []
    }
}

/// DR-77's filter tabs. `nil` is All, which leaves upkeep out (Wikipedia's bot flag, research #10).
enum HistoryBucket: String, CaseIterable, Hashable {
    case you, agents, sleep, upkeep

    var label: String {
        switch self {
        case .you: Copy.Graph.historyYou
        case .agents: Copy.Graph.historyAgents
        case .sleep: Copy.Graph.historySleep
        case .upkeep: Copy.Graph.historyUpkeep
        }
    }

    /// The row's bucket: the server's (`page_history.bucket`), else the same rule from the author's kind for a row
    /// an older backend served without one.
    static func of(_ entry: EntityHistoryEntry) -> HistoryBucket {
        if let b = HistoryBucket(rawValue: entry.bucket) { return b }
        switch entry.via {
        case "sleep": return .sleep
        case "app", "inbox": return .you
        case "agent", "remote": return .agents
        case "sync", "cicada": return .upkeep
        default: break
        }
        switch ContributorIdentity.kind(author: entry.author, serverKind: entry.authorKind) {
        case "user": return .you
        case "harness": return .agents
        case "model": return .sleep
        default: return .upkeep
        }
    }

    /// The rows one tab shows, newest first: All is everything but upkeep.
    static func filter(_ rows: [EntityHistoryEntry], _ tab: HistoryBucket?) -> [EntityHistoryEntry] {
        rows.filter { tab == nil ? of($0) != .upkeep : of($0) == tab }
    }

    /// Each tab's count over the rows read so far.
    static func counts(_ rows: [EntityHistoryEntry]) -> [HistoryBucket?: Int] {
        var out: [HistoryBucket?: Int] = [nil: 0]
        for b in allCases { out[b] = 0 }
        for row in rows {
            let b = of(row)
            out[b, default: 0] += 1
            if b != .upkeep { out[nil, default: 0] += 1 }
        }
        return out
    }
}

/// DR-77's words for one row: who, what happened as a sentence, how it got here, "+N beliefs", when. One function per
/// part so the row, its hover card and VoiceOver say the same thing.
enum HistoryRowWords {
    /// The writer's name: "You", the agent's product name, the model's display name, or "Cicada" for upkeep.
    static func who(_ e: EntityHistoryEntry) -> String {
        switch ContributorIdentity.kind(author: e.author, serverKind: e.authorKind) {
        case "user": return Copy.you
        case "system": return "Cicada"
        case "harness": return OriginIconography.label(for: e.author)
        case "unknown": return Copy.Graph.historyBeforeProvenance
        default: return ModelNames.display(e.author)
        }
    }

    private static func n(_ count: Int, _ one: String, _ many: String) -> String {
        count == 1 ? "1 \(one)" : "\(UsageFormat.count(count)) \(many)"
    }

    /// What happened, as a sentence: "Haiku 4.5 wrote this page", "Sonnet 5 added 3 beliefs", "You edited the page",
    /// "Cicada adjusted its confidence".
    static func sentence(_ e: EntityHistoryEntry) -> String {
        let name = who(e)
        let s = e.summary ?? HistorySummary()
        switch e.join {   // G227 follow-up: a page join says what it did, not what lines it touched
        case "merge": return "\(name) \(Copy.Graph.historyMerged)"
        case "split": return "\(name) \(Copy.Graph.historySplit)"
        case "undo": return "\(name) \(Copy.Graph.historyUndidJoin)"
        default: break
        }
        if e.changeType == .created { return "\(name) \(Copy.Graph.historyWrotePage)" }
        if HistoryBucket.of(e) == .upkeep {
            if e.trigger.hasPrefix("sleep/decay") { return Copy.Graph.historyDecay }
            if s.fields.contains("lat") || s.fields.contains("coordinates_by") { return Copy.Graph.historyPlaced(name) }
        }
        if s.fields.contains("in_short") && s.plusClaims == 0 && s.proseAdded == 0 {
            return "\(name) \(Copy.Graph.historyWroteInShort)"
        }
        if s.plusClaims > 0 { return "\(name) added \(n(s.plusClaims, "belief", "beliefs"))" }
        if s.endedClaims > 0 { return "\(name) ended \(n(s.endedClaims, "belief", "beliefs"))" }
        if s.removedClaims > 0 { return "\(name) removed \(n(s.removedClaims, "belief", "beliefs"))" }
        if s.proseAdded + s.proseRemoved > 0 { return "\(name) \(Copy.Graph.historyEditedPage)" }
        if e.changeType == .statusChange { return "\(name) \(Copy.Graph.historyChangedStatus)" }
        if s.changedClaims > 0 { return "\(name) \(Copy.Graph.historyUpdatedBeliefs)" }
        return "\(name) \(Copy.Graph.historyUpdatedPage)"
    }

    /// How it got here and the counts, one quiet line: "Read 2 conversations · +3 beliefs · 1 ended".
    static func detail(_ e: EntityHistoryEntry) -> String {
        var parts: [String] = []
        switch HistoryBucket.of(e) {
        case .sleep where !e.sessions.isEmpty: parts.append("Read \(n(e.sessions.count, "conversation", "conversations"))")
        case .agents: parts.append(e.via == "remote" ? Copy.Graph.historyRelayed : Copy.Graph.historyFromAgent)
        case .you: parts.append(e.via == "inbox" ? Copy.Graph.historyFromInbox : Copy.Graph.historyInCicada)
        default: break
        }
        if let s = e.summary {
            if s.plusClaims > 0 { parts.append("+\(n(s.plusClaims, "belief", "beliefs"))") }
            if s.endedClaims > 0 { parts.append("\(UsageFormat.count(s.endedClaims)) ended") }
            if s.removedClaims > 0 { parts.append("\(UsageFormat.count(s.removedClaims)) removed") }
        }
        return parts.joined(separator: " · ")
    }

    /// The hover card's "what changed", short: counts first, then which page fields moved.
    static func changed(_ e: EntityHistoryEntry) -> String {
        guard let s = e.summary else { return e.description }
        var parts: [String] = []
        if s.plusClaims > 0 { parts.append("+\(n(s.plusClaims, "belief", "beliefs"))") }
        if s.endedClaims > 0 { parts.append("\(UsageFormat.count(s.endedClaims)) ended") }
        if s.removedClaims > 0 { parts.append("\(UsageFormat.count(s.removedClaims)) removed") }
        if s.changedClaims > 0 { parts.append("\(n(s.changedClaims, "belief", "beliefs")) touched") }
        let prose = s.proseAdded + s.proseRemoved
        if prose > 0 { parts.append("\(n(prose, "line", "lines")) of prose") }
        let fields = s.fields.prefix(3).map(fieldWord)
        if !fields.isEmpty { parts.append(fields.joined(separator: ", ")) }
        return parts.isEmpty ? Copy.Graph.historyNoLineChanges : parts.joined(separator: " · ")
    }

    static func fieldWord(_ key: String) -> String {
        switch key {
        case "confidence": "confidence"
        case "last_referenced": "last mentioned"
        case "status": "status"
        case "decay_class", "decay_rate": "how fast it fades"
        case "lat", "lon", "coordinates_by", "coordinates_at": "place on the map"
        case "in_short": "In short"
        case "sources": "where to check"
        case "aliases": "other names"
        case "source_episodes": "conversations"
        default: key.replacingOccurrences(of: "_", with: " ")
        }
    }

    /// The commit's time for the row ("2:14 PM") and the hover ("Oct 27, 2026 at 2:14 PM"); the day alone from a
    /// backend that sent no time.
    static func when(_ e: EntityHistoryEntry, long: Bool = false) -> String {
        if let date = instant(e) {
            return long ? date.formatted(date: .abbreviated, time: .shortened) : date.formatted(date: .omitted, time: .shortened)
        }
        return EntityDates.shortDay(e.date) ?? e.date
    }

    static func instant(_ e: EntityHistoryEntry) -> Date? {
        guard !e.at.isEmpty else { return nil }
        return try? Date(e.at, strategy: .iso8601)
    }

    /// The day group a row sits under: Today, Yesterday, or the day.
    static func day(_ e: EntityHistoryEntry, now: Date = .now, calendar: Calendar = .current) -> String {
        let date = instant(e) ?? e.dateValue
        if calendar.isDate(date, inSameDayAs: now) { return Copy.Graph.historyToday }
        if let y = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: y) {
            return Copy.Graph.historyYesterday
        }
        return EntityDates.shortDay(e.date) ?? e.date
    }
}

/// `GET /entities/{id}/history?summary=true&limit=…`'s pager: 30 rows a page, "Older changes" asks for the next.
struct HistoryPager: Equatable {
    static let pageSize = 30
    private(set) var rows: [EntityHistoryEntry] = []
    private(set) var hasMore = false
    private(set) var loaded = false

    mutating func received(_ page: [EntityHistoryEntry], more: Bool) {
        var seen = Set(rows.map(\.commitHash).filter { !$0.isEmpty })
        rows += page.filter { $0.commitHash.isEmpty || seen.insert($0.commitHash).inserted }
        hasMore = more
        loaded = true
    }

    var nextSkip: Int { rows.count }

    static func == (a: HistoryPager, b: HistoryPager) -> Bool {
        a.rows.map(\.commitHash) == b.rows.map(\.commitHash) && a.hasMore == b.hasMore && a.loaded == b.loaded
    }
}

// MARK: - In short

/// "In short" (ruling 48 part 5, `page_blocks.summary`): Sleep's 2–3 sentences, its model, its day, and the
/// 30-day conversation count that qualified the page.
struct InShort: Codable, Equatable {
    var text: String
    var writtenAt: String?
    var by: String?
    var model: String?
    var conversations: Int?
}

// MARK: - Places

/// `GET /entities/{id}/place` (`place_coordinates.state`), read when the map draws — never when the card opens.
struct PlaceState: Codable, Equatable {
    struct Nearby: Codable, Equatable, Identifiable {
        var id: String
        var name: String
        var lat: Double
        var lon: Double
        var km: Double
    }

    struct Geocode: Codable, Equatable {
        var allowed: Bool
        var reason: String
        var query: String
    }

    var entityId: String
    var type: String?
    var coordinates: PageBlocks.Coordinates?
    var by: String?
    var at: String?
    var nearby: [Nearby]
    var geocode: Geocode?

    enum CodingKeys: String, CodingKey { case entityId, type, coordinates, by, at, nearby, geocode }

    init(entityId: String, type: String? = "location", coordinates: PageBlocks.Coordinates? = nil, by: String? = nil,
         at: String? = nil, nearby: [Nearby] = [], geocode: Geocode? = nil) {
        self.entityId = entityId; self.type = type; self.coordinates = coordinates; self.by = by; self.at = at
        self.nearby = nearby; self.geocode = geocode
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = (try? c.decode(String.self, forKey: .entityId)) ?? ""
        type = try? c.decodeIfPresent(String.self, forKey: .type)
        coordinates = (try? c.decodeIfPresent(PageBlocks.Coordinates.self, forKey: .coordinates)) ?? nil
        by = try? c.decodeIfPresent(String.self, forKey: .by)
        at = try? c.decodeIfPresent(String.self, forKey: .at)
        nearby = (try? c.decodeIfPresent([Nearby].self, forKey: .nearby)) ?? []
        geocode = (try? c.decodeIfPresent(Geocode.self, forKey: .geocode)) ?? nil
    }
}

/// `GET /places/unplaced`: public places the app's background pass may resolve on its own.
struct UnplacedPlace: Codable, Equatable {
    var entityId: String
    var name: String
    var query: String
}

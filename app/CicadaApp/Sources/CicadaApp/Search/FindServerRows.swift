import Foundation

/// Server hits → palette rows (G136 S4; round-3 design §3.3). Pure.
enum FindServerRows {
    /// R-SU14 — Pass A's and Pass B's kinds; `inbox` is the local tier's already.
    static let kinds = ["entity", "claim", "episode", "media"]

    static func group(forKind kind: String) -> FindGroupID? {
        switch kind {
        case "entity": .entities
        case "episode": .conversations
        case "claim": .beliefs
        case "media": .sources
        default: nil
        }
    }

    static func kind(for group: FindGroupID) -> String? {
        kinds.first { self.group(forKind: $0) == group }
    }

    struct Context {
        var now = Date()
        var locale = Locale.autoupdatingCurrent
        var calendar = Calendar.current
        /// A saved item's URL from the Feed snapshot the app holds — a hit carries none.
        var mediaURL: (String) -> String? = { _ in nil }
        var readerAvailable = FindReaderSeam.isAvailable
    }

    static func rows(_ response: MemorySearchResponse, query: String, context: Context) -> [FindRow] {
        let tokens = QuickMatch.tokens(query)
        func bold(_ text: String) -> [[Int]] {
            QuickMatch.match(tokens, fields: [QuickMatch.Field(text, weight: QuickMatch.Weight.name)])?.ranges(inField: 0) ?? []
        }
        func date(_ iso: String?) -> String? {
            FindDates.short(iso, now: context.now, locale: context.locale, calendar: context.calendar)
        }
        var rows: [FindRow] = []
        var conversationRow: [String: Int] = [:]
        var conversationHits: [String: Int] = [:]
        for hit in response.results {
            switch hit.kind {
            case "entity":
                let type = EntityType(rawValue: hit.type) ?? .unknown
                rows.append(FindRow(key: FindRowKey(kind: .entity, id: hit.id), group: .entities, title: hit.name,
                                    titleRanges: bold(hit.name), detail: entityDetail(hit), badge: type.label,
                                    mark: .entity(id: hit.id, name: hit.name, type: type), score: hit.score,
                                    destination: .entity(id: hit.id), secondary: .entityInClusters(id: hit.id)))
            case "media":
                rows.append(FindRow(key: FindRowKey(kind: .media, id: hit.id), group: .sources, title: hit.name,
                                    titleRanges: bold(hit.name), detail: hit.subtitle, badge: "Saved",
                                    mark: .entity(id: hit.id, name: hit.name, type: .media),
                                    trailing: date(hit.timestamp), score: hit.score,
                                    destination: .feedItem(mediaEntityId: hit.id),
                                    secondary: context.mediaURL(hit.id).map { .openURL($0) }))
            case "claim":
                let subject = hit.subjectId ?? ""
                let type = EntityType(rawValue: hit.type) ?? .concept
                // R-SU19 — the server ranks these after every current claim (R10); drawn as history.
                let isHistory = hit.validTo != nil || hit.supersededBy != nil
                let span = hit.episodeId.map {
                    ReaderSpan(doc: $0, start: hit.start, end: hit.end, hash: hit.hash, claimId: hit.id)
                }
                let detail = [hit.subtitle, speaker(hit.evidenceKind)].compactMap { $0 }.joined(separator: " · ")
                rows.append(FindRow(key: FindRowKey(kind: .belief, id: hit.id), group: .beliefs, title: hit.name,
                                    titleRanges: bold(hit.name), detail: detail.isEmpty ? nil : detail,
                                    mark: .entity(id: subject, name: hit.subtitle ?? subject, type: type),
                                    history: isHistory ? (date(hit.validTo).map { "until \($0)" } ?? "no longer current") : nil,
                                    score: hit.score, destination: .belief(subjectId: subject, claimId: hit.id),
                                    secondary: context.readerAvailable ? span.map { .evidence($0) } : nil))
            case "episode":
                // One row per conversation (the wire: "the palette does that
                // grouping on conversationId"); its best passage is the first.
                let key = hit.conversationId ?? hit.episodeId ?? hit.id
                conversationHits[key, default: 0] += 1
                if let index = conversationRow[key] {
                    rows[index].detail = "\(UsageFormat.count(conversationHits[key] ?? 1)) matches"
                    continue
                }
                conversationRow[key] = rows.count
                let span = ReaderSpan(doc: hit.episodeId ?? hit.id, start: hit.start, end: hit.end,
                                      hash: hit.hash, claimId: nil)
                let target = ConversationTarget(span: span, conversationId: hit.conversationId,
                                                harness: hit.harness, origin: hit.origin, title: hit.name)
                rows.append(FindRow(key: FindRowKey(kind: .conversation, id: key), group: .conversations,
                                    title: hit.name, titleRanges: bold(hit.name),
                                    snippet: hit.snippet.isEmpty ? nil : hit.snippet, snippetRanges: hit.snippetOffsets,
                                    mark: .origin(hit.harness ?? hit.origin ?? "unknown"),
                                    trailing: date(hit.timestamp), speaker: speaker(hit.evidenceKind), score: hit.score,
                                    destination: .conversation(target),
                                    secondary: .conversations(harness: hit.harness, origin: hit.origin, query: nil)))
            default:
                continue
            }
        }
        return rows
    }

    /// R-SU15 — per group, what the header and "Show all" may claim.
    static func totals(_ response: MemorySearchResponse, rows: [FindRow], kinds: [String], perKind: Int) -> [FindGroupID: FindCount] {
        var out: [FindGroupID: FindCount] = [:]
        for kind in kinds {
            guard let group = group(forKind: kind) else { continue }
            let hits = response.results.filter { $0.kind == kind }
            let shown = rows.filter { $0.group == group }.count
            if hits.contains(where: { $0.matchedField == "semantic" }) {
                out[group] = .atLeast   // semantic neighbours are ranked, never counted (G136 R11)
            } else if let total = response.totals[kind] {
                // `totals.episode` counts episodes: once two merged into one row it is not a row count.
                out[group] = (kind == "episode" && shown < hits.count) ? .atLeast : .exact(total)
            } else {
                out[group] = hits.count >= perKind ? .atLeast : .exact(shown)
            }
        }
        return out
    }

    /// Design §4.2's labels for `evidenceKind` — the row-level twin of the
    /// chips Track P draws on the entity card.
    static func speaker(_ kind: String?) -> String? {
        switch kind ?? "" {
        case "user": "You said"
        case "assistant": "Agent replied"
        case "page": "From page"
        case "reasoning": "Inferred"
        default: nil
        }
    }

    private static func entityDetail(_ hit: MemorySearchHit) -> String? {
        switch hit.matchedField ?? "" {
        case "alias": return hit.subtitle.map { "Also called \($0)" }
        case "claim": return hit.subtitle
        default: return hit.snippet.isEmpty ? nil : hit.snippet
        }
    }
}

/// "3 Sep" this year, "2 Jan 2025" otherwise — in the reader's own order
/// ("Sep 3" in en_US). A timestamp that does not parse is no date, never a guess.
enum FindDates {
    static func parse(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: iso) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: iso) { return date }
        formatter.formatOptions = [.withFullDate]
        return formatter.date(from: String(iso.prefix(10)))
    }

    static func short(_ iso: String?, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                      calendar: Calendar = .current) -> String? {
        guard let date = parse(iso) else { return nil }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.setLocalizedDateFormatFromTemplate(sameYear ? "dMMM" : "dMMMyyyy")
        return formatter.string(from: date)
    }
}

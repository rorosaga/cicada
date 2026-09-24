import Foundation

/// G147 — `GET /memory/decay-suggestions` and `PUT /memory/decay-tuning` (both answer this
/// shape). Not a Store domain — fetched when Settings → Memory opens, like the search index's
/// status — so no ETag and no `VersionVector` mapping. Lenient: a suggestion this build
/// cannot read is dropped alone, never the page.
struct DecayTuningResponse: Decodable, Equatable {
    var bank: String
    var windowDays: Int
    var tuning: [String: Double]
    var suggestions: [DecaySuggestion]

    enum CodingKeys: String, CodingKey { case bank, windowDays, tuning, suggestions }

    init(bank: String = "", windowDays: Int = 180, tuning: [String: Double] = [:],
         suggestions: [DecaySuggestion] = []) {
        self.bank = bank
        self.windowDays = windowDays
        self.tuning = tuning
        self.suggestions = suggestions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bank = (try? c.decode(String.self, forKey: .bank)) ?? ""
        windowDays = (try? c.decode(Int.self, forKey: .windowDays)) ?? 180
        tuning = (try? c.decode([String: Double].self, forKey: .tuning)) ?? [:]
        suggestions = ((try? c.decode([LossySuggestion].self, forKey: .suggestions)) ?? []).compactMap(\.value)
    }
}

/// One per-type suggestion: a kind of page and the counts behind it — never a page's name.
struct DecaySuggestion: Decodable, Equatable {
    enum Direction: String, Decodable { case slower, faster }

    var type: String
    var direction: Direction
    var multiplier: Double
    var kept: Int
    var archived: Int
    var answers: Int
}

private struct LossySuggestion: Decodable {
    let value: DecaySuggestion?
    init(from decoder: Decoder) throws { value = try? DecaySuggestion(from: decoder) }
}

/// One row under "How things fade": a suggestion to answer, or a pace already chosen.
struct FadeTypeRow: Identifiable, Equatable {
    enum Kind: Equatable {
        case suggestion(DecaySuggestion)
        case tuned(Double)
    }

    let type: String
    let kind: Kind
    /// The pace the person already chose for this kind, if any — a suggestion row says it.
    let current: Double?
    var id: String { type }
}

enum DecayTuningModel {
    /// Per viewer (plan R-FD8): "Not now" is a convenience, never state the bank keeps.
    static let notNowKey = "cicada.memory.fadeNotNow"
    /// A dismissed suggestion comes back only after this many more answers about that kind.
    static let notNowRepeat = 5

    static func notNowID(bank: String, _ s: DecaySuggestion) -> String {
        "\(bank)|\(s.type)|\(s.direction.rawValue)"
    }

    static func decodeNotNow(_ raw: String) -> [String: Int] {
        guard let data = raw.data(using: .utf8),
              let map = try? JSONDecoder().decode([String: Int].self, from: data) else { return [:] }
        return map
    }

    static func encodeNotNow(_ map: [String: Int]) -> String {
        guard let data = try? JSONEncoder().encode(map),
              let text = String(data: data, encoding: .utf8) else { return "" }
        return text
    }

    static func isHidden(_ s: DecaySuggestion, bank: String, notNow: [String: Int]) -> Bool {
        guard let dismissedAt = notNow[notNowID(bank: bank, s)] else { return false }
        return s.answers < dismissedAt + notNowRepeat
    }

    /// Suggestions first (the server's order: most answers first), then every chosen pace
    /// that has no visible suggestion, A→Z. One row per kind.
    static func rows(_ r: DecayTuningResponse, notNow: [String: Int]) -> [FadeTypeRow] {
        var rows: [FadeTypeRow] = []
        var seen = Set<String>()
        for s in r.suggestions where !isHidden(s, bank: r.bank, notNow: notNow) {
            guard seen.insert(s.type).inserted else { continue }
            rows.append(FadeTypeRow(type: s.type, kind: .suggestion(s), current: r.tuning[s.type]))
        }
        for (type, value) in r.tuning.sorted(by: { $0.key < $1.key }) where !seen.contains(type) {
            rows.append(FadeTypeRow(type: type, kind: .tuned(value), current: value))
        }
        return rows
    }
}

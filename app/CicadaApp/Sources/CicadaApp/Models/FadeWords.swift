import Foundation

/// G147 — how fast a page fades, in words a person reads (plan R-FD10).
///
/// The pace comes from the rate Sleep actually charges (`EntityDecay.effectiveRatePerWeek`),
/// not the class label, so a page that came up across twelve weeks reads "Slowly" even in
/// the default class. Thresholds are anchored on the default `active` rate, 0.05 a week: at
/// or under a quarter of it (the spacing floor) is "Very slowly", at or under 0.6 of it
/// (about four spaced weeks) is "Slowly", under 1.6 of it is the usual pace, anything faster
/// is "Quickly". Counts go through `UsageFormat.count` (DR-21).
enum FadeWords {
    enum Pace: Equatable {
        case never, verySlowly, slowly, usual, quickly

        var word: String {
            switch self {
            case .never: "Never"
            case .verySlowly: "Very slowly"
            case .slowly: "Slowly"
            case .usual: "At the usual pace"
            case .quickly: "Quickly"
            }
        }
    }

    static let verySlowlyMax = 0.0125
    static let slowlyMax = 0.03
    static let usualBelow = 0.08

    static func pace(ratePerWeek rate: Double) -> Pace {
        if rate <= 0 { return .never }
        if rate <= verySlowlyMax { return .verySlowly }
        if rate <= slowlyMax { return .slowly }
        if rate < usualBelow { return .usual }
        return .quickly
    }

    /// The Details row's value: "Slowly — mentioned across 12 weeks". No block (an older
    /// backend) → the class's own words, exactly as before G147.
    static func detail(_ decay: EntityDecay?, fallback: DecayClass,
                       locale: Locale = .autoupdatingCurrent) -> String {
        guard let decay else { return DetailsWords.fades(fallback) }
        let pace = pace(ratePerWeek: decay.effectiveRatePerWeek)
        guard pace != .never else { return pace.word }
        switch decay.mentionWeeks {
        case ..<1:
            return pace.word
        case 1:
            return "\(pace.word) — mentioned in a single week"
        default:
            return "\(pace.word) — mentioned across \(UsageFormat.count(decay.mentionWeeks, locale: locale)) weeks"
        }
    }

    // MARK: Settings → Memory (G147, plan R-FD6)

    /// The plain noun for a kind of page — "people", not "persons"; "ideas" for concepts.
    static func noun(_ type: String, count: Int) -> String {
        let pair: (one: String, many: String)
        switch EntityType(rawValue: type) ?? .unknown {
        case .person: pair = ("person", "people")
        case .project: pair = ("project", "projects")
        case .company: pair = ("company", "companies")
        case .concept: pair = ("idea", "ideas")
        case .tool: pair = ("tool", "tools")
        case .deadline: pair = ("deadline", "deadlines")
        case .skill: pair = ("skill", "skills")
        case .location: pair = ("place", "places")
        case .media: pair = ("saved item", "saved items")
        case .directory: pair = ("folder", "folders")
        case .hub, .unknown: pair = ("page", "pages")
        }
        return count == 1 ? pair.one : pair.many
    }

    private static func pluralNoun(_ type: String) -> String { noun(type, count: 2) }

    private static func speed(_ slower: Bool) -> String { slower ? "more slowly" : "more quickly" }

    /// "Let people fade more slowly?" — the question, stated once (DR-59).
    static func suggestionTitle(_ s: DecaySuggestion) -> String {
        "Let \(pluralNoun(s.type)) fade \(speed(s.direction == .slower))?"
    }

    /// "You kept 9 of the 10 people Cicada asked about." Each number once, through
    /// UsageFormat (DR-21); a suggestion against a pace already chosen says so, so Apply
    /// never reads as a no-op.
    static func suggestionDetail(_ s: DecaySuggestion, current: Double?,
                                 locale: Locale = .autoupdatingCurrent) -> String {
        let slower = s.direction == .slower
        let verb = slower ? "kept" : "archived"
        let part = slower ? s.kept : s.archived
        let nouns = noun(s.type, count: s.answers)
        let total = UsageFormat.count(s.answers, locale: locale)
        var text = part == s.answers
            ? "You \(verb) all \(total) \(nouns) Cicada asked about."
            : "You \(verb) \(UsageFormat.count(part, locale: locale)) of the \(total) \(nouns) Cicada asked about."
        if let current { text += " Right now they fade \(speed(current < 1))." }
        return text
    }

    /// "People fade more slowly" — a pace the person chose.
    static func tunedTitle(type: String, multiplier: Double) -> String {
        let nouns = pluralNoun(type)
        return nouns.prefix(1).uppercased() + nouns.dropFirst() + " fade " + speed(multiplier < 1)
    }

    static let tunedDetail = "You chose this. Reset to go back to the usual pace."
}

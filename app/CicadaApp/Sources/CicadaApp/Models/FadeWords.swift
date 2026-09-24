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
}

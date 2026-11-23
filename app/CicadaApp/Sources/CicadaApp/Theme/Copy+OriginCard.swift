import Foundation

extension Copy {
    /// `OriginCard` — one item of a history: the words, the app and how long ago.
    enum OriginCard {
        static let expandHint = "Shows all of it"
        static let collapseHint = "Shows less"

        /// "5d ago", "3h ago", "just now" — short, the way a glance reads it; computed when drawn (DR-58).
        static func ago(_ date: Date, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
            guard now.timeIntervalSince(date) >= 60 else { return Copy.Catalog.justNow }
            let f = RelativeDateTimeFormatter()
            f.unitsStyle = .abbreviated
            f.dateTimeStyle = .numeric
            f.locale = locale
            return f.localizedString(for: date, relativeTo: now)
        }
    }
}

import Foundation
import SwiftUI

/// The header card's mark and the windows its time bands cover (R-S3). The v2 tile it was written for retired
/// with Sources v3 (2026-10-19).
///
/// **Every scaled token is a computed `static var`, never a `static let`.**
/// `static let tileHeight = CicadaTheme.scaled(112)` is evaluated once, lazily,
/// at first access and then frozen — so ⌘+ would grow the text inside a tile
/// that never grew. That is C2 reintroduced one file over, and it is why
/// `CicadaTheme` spells its own tokens `static var spacingMD: CGFloat {
/// scaled(12) }`. `sparkDays` and `weeks` are pure counts and stay `static let`.
enum SourceCardMetrics {
    /// DR-52 — a bare mark, never on a tinted tile.
    static var markSize: CGFloat { CicadaTheme.scaled(20) }
    /// The sparkline's window, in days, and the dot row's, in weeks. Handed to
    /// Track A's `sparklinePoints(activity:days:today:)` and
    /// `weekDots(activity:weeks:today:)` (`ActivitySeries.swift`) unchanged
    /// (R-S8 — one implementation of the activity window, no alias and no
    /// second name).
    static let sparkDays = 14
    static let weeks = 4
    /// The detail page's window (R-S7). Thirty days because that is exactly what
    /// the payload carries — `source_overview.ACTIVITY_DAYS` — so the one page
    /// with room for the whole history shows the whole history instead of the
    /// tile's 14-day crop. Asking Track A's window for MORE days than the
    /// payload holds reads as leading zeros, never a crash, so the two numbers
    /// drifting apart later degrades into a shorter line rather than a broken
    /// one.
    static let detailSparkDays = 30
}

/// R-S3 — the delta is what makes the sparkline honest. The big number is a
/// LIFETIME total in the row's own unit (items / conversations / captures); the
/// line and this sentence are **captures** in the last 14 days. One noun for
/// both would let a browser's 506 bookmarks read as 506 recent captures — the
/// missing time dimension critique D3 names.
enum SourceDeltaText {
    /// `locale` is a parameter for the same reason `UsageFormat.count`'s is
    /// (R-S17): the month name and the grouped number are both locale-bound, so
    /// a default of `.autoupdatingCurrent` is what the reader sees and an
    /// explicit argument is what a test can assert on any host. Without it this
    /// sentence is green on an `en` machine and red everywhere else.
    ///
    /// `today` is unused by the `sum > 0` branch on purpose: it stays in the
    /// signature because the caller resolves ONE `today` per grid body and the
    /// two call sites must not each reach for `.now`.
    static func text(points: [Int], lastActivity: Date?, today: Date,
                     locale: Locale = .autoupdatingCurrent) -> String {
        let sum = points.reduce(0, +)
        // `points.count` is the window — never a second constant — so the
        // sentence and the line above it can never disagree about how many days
        // they cover.
        if sum > 0 {
            return "+\(UsageFormat.count(sum, locale: locale)) captured in \(points.count) days"
        }
        guard let lastActivity else { return "Nothing captured yet" }
        let month = DateFormatter()
        month.locale = locale
        month.dateFormat = "LLLL"
        // UTC because `activity`'s keys are UTC calendar days (R-A16); a local
        // time zone would name the wrong month for an activity near midnight.
        month.timeZone = TimeZone(identifier: "UTC")
        return "Nothing new since \(month.string(from: lastActivity))"
    }
}

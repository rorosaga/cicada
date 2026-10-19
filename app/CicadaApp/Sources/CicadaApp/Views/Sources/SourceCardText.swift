import SwiftUI

// Sources v3 (owner 2026-10-19) retired the v2 tile grid — packed 96 pt tiles with a sparkline, week-dots and a delta —
// for two groups of rows (`SourcesColumns.swift`). What the tiles and the rows shared stays here: the liveness tones,
// the header card's words and the one accessibility label every rendering of a source speaks.

/// R-DL20 (DR-7) — four tones: live keeps `success` (the approved mock; dated in §9), a warning or a failure speaks in
/// `warning` — DR-7's "first clause of a failed source" — and `danger` stays for destructive actions only. A failing
/// source's verb says it in words, so its dot is hidden.
extension SourceLiveness.Tone {
    var color: Color {
        switch self {
        case .live: CicadaTheme.success
        case .warning, .danger: CicadaTheme.warning
        case .dormant: CicadaTheme.textQuaternary
        }
    }

    var showsDot: Bool { self == .live || self == .dormant }
    var isAlarm: Bool { self == .warning || self == .danger }
}

/// The header card's words, one place (R-S19's rule: one projection, many renderings).
enum SourceCardText {
    static func noun(_ headline: (count: Int, noun: String)) -> String {
        headline.count == 1 ? headline.noun : headline.noun + "s"
    }

    /// Neutral text steps (P2): a flat line is `textQuaternary`, a dormant one `textTertiary`, a live one `textSecondary`.
    static func sparkColor(_ points: [Int], tone: SourceLiveness.Tone) -> Color {
        if points.allSatisfy({ $0 == 0 }) { return CicadaTheme.textQuaternary }
        return tone == .dormant ? CicadaTheme.textTertiary : CicadaTheme.textSecondary
    }
}

/// A source's spoken name and its quick action, shared by every rendering of a source (the rows, the header card).
enum SourceCard {
    /// Which quick action, if any, a source offers — sync wins when a row somehow advertises both (R-D3: no catalog
    /// row does today).
    static func quickAction(for source: SourceOverview) -> String? {
        if source.actions.contains("sync") { return "Sync now" }
        if source.actions.contains("poll") { return "Poll now" }
        return nil
    }

    /// The accessibility label, with the status light's own title appended when one is shown — the rail is "keep the
    /// accessibility label and GAIN the state title", not replace one with the other.
    ///
    /// R-S4: it leads with the same brand the row prints, not the catalog's long `label`. VoiceOver and the eye must
    /// name a source identically, or the page has two names for one row.
    static func accessibilityLabel(for source: SourceOverview, watchState: BrowserWatchState?) -> String {
        var label = "\(SourceDisplayName.of(source)), \(source.countLines.joined(separator: ", "))"
        if let watchState { label += ", \(BrowserStatusLight.title(for: watchState))" }
        return label
    }
}

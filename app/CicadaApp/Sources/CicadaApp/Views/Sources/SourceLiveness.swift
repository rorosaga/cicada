import SwiftUI

/// What a source is actually *doing* — R-S2, and the fix for the page's single
/// biggest legibility failure (critique D1).
///
/// Before this, the card painted `source.connected ? success : tertiary`, and
/// `build_overview` sets `connected = episodes > 0` for any row with no channel
/// (`api/services/source_overview.py:274-277`). So a live-watched Chrome, a
/// nightly-polled RSS feed, a hook-captured Claude Code session and a Claude
/// export imported once in July all showed the identical green dot. The dot's
/// real meaning was "has ever fed memory" — which is why the row EXISTS
/// (G124 R2), not what it is doing now.
///
/// Every input is already on the wire, so this needs **no backend field**:
/// `actions == ["import"]` is one-shot (`channel_registry._origin_channel`),
/// `poll` is the nightly connector poll (`_subscription_channel`), `sync` with
/// no watch is on-demand (`_sync_channel` / `_connector_channel`),
/// `harness != nil` is hook capture (G105), a `BrowserWatchState` refines a
/// browser (G129), and `lastError` outranks all of it.
struct SourceLiveness: Equatable {
    enum State: String, CaseIterable {
        case watching, syncing, behind, blocked, failed
        case captured, pollsNightly, syncsOnDemand, imported
    }

    /// How the card tints its dot and its sparkline. Deliberately four tones,
    /// not a per-state colour: the verb carries the meaning, the tone carries
    /// only "fine / act / broken / dormant".
    enum Tone: Equatable { case live, warning, danger, dormant }

    let state: State
    /// The error's first clause, for `.failed` and `.blocked` only (D2 — a card
    /// with room for "506 items" has room for "Can't read"). The full text
    /// stays in the tooltip, exactly where it already was.
    let detail: String?

    /// The card's one status line. `.failed` folds its clause in; every other
    /// state is a fixed phrase, so two states can never print the same words
    /// (asserted by `testEveryLivenessStateHasANonEmptyVerbAndNoStateReadsAsAnother`).
    var verb: String {
        switch state {
        case .watching: "Watching"
        case .syncing: "Syncing…"
        case .behind: "Behind — sync now"
        case .blocked: detail.map { "Can't read — \($0)" } ?? "Can't read"
        case .failed: detail.map { "Sync failed — \($0)" } ?? "Sync failed"
        case .captured: "Captured by hook"
        case .pollsNightly: "Polls nightly"
        case .syncsOnDemand: "Syncs when you ask"
        case .imported: "Imported once"
        }
    }

    var tone: Tone {
        switch state {
        case .watching, .syncing, .captured, .pollsNightly: .live
        case .behind: .warning
        case .blocked, .failed: .danger
        case .syncsOnDemand, .imported: .dormant
        }
    }

    var isLive: Bool { tone == .live }

    /// Precedence, highest first — a broken source says so before anything
    /// else, and `.blocked` stays distinct from `.failed` because it is the one
    /// failure with something the person can do (`BrowserWatchState`'s own
    /// reason, `Services/BrowserWatch.swift`, and the `.blocked` arm of
    /// `BrowserStatusLight` that renders `FullDiskAccessHint`).
    static func of(row: SourceOverview, channel: SourceChannel?, watch: BrowserWatchState?) -> SourceLiveness {
        let clause = firstClause(of: row.lastError)
        if watch == .blocked { return .init(state: .blocked, detail: clause) }
        if watch == .failed || clause != nil { return .init(state: .failed, detail: clause) }
        if watch == .syncing { return .init(state: .syncing, detail: nil) }
        if watch == .stale { return .init(state: .behind, detail: nil) }
        if watch == .watching { return .init(state: .watching, detail: nil) }
        // `harness` is set only for the `harness:<name>` family — hook capture.
        // A chat export is `kind: .harness` with `harness == nil`, and lands on
        // `.imported` below, which is exactly the standing-vs-one-shot line
        // G126 draws and the old page never showed (critique F3).
        if row.harness != nil { return .init(state: .captured, detail: nil) }
        // The channel's own actions win when the caller has the channel row:
        // `GET /sources/channels` is where `poll` vs `sync` vs `import` is
        // decided, and the overview copies it. Falling back to `row.actions`
        // keeps a channel-less row (the open `origin:` family, an unlisted
        // harness) on the same rule instead of a second one.
        let actions = Set(channel?.actions ?? row.actions)
        if actions.contains("poll") { return .init(state: .pollsNightly, detail: nil) }
        if actions.contains("sync") { return .init(state: .syncsOnDemand, detail: nil) }
        return .init(state: .imported, detail: nil)
    }

    /// A card line, not a log line: the first clause of the error, cut on the
    /// first sentence or separator boundary and capped. The whole message stays
    /// in `.help()`.
    static let maxClauseLength = 42
    static func firstClause(of error: String?) -> String? {
        guard var text = error?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        for separator in [" · ", ". ", "\n", ": "] {
            if let range = text.range(of: separator) { text = String(text[..<range.lowerBound]) }
        }
        text = text.trimmingCharacters(in: CharacterSet(charactersIn: " .·:")).trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return nil }
        if text.count > maxClauseLength { text = String(text.prefix(maxClauseLength - 1)) + "…" }
        return text
    }
}

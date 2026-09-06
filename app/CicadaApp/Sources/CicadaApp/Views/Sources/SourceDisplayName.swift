import Foundation

/// The one place an origin id becomes a product name — R-S4, and the fix for
/// four separate name defects the old grid shipped at `lineLimit(1)` in a
/// ~222 pt column:
///
/// - **A1** `source.label` is the catalog's long form (`"Chrome bookmarks"`,
///   `source_overview.CATALOG`), which truncates to "Chrome bookm…". The brand
///   is short *by construction* here, pinned by a length assertion over
///   `pinnedIds`, not by truncation at render time.
/// - **A2** `source_overview._new_state`'s open `origin:<id>` branch sets
///   `label = origin` verbatim, so an `origin:bookmark` episode set produced a
///   card titled "bookmark".
/// - **A3** `OriginIconography.label(for:)`'s `default: origin.capitalized`
///   turns `url` into "Url" and `rss-mirror` into "Rss-Mirror". Track L owns
///   that file and this plan does not edit it, so the acronym set and the
///   sentence-case rule live HERE.
/// - **A4** a card named after a null: `origin:unknown` is *an episode with no
///   `origin:` stamp* and `harness:unknown` is *an agent conversation whose
///   harness never identified itself*. Two different facts the app knows
///   exactly, so both get a name — "Unattributed" and "Other agents" — and
///   neither renders a "?" (the durable backfill,
///   `api/scripts/backfill_bookmark_origins.py`, is a separate concern).
///
/// The lookup is by **id**, never by `label`: the label is precisely the field
/// A1/A2 showed to be untrustworthy, and an id is stable across backends.
enum SourceDisplayName {
    /// Every `source_overview.CATALOG` id plus the three open-family ids a live
    /// bank actually produces. `SourcesV2Tests.testEveryDisplayNameFitsOnOneLine`
    /// drives off this list, so adding a table row without adding it here is
    /// the bug — the same rule `OriginIconography.allKnownOrigins` draws for
    /// marks.
    static let pinnedIds: [String] = Array(table.keys).sorted()

    /// Sentence case throughout ("Claude export", not "Claude Export"): the
    /// card's brand band sits above a lowercase status verb, and a table that
    /// mixed cases would make the fallback below (which cannot know which
    /// words are proper nouns) read as a different function.
    private static let table: [String: String] = [
        // CATALOG, in its own order.
        "chat-export:claude": "Claude export",
        "chat-export:chatgpt": "ChatGPT export",
        "chat-export:gemini": "Gemini export",
        "chrome-bookmarks": "Chrome",
        "safari-bookmarks": "Safari",
        "safari-tabs": "Safari tabs",
        "pinterest": "Pinterest",
        "reddit": "Reddit",
        "x": "X",
        "instagram": "Instagram",
        "youtube": "YouTube",
        "linkedin": "LinkedIn",
        "tiktok": "TikTok",
        "rss": "RSS",
        "calendar": "Calendars",
        "telegram": "Telegram",
        "notes": "Apple Notes",
        "files": "Files & links",
        // The open families a live bank produces (A2/A4).
        "origin:unknown": "Unattributed",
        "origin:bookmark": "Saved links",
        "origin:url": "Links",
        "harness:unknown": "Other agents",
    ]

    /// Ids that read as words but are pronounced as letters. Applied here
    /// rather than in `OriginIconography` because Track L owns that file, and
    /// because `String.capitalized` has no idea "rss" is not a word.
    private static let acronyms: Set<String> = ["rss", "url", "mcp", "api", "id", "ics", "pdf", "csv"]

    static func of(_ source: SourceOverview) -> String { of(id: source.id) }

    static func of(id: String) -> String {
        if let pinned = table[id] { return pinned }
        // Strip the family prefix so `harness:cursor` reaches the same rung as
        // the bare origin id `OriginIconography` already knows.
        var bare = id
        for prefix in ["harness:", "origin:"] where bare.hasPrefix(prefix) {
            bare = String(bare.dropFirst(prefix.count))
        }
        guard !bare.isEmpty else { return sentenceCase(id) }
        // Rung 1: Track L's own map, but ONLY when it has a real case for the
        // id. Its `default:` is `origin.capitalized`, so an id it does not know
        // is detectable by comparing against exactly that — and taking it would
        // reintroduce A3 ("Url", "Rss-Mirror").
        let known = OriginIconography.label(for: bare)
        if known != bare.capitalized { return known }
        // Rung 2: the deterministic shape. One function, so two reviewers
        // cannot write two fallbacks.
        return sentenceCase(bare)
    }

    /// `-`/`_` become spaces, an acronym uppercases, and the rest is **sentence
    /// case** — first word capitalised, later words left lowercase. Sentence
    /// case, not title case, because every name in `table` is sentence case; a
    /// fallback that read differently from the table is exactly the drift this
    /// type exists to remove. `String.capitalized` alone gives "Rss-Mirror" and
    /// "Brand-New".
    private static func sentenceCase(_ raw: String) -> String {
        let words = raw
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map(String.init)
        guard !words.isEmpty else { return raw }
        return words.enumerated().map { index, word -> String in
            let lower = word.lowercased()
            if acronyms.contains(lower) { return lower.uppercased() }
            guard index == 0 else { return lower }
            return lower.prefix(1).uppercased() + lower.dropFirst()
        }.joined(separator: " ")
    }
}

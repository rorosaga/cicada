import Foundation

/// One honest sentence of what Cicada reads from a source — no price, no
/// token count (the 2026-09-03 ruling), just what shows up in memory when
/// this source is connected. Keyed by `source.id` for the eighteen rows
/// `api/services/source_overview.CATALOG` declares today; a harness or
/// origin the catalog has never heard of (the `harness:<name>` and
/// `origin:<id>` open families, G124 R1) falls back to one sentence per
/// kind, built from the row's own label so it still reads as a specific
/// sentence rather than a generic placeholder.
enum SourceBlurb {
    static func text(for source: SourceOverview) -> String {
        byId[source.id] ?? fallback(kind: source.kind, label: source.label)
    }

    private static func fallback(kind: SourceKind, label: String) -> String {
        switch kind {
        case .harness:
            return "Conversations captured from \(label), one episode per session."
        case .browser:
            return "Bookmarks and tabs from \(label), synced as you browse."
        case .social:
            return "Items you saved on \(label), as links with their titles and boards."
        case .feed:
            return "New items from \(label), the feeds and calendars you subscribed to."
        case .messaging:
            return "Messages you send to \(label), as notes."
        case .import, .unknown:
            return "Links or files you added through \(label)."
        }
    }

    // Every id below is one `source_overview.CATALOG` declares (verified
    // against api/services/source_overview.py at plan time). A gap here
    // would silently fall through to the kind fallback above rather than
    // fail loud — SourcesPageTests asserts every catalog id by name so a
    // future catalog addition without a matching blurb still passes here
    // (the kind fallback is a legitimate answer), but never regresses one
    // that already had a specific sentence.
    private static let byId: [String: String] = [
        "chat-export:claude": "Claude conversations you exported and imported, one episode per thread.",
        "chat-export:chatgpt": "ChatGPT conversations you exported and imported, one episode per thread.",
        "chat-export:gemini": "Gemini conversations you exported from Takeout, one episode per thread.",
        "chrome-bookmarks": "Bookmarks you save in Chrome, synced as you add them.",
        "safari-bookmarks": "Bookmarks you save in Safari, synced as you add them.",
        "safari-tabs": "Your open Safari tabs across devices, via iCloud.",
        "pinterest": "Pins you save on Pinterest, as links with their boards.",
        "reddit": "Posts and comments you save on Reddit, as links with their titles.",
        "x": "Posts you bookmark on X, as links with their text.",
        "instagram": "Posts you save on Instagram, as links with their captions.",
        "youtube": "Videos in the YouTube playlists you follow.",
        "linkedin": "Posts you save on LinkedIn, as links with their titles.",
        "tiktok": "Videos you save on TikTok, as links with their captions.",
        "rss": "New posts from the feeds you subscribed to.",
        "calendar": "Events from the calendars you subscribed to.",
        "telegram": "Messages you send the bot, as notes.",
        "notes": "Notes you write in Apple Notes.",
        "files": "Links you pasted or files you dropped.",
    ]
}

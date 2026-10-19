import CoreServices
import Foundation

/// 2026-10-19 — the star clicked on a page already bookmarked (owner: "Touching the star, even if it's already
/// bookmarked, keeps prompting me about what interests me … It should just put the same Cicada prompt, but with the
/// text already filled in or the selection already made if I already did it").
///
/// Chrome's "Edit bookmark" bubble is the same window as "Bookmark added" (448 × 224, measured), and on a page already
/// bookmarked Chrome writes nothing, so neither the window list nor the file can say which bookmark it is. The page's
/// own link can: Chrome's `URL of active tab`, asked through Apple Events — **only when the person has already allowed
/// Cicada to control Chrome** (`ChromeFrontTab.granted`, which never asks: the Automation prompt still comes only from
/// Remove bookmark…, G191 v3), and only in the moment after the person's own star click opened the bubble. The link is
/// compared with what Chrome's file held before the click (`BookmarkFileDiff`'s baseline) and with the bookmarks
/// Cicada holds; it is never stored, logged or posted — the panel binds to Cicada's own record of that bookmark.
struct ExistingBookmark: Equatable, Sendable {
    /// The bookmark as the panel binds it: its link, title, browser and the moment it was saved.
    let item: FreshBookmark
    /// Its newest answer, and when that was said (the answer's key for an edit); nil when it was never answered.
    let answer: SavedWhyAnswer?
    let at: String?

    /// The record behind `url` on `channel`'s browser, when that browser held the link before the click
    /// (`browserHolds`, the diff's baseline — a link it did not hold is a new bookmark, asked about as one) and Cicada
    /// holds it as that browser's bookmark. Exact links only: never a near match.
    static func find(url: String, channel: String, items: [MediaFeedItem], browserHolds: Set<String>?)
        -> ExistingBookmark? {
        guard let browserHolds, browserHolds.contains(url) else { return nil }
        let origin = SavedBookmarkLookup.origin(forChannel: channel)
        guard let record = items.first(where: { $0.url == url && $0.origin == origin }) else { return nil }
        let newest = record.savedWhy
        let item = FreshBookmark(url: record.url, title: record.title, origin: origin, channel: channel,
                                 addedAt: newest?.addedAt ?? record.lastSavedAt)
        guard let newest, let at = newest.at, !newest.answer.isEmpty else {
            return ExistingBookmark(item: item, answer: nil, at: nil)
        }
        return ExistingBookmark(item: item, answer: newest.answer, at: at)
    }
}

enum SavedBookmarkLookup {
    /// `chrome-bookmarks` → `chrome-bookmark`: the origin a channel's sync stamps on its saved items.
    static func origin(forChannel channel: String) -> String {
        channel.hasSuffix("s") ? String(channel.dropLast()) : channel
    }

    /// The live lookup: nothing unless Automation of the browser is already allowed; then the front tab's link,
    /// matched against the browser's file and the Store's bookmarks.
    @MainActor
    static func live(channel: String, items: [MediaFeedItem]) async -> ExistingBookmark? {
        guard let bundleId = BrowserInventory.spec(forBookmarksChannel: channel)?.bundleId else { return nil }
        let granted = await Task.detached(priority: .userInitiated) { ChromeFrontTab.granted(bundleId: bundleId) }.value
        guard granted, let url = await ChromeFrontTab.url(bundleId: bundleId) else { return nil }
        return ExistingBookmark.find(url: url, channel: channel, items: items,
                                     browserHolds: BookmarkFileDiff.shared.baselines[channel]?.urls)
    }
}

/// The front tab's link of a Chromium browser, through Apple Events — never when that would ask the person.
enum ChromeFrontTab {
    /// Whether macOS already lets Cicada send this browser Apple Events. `askUserIfNeeded` is false: this never shows
    /// the Automation prompt (an undecided or refused grant answers false). Off the main thread — it can block.
    nonisolated static func granted(bundleId: String) -> Bool {
        var target = AEAddressDesc()
        let bytes = Array(bundleId.utf8)
        let created = bytes.withUnsafeBytes { raw in
            AECreateDesc(DescType(typeApplicationBundleID), raw.baseAddress, raw.count, &target)
        }
        guard created == noErr else { return false }
        defer { AEDisposeDesc(&target) }
        let status = AEDeterminePermissionToAutomateTarget(&target, AEEventClass(typeWildCard),
                                                           AEEventID(typeWildCard), false)
        return status == noErr
    }

    /// The active tab's URL of the front window, or nil (no window, a refusal, a timeout). Only call after `granted`.
    static func url(bundleId: String,
                    run: (String) async -> ChildProcess.Output = { script in
                        await ChildProcess.run(URL(fileURLWithPath: "/usr/bin/osascript"), arguments: ["-e", script],
                                               timeout: 2)
                    }) async -> String? {
        let script = "tell application id \"\(bundleId)\" to get URL of active tab of front window"
        let output = await run(script)
        guard output.status == 0, !output.timedOut else { return nil }
        let url = output.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        return url.hasPrefix("http://") || url.hasPrefix("https://") ? url : nil
    }
}

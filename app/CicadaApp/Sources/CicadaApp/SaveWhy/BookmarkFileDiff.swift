import Foundation

/// G191 v3 — the link fills in before the backend answers. Measured on a synthetic 20,000-bookmark Chrome file (see
/// REPORT / app.md): after Chrome writes, the early look spent most of its time base64-encoding the file, posting
/// it, and the backend decoding and parsing it again before it could say which link was new. The app already holds
/// the bytes it just read, so it parses them itself and diffs them against the set it saw last time: one link that
/// was not there (or a bookmark node newer than any it saw — saved again) is shown at once, while the early look and
/// the sync still decide — the backend stays the one writer, and the answer is posted only once it agrees
/// (`SaveWhyCenter.confirmed`).
///
/// The baseline is per channel, in memory: the first read after launch (a catch-up, a seed or the first live save)
/// only records it, so the diff never asks about a bookmark it has no "before" for — the backend's look does then.
struct BookmarkEntry: Equatable, Sendable {
    let url: String
    let title: String
    /// Chromium's node id (`id`) — what Apple Events address a bookmark by.
    var nodeId: String? = nil
    /// Chromium's `date_added` (WebKit microseconds); Safari records none for a bookmark.
    var addedMicros: Int64? = nil
    /// The root it hangs under (`bookmark_bar`, `other`, `synced`) and the folder ids from it down.
    var root: String? = nil
    var folderIds: [String] = []

    /// The browser's own instant as the backend writes it (aware UTC ISO, seconds).
    var addedAt: String? {
        guard let addedMicros, addedMicros > 0 else { return nil }
        let seconds = Double(addedMicros) / 1_000_000 - 11_644_473_600
        guard seconds > 0 else { return nil }
        return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: seconds.rounded(.down)))
    }
}

enum BookmarkFileParse {
    /// Chromium's `Bookmarks` JSON: every `url` node, with its id, instant and folder path. Malformed bytes → [].
    static func chromium(_ data: Data) -> [BookmarkEntry] {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let roots = object["roots"] as? [String: Any] else { return [] }
        var out: [BookmarkEntry] = []
        func walk(_ node: [String: Any], root: String, folders: [String]) {
            if (node["type"] as? String) == "url" {
                guard let url = node["url"] as? String, url.hasPrefix("http://") || url.hasPrefix("https://") else {
                    return
                }
                out.append(BookmarkEntry(url: url, title: node["name"] as? String ?? "",
                                         nodeId: node["id"] as? String,
                                         addedMicros: (node["date_added"] as? String).flatMap { Int64($0) },
                                         root: root, folderIds: folders))
                return
            }
            let path = node["id"] as? String
            for child in node["children"] as? [[String: Any]] ?? [] {
                walk(child, root: root, folders: folders + (path.map { [$0] } ?? []))
            }
        }
        for key in roots.keys.sorted() {
            guard let node = roots[key] as? [String: Any] else { continue }
            // A root's own id is the folder Apple Events reach as `bookmarks bar` / `other bookmarks`: not in the path.
            for child in node["children"] as? [[String: Any]] ?? [] { walk(child, root: key, folders: []) }
        }
        return out
    }

    /// Safari's `Bookmarks.plist`: every leaf's URL and title (Safari keeps no instant for a bookmark).
    static func safari(_ data: Data) -> [BookmarkEntry] {
        guard let root = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
            return []
        }
        var out: [BookmarkEntry] = []
        func walk(_ node: [String: Any]) {
            if (node["WebBookmarkType"] as? String) == "WebBookmarkTypeLeaf" {
                guard let url = node["URLString"] as? String, url.hasPrefix("http://") || url.hasPrefix("https://")
                else { return }
                let title = (node["URIDictionary"] as? [String: Any])?["title"] as? String ?? ""
                out.append(BookmarkEntry(url: url, title: title))
                return
            }
            for child in node["Children"] as? [[String: Any]] ?? [] { walk(child) }
        }
        walk(root)
        return out
    }

    static func entries(channel: String, data: Data) -> [BookmarkEntry] {
        channel == "safari-bookmarks" ? safari(data) : chromium(data)
    }
}

/// What a channel's file held at the last read: its links, and the newest instant any node carried.
struct BookmarkBaseline: Equatable, Sendable {
    var urls: Set<String>
    var newest: Int64?

    init(_ entries: [BookmarkEntry]) {
        urls = Set(entries.map(\.url))
        newest = entries.compactMap(\.addedMicros).max()
    }

    /// The bookmarks saved since this baseline: a link it did not hold, or a node newer than any it saw (the same
    /// link removed and saved again between two reads, or bookmarked twice). A move or a rename keeps both, so it is
    /// never one. One per link.
    func saved(in entries: [BookmarkEntry]) -> [BookmarkEntry] {
        var seen = Set<String>()
        return entries.filter { entry in
            guard !seen.contains(entry.url) else { return false }
            let isNew = !urls.contains(entry.url)
                || (entry.addedMicros.map { stamp in newest.map { stamp > $0 } ?? false } ?? false)
            if isNew { seen.insert(entry.url) }
            return isNew
        }
    }
}

/// The app's own diff, per channel. `observe` records every read and, for a live one, returns the single bookmark
/// saved since the last read (nil for none, several, or no baseline yet).
@MainActor
final class BookmarkFileDiff {
    static let shared = BookmarkFileDiff()

    private(set) var baselines: [String: BookmarkBaseline] = [:]

    func reset() { baselines = [:] }

    /// Record a baseline for each channel not yet read, from its file (a browser macOS refuses is skipped quietly —
    /// its first live save is then decided by the backend's look alone).
    func seed(channels: [String]) async {
        for channel in channels where baselines[channel] == nil {
            guard let spec = BrowserInventory.spec(forBookmarksChannel: channel),
                  let file = BrowserFile.bookmarks(forBrowser: spec.id),
                  let data = try? await BrowserFileReader.read(file) else { continue }
            _ = await observe(channel: channel, data: data, live: false)
        }
    }

    /// Parse off the main actor, then diff and advance the baseline here (in read order: the caller awaits).
    func observe(channel: String, data: Data, live: Bool) async -> FreshBookmark? {
        let entries = await Task.detached(priority: .userInitiated) {
            BookmarkFileParse.entries(channel: channel, data: data)
        }.value
        return record(channel: channel, entries: entries, live: live)
    }

    func record(channel: String, entries: [BookmarkEntry], live: Bool) -> FreshBookmark? {
        let before = baselines[channel]
        baselines[channel] = BookmarkBaseline(entries)
        guard live, let before else { return nil }
        let saved = before.saved(in: entries)
        guard saved.count == 1, let entry = saved.first else { return nil }
        let origin = channel.replacingOccurrences(of: "-bookmarks", with: "-bookmark")
        return FreshBookmark(url: entry.url, title: entry.title, origin: origin, channel: channel, episodeId: "",
                             addedAt: entry.addedAt, resave: before.urls.contains(entry.url))
    }
}

/// G191 v3 — removing a bookmark from Chrome on the person's click. Chrome is scriptable (`delete bookmark item id …`),
/// so the app finds the bookmark's nodes in the `Bookmarks` file it already reads and addresses each by its folder
/// chain; the backend never touches the browser. Safari offers no such dictionary for its bookmarks — another app
/// cannot safely edit them — so the app says so and opens Safari instead.
///
/// **Review 2026-10-15 — never the wrong bookmark.** The app reads the default profile's file, but Chrome's Apple Events
/// act on the profile last used, and node ids are per profile: an id from the file can name an unrelated bookmark
/// there. So the script checks each node's URL before deleting it (`if URL of b is targetURL then delete b`), the URL
/// reaches the script as an argument (`on run argv`), never pasted into its source, and the script returns how many it
/// really deleted. And only the bookmark this save made is targeted — the node whose `date_added` matches the
/// record's `lastSavedAt` — while other copies of the same link are named in the confirmation and removed only when
/// the person asks for all of them (`ChromeRemovalPlan`).
enum ChromeBookmarkScript {
    /// Every node holding `url`, in the roots Apple Events can reach (the bookmarks bar and other bookmarks; the
    /// mobile folder is not scriptable).
    static func nodes(for url: String, in entries: [BookmarkEntry]) -> [BookmarkEntry] {
        entries.filter { $0.url == url && $0.nodeId != nil && rootSpecifier($0.root) != nil }
    }

    /// Nodes holding `url` that no script can reach (the mobile bookmarks folder).
    static func unreachable(for url: String, in entries: [BookmarkEntry]) -> Int {
        entries.filter { $0.url == url && ($0.nodeId == nil || rootSpecifier($0.root) == nil) }.count
    }

    static func rootSpecifier(_ root: String?) -> String? {
        switch root {
        case "bookmark_bar": return "bookmarks bar"
        case "other": return "other bookmarks"
        default: return nil
        }
    }

    /// The AppleScript that deletes `nodes` from Chrome (`bundleId`) — each only if its URL is the one passed as the
    /// script's first argument — and returns the number deleted. Ids are digits only (anything else is dropped), and
    /// the URL is never part of the source. A refused Automation (-1743/-1744) stops the script with that error; any
    /// other per-node error (the node is gone, another profile) skips that node.
    static func delete(_ nodes: [BookmarkEntry], bundleId: String = "com.google.Chrome") -> String? {
        let blocks: [String] = nodes.compactMap { node in
            guard let id = node.nodeId, isDigits(id), let root = rootSpecifier(node.root),
                  node.folderIds.allSatisfy(isDigits) else { return nil }
            let chain = node.folderIds.reversed().map { "bookmark folder id \($0)" } + [root]
            return """
                    try
                        set b to bookmark item id \(id) of \(chain.joined(separator: " of "))
                        if (URL of b) is targetURL then
                            delete b
                            set removed to removed + 1
                        end if
                    on error message number code
                        if code is -1743 or code is -1744 then error message number code
                    end try
            """
        }
        guard !blocks.isEmpty, isBundleId(bundleId) else { return nil }
        return """
        on run argv
            set targetURL to item 1 of argv
            set removed to 0
            tell application id "\(bundleId)"
        \(blocks.joined(separator: "\n"))
            end tell
            return removed
        end run
        """
    }

    private static func isDigits(_ s: String) -> Bool { !s.isEmpty && s.allSatisfy { $0.isASCII && $0.isNumber } }
    private static func isBundleId(_ s: String) -> Bool {
        !s.isEmpty && s.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }
    }
}

/// What Remove would do in Chrome: the copies of the link Chrome holds (that a script can reach), and the one this
/// save made — the node whose `date_added` is the record's `lastSavedAt` (within a second), else the only copy, else
/// the newest.
struct ChromeRemovalPlan: Equatable {
    let copies: [BookmarkEntry]
    let target: BookmarkEntry?
    /// Copies under Mobile bookmarks, which no script reaches.
    let unreachable: Int

    var hasSeveral: Bool { copies.count > 1 }

    static func make(url: String, lastSavedAt: String?, entries: [BookmarkEntry]) -> ChromeRemovalPlan {
        let copies = ChromeBookmarkScript.nodes(for: url, in: entries)
        let saved = lastSavedAt.flatMap { ISO8601DateFormatter().date(from: $0) }
        let matched = saved.flatMap { when in
            copies.first { entry in
                entry.addedAt.flatMap { ISO8601DateFormatter().date(from: $0) }
                    .map { abs($0.timeIntervalSince(when)) <= 1 } ?? false
            }
        }
        let target = matched ?? (copies.count == 1 ? copies.first
                                                   : copies.max { ($0.addedMicros ?? 0) < ($1.addedMicros ?? 0) })
        return ChromeRemovalPlan(copies: copies, target: target,
                                 unreachable: ChromeBookmarkScript.unreachable(for: url, in: entries))
    }
}

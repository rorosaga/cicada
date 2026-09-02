import Foundation

// Mirrors of the `SafariTabs*` / `BookmarkTree*` models in
// `api/models/schemas.py` (Tasks 1–2), plus the app-side selection state
// for the device picker and the folder tree. Every decode is exact-key: the
// backend's `CamelModel` emits these names, and a mismatch is a loud test
// failure (`BrowserImportModelTests.testDecodesTheBackendShapes`) rather
// than a silently-empty picker.

/// One device in a CloudTabs.db, with its importable-tab count. `selected`
/// is only present on a sync RESULT (`SafariTabsSelectedDevice` on the
/// backend); a preview row has no selection yet, so it decodes as nil.
struct SafariTabsDevice: Codable, Hashable, Identifiable {
    let name: String
    let count: Int
    var selected: Bool? = nil
    var id: String { name }

    init(name: String, count: Int, selected: Bool? = nil) { self.name = name; self.count = count; self.selected = selected }

    /// "iPhone · 202 tabs" — the device picker row.
    static func line(_ d: SafariTabsDevice) -> String { "\(d.name) · \(d.count) \(d.count == 1 ? "tab" : "tabs")" }
}

/// `POST /sources/sync-safari-tabs?preview=true` — per-device counts, stages nothing.
struct SafariTabsPreview: Codable {
    let total: Int
    let devices: [SafariTabsDevice]
    let warnings: [String]
}

/// `POST /sources/sync-safari-tabs` — `seen` is every tab on the chosen
/// devices; `new` + `skipped` is how `ingest_batch`'s `url_index.json` dedup
/// split them (R3).
struct SafariTabsSyncResult: Codable {
    let new: Int
    let skipped: Int
    let seen: Int
    let devices: [SafariTabsDevice]
}

/// Mirror of `schemas.BookmarkFolderNode`. `id` is the path — unique by
/// construction and stable across previews of the same file — never the
/// display `name`, which R5 maps for Safari's three root folders
/// (`BookmarksBar` → "Favorites") while the path keeps the raw key the
/// backend filters on.
struct BookmarkFolderNode: Codable, Hashable, Identifiable {
    let name: String
    let path: String
    let count: Int
    let children: [BookmarkFolderNode]
    var id: String { path }
}

struct BookmarkTreeSource: Codable { let origin: String; let total: Int; let tree: BookmarkFolderNode }

/// `POST /sources/sync-bookmarks?preview=true` — one tree per browser whose
/// bytes were sent. Stages nothing.
struct BookmarkTreePreview: Codable { let sources: [BookmarkTreeSource] }

/// Which folders are ticked (R5). Stored as the MINIMAL set of paths — a
/// ticked parent implies its children — and sent to the backend as-is.
/// `""` (the root) means everything and sends no filter at all, which is
/// byte-identical to the pre-existing sync.
struct BookmarkFolderSelection: Equatable {
    var paths: Set<String>

    static let all = BookmarkFolderSelection(paths: [""])

    /// Segment-boundary prefix match, the same rule as
    /// `bookmark_sync.filter_by_folders`: "BookmarksBar" covers
    /// "BookmarksBar/Big Folder" but never "BookmarksBarMore".
    func isSelected(_ path: String) -> Bool {
        paths.contains("") || paths.contains(path) || paths.contains { $0 != "" && path.hasPrefix($0 + "/") }
    }

    mutating func toggle(_ node: BookmarkFolderNode) {
        if isSelected(node.path) {
            // Untick: drop the node and anything beneath it. If it was only
            // covered by an ancestor, the whole ancestor comes off — the
            // user is narrowing, not carving; they re-tick siblings.
            paths = paths.filter { !($0 == node.path || $0.hasPrefix(node.path + "/") || node.path.hasPrefix($0 + "/") || $0 == "") }
        } else {
            // Tick: the node subsumes any descendants already ticked, so
            // they are dropped rather than sent twice.
            paths = paths.filter { !$0.hasPrefix(node.path + "/") }
            paths.insert(node.path)
        }
    }

    /// Leaf count under the selection — a ticked node contributes its whole
    /// subtree count (the backend's `count` already includes every leaf
    /// beneath it), an unticked one only whatever is ticked below.
    func selectedCount(in tree: BookmarkFolderNode) -> Int {
        if isSelected(tree.path) { return tree.count }
        return tree.children.reduce(0) { $0 + selectedCount(in: $1) }
    }

    /// nil = everything (no `folders` key on the wire); [] = nothing selected.
    var requestFolders: [String]? { paths.contains("") ? nil : paths.sorted() }
}

/// The honest one-line result shown after an import (R8) — `new` and
/// `skipped` are the server's own tallies, never inferred client-side.
enum BrowserImportSummary {
    static func tabs(_ r: SafariTabsSyncResult) -> String {
        let newPart = r.new == 0 ? "Nothing new" : "\(r.new) new"
        return "\(newPart) · \(r.skipped) already saved · \(r.seen) \(r.seen == 1 ? "tab" : "tabs") seen"
    }
    static func bookmarks(_ r: BookmarkSyncResult) -> String {
        "\(r.new == 0 ? "Nothing new" : "\(r.new) new") · \(r.skipped) already saved"
    }
}

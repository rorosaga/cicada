import Foundation

/// The four files this Mac's browsers keep under `~/Library` that Cicada
/// imports from. **The app reads them, the backend parses the bytes (R1)**:
/// the launchd backend has no Full Disk Access and must never try — the app
/// bundle is the thing the user grants it to. Before this seam existed the
/// app called `POST /sources/sync-bookmarks` with no body, the backend tried
/// `~/Library/Safari/Bookmarks.plist` itself, and — lacking the grant —
/// silently synced nothing (`bookmark_sync.sync_from_local_files` swallows
/// the `OSError`). Reading here means a missing grant fails exactly once, in
/// the app, with the fix beside it (R9).
enum BrowserFile: CaseIterable {
    case safariTabsDb, safariTabsWal, safariBookmarks, chromeBookmarks

    /// Where the file lives, most-likely first. iCloud tabs moved into
    /// Safari's container on modern macOS; the legacy path is kept second
    /// (R2 — verified by the orchestrator against a real install, not
    /// assumed). Bookmarks.plist never moved.
    var candidatePaths: [URL] {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let container = home.appendingPathComponent("Library/Containers/com.apple.Safari/Data/Library/Safari")
        let legacy = home.appendingPathComponent("Library/Safari")
        switch self {
        case .safariTabsDb:
            return [container.appendingPathComponent("CloudTabs.db"), legacy.appendingPathComponent("CloudTabs.db")]
        case .safariTabsWal:
            return [container.appendingPathComponent("CloudTabs.db-wal"), legacy.appendingPathComponent("CloudTabs.db-wal")]
        case .safariBookmarks:
            return [legacy.appendingPathComponent("Bookmarks.plist")]
        case .chromeBookmarks:
            return [home.appendingPathComponent("Library/Application Support/Google/Chrome/Default/Bookmarks")]
        }
    }

    var displayName: String {
        switch self {
        case .safariTabsDb, .safariTabsWal: "Safari iCloud tabs"
        case .safariBookmarks: "Safari bookmarks"
        case .chromeBookmarks: "Chrome bookmarks"
        }
    }
}

/// Why a read failed, with the exact fix (R9). Only two cases matter to the
/// user: "grant Full Disk Access" and "there is nothing here yet". Anything
/// that is not provably an absence is treated as a permission problem —
/// that is the case with a fix, so it is the safer default to show.
///
/// `LocalizedError` is load-bearing, not decoration: the Feed strip's
/// "Sync now" (`ConnectedChannelsStrip.run`) does not pattern-match this
/// type — it hands whatever was thrown to `AddSourceSheet.friendlyError`,
/// which falls back to `error.localizedDescription`. Without the
/// conformance that fallback is Foundation's generic "The operation couldn't
/// be completed. (CicadaApp.BrowserFileError error 1.)", so the one place
/// R9 promised the fix would surface once showed gibberish instead (Task 3
/// review round 1, H1). The panels keep using `userMessage` directly; both
/// paths now read the same sentence.
enum BrowserFileError: Error, Equatable, LocalizedError {
    case missing(BrowserFile, [String])
    case notReadable(BrowserFile, String)

    var errorDescription: String? { userMessage }

    /// Deep link straight to the Full Disk Access pane, so the fix is one
    /// click rather than a sentence to follow.
    static let fullDiskAccessURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!

    /// `NSFileReadNoSuchFileError` (260) / POSIX `ENOENT` → `.missing`;
    /// everything else (`NSFileReadNoPermissionError` 257 included) →
    /// `.notReadable`.
    static func classify(_ error: Error, file: BrowserFile, path: String) -> BrowserFileError {
        let ns = error as NSError
        if ns.domain == NSCocoaErrorDomain && ns.code == NSFileReadNoSuchFileError { return .missing(file, [path]) }
        if ns.domain == NSPOSIXErrorDomain && ns.code == Int(ENOENT) { return .missing(file, [path]) }
        return .notReadable(file, path)
    }

    var userMessage: String {
        switch self {
        case .notReadable(let file, let path):
            return "Cicada can't read \(path) (\(file.displayName)). Allow it under System Settings → Privacy & Security → Full Disk Access → Cicada, then try again."
        case .missing(let file, _):
            switch file {
            case .safariTabsDb, .safariTabsWal:
                return "Safari hasn't synced any iCloud tabs on this Mac yet — turn on Safari in iCloud settings on both devices and wait for a sync."
            case .safariBookmarks:
                return "Safari has no Bookmarks.plist on this Mac."
            case .chromeBookmarks:
                return "Chrome isn't installed, or has no default profile bookmarks yet."
            }
        }
    }
}

/// Off-main file reads. `read` tries every candidate path in order and
/// throws only when all of them failed; a permission error on the first
/// candidate is not masked by a "missing" on the second — the permission
/// error wins, because it is the one with a fix. When every candidate is
/// simply absent the error names all of them, so the user sees where Cicada
/// looked.
enum BrowserFileReader {
    static func read(_ file: BrowserFile, candidates: [URL]? = nil) async throws -> Data {
        let urls = candidates ?? file.candidatePaths
        return try await Task.detached(priority: .userInitiated) {
            var firstPermissionError: BrowserFileError?
            for url in urls {
                do {
                    // `.uncached`: a CloudTabs.db can be tens of MB and is
                    // read once per import — no point polluting the page
                    // cache with it.
                    return try Data(contentsOf: url, options: [.uncached])
                } catch {
                    let classified = BrowserFileError.classify(error, file: file, path: url.path)
                    if case .notReadable = classified, firstPermissionError == nil { firstPermissionError = classified }
                }
            }
            throw firstPermissionError ?? BrowserFileError.missing(file, urls.map(\.path))
        }.value
    }

    /// For the WAL sidecar (R2): nil when genuinely absent, the bytes when
    /// present. Built on `read` rather than a `fileExists` pre-filter so the
    /// stat happens inside the detached task like every other touch of
    /// `~/Library` (Task 3 review round 1, L2 — the filter ran on the
    /// caller's actor, the panels' `@MainActor` task), and so a permission
    /// failure is no longer swallowed into nil: `fileExists` answers false for
    /// a path it cannot stat, which made "no WAL" and "can't read the WAL"
    /// indistinguishable. Now only `.missing` maps to nil; `.notReadable`
    /// propagates with the Full Disk Access fix, so an import can never
    /// silently proceed on a stale main db beside a WAL it was denied.
    static func readIfPresent(_ file: BrowserFile, candidates: [URL]? = nil) async throws -> Data? {
        do {
            return try await read(file, candidates: candidates)
        } catch BrowserFileError.missing {
            return nil
        }
    }
}

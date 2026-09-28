import Foundation

/// Lists the folder a `directory` or `location` page declares.
///
/// The backend only says which path the page declares (`GET /entities/{id}/location`)
/// and never touches it: under launchd its interpreter is what macOS names, so a
/// stat there made the person's Mac ask whether "python3.12" may read their folder.
/// The app reads it instead (the `~/Library` rail), so a prompt names Cicada.
///
/// Immediate children only — name, is-dir and size, never a file's bytes — directories
/// first, then names case-insensitively, hidden entries included, capped at
/// `maxEntries` with `truncated`. A symlink is reported as itself, never followed.
enum LocationLister {
    static let maxEntries = 200

    /// One child as the file system reports it, before sorting and the cap.
    struct RawEntry: Equatable, Sendable {
        let name: String
        let isDir: Bool
        let size: Int
    }

    /// The seam: tests inject outcomes (a listing, or the error the system threw).
    protocol FileSystem: Sendable {
        func contents(ofDirectory path: String) throws -> [RawEntry]
    }

    /// The real one: `FileManager`, which throws Cocoa errors wrapping the POSIX code.
    struct Disk: FileSystem {
        func contents(ofDirectory path: String) throws -> [RawEntry] {
            let url = URL(fileURLWithPath: path, isDirectory: true)
            let keys: [URLResourceKey] = [.isDirectoryKey, .isSymbolicLinkKey, .fileSizeKey]
            let children = try FileManager.default.contentsOfDirectory(
                at: url, includingPropertiesForKeys: keys, options: [])
            return children.map { child in
                let values = try? child.resourceValues(forKeys: Set(keys))
                let isLink = values?.isSymbolicLink ?? false
                let isDir = !isLink && (values?.isDirectory ?? false)
                return RawEntry(name: child.lastPathComponent,
                                isDir: isDir,
                                size: isDir ? 0 : (values?.fileSize ?? 0))
            }
        }
    }

    /// Off the main actor: a slow or network volume never stalls the card.
    static func list(_ declared: String, fileSystem: any FileSystem = Disk()) async -> LocationListing {
        await Task.detached(priority: .userInitiated) {
            listNow(declared, fileSystem: fileSystem)
        }.value
    }

    /// Synchronous and pure over the seam, for tests.
    static func listNow(_ declared: String, fileSystem: any FileSystem) -> LocationListing {
        let path = expanded(declared)
        // A relative path names no folder here; never resolve it against the app's own cwd.
        guard path.hasPrefix("/") else {
            return LocationListing(path: declared, exists: false, accessible: true, truncated: false, entries: [])
        }
        let raw: [RawEntry]
        do {
            raw = try fileSystem.contents(ofDirectory: path)
        } catch {
            if isMissing(error) {
                return LocationListing(path: declared, exists: false, accessible: true, truncated: false, entries: [])
            }
            // A refusal — the one failure whose fix (Files and Folders) the card can name —
            // or anything else the system would not let us read.
            return LocationListing(path: declared, exists: true, accessible: false, truncated: false, entries: [])
        }
        let sorted = raw.sorted { a, b in
            if a.isDir != b.isDir { return a.isDir }
            let la = a.name.lowercased(), lb = b.name.lowercased()
            return la != lb ? la < lb : a.name < b.name
        }
        let kept = sorted.prefix(maxEntries).map { LocationEntry(name: $0.name, isDir: $0.isDir, size: $0.size) }
        return LocationListing(path: declared, exists: true, accessible: true,
                               truncated: sorted.count > maxEntries, entries: Array(kept))
    }

    /// `~` and `~/…` expanded to the viewer's home; anything else as written.
    static func expanded(_ declared: String) -> String {
        let trimmed = declared.trimmingCharacters(in: .whitespacesAndNewlines)
        return (trimmed as NSString).expandingTildeInPath
    }

    /// Nothing there, or something that is not a folder: the card says it was not found.
    static func isMissing(_ error: Error) -> Bool {
        if FolderScanner.isPermissionError(error) { return false }
        return isMissingCode(error as NSError)
    }

    private static func isMissingCode(_ ns: NSError) -> Bool {
        if ns.domain == NSCocoaErrorDomain
            && (ns.code == NSFileReadNoSuchFileError || ns.code == NSFileNoSuchFileError) { return true }
        if ns.domain == NSPOSIXErrorDomain && (ns.code == Int(ENOENT) || ns.code == Int(ENOTDIR)) { return true }
        if let underlying = ns.userInfo[NSUnderlyingErrorKey] as? NSError { return isMissingCode(underlying) }
        return false
    }
}

import CryptoKit
import Foundation

/// G133 — what the APP does with a watched folder: walk it, decide which files
/// moved since the last successful sync, read those bytes, and hand them to the
/// backend in bounded batches (R-F1). The backend never opens the folder.
///
/// Change detection is `BrowserWatchPolicy`'s idea, per file: size + mtime
/// first (a `stat` is free), then a SHA-256 of the bytes only for a file whose
/// size or mtime moved — so a `touch` or a re-save of the same text costs a
/// hash, never a request.
struct FolderFileStat: Equatable, Sendable {
    let size: Int64
    let modified: Double
}

struct FolderFileSignature: Codable, Equatable, Sendable {
    let size: Int64
    let modified: Double
    let sha256: String
}

struct FolderUpload: Equatable, Sendable {
    let relpath: String
    let size: Int64
    let mtime: Double
    let sha256: String
    let data: Data
}

/// Why a folder's root could not be listed at all.
enum FolderWalkError: Equatable, Sendable {
    /// The system refused (Files and Folders, a lost grant): the fix is a setting.
    case permissionDenied
    /// Gone, unmounted, or otherwise not listable.
    case unreachable
}

/// What one walk saw, and where it could not look.
struct FolderWalk: Sendable {
    var files: [String: FolderFileStat] = [:]
    /// Relative directories the walk could not list ("" is the root itself).
    var unlisted: Set<String> = []
    var rootError: FolderWalkError?
}

struct FolderReadResult: Sendable {
    var uploads: [FolderUpload] = []
    /// Files whose stat moved but whose bytes did not: the manifest learns the
    /// new stat, nothing is posted.
    var touched: [String: FolderFileSignature] = [:]
    var unreadable: [String] = []
    var tooLarge: [String] = []
    /// Any read refused by the system (the Files & Folders grant), which is the
    /// one failure with a fix to show.
    var permissionDenied = false
}

enum FolderScanner {
    /// Mirrors `folder_source.MAX_FILE_BYTES`; a bigger file is skipped app-side.
    static let maxFileBytes: Int64 = 2_000_000
    /// Under the backend's 200 files / 8 MB (R-LS8), leaving room for base64.
    static let maxBatchFiles = 100
    static let maxBatchBytes = 6_000_000

    /// Every included regular file under `root`, by relative path, plus what the
    /// walk could NOT see. Symlinks are skipped (never followed out of the folder
    /// the person picked), and an excluded directory is not descended into.
    ///
    /// Task 6 review r1: an enumerator that cannot list the root (mode 000, a
    /// Files & Folders denial, a grant lost after a re-sign, an unmounted drive)
    /// is still non-nil and simply yields nothing. Read as "the folder is empty",
    /// that tombstoned every episode the folder had made and proposed a removal
    /// for every paper, committed as the person. So every error is recorded, and
    /// the directory it names becomes `unlisted`: nothing under it may be
    /// called deleted on this pass.
    static func walk(root: URL, rules: CompiledFolderRules) -> FolderWalk {
        let keys: [URLResourceKey] = [.isRegularFileKey, .isDirectoryKey, .isSymbolicLinkKey,
                                      .fileSizeKey, .contentModificationDateKey]
        let base = root.resolvingSymlinksInPath().path
        let prefix = base.hasSuffix("/") ? base : base + "/"
        final class Errors { var list: [(URL, Error)] = [] }
        let errors = Errors()
        guard let walker = FileManager.default.enumerator(
            at: root, includingPropertiesForKeys: keys, options: [],
            errorHandler: { url, error in errors.list.append((url, error)); return true }
        ) else { return FolderWalk(rootError: .unreachable) }
        var out = FolderWalk()
        while let url = walker.nextObject() as? URL {
            guard let values = try? url.resourceValues(forKeys: Set(keys)) else { continue }
            if values.isSymbolicLink == true { continue }
            let path = url.resolvingSymlinksInPath().path
            guard path.hasPrefix(prefix) else { continue }
            let rel = String(path.dropFirst(prefix.count))
            if values.isDirectory == true {
                if rules.excludesDirectory(rel) { walker.skipDescendants() }
                continue
            }
            guard values.isRegularFile == true, rules.included(rel) else { continue }
            out.files[rel] = FolderFileStat(size: Int64(values.fileSize ?? 0),
                                            modified: values.contentModificationDate?.timeIntervalSince1970 ?? 0)
        }
        for (url, error) in errors.list {
            let path = url.resolvingSymlinksInPath().path
            if path == base || !path.hasPrefix(prefix) {
                // The root itself, or a path we cannot place: nothing is known gone.
                out.unlisted.insert("")
                if path == base, out.rootError == nil {
                    out.rootError = isPermissionError(error) ? .permissionDenied : .unreachable
                }
            } else {
                out.unlisted.insert(String(path.dropFirst(prefix.count)))
            }
        }
        return out
    }

    /// The system refused the read: the one failure whose fix (Files and Folders)
    /// the app can name. Cocoa wraps the POSIX code, so the underlying error is
    /// checked too.
    static func isPermissionError(_ error: Error) -> Bool {
        let ns = error as NSError
        if ns.domain == NSCocoaErrorDomain && ns.code == NSFileReadNoPermissionError { return true }
        if ns.domain == NSPOSIXErrorDomain && (ns.code == Int(EPERM) || ns.code == Int(EACCES)) { return true }
        if let underlying = ns.userInfo[NSUnderlyingErrorKey] as? Error { return isPermissionError(underlying) }
        return false
    }

    /// Pure: which files need their bytes read, and which are gone. A manifest
    /// entry under an `unlisted` directory is neither — the walk could not look
    /// there, so its absence from `current` proves nothing (review r1).
    static func candidates(current: [String: FolderFileStat],
                           manifest: [String: FolderFileSignature],
                           unlisted: Set<String> = []) -> (changed: [String], deleted: [String]) {
        let changed = current.keys.filter { rel in
            guard let known = manifest[rel], let now = current[rel] else { return true }
            return known.size != now.size || known.modified != now.modified
        }.sorted()
        let deleted = manifest.keys.filter { rel in
            current[rel] == nil && !unlisted.contains { dir in dir.isEmpty || rel == dir || rel.hasPrefix(dir + "/") }
        }.sorted()
        return (changed, deleted)
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func readUploads(root: URL, changed: [String], current: [String: FolderFileStat],
                            manifest: [String: FolderFileSignature]) -> FolderReadResult {
        var result = FolderReadResult()
        for rel in changed {
            guard let stat = current[rel] else { continue }
            if stat.size > maxFileBytes {
                result.tooLarge.append(rel)
                continue
            }
            do {
                let data = try Data(contentsOf: root.appendingPathComponent(rel), options: [.uncached])
                let digest = sha256(data)
                if manifest[rel]?.sha256 == digest {
                    result.touched[rel] = FolderFileSignature(size: stat.size, modified: stat.modified, sha256: digest)
                    continue
                }
                result.uploads.append(FolderUpload(relpath: rel, size: stat.size, mtime: stat.modified,
                                                   sha256: digest, data: data))
            } catch {
                if isPermissionError(error) { result.permissionDenied = true }
                result.unreadable.append(rel)
            }
        }
        return result
    }

    static func batches(_ uploads: [FolderUpload]) -> [[FolderUpload]] {
        var out: [[FolderUpload]] = []
        var current: [FolderUpload] = []
        var bytes = 0
        for upload in uploads {
            if !current.isEmpty && (current.count >= maxBatchFiles || bytes + upload.data.count > maxBatchBytes) {
                out.append(current)
                current = []
                bytes = 0
            }
            current.append(upload)
            bytes += upload.data.count
        }
        if !current.isEmpty { out.append(current) }
        return out
    }
}

/// The last-synced signature of every file, per bank and folder, in the app's
/// own Application Support — never the bank (it is this Mac's view of the
/// folder, not memory). Keyed by bank too: the same folder registered in two
/// banks must reach both.
struct FolderManifestStore: Sendable {
    let directory: URL

    static var standard: FolderManifestStore {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return FolderManifestStore(directory: base.appendingPathComponent("Cicada/FolderWatch", isDirectory: true))
    }

    private func file(_ key: String) -> URL { directory.appendingPathComponent("\(key).json") }

    func load(_ key: String) -> [String: FolderFileSignature] {
        guard let data = try? Data(contentsOf: file(key)) else { return [:] }
        return (try? JSONDecoder().decode([String: FolderFileSignature].self, from: data)) ?? [:]
    }

    func save(_ manifest: [String: FolderFileSignature], for key: String) {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        if let data = try? JSONEncoder().encode(manifest) { try? data.write(to: file(key), options: .atomic) }
    }

    func remove(_ key: String) { try? FileManager.default.removeItem(at: file(key)) }
}

/// Where each folder is on THIS Mac. A security-scoped bookmark when the system
/// grants one (a sandboxed build); the app is unsandboxed today
/// (`VideoPlayerView.state(for:)`'s note), where a plain bookmark is what is
/// available — both survive a rename or move of the folder.
struct FolderBookmarks {
    let defaults: UserDefaults

    private func key(_ id: String) -> String { "cicada.folderWatch.bookmark.\(id)" }

    func save(_ url: URL, for id: String) {
        let data = (try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil))
            ?? (try? url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil))
        if let data { defaults.set(data, forKey: key(id)) }
    }

    func resolve(_ id: String) -> URL? {
        guard let data = defaults.data(forKey: key(id)) else { return nil }
        var stale = false
        let url = (try? URL(resolvingBookmarkData: data, options: .withSecurityScope, relativeTo: nil,
                            bookmarkDataIsStale: &stale))
            ?? (try? URL(resolvingBookmarkData: data, options: [], relativeTo: nil, bookmarkDataIsStale: &stale))
        if let url, stale { save(url, for: id) }
        return url
    }

    func remove(_ id: String) { defaults.removeObject(forKey: key(id)) }
}

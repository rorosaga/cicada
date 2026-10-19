import Foundation
import ImageIO
import SQLite3
import UniformTypeIdentifiers

/// The photo a chat's other side shares through Messages' "Share Name and Photo" (owner, 2026-10-16: "a small circle
/// with the profile picture of that chat") — the picture rung after the Contacts photo: on the Messages bubbles from
/// memory, and (2026-10-16) on the chat's own page everywhere, posted as these small bytes to the backend, which keeps
/// them outside every bank (`messages_photos`) and draws them at the page the chat's correspondent links.
///
/// **Where macOS keeps it.** `~/Library/Messages/NickNameCache/handledNicknamesKeyStore.db` holds
/// `kvtable(key TEXT = the sender's handle, value BLOB = a keyed archive of a dictionary)`; among the archive's objects
/// is the shared avatar (`<base64>-ad`), a PNG in the same folder. Measured 2026-10-19 on the current macOS: the record
/// names it as an ABSOLUTE path (`imageFilePath`, `…/Library/Messages/NickNameCache/<base64 with "/" as "_">-ad`) inside
/// a nested `NickNameImage` dictionary; an older record named the bare file. Both are accepted — the path only when its
/// parent is exactly this folder, and then only its last component is used, through the same file checks. The
/// record's `rid` (the same base64, with "/") is not turned into a file name: the path is what Messages itself wrote,
/// and the "/" → "_" rule would be a guess at its encoding.
///
/// **How it is read.** By the APP (which already holds Full Disk Access for `~/Library/Messages`), only for the handles
/// of conversations the person ticked, and never in place: the key store and its `-wal`/`-shm` are copied into a
/// private temporary folder and the copy is queried, so Messages' own files are never written, locked or checkpointed.
/// The archive is read as a property list — its `$objects` are scanned for a file name, no class is ever instantiated
/// (`NSKeyedUnarchiver` would build whatever classes an archive names). A name is used only when it is a plain file
/// name ending in `-ad` that resolves to a regular file inside the folder, under `maxFileBytes`; the image is made
/// `maxPixels` small here. Nothing is written to a bank or kept on disk by the app; the watcher posts the small PNG of
/// each ticked chat to the backend's picture cache (`PUT /sources/messages/photos`) and keeps it in memory.
enum MessagesSharedPhotos {
    static let keyStore = "handledNicknamesKeyStore.db"
    static let avatarSuffix = "-ad"
    /// The shared avatars measured on the owner's Mac are 1024 × 1024 PNGs; past this a file is not one of them.
    static let maxFileBytes = 8 * 1024 * 1024
    static let maxArchiveBytes = 256 * 1024
    static let maxPixels = 128

    static let folderName = "NickNameCache"
    static var standardFolder: URL { MessagesWatcher.messagesFolder.appendingPathComponent(folderName, isDirectory: true) }

    /// The shared photo for each of `handles` that has one, keyed by handle, as small PNG bytes. Empty when the folder
    /// is missing or unreadable — the bubble then falls to the monogram.
    static func photos(for handles: [String], folder: URL = standardFolder) -> [String: Data] {
        photosIfReadable(for: handles, folder: folder) ?? [:]
    }

    /// As `photos`, but nil when the key store is there and could not be read (Full Disk Access revoked, a copy that
    /// failed): "could not look" is never posted as "shares no photo", which would remove a page's picture. A missing
    /// key store is a definite empty answer — nobody shared a photo on this Mac.
    static func photosIfReadable(for handles: [String], folder: URL = standardFolder) -> [String: Data]? {
        let wanted = Set(handles.filter { !$0.isEmpty })
        guard !wanted.isEmpty else { return [:] }
        guard let names = avatarNamesIfReadable(for: wanted, folder: folder) else { return nil }
        var out: [String: Data] = [:]
        for (handle, name) in names {
            if let file = avatarFile(named: name, in: folder), let small = downsized(file) { out[handle] = small }
        }
        return out
    }

    /// The avatar file name each handle's record names, read from a private copy of the key store.
    static func avatarNames(for handles: Set<String>, folder: URL) -> [String: String] {
        avatarNamesIfReadable(for: handles, folder: folder) ?? [:]
    }

    /// nil when the key store exists but cannot be read or queried; empty when there is none.
    static func avatarNamesIfReadable(for handles: Set<String>, folder: URL) -> [String: String]? {
        let fm = FileManager.default
        let source = folder.appendingPathComponent(keyStore)
        guard fm.fileExists(atPath: source.path) else { return [:] }
        guard fm.isReadableFile(atPath: source.path) else { return nil }
        let scratch = fm.temporaryDirectory.appendingPathComponent("cicada-nicknames-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: scratch) }
        do {
            try fm.createDirectory(at: scratch, withIntermediateDirectories: true)
            for suffix in ["", "-wal", "-shm"] {
                let from = URL(fileURLWithPath: source.path + suffix)
                guard fm.fileExists(atPath: from.path) else { continue }
                try fm.copyItem(at: from, to: scratch.appendingPathComponent(keyStore + suffix))
            }
        } catch {
            return nil
        }
        var db: OpaquePointer?
        // The copy is ours: opened read-write so SQLite can read its WAL; closing it may fold that WAL into the copy,
        // never into Messages' file.
        guard sqlite3_open_v2(scratch.appendingPathComponent(keyStore).path, &db,
                              SQLITE_OPEN_READWRITE | SQLITE_OPEN_NOMUTEX, nil) == SQLITE_OK else {
            sqlite3_close(db)
            return nil
        }
        defer { sqlite3_close(db) }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT value FROM kvtable WHERE key = ?1", -1, &stmt, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(stmt) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        var out: [String: String] = [:]
        for handle in handles.sorted() {
            sqlite3_reset(stmt)
            sqlite3_clear_bindings(stmt)
            sqlite3_bind_text(stmt, 1, handle, -1, transient)
            guard sqlite3_step(stmt) == SQLITE_ROW, sqlite3_column_type(stmt, 0) == SQLITE_BLOB else { continue }
            let count = Int(sqlite3_column_bytes(stmt, 0))
            guard count > 0, count <= maxArchiveBytes, let bytes = sqlite3_column_blob(stmt, 0) else { continue }
            if let name = avatarName(inArchive: Data(bytes: bytes, count: count), folder: folder) { out[handle] = name }
        }
        return out
    }

    /// The avatar file name a record's keyed archive names: the first `$objects` string that is a plain file name
    /// ending in `-ad`, or an absolute path to one directly inside `folder` (`folderFileName`). Read as a property
    /// list only — nothing is unarchived.
    static func avatarName(inArchive data: Data, folder: URL = standardFolder) -> String? {
        guard let plist = try? PropertyListSerialization.propertyList(from: data, options: [], format: nil)
                as? [String: Any],
              let objects = plist["$objects"] as? [Any] else { return nil }
        return objects.lazy.compactMap { $0 as? String }
            .compactMap { isAvatarName($0) ? $0 : folderFileName($0, in: folder) }.first
    }

    /// An absolute path's file name, only when the path's parent is exactly `folder` (the macOS record's
    /// `imageFilePath`). A path anywhere else — another folder, a `..` that climbs out, a relative path — is nil.
    static func folderFileName(_ path: String, in folder: URL) -> String? {
        guard path.hasPrefix("/"), path.hasSuffix(avatarSuffix), path.count <= 1024, !path.contains("\0") else { return nil }
        let url = URL(fileURLWithPath: path, isDirectory: false)
        let name = url.lastPathComponent
        guard isAvatarName(name), url.standardizedFileURL.lastPathComponent == name,
              url.deletingLastPathComponent().resolvingSymlinksInPath().standardizedFileURL.path
                == folder.resolvingSymlinksInPath().standardizedFileURL.path
        else { return nil }
        return name
    }

    static func isAvatarName(_ name: String) -> Bool {
        name.hasSuffix(avatarSuffix) && name.count > avatarSuffix.count && name.count <= 255
            && !name.contains("/") && !name.contains("\0") && !name.hasPrefix(".")
    }

    /// The file a name points at, only when it is a regular file (never a link) directly inside the folder.
    static func avatarFile(named name: String, in folder: URL) -> URL? {
        guard isAvatarName(name) else { return nil }
        let file = folder.appendingPathComponent(name, isDirectory: false)
        guard let values = try? file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
              values.isRegularFile == true, values.isSymbolicLink != true,
              let size = values.fileSize, size > 0, size <= maxFileBytes,
              file.resolvingSymlinksInPath().deletingLastPathComponent().standardizedFileURL.path
                == folder.resolvingSymlinksInPath().standardizedFileURL.path
        else { return nil }
        return file
    }

    /// The image made at most `maxPixels` on its longer side, as PNG; nil for anything that is not an image.
    static func downsized(_ file: URL) -> Data? {
        guard let source = CGImageSourceCreateWithURL(file as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetCount(source) > 0,
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceCreateThumbnailWithTransform: true,
                  kCGImageSourceThumbnailMaxPixelSize: maxPixels,
              ] as CFDictionary)
        else { return nil }
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(out, UTType.png.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, image, nil)
        return CGImageDestinationFinalize(dest) ? out as Data : nil
    }
}

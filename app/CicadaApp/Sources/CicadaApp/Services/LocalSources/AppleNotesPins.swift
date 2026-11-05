import Darwin
import Foundation
import SQLite3

/// ROR-15 (owner 2026-11-05: "having a note pinned is important, normally has a reason"). Notes' scripting dictionary has
/// no pin property, so the pin is read from Notes' own store: a COPY of `NoteStore.sqlite` with its `-wal` (the Chrome
/// history rule), one query for `Z_PK` alone, where the note is pinned and not locked. Never a title, a snippet, a body or
/// `ZICNOTEDATA`; a locked note's pin is not read (G234), and only ids already in the unlocked dump leave the app.
///
/// A note's AppleScript id is the Core Data `NSManagedObjectID` URI, `x-coredata://<store uuid>/ICNote/p<Z_PK>`: the
/// entity name, then `p` (a permanent id) and the row's primary key. A row that does not map is simply not pinned.
///
/// Only with Full Disk Access the app already holds: no prompt, no setup step, no copy asking for it. Without it, or on
/// any failure, the answer is nil and the sync goes on as it did — nil is "could not tell" (the backend leaves every pin as
/// it was), never "nothing is pinned".
enum AppleNotesPins {
    static let storeComponents = ["Library", "Group Containers", "group.com.apple.notes", "NoteStore.sqlite"]
    /// Only the app's own grant can open it; opening it for reading asks the person nothing (TCC denies Full Disk Access
    /// silently, where a protected folder's first read would prompt).
    static let accessProbe = URL(fileURLWithPath: "/Library/Application Support/com.apple.TCC/TCC.db")
    /// A bigger store is left alone rather than copied every two hours.
    static let sizeCap: Int64 = 1_000_000_000
    static let timeout: TimeInterval = 10

    static let table = "ZICCLOUDSYNCINGOBJECT"
    static let columns = ["Z_PK", "ZISPINNED", "ZISPASSWORDPROTECTED"]
    static let query = "SELECT Z_PK FROM \(table) WHERE ZISPINNED = 1 AND ZISPASSWORDPROTECTED = 0"

    static func store(home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)) -> URL {
        storeComponents.reduce(home) { $0.appendingPathComponent($1) }
    }

    /// Whether this process may read what Full Disk Access guards. `open(2)` only: nothing is asked.
    static func hasFullDiskAccess(probe: URL = accessProbe) -> Bool {
        let fd = open(probe.path, O_RDONLY)
        if fd >= 0 { close(fd); return true }
        return false
    }

    /// `x-coredata://<uuid>/ICNote/p12` -> 12. Nil for anything else: another entity, a temporary id, no number.
    static func rowKey(_ noteId: String) -> Int64? {
        guard noteId.hasPrefix("x-coredata://") else { return nil }
        let parts = noteId.dropFirst("x-coredata://".count).split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[1] == "ICNote", parts[2].hasPrefix("p"), parts[2].count > 1 else { return nil }
        let digits = parts[2].dropFirst()
        guard digits.allSatisfy(\.isASCII), digits.allSatisfy(\.isNumber) else { return nil }
        return Int64(digits)
    }

    /// The ids of the dump's notes, in order, for the pins to be matched against.
    static func ids(inDump dump: String) -> [String] {
        dump.components(separatedBy: AppleNotesReader.recordSeparator).compactMap { record in
            let id = record.components(separatedBy: AppleNotesReader.fieldSeparator)[0]
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return id.isEmpty ? nil : id
        }
    }

    /// Which of these notes are pinned, given the pinned rows' keys. Pure.
    static func pinned(among ids: [String], keys: Set<Int64>) -> [String] {
        ids.filter { id in rowKey(id).map(keys.contains) ?? false }
    }

    /// The pinned rows' primary keys from a store (already a plain file), or nil when the table or a column is not there.
    static func keys(in store: URL) -> Set<Int64>? {
        guard let db = try? SQLiteReadOnly(url: store) else { return nil }
        defer { db.close() }
        guard db.columns(of: table, whitelist: columns).count == columns.count,
              let rows = try? db.query(query, binds: []) else { return nil }
        return Set(rows.compactMap { ($0["Z_PK"] as? NSNumber)?.int64Value })
    }

    /// Copy the store and its `-wal`, fold it into the copy, read, delete the copy. Nil on any failure.
    static func snapshotKeys(store: URL) -> Set<Int64>? {
        let fm = FileManager.default
        guard let size = (try? fm.attributesOfItem(atPath: store.path))?[.size] as? NSNumber,
              size.int64Value <= sizeCap else { return nil }
        let scratch = fm.temporaryDirectory.appendingPathComponent("cicada-notes-pins-\(UUID().uuidString)", isDirectory: true)
        guard (try? fm.createDirectory(at: scratch, withIntermediateDirectories: true)) != nil else { return nil }
        defer { try? fm.removeItem(at: scratch) }
        let target = scratch.appendingPathComponent(store.lastPathComponent)
        guard (try? fm.copyItem(at: store, to: target)) != nil else { return nil }
        for suffix in ["-wal", "-shm"] {
            let side = URL(fileURLWithPath: store.path + suffix)
            if fm.fileExists(atPath: side.path) { try? fm.copyItem(at: side, to: URL(fileURLWithPath: target.path + suffix)) }
        }
        AppleBooksStore.settle(target)
        return keys(in: target)
    }

    /// The notes among `ids` the person pinned, or nil when that could not be told (no Full Disk Access, no store, a
    /// failure, or longer than `timeout`). Off the main actor; never throws and never stalls the sync that asked.
    static func read(ids: [String], home: URL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true),
                     hasAccess: @escaping @Sendable () -> Bool = { hasFullDiskAccess() },
                     snapshot: @escaping @Sendable (URL) -> Set<Int64>? = { snapshotKeys(store: $0) },
                     timeout: TimeInterval = timeout) async -> [String]? {
        guard !ids.isEmpty else { return nil }
        let location = store(home: home)
        let answer = OneAnswer()
        return await withCheckedContinuation { (continuation: CheckedContinuation<[String]?, Never>) in
            // Unstructured on purpose: a copy that outlasts the timeout finishes and cleans up on its own, while the
            // sync that asked has already gone on without a pin.
            Task.detached(priority: .utility) {
                let result: [String]? = hasAccess() ? snapshot(location).map { pinned(among: ids, keys: $0) } : nil
                if answer.take() { continuation.resume(returning: result) }
            }
            Task.detached {
                try? await Task.sleep(for: .seconds(timeout))
                if answer.take() { continuation.resume(returning: nil) }
            }
        }
    }

    /// The first of two racers to ask gets true.
    private final class OneAnswer: @unchecked Sendable {
        private let lock = NSLock()
        private var taken = false
        func take() -> Bool {
            lock.lock(); defer { lock.unlock() }
            if taken { return false }
            taken = true
            return true
        }
    }
}

import AppKit
import Foundation

/// G197 layer c (2026-11-04) — the export someone is waiting for, picked up the moment it lands in Downloads.
///
/// claude.ai, the Claude desktop app's chats and ChatGPT keep their history on the vendor's servers and run no hook,
/// so the one way in that needs no model's cooperation is the person's own export (G105). Cicada already waits on one
/// (`ExportWaitStore`, R-IB22); this is the last step: while a wait is open, a new `.zip` at the top of the person's
/// Downloads folder whose member NAMES are that vendor's export is handed to the one intake
/// (`IntakeRouter.accept(urls:from: .reminder(vendor))`), whose preview and Import are unchanged — so a conversation
/// the remote connector relayed is upgraded in place (ruling 32), and one already imported is `unchanged`.
///
/// What is read, and when: only while a wait is open; only the folder's top-level names, sizes and dates; and of a
/// new `.zip`, only its central directory (member names, never a member's bytes). Nothing is sent anywhere until the
/// file is recognised, and then only through the intake the person would have dropped it on. No setting: the
/// person's own *Remind me* is the ask, and *Stop waiting* (or the export arriving) ends it.
enum ExportArrivals {
    /// How long a new zip must keep the same size before it is read: a browser renames a finished download into
    /// place, so this is a guard against a copy still being written, not the main signal.
    static let settle: Duration = .milliseconds(1500)
    /// How many looks a growing file gets before it is left for the next folder event.
    static let maxLooks = 40

    /// The vendor whose export these member names are, by the files each vendor's export carries (`intake.py`'s
    /// `SKIPPED_MEMBERS` names the same ones): Claude's `conversations.json` beside `users.json`; ChatGPT's beside
    /// `user.json`, `chat.html` or `message_feedback.json`; Google Takeout's Gemini Apps activity. Anything else —
    /// or both Claude's and ChatGPT's account file at once — is nobody's, and is never read further.
    static func vendor(members: [String]) -> ChatVendor? {
        var names = Set<String>()
        var gemini = false
        for member in members {
            let low = member.lowercased()
            names.insert((low as NSString).lastPathComponent)
            if low.contains("my activity/gemini apps/") { gemini = true }
        }
        let conversations = names.contains("conversations.json")
        let claude = conversations && names.contains("users.json")
        let chatgpt = conversations && (names.contains("user.json") || names.contains("chat.html")
                                        || names.contains("message_feedback.json"))
        switch (claude, chatgpt) {
        case (true, false): return .claude
        case (false, true): return .chatgpt
        case (true, true): return nil
        case (false, false): return gemini ? .gemini : nil
        }
    }
}

/// One top-level entry of the watched folder: what the tracker compares between looks. Never a file's contents.
struct FolderEntry: Equatable, Hashable {
    let name: String
    let size: Int64
    let modified: Date
}

/// The pure half of the watch: which new zips have settled. The baseline is every zip present when the wait began,
/// so an old export in Downloads is never offered; a file is offered once, whatever it turned out to be.
struct ArrivalTracker {
    private(set) var seen: Set<FolderEntry>
    private(set) var pending: [String: (size: Int64, looks: Int)] = [:]

    init(baseline: [FolderEntry]) { seen = Set(baseline.filter(Self.isZip)) }

    static func isZip(_ e: FolderEntry) -> Bool { (e.name as NSString).pathExtension.lowercased() == "zip" }

    /// One look at the folder: the zips that are new and kept their size since the last look. A zip still growing
    /// stays pending (dropped after `ExportArrivals.maxLooks`); one that vanished is forgotten.
    mutating func look(_ listing: [FolderEntry]) -> [FolderEntry] {
        let zips = listing.filter(Self.isZip)
        let names = Set(zips.map(\.name))
        pending = pending.filter { names.contains($0.key) }
        var ready: [FolderEntry] = []
        for entry in zips where !seen.contains(entry) {
            if let last = pending[entry.name], last.size == entry.size, entry.size > 0 {
                pending[entry.name] = nil
                ready.append(entry)
            } else {
                let looks = (pending[entry.name]?.looks ?? 0) + 1
                if looks > ExportArrivals.maxLooks {
                    pending[entry.name] = nil
                    seen.insert(entry)
                } else {
                    pending[entry.name] = (entry.size, looks)
                }
            }
        }
        return ready.sorted { $0.name < $1.name }
    }

    /// Offered (or read and found to be nobody's export): never looked at again.
    mutating func done(_ entry: FolderEntry) { seen.insert(entry) }

    /// The intake was busy: settled already, so it is ready again at the next look — which the pending entry keeps
    /// coming while the import before it lands.
    mutating func retry(_ entry: FolderEntry) { pending[entry.name] = (entry.size, 1) }

    var waitingOnGrowth: Bool { !pending.isEmpty }
}

/// A zip's member names from its central directory — the end of the file only, never a member's bytes. Handles
/// zip64 (an export over 4 GB, or with more than 65,535 members). `nil` for anything that is not a well-formed zip.
enum ZipMembers {
    static let maxDirectoryBytes = 32 << 20
    static let maxNames = 50_000

    static func names(of url: URL) -> [String]? {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }
        guard let size = try? handle.seekToEnd(), size >= 22 else { return nil }
        let tailLength = min(size, 22 + 65_535)
        guard let tail = read(handle, at: size - tailLength, count: Int(tailLength)) else { return nil }
        guard let eocd = lastIndex(of: 0x0605_4b50, in: tail) else { return nil }
        var entries = UInt64(u16(tail, eocd + 10))
        var dirSize = UInt64(u32(tail, eocd + 12))
        var dirOffset = UInt64(u32(tail, eocd + 16))
        if entries == 0xFFFF || dirSize == 0xFFFF_FFFF || dirOffset == 0xFFFF_FFFF {
            // The zip64 locator sits just before the classic record and points at the zip64 one.
            let eocdAbsolute = size - tailLength + UInt64(eocd)
            guard eocdAbsolute >= 20, let locator = read(handle, at: eocdAbsolute - 20, count: 20),
                  u32(locator, 0) == 0x0706_4b50 else { return nil }
            let recordAt = u64(locator, 8)
            guard recordAt <= size, size - recordAt >= 56, let record = read(handle, at: recordAt, count: 56),
                  u32(record, 0) == 0x0606_4b50 else { return nil }
            entries = u64(record, 32)
            dirSize = u64(record, 40)
            dirOffset = u64(record, 48)
        }
        // Every bound below is checked by subtraction from a value already known to be smaller, never by adding two
        // values read from the file: a crafted zip64 offset near `UInt64.max` must answer nil, not trap.
        guard dirSize <= UInt64(maxDirectoryBytes), dirOffset <= size, dirSize <= size - dirOffset,
              let dir = read(handle, at: dirOffset, count: Int(dirSize)) else { return nil }
        var names: [String] = []
        var at = 0
        while names.count < min(Int(min(entries, UInt64(Int.max))), maxNames) {
            // `at` ≤ the directory's length (≤ 32 MB) and each length ≤ 65,535, so these sums cannot overflow an Int.
            guard dir.count - at >= 46, u32(dir, at) == 0x0201_4b50 else { return nil }
            let nameLength = Int(u16(dir, at + 28)), extra = Int(u16(dir, at + 30)), comment = Int(u16(dir, at + 32))
            guard dir.count - at - 46 >= nameLength else { return nil }
            let raw = dir.subdata(in: (at + 46)..<(at + 46 + nameLength))
            names.append(String(data: raw, encoding: .utf8) ?? String(decoding: raw, as: UTF8.self))
            at += 46 + nameLength + extra + comment
        }
        return names
    }

    private static func read(_ handle: FileHandle, at offset: UInt64, count: Int) -> Data? {
        guard (try? handle.seek(toOffset: offset)) != nil, let data = try? handle.read(upToCount: count),
              data.count == count else { return nil }
        return data
    }

    private static func lastIndex(of signature: UInt32, in data: Data) -> Int? {
        guard data.count >= 22 else { return nil }
        var i = data.count - 22
        while i >= 0 {
            if u32(data, i) == signature { return i }
            i -= 1
        }
        return nil
    }

    private static func u16(_ d: Data, _ i: Int) -> UInt16 {
        let base = d.startIndex
        return UInt16(d[base + i]) | UInt16(d[base + i + 1]) << 8
    }
    private static func u32(_ d: Data, _ i: Int) -> UInt32 {
        UInt32(u16(d, i)) | UInt32(u16(d, i + 2)) << 16
    }
    private static func u64(_ d: Data, _ i: Int) -> UInt64 {
        UInt64(u32(d, i)) | UInt64(u32(d, i + 4)) << 32
    }
}

/// The live half: one FSEvents watch on the top of Downloads, open only while an export the person asked about IN
/// THIS RUN is awaited in the memory now open (so a wait from an earlier launch never raises macOS's Downloads prompt
/// at launch). The app owns one for its lifetime (`CicadaApp`) and calls `sync` when the waits or the memory change.
@MainActor
final class ExportArrivalWatcher {
    /// The vendors awaited now (pruned, this memory, asked this run) — read at every look; empty stops the watch.
    var waitedVendors: () -> Set<ChatVendor> = { [] }
    /// When the last of those waits expires; `nil` when there is none. The watch closes at that moment by itself.
    var waitsUntil: () -> Date? = { nil }
    /// A recognised export: hand it to the intake. `false` means it is busy (an import, or a preview the person has
    /// open) and the file should be offered again at the next look.
    var deliver: (URL, ChatVendor) -> Bool = { _, _ in true }
    /// macOS refused to list Downloads: said once per attempt to open the watch.
    var onRefused: () -> Void = {}

    private let folder: URL?
    private let sleep: @Sendable (Duration) async throws -> Void
    private let expirySleep: @Sendable (Duration) async throws -> Void
    private let now: () -> Date
    private var watch: FSEventsWatch?
    private var tracker: ArrivalTracker?
    private var looking: Task<Void, Never>?
    private var expiry: Task<Void, Never>?
    /// Bumped by every open and close, so a look that awaited across a `stop()` never writes its state back.
    private var epoch = 0

    init(folder: URL? = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first,
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
         expirySleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
         now: @escaping () -> Date = Date.init) {
        self.folder = folder
        self.sleep = sleep
        self.expirySleep = expirySleep
        self.now = now
    }

    var isWatching: Bool { tracker != nil }

    /// Open the watch while a wait is, close it when none is (or the last one has expired). The baseline is taken
    /// here, so the listing — and macOS's one Downloads prompt, if it asks — follows the person's own tap.
    func sync() {
        guard let until = waitsUntil(), until > now(), !waitedVendors().isEmpty else {
            stop()
            return
        }
        if tracker == nil, let folder {
            guard let baseline = Self.listing(folder) else {
                onRefused()
                return
            }
            epoch &+= 1
            tracker = ArrivalTracker(baseline: baseline)
            watch = FSEventsWatch(path: folder.path) { [weak self] in self?.schedule() }
        }
        guard tracker != nil else { return }
        expiry?.cancel()
        let left = until.timeIntervalSince(now())
        expiry = Task { [weak self, expirySleep] in
            guard (try? await expirySleep(.milliseconds(Int64(left * 1000) + 1))) != nil, !Task.isCancelled else { return }
            self?.sync()
        }
    }

    func stop() {
        epoch &+= 1
        watch?.stop()
        watch = nil
        tracker = nil
        looking?.cancel()
        looking = nil
        expiry?.cancel()
        expiry = nil
    }

    private func schedule() {
        guard looking == nil else { return }
        looking = Task { [weak self] in
            guard let self else { return }
            try? await self.sleep(ExportArrivals.settle)
            guard !Task.isCancelled else { return }
            await self.lookOnce()
            self.looking = nil
            if self.tracker?.waitingOnGrowth == true { self.schedule() }
        }
    }

    /// One look: nothing awaited any more closes the watch before anything is read; otherwise list the folder and
    /// read the central directory of each zip that has settled. Internal for tests.
    func lookOnce() async {
        guard let folder, var tracker else { return }
        let vendors = waitedVendors()
        guard !vendors.isEmpty, (waitsUntil() ?? .distantPast) > now() else {
            stop()
            return
        }
        guard let listing = Self.listing(folder) else { return }
        let started = epoch
        let ready = tracker.look(listing)
        for entry in ready {
            let url = folder.appendingPathComponent(entry.name)
            let members = await Task.detached(priority: .utility) { ZipMembers.names(of: url) }.value
            guard epoch == started else { return }
            guard let vendor = members.flatMap(ExportArrivals.vendor(members:)), vendors.contains(vendor) else {
                tracker.done(entry)
                continue
            }
            if deliver(url, vendor) { tracker.done(entry) } else { tracker.retry(entry) }
            guard epoch == started else { return }
        }
        self.tracker = tracker
    }

    /// The folder's top level: names, sizes and dates only. `nil` when it cannot be listed (macOS said no).
    static func listing(_ folder: URL) -> [FolderEntry]? {
        let keys: [URLResourceKey] = [.fileSizeKey, .contentModificationDateKey, .isRegularFileKey]
        guard let urls = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: keys,
                                                                      options: [.skipsHiddenFiles]) else { return nil }
        return urls.compactMap { url in
            guard let v = try? url.resourceValues(forKeys: Set(keys)), v.isRegularFile == true else { return nil }
            return FolderEntry(name: url.lastPathComponent, size: Int64(v.fileSize ?? 0),
                               modified: v.contentModificationDate ?? .distantPast)
        }
    }
}

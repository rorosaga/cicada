import Foundation

/// One open tab group as Chrome's session file describes it (round 4, G160 first slice).
struct ChromiumTabGroup: Equatable, Sendable {
    /// Chrome's per-session token, hex — never stable across a restart (R-SR4).
    let key: String
    var title: String
    /// A `TabGroupColor` word.
    var color: String
    var collapsed: Bool
    var savedGuid: String?
    var tabs: [ChromiumTab]
}

struct ChromiumTab: Equatable, Sendable {
    let title: String
    let url: String
}

enum ChromiumSessionError: Error, Equatable, LocalizedError {
    case notASessionFile
    /// 5 is Chrome's Keychain-encrypted file (R-SR3) — refused, never decoded.
    case unsupportedVersion(Int32)
    /// Chrome was still writing the file's initial state; the reader tries the file before it.
    case noMarker
    case tooLarge

    /// A card's Sync now shows `localizedDescription` (`AddSourceSheet.friendlyError`'s fallback) — without this it
    /// read "The operation couldn't be completed" (the `BrowserFileError` precedent, Task 3 review round 1, H1).
    var errorDescription: String? { Copy.tabGroupsUnreadable }
}

/// Round 4 (G160; decisions addendum 3) — Chrome's SNSS session file, read for its OPEN tab groups and nothing else.
///
/// **The format, from Chromium's source (`main`, 2026-09-24).** A header `{int32 0x53534E53 ("SNSS"), int32 version}`
/// (`command_storage_backend.cc`: 3 is the clear file with an initial-state marker, 5 is encrypted), then records
/// `{uint16 size, uint8 id, size − 1 bytes}`. Commands read (`session_service_commands.cc`): 0 `SetTabWindow`
/// (`id_type[2]`: window, tab); 2 `SetTabIndexInWindow` and 7 `SetSelectedNavigationIndex` (`IDAndIndexPayload
/// {int32 id; int32 index}`); 6 `UpdateTabNavigation`, a pickle of tab, index, url, title — then the encoded page
/// state, which is **never read** (it is the page's own contents, R-SR6); 16 / 17 `TabClosed` / `WindowClosed`
/// (`ClosedPayload {int32 id; int64 close_time}`); 25 `SetTabGroup` (`TabGroupPayload {int32 tab_id; {uint64 high;
/// uint64 low} token; bool has_group}` — natural alignment puts them at 0, 8, 16 and 24); and 27
/// `SetTabGroupMetadata2`, a pickle of the token (two uint64, `base/token.cc`), the string16 title, the uint32 colour,
/// then `is_collapsed` (M88) and `is_saved` + `saved_guid` (M113). **A short pickle is read, never refused** — what is
/// there is kept and the rest defaults, the rule Chrome's own reader follows. A torn last record (Chrome mid-append)
/// ends the read and what came before stands. Incognito windows are never written to these files at all.
enum ChromiumSessionParser {
    static let signature: UInt32 = 0x53534E53
    static let clearVersion: Int32 = 3
    static let markerCommand: UInt8 = 255
    static let maxBytes = 32 * 1024 * 1024

    enum Command {
        static let setTabWindow: UInt8 = 0
        static let setTabIndexInWindow: UInt8 = 2
        static let updateTabNavigation: UInt8 = 6
        static let setSelectedNavigationIndex: UInt8 = 7
        static let tabClosed: UInt8 = 16
        static let windowClosed: UInt8 = 17
        static let setTabGroup: UInt8 = 25
        static let setTabGroupMetadata2: UInt8 = 27
    }

    static func parse(_ data: Data) throws -> [ChromiumTabGroup] {
        guard data.count <= maxBytes else { throw ChromiumSessionError.tooLarge }
        let bytes = [UInt8](data)
        guard bytes.count >= 8, le32(bytes, 0) == signature else { throw ChromiumSessionError.notASessionFile }
        let version = Int32(bitPattern: le32(bytes, 4))
        guard version == clearVersion else { throw ChromiumSessionError.unsupportedVersion(version) }
        var state = SessionState()
        var sawMarker = false
        var offset = 8
        while offset + 2 <= bytes.count {
            let size = Int(le16(bytes, offset))
            offset += 2
            guard size >= 1, offset + size <= bytes.count else { break }
            let id = bytes[offset]
            let contents = Array(bytes[(offset + 1)..<(offset + size)])
            offset += size
            if id == markerCommand { sawMarker = true } else { state.apply(id, contents) }
        }
        guard sawMarker else { throw ChromiumSessionError.noMarker }
        return state.groups()
    }

    static func le16(_ b: [UInt8], _ i: Int) -> UInt16 { UInt16(b[i]) | UInt16(b[i + 1]) << 8 }
    static func le32(_ b: [UInt8], _ i: Int) -> UInt32 {
        UInt32(b[i]) | UInt32(b[i + 1]) << 8 | UInt32(b[i + 2]) << 16 | UInt32(b[i + 3]) << 24
    }
    static func le64(_ b: [UInt8], _ i: Int) -> UInt64 { UInt64(le32(b, i)) | UInt64(le32(b, i + 4)) << 32 }
    static func int32(_ b: [UInt8], _ i: Int) -> Int32 { Int32(bitPattern: le32(b, i)) }
    static func tokenHex(high: UInt64, low: UInt64) -> String { String(format: "%016llx%016llx", high, low) }
}

/// `base::Pickle`'s reader: a uint32 payload size, then 4-byte-aligned fields. Every read returns nil past the end —
/// how a short (older) pickle ends.
struct PickleReader {
    private let bytes: [UInt8]
    private var position = 4
    private let end: Int

    init?(_ contents: [UInt8]) {
        guard contents.count >= 4 else { return nil }
        let payload = Int(ChromiumSessionParser.le32(contents, 0))
        guard payload <= contents.count - 4 else { return nil }
        bytes = contents
        end = 4 + payload
    }

    private static func aligned(_ n: Int) -> Int { (n + 3) & ~3 }

    mutating func readUInt32() -> UInt32? {
        guard position + 4 <= end else { return nil }
        defer { position += 4 }
        return ChromiumSessionParser.le32(bytes, position)
    }
    mutating func readInt32() -> Int32? { readUInt32().map { Int32(bitPattern: $0) } }
    mutating func readUInt64() -> UInt64? {
        guard position + 8 <= end else { return nil }
        defer { position += 8 }
        return ChromiumSessionParser.le64(bytes, position)
    }
    mutating func readBool() -> Bool? { readInt32().map { $0 != 0 } }
    mutating func readString() -> String? {
        guard let n = readInt32(), n >= 0, position + Int(n) <= end else { return nil }
        let text = String(decoding: bytes[position..<(position + Int(n))], as: UTF8.self)
        position += Self.aligned(Int(n))
        return text
    }
    mutating func readString16() -> String? {
        guard let n = readInt32(), n >= 0, position + Int(n) * 2 <= end else { return nil }
        let units = (0..<Int(n)).map { ChromiumSessionParser.le16(bytes, position + 2 * $0) }
        position += Self.aligned(Int(n) * 2)
        return String(decoding: units, as: UTF16.self)
    }
}

/// The session replayed: each command updates the state it names; only groups with an open member tab survive.
private struct SessionState {
    var navigations: [Int32: [Int32: ChromiumTab]] = [:]
    var selected: [Int32: Int32] = [:]
    var tabWindow: [Int32: Int32] = [:]
    var tabIndex: [Int32: Int32] = [:]
    var tabGroup: [Int32: String] = [:]
    var closedTabs: Set<Int32> = []
    var closedWindows: Set<Int32> = []
    var groupsByKey: [String: ChromiumTabGroup] = [:]
    var groupOrder: [String] = []

    mutating func apply(_ id: UInt8, _ c: [UInt8]) {
        typealias P = ChromiumSessionParser
        switch id {
        case P.Command.setTabWindow where c.count >= 8:
            tabWindow[P.int32(c, 4)] = P.int32(c, 0)
        case P.Command.setTabIndexInWindow where c.count >= 8:
            tabIndex[P.int32(c, 0)] = P.int32(c, 4)
        case P.Command.setSelectedNavigationIndex where c.count >= 8:
            selected[P.int32(c, 0)] = P.int32(c, 4)
        case P.Command.tabClosed where c.count >= 4:
            closedTabs.insert(P.int32(c, 0))
        case P.Command.windowClosed where c.count >= 4:
            closedWindows.insert(P.int32(c, 0))
        case P.Command.updateTabNavigation:
            guard var r = PickleReader(c), let tab = r.readInt32(), let index = r.readInt32(),
                  let url = r.readString(), let title = r.readString16() else { return }
            navigations[tab, default: [:]][index] = ChromiumTab(title: title, url: url)
        case P.Command.setTabGroup where c.count >= 25:
            let tab = P.int32(c, 0)
            tabGroup[tab] = c[24] != 0 ? P.tokenHex(high: P.le64(c, 8), low: P.le64(c, 16)) : nil
        case P.Command.setTabGroupMetadata2:
            guard var r = PickleReader(c), let high = r.readUInt64(), let low = r.readUInt64(),
                  let title = r.readString16(), let color = r.readUInt32() else { return }
            let collapsed = r.readBool() ?? false      // M88
            let saved = r.readBool() ?? false          // M113
            let guid = saved ? r.readString() : nil
            let key = P.tokenHex(high: high, low: low)
            if groupsByKey[key] == nil { groupOrder.append(key) }
            groupsByKey[key] = ChromiumTabGroup(key: key, title: title, color: TabGroupColor.word(color),
                                                collapsed: collapsed, savedGuid: guid, tabs: [])
        default:
            break
        }
    }

    func groups() -> [ChromiumTabGroup] {
        var members: [String: [(window: Int32, index: Int32, tab: Int32, page: ChromiumTab)]] = [:]
        for (tab, key) in tabGroup where !closedTabs.contains(tab) {
            if let window = tabWindow[tab], closedWindows.contains(window) { continue }
            guard let pages = navigations[tab], let last = pages.max(by: { $0.key < $1.key }) else { continue }
            let page = selected[tab].flatMap { pages[$0] } ?? last.value
            members[key, default: []].append((tabWindow[tab] ?? 0, tabIndex[tab] ?? .max, tab, page))
        }
        return groupOrder.compactMap { key in
            guard var group = groupsByKey[key], let tabs = members[key], !tabs.isEmpty else { return nil }
            group.tabs = tabs.sorted { ($0.window, $0.index, $0.tab) < ($1.window, $1.index, $1.tab) }.map(\.page)
            return group
        }
    }
}

/// Which file to read (R-SR3): the profile's `Sessions/Session_<n>` files, newest first by the number in the name —
/// never `Tabs_*` (recently closed tabs) and never Chrome's encrypted directory beside `Sessions/`.
enum ChromiumSessionFiles {
    static func sessionFiles(in directory: URL, names: [String]) -> [URL] {
        names.compactMap { name -> (stamp: UInt64, name: String)? in
            guard name.hasPrefix("Session_"), let stamp = UInt64(name.dropFirst("Session_".count)) else { return nil }
            return (stamp, name)
        }
        .sorted { $0.stamp > $1.stamp }
        .map { directory.appendingPathComponent($0.name) }
    }

    /// The groups in the newest file Chrome itself would restore from — the first of the three newest that parses
    /// with its marker. Off the main actor (the caller detaches). A folder that is not there is `.missing`.
    static func newestGroups(in directory: URL) throws -> [ChromiumTabGroup] {
        let names: [String]
        do {
            names = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        } catch {
            throw BrowserFileError.classify(error, file: .chromeSessions, path: directory.path)
        }
        let files = sessionFiles(in: directory, names: names)
        guard !files.isEmpty else { throw BrowserFileError.missing(.chromeSessions, [directory.path]) }
        var firstError: Error?
        for url in files.prefix(3) {
            do {
                return try ChromiumSessionParser.parse(Data(contentsOf: url, options: [.uncached]))
            } catch {
                if firstError == nil { firstError = error }
            }
        }
        throw firstError ?? ChromiumSessionError.noMarker
    }
}

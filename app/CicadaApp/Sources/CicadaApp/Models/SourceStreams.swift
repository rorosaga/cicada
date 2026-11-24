import Foundation

// G245 (ruling 78) — `GET /sources/streams`: what every source reads, one row per stream (plan 2.1). Decoded
// leniently on purpose: the backend and the app ship apart, so a kind, a way, a health or a field this build does not
// know never fails the page. A value it cannot read is dropped alone (a stream), or falls to the lighter reading (a
// state it does not know reads Off, a depth it does not know reads Index). Pure and `Sendable`; nothing here draws.

/// What a stream holds. The wire's own words; a kind this build does not know is kept as `other` and is never a list.
enum StreamKind: RawRepresentable, Hashable, Sendable {
    case saved, liked, reposted, history, later, playlists, connections, following, notes, pages, chats, events, tasks, code, books, feed, files
    case other(String)

    init(rawValue: String) {
        switch rawValue {
        case "saved": self = .saved
        case "liked": self = .liked
        case "reposted": self = .reposted
        case "history": self = .history
        case "later": self = .later
        case "playlists": self = .playlists
        case "connections": self = .connections
        case "following": self = .following
        case "notes": self = .notes
        case "pages": self = .pages
        case "chats": self = .chats
        case "events": self = .events
        case "tasks": self = .tasks
        case "code": self = .code
        case "books": self = .books
        case "feed": self = .feed
        case "files": self = .files
        default: self = .other(rawValue)
        }
    }

    var rawValue: String {
        switch self {
        case .saved: "saved"
        case .liked: "liked"
        case .reposted: "reposted"
        case .history: "history"
        case .later: "later"
        case .playlists: "playlists"
        case .connections: "connections"
        case .following: "following"
        case .notes: "notes"
        case .pages: "pages"
        case .chats: "chats"
        case .events: "events"
        case .tasks: "tasks"
        case .code: "code"
        case .books: "books"
        case .feed: "feed"
        case .files: "files"
        case .other(let raw): raw
        }
    }

    /// The kinds a source's page lists as item cards under tabs (plan 3.2, item 3): saved, liked, reposted, history, later,
    /// playlists. Every other kind keeps the source's own content slot.
    var isList: Bool {
        switch self {
        case .saved, .liked, .reposted, .history, .later, .playlists: true
        default: false
        }
    }
}

/// How a stream is read. `browser`: the person's own AI app in their signed-in browser. `app`: this app, on this Mac.
/// `account`: a sign-in the person gave. `click`: noticed when the person saves, on this Mac.
enum StreamHow: RawRepresentable, Hashable, Sendable {
    case browser, app, account, click
    case other(String)

    init(rawValue: String) {
        switch rawValue {
        case "browser": self = .browser
        case "app": self = .app
        case "account": self = .account
        case "click": self = .click
        default: self = .other(rawValue)
        }
    }

    var rawValue: String {
        switch self {
        case .browser: "browser"
        case .app: "app"
        case .account: "account"
        case .click: "click"
        case .other(let raw): raw
        }
    }
}

/// Who is the truth for `state` and `health`: the backend, or this app's own switch and permission.
enum StreamOwner: String, Sendable {
    case backend, app
}

/// What the row's control is: one PUT flips it, or the source's own connect step stands in its place (choose chats,
/// a sign-in, a QR, a permission, a folder). A control this build does not know is a setup, never a switch it cannot drive.
enum StreamControl: String, Sendable {
    case `switch`, setup
}

enum StreamState: String, Sendable {
    case on, off, unavailable
}

/// What the last read said. A word this build does not know reads as no word (nil on the stream).
enum StreamHealth: String, Sendable {
    case read
    case notRead = "not_read"
    case signedOut = "signed_out"
    case couldntRead = "couldnt_read"
    case paused
}

/// How deep a stream's items go: kept and findable only (`index`), or read by Sleep (`read`).
enum StreamDepth: String, Sendable {
    case index, read
}

/// What `PUT /reading/settings` takes to flip a stream: the setting family and the key inside it.
struct StreamSwitch: Equatable, Hashable, Sendable {
    var setting: String
    var key: String
}

struct StreamAccount: Equatable, Sendable {
    var handle: String?
    var profileUrl: String?
}

/// One thing a source reads, as the backend names it (plan 2.1).
struct SourceStream: Equatable, Identifiable, Sendable {
    /// `<source>.<stream>`, frozen once shipped.
    var id: String
    var label: String
    var kind: StreamKind
    var how: StreamHow
    var owner: StreamOwner
    var control: StreamControl
    var state: StreamState
    var health: StreamHealth?
    var lastReadAt: Date?
    var pausedUntil: Date?
    /// Set by a check, cleared by the next read (plan 3.3).
    var checkRequestedAt: Date?
    /// Items the memory holds on this list (list membership, not origin), or nil.
    var count: Int?
    /// Folders, collections or playlists kept for this stream; 0 when none were seen.
    var folderCount: Int
    var depth: StreamDepth
    var switchRef: StreamSwitch?
    /// One sentence, only when unavailable.
    var why: String?
    /// G246 (ruling 81) — the page that stands for this list of saved posts (`GET /sources/streams` `page`), and for each
    /// of its folders (`folderPages`, by the folder's name as the site shows it). Absent until the page exists, and every
    /// time while the posts-as-rows switch is off: no link is drawn for what is not there.
    var page: String?
    var folderPages: [String: String]

    init(id: String, label: String, kind: StreamKind = .saved, how: StreamHow = .browser, owner: StreamOwner = .backend,
         control: StreamControl = .switch, state: StreamState = .off, health: StreamHealth? = nil,
         lastReadAt: Date? = nil, pausedUntil: Date? = nil, checkRequestedAt: Date? = nil, count: Int? = nil,
         folderCount: Int = 0, depth: StreamDepth = .index, switchRef: StreamSwitch? = nil, why: String? = nil,
         page: String? = nil, folderPages: [String: String] = [:]) {
        self.id = id; self.label = label; self.kind = kind; self.how = how; self.owner = owner; self.control = control
        self.state = state; self.health = health; self.lastReadAt = lastReadAt; self.pausedUntil = pausedUntil
        self.checkRequestedAt = checkRequestedAt; self.count = count; self.folderCount = folderCount
        self.depth = depth; self.switchRef = switchRef; self.why = why
        self.page = page; self.folderPages = folderPages
    }

    /// The part of the id after the source's: `x.bookmarks` is `bookmarks`.
    var tail: String {
        guard let dot = id.firstIndex(of: ".") else { return id }
        return String(id[id.index(after: dot)...])
    }

    var isOn: Bool { state == .on }
}

extension SourceStream: Decodable {
    private enum CodingKeys: String, CodingKey {
        case id, label, kind, how, owner, control, state, health, lastReadAt, pausedUntil, checkRequestedAt, count
        case folderCount, depth, `switch`, why, page, folderPages
    }

    private struct Switch: Decodable {
        var setting: String?
        var key: String?
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let id = try c.decode(String.self, forKey: .id)
        self.id = id
        let tail = id.firstIndex(of: ".").map { String(id[id.index(after: $0)...]) } ?? id
        label = c.lenient(.label, tail)
        kind = StreamKind(rawValue: c.lenient(.kind, ""))
        how = StreamHow(rawValue: c.lenient(.how, ""))
        owner = (c.lenient(.owner) as String?).flatMap(StreamOwner.init(rawValue:)) ?? .backend
        control = (c.lenient(.control) as String?).flatMap(StreamControl.init(rawValue:)) ?? .setup
        state = (c.lenient(.state) as String?).flatMap(StreamState.init(rawValue:)) ?? .off
        health = (c.lenient(.health) as String?).flatMap(StreamHealth.init(rawValue:))
        lastReadAt = (c.lenient(.lastReadAt) as String?).flatMap(ISODate.parse)
        pausedUntil = (c.lenient(.pausedUntil) as String?).flatMap(ISODate.parse)
        checkRequestedAt = (c.lenient(.checkRequestedAt) as String?).flatMap(ISODate.parse)
        count = c.lenient(.count)
        folderCount = max(0, c.lenient(.folderCount, 0) as Int)
        depth = (c.lenient(.depth) as String?).flatMap(StreamDepth.init(rawValue:)) ?? .index
        let ref: Switch? = c.lenient(.switch)
        if let setting = ref?.setting, let key = ref?.key, !setting.isEmpty, !key.isEmpty {
            switchRef = StreamSwitch(setting: setting, key: key)
        } else {
            switchRef = nil
        }
        why = c.lenient(.why)
        let page: String? = c.lenient(.page)
        self.page = page.flatMap { $0.isEmpty ? nil : $0 }
        folderPages = (c.lenient(.folderPages) as [String: String]?)?.filter { !$0.key.isEmpty && !$0.value.isEmpty } ?? [:]
    }
}

/// One source and the streams it reads.
struct SourceStreamsSource: Equatable, Identifiable, Sendable {
    /// The catalogue id the app uses (`SourceCatalogEntry.id`).
    var id: String
    var label: String
    var account: StreamAccount?
    var streams: [SourceStream]

    init(id: String, label: String? = nil, account: StreamAccount? = nil, streams: [SourceStream] = []) {
        self.id = id; self.label = label ?? id; self.account = account; self.streams = streams
    }
}

extension SourceStreamsSource: Decodable {
    private enum CodingKeys: String, CodingKey { case id, label, account, streams }

    private struct Account: Decodable {
        var handle: String?
        var profileUrl: String?
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(.label, id)
        let account: Account? = c.lenient(.account)
        self.account = account.flatMap { $0.handle == nil && $0.profileUrl == nil ? nil
            : StreamAccount(handle: $0.handle, profileUrl: $0.profileUrl) }
        streams = (c.lenient(.streams) as LossyList<SourceStream>?)?.items ?? []
    }
}

/// `GET /sources/streams`.
struct SourceStreamsResponse: Decodable, Equatable, Sendable {
    var sources: [SourceStreamsSource]
    /// `POST /sources/streams/check` only: the backend's one word per stream it was asked about (`requested`, `signed_out`,
    /// `paused`, `app`, `read`, `failed`, `off`, `not_connected`, `noted`), by stream id. Empty from the GET. An unknown
    /// word is kept as it is and read as no word.
    var checked: [String: String]

    init(sources: [SourceStreamsSource] = [], checked: [String: String] = [:]) {
        self.sources = sources
        self.checked = checked
    }

    /// The answer's top-level `shape` ("streams-1") is not read: every field is read leniently by name.
    private enum CodingKeys: String, CodingKey { case sources, checked }

    private struct Checked: Decodable {
        var stream: String
        var result: String
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sources = (c.lenient(.sources) as LossyList<SourceStreamsSource>?)?.items ?? []
        let rows = (c.lenient(.checked) as LossyList<Checked>?)?.items ?? []
        checked = Dictionary(rows.map { ($0.stream, $0.result) }, uniquingKeysWith: { _, last in last })
    }

    func source(_ id: String) -> SourceStreamsSource? { sources.first { $0.id == id } }
}

/// A list whose bad elements are dropped one by one: one stream or source this build cannot read never blanks the rest.
struct LossyList<T: Decodable>: Decodable {
    var items: [T]

    private struct Slot: Decodable {
        var value: T?
        init(from decoder: Decoder) throws { value = try? T(from: decoder) }
    }

    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        var out: [T] = []
        // `Slot` never throws, so the container always moves on to the next element.
        while !container.isAtEnd {
            if let value = try container.decode(Slot.self).value { out.append(value) }
        }
        items = out
    }
}

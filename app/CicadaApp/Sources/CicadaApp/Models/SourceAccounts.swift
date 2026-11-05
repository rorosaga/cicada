import Foundation

// 2026-11-04 (owner, on the Sources pages of Apple Notes, Reminders, Contacts and Calendar: "replicate this layout …
// starting from those that are iCloud, those that are iPhone, or whatever, and then you go into it, and then you can see
// the notes … or you can see folders"; "they should be separate using the respective logos") — every source this Mac
// reads files its items the way its own app does: an ACCOUNT (iCloud, On My Mac, a Google or Exchange account) holding
// COLLECTIONS (a calendar, a Reminders list, a Notes folder, a recorder's folder) holding the ITEMS. The page browses the
// same three levels (`SourceBrowser`), read from the backend (`GET /sources/channels/{id}/collections`), so a client or
// a replica shows what Cicada holds, never this Mac's own store.

/// A list of one collection's items, held by `ChannelItemsCache` and asked of the backend under one key: the channel
/// and the collection joined by a separator that never occurs in either (the cache's search key uses U+001F).
enum SourceListKey {
    static let separator: Character = "\u{1E}"

    static func make(_ channel: String, collection: String?) -> String {
        guard let collection, !collection.isEmpty else { return channel }
        return channel + String(separator) + collection
    }

    /// The channel and, when the key names one, the collection.
    static func parts(_ key: String) -> (channel: String, collection: String?) {
        guard let cut = key.firstIndex(of: separator) else { return (key, nil) }
        let collection = String(key[key.index(after: cut)...])
        return (String(key[..<cut]), collection.isEmpty ? nil : collection)
    }

    static func channel(of key: String) -> String { parts(key).channel }
}

/// `GET /sources/channels/{id}/collections` — lenient, so a backend a field ahead or behind never fails the page.
struct ChannelCollections: Decodable, Equatable, Sendable {
    var channel: String
    var accounts: [SourceAccount]
    /// G234: locked notes the last read found (Notes only); nothing else of them is kept.
    var locked: Int

    init(channel: String, accounts: [SourceAccount], locked: Int = 0) {
        self.channel = channel; self.accounts = accounts; self.locked = locked
    }

    enum CodingKeys: String, CodingKey { case channel, accounts, locked }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        channel = (try? c.decodeIfPresent(String.self, forKey: .channel)) ?? ""
        accounts = (try? c.decodeIfPresent([SourceAccount].self, forKey: .accounts)) ?? []
        locked = (try? c.decodeIfPresent(Int.self, forKey: .locked)) ?? 0
    }
}

struct SourceAccount: Decodable, Equatable, Sendable, Identifiable {
    /// The account's own name ("iCloud", "On My Mac", an address); nil when the sync that kept it named none.
    var name: String?
    /// What kind of account (`SourceAccountProvider`), when the Mac said.
    var provider: String?
    var count: Int
    var collections: [SourceCollection]

    var id: String { name ?? "" }

    init(name: String?, provider: String? = nil, count: Int, collections: [SourceCollection]) {
        self.name = name; self.provider = provider; self.count = count; self.collections = collections
    }

    enum CodingKeys: String, CodingKey { case name, provider, count, collections }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try? c.decodeIfPresent(String.self, forKey: .name)
        provider = try? c.decodeIfPresent(String.self, forKey: .provider)
        collections = (try? c.decodeIfPresent([SourceCollection].self, forKey: .collections)) ?? []
        count = (try? c.decodeIfPresent(Int.self, forKey: .count)) ?? collections.reduce(0) { $0 + $1.count }
    }

    var kind: SourceAccountProvider { SourceAccountProvider.of(posted: provider, name: name) }
}

struct SourceCollection: Decodable, Equatable, Hashable, Sendable, Identifiable {
    var id: String
    var name: String
    var count: Int
    /// The day (`YYYY-MM-DD`) its newest item came in.
    var latest: String?
    /// ROR-108, a followed feed only: its address, its last check's day, and a failed check in words.
    var url: String?
    var polled: String?
    var problem: String?

    init(id: String, name: String, count: Int, latest: String? = nil, url: String? = nil, polled: String? = nil,
         problem: String? = nil) {
        self.id = id; self.name = name; self.count = count; self.latest = latest
        self.url = url; self.polled = polled; self.problem = problem
    }

    enum CodingKeys: String, CodingKey { case id, name, count, latest, url, polled, problem }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        count = (try? c.decodeIfPresent(Int.self, forKey: .count)) ?? 0
        latest = try? c.decodeIfPresent(String.self, forKey: .latest)
        url = try? c.decodeIfPresent(String.self, forKey: .url)
        polled = try? c.decodeIfPresent(String.self, forKey: .polled)
        problem = try? c.decodeIfPresent(String.self, forKey: .problem)
    }
}

/// What kind of account a source's items live in, and the mark it wears. One decision for every page: Calendar and
/// Reminders say it from EventKit's own source type (`of(sourceType:title:)`, posted with each sync); Apple Notes names
/// only the account, so its kind is read from that name (`of(posted:name:)`).
///
/// Why Calendar showed a Google account (owner 2026-11-04: "I don't know why there's an Ada Google account for the
/// macOS calendar"): Calendar on this Mac holds every account in System Settings → Internet Accounts, a Google one
/// included, and the old page said so in a standing line with an *Add a Google account* button. Now each account is its
/// own row with its own mark; a Google account shows only when the Mac holds one.
enum SourceAccountProvider: String, Equatable, Sendable, CaseIterable {
    case icloud, local, google, exchange, subscribed, other

    /// EventKit's `EKSourceType` raw values: local 0, exchange 1, calDAV 2, mobileMe 3, subscribed 4, birthdays 5.
    /// A CalDAV account is iCloud when it says so, Google when its name is Google's or a Google address, else other.
    static func of(sourceType: Int, title: String?) -> SourceAccountProvider {
        switch sourceType {
        case 0: return .local
        case 1: return .exchange
        case 3: return .icloud
        case 4, 5: return .subscribed
        case 2: return byName(title) ?? .other
        default: return .other
        }
    }

    /// A posted kind when there is one, else the account's name read the way the apps name them.
    static func of(posted: String?, name: String?) -> SourceAccountProvider {
        if let posted, let kind = SourceAccountProvider(rawValue: posted.lowercased()) { return kind }
        return byName(name) ?? .other
    }

    /// "iCloud", "On My Mac" (and its few spellings), a Google or Gmail account or address, Exchange or Outlook.
    static func byName(_ name: String?) -> SourceAccountProvider? {
        let n = (name ?? "").trimmingCharacters(in: .whitespaces).lowercased()
        guard !n.isEmpty else { return nil }
        if n == "icloud" || n.hasSuffix("@icloud.com") || n.hasSuffix("@me.com") || n.hasSuffix("@mac.com") {
            return .icloud
        }
        if n.hasPrefix("on my ") || n == "local" { return .local }
        if n.contains("google") || n.contains("gmail") || n.hasSuffix("@googlemail.com") { return .google }
        if n.contains("exchange") || n.contains("outlook") || n.contains("office 365") || n.contains("microsoft") {
            return .exchange
        }
        if n.contains("subscri") || n == "birthdays" || n == "holidays" { return .subscribed }
        return nil
    }

    /// The bundled brand mark a row draws (`LogoTile`'s logo), for the source it is listed under: Google's calendar mark
    /// on Calendar and Reminders, Gmail's on Notes (a Gmail account's notes). Apple's marks are never committed (Track L),
    /// so iCloud and this Mac draw a system symbol instead (`symbol`).
    func logo(channel: String) -> String? {
        switch self {
        case .google: channel == "notes" ? "gmail" : "google-calendar"
        default: nil
        }
    }

    var symbol: String {
        switch self {
        case .icloud: "icloud"
        case .local: "laptopcomputer"
        case .google: "envelope"
        case .exchange: "building.2"
        case .subscribed: "dot.radiowaves.up.forward"
        case .other: "person.crop.circle"
        }
    }
}

/// The browser's words, pure (`SourceBrowserTests`).
enum SourceBrowserText {
    /// The Recent section under the accounts: DR-81's five rows, then "All N".
    static let recent = 5

    /// The account's name as the row says it: its own, else its kind's ("On My Mac" for a nameless local one).
    static func accountName(_ account: SourceAccount) -> String {
        if let name = account.name?.trimmingCharacters(in: .whitespaces), !name.isEmpty { return name }
        return Copy.SourceBrowser.unnamedAccount(account.kind)
    }

    /// What the page opens on: the accounts when there are several; one account's collections when there is one
    /// account with several; one collection's items when there is only one; the plain list when nothing is filed.
    enum Start: Equatable {
        case accounts
        case collections(SourceAccount)
        case items(SourceCollection)
        case flat
    }

    static func start(_ tree: ChannelCollections?) -> Start {
        guard let tree, !tree.accounts.isEmpty else { return .flat }
        if tree.accounts.count > 1 { return .accounts }
        let only = tree.accounts[0]
        if only.collections.count == 1 { return .items(only.collections[0]) }
        return only.collections.isEmpty ? .flat : .collections(only)
    }

    /// "32 min", "1 h 05 min" — a meeting's length; nil under a minute or with none.
    static func duration(_ seconds: Int?) -> String? {
        guard let seconds, seconds >= 60 else { return nil }
        let minutes = seconds / 60
        if minutes < 60 { return "\(minutes) min" }   // count-lint:ok — minutes never reach a thousand
        return String(format: "%d h %02d min", minutes / 60, minutes % 60)
    }
}

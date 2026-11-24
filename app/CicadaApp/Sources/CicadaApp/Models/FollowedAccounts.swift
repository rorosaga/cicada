import Foundation

// G245 (ruling 79 (b), owner 2026-11-24) — the wire shape of X's Following list: `GET /sources/follows/list`. The one route
// that names an account the person follows, so the app holds what it brings in MEMORY ONLY: no cache on disk, no Store
// domain, nothing in a bank. Decoded leniently like every wire shape here (a field this build does not know, or a malformed
// one, drops that field alone, never the row). Pure and `Sendable`; nothing here draws.

/// One followed account: a name, a handle, the profile link, the day this stretch of following began and the one page it is
/// when there is exactly one (`proposed`: matched by name alone).
struct FollowedAccount: Decodable, Hashable, Identifiable, Sendable {
    let id: String
    let name: String
    var handle: String = ""
    var url: String?
    var day: String?
    var page: String?
    var proposed: Bool = false

    enum CodingKeys: String, CodingKey { case id, name, handle, url, day, page, proposed }

    init(id: String, name: String, handle: String = "", url: String? = nil, day: String? = nil, page: String? = nil,
         proposed: Bool = false) {
        self.id = id; self.name = name; self.handle = handle; self.url = url; self.day = day; self.page = page
        self.proposed = proposed
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        handle = (try? c.decodeIfPresent(String.self, forKey: .handle)) ?? ""
        url = try? c.decodeIfPresent(String.self, forKey: .url)
        day = try? c.decodeIfPresent(String.self, forKey: .day)
        page = try? c.decodeIfPresent(String.self, forKey: .page)
        proposed = (try? c.decodeIfPresent(Bool.self, forKey: .proposed)) ?? false
    }

    /// What a row says first: the display name, else the handle.
    var title: String { name.isEmpty ? "@\(handle)" : name }
}

/// One page of the list, newest first. `total` is the matches' count under a search; `kept` is how many accounts are
/// followed now whatever the search says (what "Forget kept accounts" would forget, the gone aside).
struct FollowedAccountsPage: Decodable, Equatable, Sendable {
    var rows: [FollowedAccount] = []
    var total: Int = 0
    var offset: Int = 0
    var next: Int?
    var kept: Int = 0

    enum CodingKeys: String, CodingKey { case rows, total, offset, next, kept }

    init(rows: [FollowedAccount] = [], total: Int = 0, offset: Int = 0, next: Int? = nil, kept: Int = 0) {
        self.rows = rows; self.total = total; self.offset = offset; self.next = next; self.kept = kept
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        rows = (c.lenient(.rows) as LossyList<FollowedAccount>?)?.items ?? []   // one row this build cannot read never blanks the rest
        total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? rows.count
        offset = (try? c.decodeIfPresent(Int.self, forKey: .offset)) ?? 0
        next = try? c.decodeIfPresent(Int.self, forKey: .next)
        kept = (try? c.decodeIfPresent(Int.self, forKey: .kept)) ?? total
    }
}

/// The words of a row, pure (`FollowedAccountsTests`).
enum FollowedAccountsText {
    /// The profile link, when it is an http(s) address with a host.
    static func profile(_ row: FollowedAccount) -> URL? {
        guard let raw = row.url, let url = URL(string: raw), let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http", url.host?.isEmpty == false else { return nil }
        return url
    }

    /// "@handle" under the name, nothing when the name already is the handle.
    static func handleLine(_ row: FollowedAccount) -> String? {
        guard !row.handle.isEmpty, !row.name.isEmpty, row.name.lowercased() != row.handle.lowercased() else { return nil }
        return "@\(row.handle)"
    }

    /// The day on a row's trailing edge: "since Nov 14" with the full date as the help. Nil with no day.
    static func since(_ row: FollowedAccount, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String)? {
        guard let day = ISODay(row.day) else { return nil }
        return (Copy.Streams.followingSince(RelativeDay.absolute(day, today: today, locale: locale)),
                Copy.Streams.followingSinceHelp(RelativeDay.full(day, locale: locale)))
    }

    enum Empty: Equatable { case off, waiting, noMatch }

    static func empty(streamOn: Bool, searching: Bool) -> Empty {
        searching ? .noMatch : (streamOn ? .waiting : .off)
    }
}

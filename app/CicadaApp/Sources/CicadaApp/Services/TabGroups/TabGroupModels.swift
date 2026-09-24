import CryptoKit
import Foundation
import SwiftUI

/// `POST /sources/tab-groups/sync` (Task 1) — one browser profile's whole set of open groups.
struct TabGroupsPayload: Codable, Equatable, Sendable {
    struct Group: Codable, Equatable, Sendable {
        struct Tab: Codable, Equatable, Sendable {
            let title: String
            let url: String
        }
        let key: String
        let title: String
        let color: String
        let collapsed: Bool
        let savedGuid: String?
        let tabs: [Tab]
    }

    let browser: String
    let profile: String
    let groups: [Group]

    init(browser: String, profile: String, groups: [ChromiumTabGroup]) {
        self.browser = browser
        self.profile = profile
        self.groups = groups.map { g in
            Group(key: g.key, title: g.title, color: g.color, collapsed: g.collapsed, savedGuid: g.savedGuid,
                  tabs: g.tabs.map { Group.Tab(title: $0.title, url: $0.url) })
        }
    }

    /// R-SR7 — what is compared before a post: the bank and every group's identity-bearing fields, never `collapsed`
    /// (folding a group is not news).
    static func digest(_ payload: TabGroupsPayload, bank: String) -> String {
        var hasher = SHA256()
        func feed(_ text: String) {
            hasher.update(data: Data(text.utf8))
            hasher.update(data: Data([0]))
        }
        feed(bank)
        for group in payload.groups {
            feed(group.key); feed(group.title); feed(group.color); feed(group.savedGuid ?? "")
            for tab in group.tabs { feed(tab.title); feed(tab.url) }
            hasher.update(data: Data([1]))
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

/// Task 1's answer; lenient, so a backend one field ahead or behind never fails the sync.
struct TabGroupsSyncResult: Decodable, Equatable, Sendable {
    var created = 0, updated = 0, unchanged = 0, tombstoned = 0, groups = 0, tabs = 0
    var bank = ""

    init(created: Int = 0, updated: Int = 0, unchanged: Int = 0, tombstoned: Int = 0, groups: Int = 0, tabs: Int = 0,
         bank: String = "") {
        self.created = created; self.updated = updated; self.unchanged = unchanged; self.tombstoned = tombstoned
        self.groups = groups; self.tabs = tabs; self.bank = bank
    }

    enum CodingKeys: String, CodingKey { case created, updated, unchanged, tombstoned, groups, tabs, bank }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = c.lenient(.created, 0); updated = c.lenient(.updated, 0); unchanged = c.lenient(.unchanged, 0)
        tombstoned = c.lenient(.tombstoned, 0); groups = c.lenient(.groups, 0); tabs = c.lenient(.tabs, 0)
        bank = c.lenient(.bank, "")
    }
}

protocol TabGroupsSyncAPI: Sendable {
    func syncTabGroups(_ payload: TabGroupsPayload) async throws -> TabGroupsSyncResult
}

extension APIClient: TabGroupsSyncAPI {}

/// Chrome's group colours (`components/tab_groups/tab_group_color.h`: kGrey = 0 … kOrange = 8). The hue is a data
/// dot on a `Tag` (DR-44) — the browser's own colour as data, never a UI state (DR-8's rule for data hues).
enum TabGroupColor {
    static let words = ["grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange"]

    static func word(_ raw: UInt32) -> String { raw < words.count ? words[Int(raw)] : "grey" }

    static func hue(_ word: String) -> Color {
        switch word {
        case "blue": Color(hex: 0x1A73E8)
        case "red": Color(hex: 0xD93025)
        case "yellow": Color(hex: 0xF9AB00)
        case "green": Color(hex: 0x188038)
        case "pink": Color(hex: 0xD01884)
        case "purple": Color(hex: 0xA142F4)
        case "cyan": Color(hex: 0x007B83)
        case "orange": Color(hex: 0xFA903E)
        default: Color(hex: 0x5F6368)
        }
    }
}

import SwiftUI

/// The top level of the `+` sheet (2026-09-02 brief): one tile per family,
/// wearing its members' marks, so the user sees *where things come from*
/// before any route detail. `AddSourceTile` stays the leaf (R6) — every
/// flow, `forChannel` and "Manage…" still key on it; a family is only a
/// grouping in front of the tiles, never a new identity a channel maps to.
///
/// `allCases` order is the display order of the top-level grid, and each
/// `members` list is the display order of the members level — the brief
/// listed the browsers first because they are the two routes this track
/// shipped (Safari iCloud tabs, bookmark folders), and `ImportFamilyTests`
/// pins both orders.
enum ImportFamily: String, CaseIterable, Identifiable {
    case browsers, websites, chatExports, feedsAndCalendars, files
    var id: String { rawValue }

    var title: String {
        switch self {
        case .browsers: "Browsers"
        case .websites: "Websites & apps"
        case .chatExports: "Chat exports"
        case .feedsAndCalendars: "Feeds & calendars"
        case .files: "Files"
        }
    }

    var blurb: String {
        switch self {
        case .browsers: "Bookmarks, Reading List, and the tabs open on your iPhone."
        case .websites: "Everything you saved on TikTok, Instagram, YouTube, LinkedIn, Reddit, Pinterest and X."
        case .chatExports: "Your Claude and ChatGPT conversations, backdated."
        case .feedsAndCalendars: "Blogs, newsletters, calendars — and a Telegram bot for the road."
        case .files: "A bookmarks file, a pasted link, or Apple Notes."
        }
    }

    /// The family's own SF Symbol — the accessibility/monochrome stand-in
    /// for its mark cluster, not what the tile draws (that is
    /// `FamilyMarkCluster`).
    var icon: String {
        switch self {
        case .browsers: "globe"
        case .websites: "square.grid.2x2"
        case .chatExports: "bubble.left.and.bubble.right"
        case .feedsAndCalendars: "dot.radiowaves.up.forward"
        case .files: "doc"
        }
    }

    var members: [AddSourceTile] {
        switch self {
        case .browsers: [.safari, .chrome]
        case .websites: [.tiktok, .instagram, .youtube, .linkedin, .reddit, .pinterest, .x]
        case .chatExports: [.chatExport]
        case .feedsAndCalendars: [.rssFeed, .calendar, .telegram]
        case .files: [.bookmarksFile, .pasteLink, .appleNotes]
        }
    }

    /// Total over `AddSourceTile` — every tile is listed in exactly one
    /// family (`ImportFamilyTests.testEveryTileBelongsToExactlyOneFamily`
    /// pins the partition), so the `.files` fallback can only fire for a
    /// tile added later without a family, and the test fails first.
    static func forTile(_ tile: AddSourceTile) -> ImportFamily {
        allCases.first { $0.members.contains(tile) } ?? .files
    }

    /// The marks the family tile wears: up to four members, in listed order,
    /// preferring ones with a logo or glyph. A family whose members have
    /// only SF Symbols (Files) still shows them — never an empty cluster.
    var previewMarks: [AddSourceTile] {
        let branded = members.filter { $0.logoName != nil || $0.brandGlyph != nil }
        return Array((branded.isEmpty ? members : branded).prefix(4))
    }
}

/// Marks drawn in-app for the browsers (R7): no brand asset is downloaded.
/// Drop `Resources/logos/safari.png` / `chrome.png` in and set the tile's
/// `logoName` to switch to an official mark — `PlatformTile` prefers a
/// bundled PNG over a glyph, so nothing else needs to change.
enum BrandGlyph: Equatable { case safari, chrome }

extension AddSourceTile {
    /// The drawn mark, when this tile has one. Mutually exclusive with
    /// `logoName` by construction (`ImportCatalogTests
    /// .testAGlyphAndAPngAreNeverBothDeclared`): a tile carrying both would
    /// leave `MemberMark` to pick one silently.
    var brandGlyph: BrandGlyph? {
        switch self {
        case .safari: .safari
        case .chrome: .chrome
        default: nil
        }
    }

    /// Every way this member can import — the line under its name at the
    /// members level, so the user can tell "folders" from "tabs" before
    /// opening it. Distinct from `route`, which is the ONE badge verb: a
    /// tile has one route badge but may have several ways in (Reddit is
    /// Connect-first with a GDPR export past the API's listing cap).
    var routeLines: [String] {
        switch self {
        case .safari: ["Bookmarks (folders)", "Reading List", "iCloud tabs"]
        case .chrome: ["Bookmarks (folders)"]
        case .tiktok: ["Favourites & likes export", "Browsing history (opt-in)"]
        case .instagram: ["Saved export"]
        case .youtube: ["Playlist / Takeout export"]
        case .linkedin: ["Saved items export"]
        case .reddit: ["Connect account", "GDPR export"]
        case .pinterest, .x: ["Connect account"]
        case .chatExport: ["Claude export", "ChatGPT export"]
        case .rssFeed: ["Subscribe to a feed URL"]
        case .calendar: ["Subscribe to a webcal/ICS URL"]
        case .telegram: ["Your own bot"]
        case .bookmarksFile: ["HTML / JSON / CSV / Takeout zip"]
        case .pasteLink: ["One URL"]
        case .appleNotes: ["One-way sync"]
        }
    }
}

/// Which level the sheet is showing: `families → members → flow`. Esc walks
/// back exactly one level (`AddSourceSheet.escapeAction(level:)`), so one
/// keypress can never discard both a half-typed URL and the sheet.
enum CatalogLevel: Equatable {
    case families
    case members(ImportFamily)
    case flow(AddSourceTile)
}

/// Pure grid-focus arithmetic (R10): arrows move within a `columns`-wide
/// grid of `count` items, clamped at the edges — never wrapping, so a held
/// key stops rather than cycles. A struct with no SwiftUI in it so the
/// keyboard model is unit-tested without a view.
struct CatalogFocus: Equatable {
    var index: Int
    let columns: Int
    let count: Int

    enum Direction { case up, down, left, right }

    func moved(_ d: Direction) -> CatalogFocus {
        guard count > 0, columns > 0 else { return CatalogFocus(index: 0, columns: columns, count: count) }
        // Clamp first: a focus left pointing past the end (the grid shrank
        // underneath it) must land back inside rather than index out of the
        // members array on activation.
        let current = min(max(index, 0), count - 1)
        var next = current
        switch d {
        case .left: next = max(0, current - 1)
        case .right: next = min(count - 1, current + 1)
        case .up: next = current - columns >= 0 ? current - columns : current
        case .down: next = current + columns < count ? current + columns : current
        }
        return CatalogFocus(index: next, columns: columns, count: count)
    }
}

/// Chrome's mark: three 120° arcs (red, yellow, green) around a blue disc.
/// Drawn with `Canvas` rather than shipped as a PNG (R7) so the app carries
/// no downloaded brand asset for a browser it merely reads a file from.
struct ChromeGlyph: View {
    var size: CGFloat = 24
    var body: some View {
        Canvas { ctx, sz in
            let c = CGPoint(x: sz.width / 2, y: sz.height / 2)
            let r = min(sz.width, sz.height) / 2
            let colors: [Color] = [Color(hex: 0xDB4437), Color(hex: 0xF4B400), Color(hex: 0x0F9D58)]
            for (i, color) in colors.enumerated() {
                var p = Path()
                p.move(to: c)
                p.addArc(center: c, radius: r,
                         startAngle: .degrees(-90 + Double(i) * 120),
                         endAngle: .degrees(30 + Double(i) * 120),
                         clockwise: false)
                p.closeSubpath()
                ctx.fill(p, with: .color(color))
            }
            let inner = CGRect(x: c.x - r * 0.42, y: c.y - r * 0.42, width: r * 0.84, height: r * 0.84)
            ctx.fill(Path(ellipseIn: inner), with: .color(.white))
            let core = inner.insetBy(dx: r * 0.08, dy: r * 0.08)
            ctx.fill(Path(ellipseIn: core), with: .color(Color(hex: 0x4285F4)))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// Safari's mark is Apple's own compass symbol, tinted Safari blue — the
/// same glyph `OriginIconography` already uses for `safari-bookmark`.
struct SafariGlyph: View {
    var size: CGFloat = 24
    var body: some View {
        Image(systemName: "safari")
            .resizable().scaledToFit()
            .foregroundStyle(Color(hex: 0x00A2E8))
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// One member's mark: PNG when bundled, else its drawn glyph, else its SF
/// Symbol. The precedence lives in `LogoImage.platformTile(glyph:)`, not
/// here, so a browser PNG dropped into `Resources/logos/` later wins with
/// no code change beyond the tile's `logoName` (R7).
struct MemberMark: View {
    let tile: AddSourceTile
    var size: CGFloat = 32
    var body: some View {
        // Pick the overload per glyph rather than passing an `EmptyView`
        // through the glyph slot: conditional content is never type-equal to
        // `EmptyView`, so the un-glyphed tiles would have rendered an empty
        // card instead of falling through to their SF Symbol.
        switch tile.brandGlyph {
        case .safari:
            LogoImage.platformTile(name: tile.logoName ?? "", size: size, systemFallback: tile.icon) { SafariGlyph(size: $0) }
        case .chrome:
            LogoImage.platformTile(name: tile.logoName ?? "", size: size, systemFallback: tile.icon) { ChromeGlyph(size: $0) }
        case nil:
            LogoImage.platformTile(name: tile.logoName ?? "", size: size, systemFallback: tile.icon)
        }
    }
}

/// The family tile's cluster: up to four member marks in a 2×2 grid (two
/// side by side when there are only two). Hidden from accessibility — the
/// family button's own label already names the family and its blurb.
struct FamilyMarkCluster: View {
    let family: ImportFamily
    var body: some View {
        let marks = family.previewMarks
        let cols = marks.count <= 2 ? marks.count : 2
        LazyVGrid(columns: Array(repeating: GridItem(.fixed(22), spacing: 4), count: max(cols, 1)),
                  alignment: .leading, spacing: 4) {
            ForEach(marks) { MemberMark(tile: $0, size: 22) }
        }
        .frame(height: marks.count <= 2 ? 22 : 48, alignment: .topLeading)
        .accessibilityHidden(true)
    }
}

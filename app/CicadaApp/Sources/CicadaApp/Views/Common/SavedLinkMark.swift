import SwiftUI

/// Owner 2026-10-20 — one rule for a saved link's main mark, on every surface that draws one (Sources' saved rows,
/// Sleep's Saved, Videos and Waiting rows, an open saved item's header, the Reader's header for a saved link): the
/// link's OWN site — its icon, asked of that site only by the backend (owner ruling 2026-10-19, behind
/// `CICADA_ALLOW_LOGO_FETCH`, cached per site outside every bank) — else a known family's bundled mark, else a ring
/// monogram of the site. Never the browser's or the app's mark it was saved from: the row is the site, and where it
/// was saved from is words on the row (or the "Saved from" section), never the main mark.
///
/// Pure, so `SavedLinkMarkTests` holds it; `SavedLinkMark` is its only view, so the surfaces cannot drift.
enum SavedLinkMarkModel {
    /// How the backend is asked for the icon: by the saved item's media page, or — before Sleep made the page — by its
    /// waiting episode. Nil when there is no id to ask by (the mark stops at the bundled mark or the monogram).
    enum Door: Equatable, Sendable {
        case media(String)
        case episode(String)

        var ref: SiteIconStore.SavedRef {
            switch self {
            case .media(let id): .media(id)
            case .episode(let id): .episode(id)
            }
        }
    }

    enum Mark: Equatable {
        /// The site's key (the backend's `reading_hosts.mark_key`), the words its monogram is drawn from, and the door.
        case site(key: String, label: String, door: Door?)
        /// No site to name: a ring monogram of the host or the title.
        case monogram(String)
    }

    /// The mark for a saved thing: its site's when the backend named one, else a monogram of the host or the title.
    static func mark(site: String?, host: String?, title: String, door: Door?) -> Mark {
        let label = nonEmpty(host) ?? title
        if let key = nonEmpty(site) { return .site(key: key, label: label, door: door) }
        return .monogram(SiteMonogram.letter(label))
    }

    /// Whether a row's main mark is its site's: only when the backend named the site. A row without one (an older
    /// backend, a conversation, a captured page) keeps the mark it had.
    static func applies(site: String?) -> Bool { nonEmpty(site) != nil }

    /// A Sleep › Saved or Videos row (`MediaFeedItem`): its page is the door.
    static func mark(_ item: MediaFeedItem) -> Mark? {
        guard applies(site: item.siteKey) else { return nil }
        return mark(site: item.siteKey, host: item.site, title: item.title.isEmpty ? item.url : item.title,
                    door: .media(item.mediaEntityId))
    }

    /// A Waiting row (`EpisodeQueueItem`) of a saved link: the episode is the door until Sleep made its page.
    static func mark(_ item: EpisodeQueueItem) -> Mark? {
        guard applies(site: item.site) else { return nil }
        let host = item.copyKind == "link" ? item.copyValue.flatMap(LinkGrammar.site) : nil
        return mark(site: item.site, host: host, title: item.title ?? "", door: .episode(item.id))
    }

    private static func nonEmpty(_ value: String?) -> String? {
        guard let value = value?.trimmingCharacters(in: .whitespaces), !value.isEmpty else { return nil }
        return value
    }
}

/// The one view of `SavedLinkMarkModel.Mark`: `SiteIcon` for a site (its own icon, else the family's bundled mark,
/// else the site's monogram — DR-52, no ring around a real icon), a ring monogram otherwise (never a solid fill).
struct SavedLinkMark: View {
    let mark: SavedLinkMarkModel.Mark
    var size: SiteIconLayout.Size = .row

    var body: some View {
        switch mark {
        case .site(let key, let label, let door):
            switch door {
            case .media(let id)?: SiteIcon(site: key, label: label, size: size, savedItem: id)
            case .episode(let id)?: SiteIcon(site: key, label: label, size: size, savedEpisode: id)
            case nil: SiteIcon(site: key, label: label, size: size)
            }
        case .monogram(let letter):
            SiteMonogram(letter: letter, side: CicadaTheme.scaled(size.points))
                .accessibilityHidden(true)
        }
    }
}

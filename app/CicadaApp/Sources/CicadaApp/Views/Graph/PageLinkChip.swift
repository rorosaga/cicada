import AppKit
import SwiftUI

// MARK: - A link is a chip (owner 2026-11-23, DESIGN_RULES §9; amends how a page draws links)
//
// *"I want something minimal where hyperlinks look nice, like embedded buttons that take you to the other pages, with a
// picture if relevant, like a YouTube logo, or the pfp of a person."* A link to another page is a soft rounded chip: the
// page's own picture where it has one (`EntityPicture`'s precedence: a person's photo or initials, a company's logo, a
// media thumbnail, a project's mark — a page with none draws the name alone, DR-48), then **the page's own name**, never
// the words the link was written under. A link to the web is the same chip with the site's mark where the app already
// has one (a bundled brand mark, or the icon the page's own icon route serves) and nothing otherwise. No underline, no
// accent (DR-5): the fill and the picture say it is a control; hover takes the row-hover fill; ⏎ opens it from the
// keyboard. The app loads no picture from the web to draw one (rail: `network.md`).

/// Which bundled mark a link's site wears, by host. Pure: `PageInlineTests` pins it. A site with no mark here may still
/// have the icon the page's own icon route serves (`LinkFact.icon`); otherwise the chip has no picture.
enum PageChipMark {
    private static let hosts: [(suffix: String, mark: String)] = [
        ("youtube.com", "youtube"), ("youtu.be", "youtube"), ("youtube-nocookie.com", "youtube"),
        ("github.com", "github"), ("x.com", "x"), ("twitter.com", "x"), ("linkedin.com", "linkedin"),
        ("instagram.com", "instagram"), ("reddit.com", "reddit"), ("tiktok.com", "tiktok"),
        ("pinterest.com", "pinterest"), ("spotify.com", "spotify"), ("notion.so", "notion"),
        ("notion.site", "notion"), ("linear.app", "linear"), ("goodreads.com", "goodreads"),
        ("substack.com", "substack"), ("claude.ai", "claude"), ("chatgpt.com", "chatgpt"),
        ("openai.com", "openai"), ("gemini.google.com", "gemini"), ("perplexity.ai", "perplexity"),
        ("t.me", "telegram"), ("whatsapp.com", "whatsapp"), ("mail.google.com", "gmail"),
    ]

    /// The bundled mark for `url`'s host (a host or any subdomain of it), when one ships.
    static func bundled(url: URL, exists: (String) -> Bool = LogoImage.exists(name:)) -> String? {
        guard let host = url.host?.lowercased() else { return nil }
        for entry in hosts where host == entry.suffix || host.hasSuffix("." + entry.suffix) {
            return exists(entry.mark) ? entry.mark : nil
        }
        return nil
    }
}

struct PageLinkChip: View {
    enum Face: Equatable {
        case page(PageLinkTarget)
        case web(label: String)
    }

    let face: Face
    let url: URL
    /// The page the chip is on: its icon route serves a linked site's mark.
    let entityId: String?

    @Environment(\.openURL) private var openURL
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(Store.self) private var store: Store?
    @State private var hovering = false
    @State private var siteImage: NSImage?
    /// The keyboard's stop is on this chip. The article's text view owns the keyboard (`PageTextView`: Tab moves between
    /// chips, quiet links and the cluster, ⏎ opens), because the key-view loop does not reach a view inside text.
    var focused = false

    private var name: String {
        switch face {
        case .page(let target): target.name
        case .web(let label): label
        }
    }

    /// 16 pt, the line's own size: a person's disc and a company's mark; a media page's thumbnail is its 3:2 well.
    private static var side: CGFloat { CicadaTheme.scaled(16) }

    private var pageHasPicture: Bool {
        guard case .page(let target) = face else { return false }
        return store.map { !EntityPictureLayout.isEmpty(target.type, picture: $0.picture(for: target.id)) } ?? false
    }

    private var bundledMark: String? {
        guard case .web = face else { return nil }
        return PageChipMark.bundled(url: url)
    }

    private var drawsPicture: Bool { pageHasPicture || bundledMark != nil || siteImage != nil }

    private var pictureWidth: CGFloat {
        if case .page(let target) = face, pageHasPicture {
            return EntityPictureLayout.frame(target.type, size: Self.side).width
        }
        return Self.side
    }

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadiusSmall) }

    var body: some View {
        Button(action: open) {
            // The picture is an overlay, so the chip's first text baseline is its name's: the layout lines it up with
            // the words around it.
            Text(name)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
                .truncationMode(.tail)
                .padding(.leading, drawsPicture ? pictureWidth + CicadaTheme.scaled(8) : CicadaTheme.scaled(6))
                // Snug on the trailing side: a full stop or a bracket after the chip must read as hugging it.
                .padding(.trailing, CicadaTheme.scaled(6))
                .overlay(alignment: .leading) {
                    picture
                        .padding(.leading, CicadaTheme.scaled(4))
                        .accessibilityHidden(true)
                }
                // The fill reaches past the text's own height into the line gap, so a line with a chip is as tall as a
                // line of words and a paragraph keeps one rhythm.
                .background {
                    shape.fill(hovering || focused ? CicadaTheme.bgHover : CicadaTheme.bgFocus)
                        .padding(.vertical, -CicadaTheme.scaled(1.5))
                }
                .overlay {
                    shape.strokeBorder(CicadaTheme.ring(focused ? .strong : .resting), lineWidth: 1)
                        .padding(.vertical, -CicadaTheme.scaled(1.5))
                }
                .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .help(help)
        .accessibilityLabel(name)
        .accessibilityHint(hint)
        .accessibilityAddTraits(.isLink)
        .task(id: siteKey) { await loadSiteImage() }
    }

    @ViewBuilder
    private var picture: some View {
        switch face {
        case .page(let target):
            if pageHasPicture {
                let well = EntityPictureLayout.frame(target.type, size: Self.side)
                // `EntityPicture` is 20 pt at the least (C11); the chip's 16 is that, drawn at four fifths.
                EntityPicture(id: target.id, name: target.name, type: target.type, size: 20)
                    .scaleEffect(0.8)
                    .frame(width: well.width, height: well.height)
            }
        case .web:
            if let mark = bundledMark {
                LogoImage(name: mark, size: Self.side)
            } else if let siteImage {
                Image(nsImage: siteImage).resizable().interpolation(.high).scaledToFit()
                    .frame(width: Self.side, height: Self.side)
                    .clipShape(CicadaTheme.shape(CicadaTheme.scaled(SiteIconLayout.cornerRadius)))
            }
        }
    }

    private func open() { openURL(url) }

    private var help: String {
        switch face {
        case .page(let target): Copy.Pages.openPage(target.name)
        case .web: url.absoluteString
        }
    }

    private var hint: String {
        switch face {
        case .page: Copy.Pages.opensPage
        case .web: Copy.Pages.opensInBrowser
        }
    }

    // MARK: A linked site's icon, from the page's own icon route

    /// Only a site whose icon the page's link facts say is served (`LinkFact.icon`, a trusted source or a saved page) —
    /// the same rule a mention's icon always followed; never a fetch the app makes itself.
    private var siteKey: String {
        guard case .web = face, bundledMark == nil, let entityId else { return "" }
        let fact = LinkFactsCache.shared.fact(url.absoluteString, on: entityId)
        return fact.icon ? "\(store?.bank ?? "")|\(entityId)|\(fact.site ?? LinkGrammar.site(url.absoluteString) ?? "")" : ""
    }

    private func loadSiteImage() async {
        guard !siteKey.isEmpty, let entityId,
              let site = LinkFactsCache.shared.fact(url.absoluteString, on: entityId).site
                ?? LinkGrammar.site(url.absoluteString) else {
            siteImage = nil
            return
        }
        siteImage = await SiteIconStore.shared.image(site: site, bank: store?.bank ?? "", entity: entityId, saved: nil)
    }
}

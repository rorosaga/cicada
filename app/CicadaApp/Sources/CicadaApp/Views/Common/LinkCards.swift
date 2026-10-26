import AppKit
import SwiftUI

// MARK: - Links show as what they are (owner rulings 2026-10-14)
//
// The block views a link can ask for (`LinkView.swift`'s grammar) and the person's view switcher. Every fact a card
// draws comes from Cicada's own API (`/entities/{id}/links`, `LinkFactsCache`): the app fetches nothing of the web,
// and a link Cicada never read shows only what is known — its words, its site and "Not read yet" (ruling 3). Every
// view degrades one step and says so in words (DR-32): a screenshot with no picture of the page is a bookmark card
// with "No capture of this page yet". Depth is a ring (DR-9); hover is a fill change (DR-63); one date per card, the
// date of what is shown, computed at read (DR-58).

/// Where a link card's click goes: the saved item's own page when Cicada has one (the backend matched the URL with
/// its one normaliser), else the browser; ⌘-click always opens the browser.
@MainActor
enum LinkOpen {
    static func open(_ fact: LinkFact, openURL: OpenURLAction) {
        let browser = NSEvent.modifierFlags.contains(.command)
        if !browser, let page = fact.pageId, let url = URL(string: MarkdownBody.entityLink(for: page)) {
            openURL(url)
            return
        }
        browserOpen(fact.url)
    }

    static func browserOpen(_ raw: String) {
        guard let url = URL(string: raw), let scheme = url.scheme?.lowercased(), scheme == "https" || scheme == "http"
        else { return }
        NSWorkspace.shared.open(url)
    }
}

/// A linked site's mark: its icon only where this page's icon route serves it (a trusted source, or a page the
/// person saved — G159 keeps people's and media pages out), else a ring monogram. DR-52.
struct LinkSiteMark: View {
    let fact: LinkFact
    let entityId: String?
    var size: SiteIconLayout.Size = .inline

    var body: some View {
        if let site = fact.site, !site.isEmpty {
            if fact.icon, let entityId {
                SiteIcon(site: site, size: size, entity: entityId)
            } else {
                SiteMonogram(letter: SiteMonogram.letter(site), side: CicadaTheme.scaled(size.points))
                    .accessibilityHidden(true)
            }
        } else {
            Image(systemName: "link")
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
        }
    }
}

/// research-hub's bookmark (owner 2026-10-26, measured from their editor): a horizontal card on a ring, the stored
/// picture on the left at full height (220 pt wide, no corner of its own — the card's clip rounds it), then title (one
/// line, 14 medium), description (two lines, 12) and mark · address · the one date line (12, tertiary). On top when the
/// card is narrower than 440 pt (`ViewThatFits`). The picture is only one Cicada stores (`StoredPreview`); else none.
struct BookmarkCard: View {
    static let wideMinWidth: CGFloat = 440
    /// The measured look (DESIGN_RULES §9, 2026-10-26): the card's height with a picture, the picture's width, and the
    /// words' padding (top, sides, bottom) and gap.
    static let pictureHeight: CGFloat = 124
    static let pictureWidth: CGFloat = 220
    static let padTop: CGFloat = 11
    static let padSide: CGFloat = 14
    static let padBottom: CGFloat = 12
    static let gap: CGFloat = 5

    let fact: LinkFact
    var ref: LinkRef? = nil
    var entityId: String? = nil
    /// A degraded view says why in words, under the date line ("No capture of this page yet").
    var status: String? = nil
    /// Room kept at the title's end for a control drawn over the card's corner (the link's view menu).
    var trailingInset: CGFloat = 0

    @Environment(\.openURL) private var openURL
    @State private var hovering = false

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadius) }
    private var hasPicture: Bool { StoredPreviewPath.loads(fact.preview) }

    var body: some View {
        Button { LinkOpen.open(fact, openURL: openURL) } label: {
            // The wide form asks for 440 pt and no more, so it is chosen whenever 440 pt are there (a long title or
            // description would otherwise make it ask for its whole single line and never fit).
            ViewThatFits(in: .horizontal) {
                wide.frame(minWidth: Self.wideMinWidth, idealWidth: Self.wideMinWidth, maxWidth: .infinity,
                           alignment: .leading)
                narrow
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(shape.fill(hovering ? CicadaTheme.bgHover : CicadaTheme.bgFocus))
            .clipShape(shape)
            .ringed(.resting, in: shape)
            .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help("\(fact.url)\n\(Copy.Links.openHint)")
        .accessibilityElement(children: .combine)
        .accessibilityHint(Copy.Links.openHint)
    }

    private var wide: some View {
        HStack(alignment: .top, spacing: 0) {
            if hasPicture {
                picture.frame(width: CicadaTheme.scaled(Self.pictureWidth)).frame(maxHeight: .infinity).clipped()
            }
            words
        }
        .frame(minHeight: hasPicture ? CicadaTheme.scaled(Self.pictureHeight) : nil)
        .fixedSize(horizontal: false, vertical: true)
    }

    private var narrow: some View {
        VStack(alignment: .leading, spacing: 0) {
            if hasPicture {
                picture.frame(height: 140).frame(maxWidth: .infinity).clipped()
            }
            words
        }
    }

    private var picture: some View {
        StoredPreview(path: fact.preview) { CicadaTheme.bgPane }
    }

    private var words: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(Self.gap)) {
            Text(LinkCardModel.title(ref, fact: fact))
                .font(CicadaTheme.font(size: 14, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
                .padding(.trailing, trailingInset)
            if let description = fact.description, !description.isEmpty {
                Text(description)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2)
            }
            HStack(spacing: CicadaTheme.spacingXS) {
                LinkSiteMark(fact: fact, entityId: entityId)
                Text(footer)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            if let status {
                Text(status)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, CicadaTheme.scaled(Self.padTop))
        .padding(.horizontal, CicadaTheme.scaled(Self.padSide))
        .padding(.bottom, CicadaTheme.scaled(Self.padBottom))
    }

    private var footer: String { LinkCardModel.footer(fact) }
}

/// A picture of the page at 16:10, then its caption below it — never over it (DR-13): mark · title · "Captured Oct 14,
/// 2026 · 3 months ago". ⤢ opens the lightbox, which keeps the date line; ↗ opens the page.
struct CaptureCard: View {
    let fact: LinkFact
    let shot: LinkCardModel.Shot
    var ref: LinkRef? = nil
    var entityId: String? = nil

    @Environment(Store.self) private var store: Store?
    @Environment(\.openURL) private var openURL
    @State private var image: NSImage?
    @State private var showLightbox = false

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadiusSmall) }
    private var dateLine: String { LinkCardModel.capturedLine(shot) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Button { LinkOpen.open(fact, openURL: openURL) } label: {
                Color.clear
                    .aspectRatio(16.0 / 10.0, contentMode: .fit)
                    .frame(maxWidth: .infinity)
                    .overlay {
                        if let image {
                            Image(nsImage: image).resizable().scaledToFill()
                        } else {
                            CicadaTheme.bgPane
                        }
                    }
                    .clipShape(shape)
                    .ringed(.resting, in: shape)
                    .contentShape(shape)
            }
            .buttonStyle(.cicadaPlain)
            .help("\(fact.url)\n\(Copy.Links.openHint)")
            HStack(spacing: CicadaTheme.spacingXS) {
                LinkSiteMark(fact: fact, entityId: entityId)
                Text("\(LinkCardModel.title(ref, fact: fact)) · \(dateLine)")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
                IconButton(systemName: "arrow.up.right", help: Copy.Links.openInBrowser) { LinkOpen.browserOpen(fact.url) }
                IconButton(systemName: "arrow.up.left.and.arrow.down.right", help: Copy.Links.enlarge) {
                    if image != nil { showLightbox = true }
                }
            }
        }
        .task(id: "\(store?.bank ?? "")|\(shot.image)") {
            image = nil
            guard let url = StoredPreviewPath.url(shot.image) else { return }
            image = await PictureStore.shared.image(url, bank: store?.bank ?? "")
        }
        .sheet(isPresented: $showLightbox) {
            if let image { ImageLightbox(image: image, caption: dateLine) }
        }
    }
}

/// "How it looked": every capture of the page, oldest to newest, each with its own day under it. ⧗ Captures come from
/// site exploration; until it lands a `captures` link draws a bookmark that says there are none yet.
struct CaptureStrip: View {
    let fact: LinkFact
    var entityId: String? = nil

    var body: some View {
        let shots = fact.captures.sorted { $0.day < $1.day }
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Links.howItLooked(shots.count))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                    ForEach(Array(shots.enumerated()), id: \.offset) { _, shot in
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            ImageThumbnail(path: shot.image, width: 96, height: 60,
                                           caption: Copy.Links.captured(EntityDates.day(shot.day) ?? shot.day))
                            Text(EntityDates.shortDay(shot.day) ?? shot.day)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                }
            }
        }
    }
}

/// A saved look (G196) of the page: its screenshot cropped, the proportional colour strip, the site and the day it
/// was saved to Looks.
struct LookSwatch: View {
    let fact: LinkFact
    let look: LinkFact.Look
    var entityId: String? = nil

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadiusSmall) }

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            ImageThumbnail(path: look.image, width: 96, height: 64,
                           caption: Copy.Links.savedToLooks(EntityDates.day(look.day) ?? look.day))
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                LooksPaletteStrip(colours: look.palette).frame(height: 10)
                HStack(spacing: CicadaTheme.spacingXS) {
                    LinkSiteMark(fact: fact, entityId: entityId)
                    Text("\(fact.site ?? LinkGrammar.display(fact.url)) · "
                         + Copy.Links.savedToLooks(EntityDates.shortDay(look.day) ?? look.day))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(CicadaTheme.spacingSM)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: shape)
        .help(fact.url)
    }
}

/// A link drawn as a block: the card for the view it draws as (`LinkCardModel.current` — its own word, else a bookmark
/// by context), degraded one step and said in words when Cicada has nothing for it yet, the link's view menu in the
/// card's corner — a click away, never only on hover (owner 2026-10-26) — then the line's note.
struct LinkBlockView: View {
    let ref: LinkRef
    let note: String?
    let entityId: String?

    @State private var status: String?

    var body: some View {
        let fact = LinkFactsCache.shared.fact(ref.url, on: entityId)
        let menu = entityId != nil && !LinkCardModel.offered(ref, fact: fact).isEmpty
        let inset = menu ? LinkViewMenu.side + CicadaTheme.spacingXS : 0
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            card(fact, inset: inset)
                .overlay(alignment: .topTrailing) {
                    if menu, let entityId {
                        LinkViewMenu(ref: ref, fact: fact, entityId: entityId, compact: true, status: $status)
                            .padding(CicadaTheme.spacingXS)
                    }
                }
                .contextMenu {
                    if let entityId { LinkViewMenuItems(ref: ref, fact: fact, entityId: entityId, status: $status) }
                }
            if let status {
                Text(status)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            if let note, !note.isEmpty {
                Text(note)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
            }
        }
        .frame(maxWidth: 640, alignment: .leading)
    }

    @ViewBuilder
    private func card(_ fact: LinkFact, inset: CGFloat) -> some View {
        switch LinkCardModel.current(ref) {
        case .embed:
            if let embed = LinkEmbed.of(ref.url) {
                LinkEmbedView(ref: ref, fact: fact, embed: embed, entityId: entityId, trailingInset: inset)
            } else {
                BookmarkCard(fact: fact, ref: ref, entityId: entityId, trailingInset: inset)
            }
        case .screenshot:
            if let shot = LinkCardModel.shot(fact, day: ref.day) {
                CaptureCard(fact: fact, shot: shot, ref: ref, entityId: entityId)
            } else {
                BookmarkCard(fact: fact, ref: ref, entityId: entityId, status: Copy.Links.noCapture,
                             trailingInset: inset)
            }
        case .captures:
            if fact.captures.isEmpty {
                BookmarkCard(fact: fact, ref: ref, entityId: entityId, status: Copy.Links.noCaptures,
                             trailingInset: inset)
            } else {
                CaptureStrip(fact: fact, entityId: entityId)
            }
        case .look:
            if let look = LinkCardModel.look(fact, day: ref.day) {
                LookSwatch(fact: fact, look: look, entityId: entityId)
            } else {
                BookmarkCard(fact: fact, ref: ref, entityId: entityId, status: Copy.Links.noLook, trailingInset: inset)
            }
        default:
            BookmarkCard(fact: fact, ref: ref, entityId: entityId, trailingInset: inset)
        }
    }
}

/// The Embed view (owner 2026-10-26). A video: its stored still (the picture Cicada keeps for a saved video — YouTube's
/// own still among them) behind a play button, and on the person's click the provider's own player in place — the
/// player URL `VideoRef` derives from the link, loaded only now, never autoplaying (G162, R11). A PDF: a card with the
/// document's mark, its words and "PDF"; nothing is fetched to draw it, and a click opens it like any card.
struct LinkEmbedView: View {
    let ref: LinkRef
    let fact: LinkFact
    let embed: LinkEmbed
    var entityId: String? = nil
    var trailingInset: CGFloat = 0

    @Environment(\.openURL) private var openURL
    @State private var playing = false
    @State private var hovering = false

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadius) }

    var body: some View {
        switch embed {
        case .video(let player): video(player)
        case .pdf: pdf
        }
    }

    private func video(_ player: URL) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Color.clear
                .aspectRatio(16.0 / 9.0, contentMode: .fit)
                .frame(maxWidth: .infinity)
                .overlay {
                    if playing {
                        WebView(url: player)
                    } else {
                        Button { playing = true } label: {
                            ZStack {
                                if StoredPreviewPath.loads(fact.preview) {
                                    StoredPreview(path: fact.preview) { CicadaTheme.bgPane }
                                } else {
                                    CicadaTheme.bgPane
                                }
                                Image(systemName: "play.fill")
                                    .font(CicadaTheme.icon(.titlebar))
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                    .frame(width: CicadaTheme.scaled(44), height: CicadaTheme.scaled(44))
                                    .background(Circle().fill(hovering ? CicadaTheme.bgHover : CicadaTheme.bgFocus))
                                    .overlay(Circle().strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.cicadaPlain)
                        .onHover { hovering = $0 }
                        .help(Copy.Links.play)
                        .accessibilityLabel(Copy.Links.play)
                    }
                }
                .clipShape(shape)
                .ringed(.resting, in: shape)
            HStack(spacing: CicadaTheme.spacingXS) {
                LinkSiteMark(fact: fact, entityId: entityId)
                Text("\(LinkCardModel.title(ref, fact: fact)) · \(fact.site ?? LinkGrammar.display(fact.url))")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
                IconButton(systemName: "arrow.up.right", help: Copy.Links.openInBrowser) { LinkOpen.browserOpen(ref.url) }
            }
        }
    }

    private var pdf: some View {
        Button { LinkOpen.open(fact, openURL: openURL) } label: {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "doc.richtext")
                    .font(CicadaTheme.icon(.titlebar))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(40), height: CicadaTheme.scaled(52))
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgPane))
                    .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(BookmarkCard.gap)) {
                    Text(LinkCardModel.title(ref, fact: fact))
                        .font(CicadaTheme.font(size: 14, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                        .padding(.trailing, trailingInset)
                    if let description = fact.description, !description.isEmpty {
                        Text(description)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(2)
                    }
                    Text("\(Copy.Links.pdf) · \(LinkCardModel.footer(fact))")
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.top, CicadaTheme.scaled(BookmarkCard.padTop))
            .padding(.horizontal, CicadaTheme.scaled(BookmarkCard.padSide))
            .padding(.bottom, CicadaTheme.scaled(BookmarkCard.padBottom))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(shape.fill(hovering ? CicadaTheme.bgHover : CicadaTheme.bgFocus))
            .clipShape(shape)
            .ringed(.resting, in: shape)
            .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help("\(fact.url)\n\(Copy.Links.openHint)")
        .accessibilityElement(children: .combine)
        .accessibilityHint(Copy.Links.openHint)
    }
}

/// `![alt](url)` in a page's prose. A picture Cicada stores (a path on its own API) draws as a thumbnail; a picture on
/// the web is never loaded by the app — it draws as a bookmark of its URL that says so.
struct ProseImage: View {
    let url: String
    let alt: String
    var entityId: String? = nil

    /// What Cicada knows of the image's URL, titled by its alt text when it knows no title.
    private var webFact: LinkFact {
        var fact = LinkFactsCache.shared.fact(url, on: entityId)
        if fact.title == nil, !alt.isEmpty { fact.title = alt }
        return fact
    }

    var body: some View {
        if StoredPreviewPath.loads(url) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ImageThumbnail(path: url, width: 320, height: 180, caption: alt.isEmpty ? nil : alt)
                if !alt.isEmpty {
                    Text(alt)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        } else if LinkGrammar.site(url) != nil, url.lowercased().hasPrefix("http") {
            BookmarkCard(fact: webFact, entityId: entityId, status: Copy.Links.image)
                .frame(maxWidth: 640, alignment: .leading)
        } else {
            Text(alt.isEmpty ? url : alt)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

// MARK: - A link's view menu (owner 2026-10-26)

/// Writes the person's choice: an ordinary page edit under their name, pinned so Sleep's next rewrite keeps it (owner
/// ruling 4); undo is the page's history, like any edit. The answer is the line the menu shows (nil: nothing to do).
@MainActor
enum LinkViewChange {
    /// `reload` re-reads the page, so the link redraws in its new view at once (the card's body is memoised; before
    /// 2026-10-26 a switch said "Saved" and the page kept drawing the old view until it was reopened).
    static func apply(_ ref: LinkRef, _ view: LinkViewKind, entityId: String,
                      reload: (() async -> Void)? = nil) async -> String? {
        guard let new = LinkCardModel.token(ref, choosing: view) else { return nil }
        do {
            _ = try await APIClient.shared.editPage(entityId: entityId, reason: Copy.Links.reason(view),
                                                    old: ref.markdown, new: new)
            await LinkFactsCache.shared.refresh(entityId)
            await reload?()
            return Copy.Links.savedAs(view)
        } catch let error where SleepRefusal.matches(error) {
            return Copy.Links.busy
        } catch {
            return Copy.Links.couldNotSave
        }
    }
}

/// The views a link's menu offers, as one inline picker — the native menu checks the one the link draws as now — then
/// ↗ and Copy link. Shared by the card's menu, a row's right-click menu and the 🔗 popover.
struct LinkViewMenuItems: View {
    let ref: LinkRef
    let fact: LinkFact
    let entityId: String
    @Binding var status: String?
    /// Titles the picker with the link's words (a right-click menu over a line with several links).
    var titled = false
    @Environment(GraphViewModel.self) private var graphVM: GraphViewModel?

    var body: some View {
        let current = LinkCardModel.current(ref)
        Picker(titled ? ref.shownLabel : Copy.Links.showAs, selection: Binding(get: { current }, set: { chosen in
            guard chosen != current else { return }
            status = Copy.Links.saving
            let graph = graphVM
            Task {
                status = await LinkViewChange.apply(ref, chosen, entityId: entityId) {
                    await graph?.reloadEntity(id: entityId)
                }
            }
        })) {
            ForEach(LinkCardModel.offered(ref, fact: fact), id: \.self) { view in
                Text(Copy.Links.menuName(view, url: ref.url)).tag(view)
            }
        }
        .pickerStyle(.inline)
        Button(Copy.Links.openInBrowser) { LinkOpen.browserOpen(ref.url) }
        Button(Copy.Links.copyLink) { AppPasteboard.copy(ref.url) }
    }
}

/// A link's view menu as a control: Mention, Bookmark, Embed (only when there is something to embed), URL, then the
/// capture views Cicada has — the current one checked. `compact` is the card corner's ⋯ (a 24 pt target on the card's
/// own fill, DR-53/DR-69); otherwise "Show as · Bookmark" in the meta face.
struct LinkViewMenu: View {
    static let side: CGFloat = 24

    let ref: LinkRef
    let fact: LinkFact
    let entityId: String
    var compact = false
    @Binding var status: String?

    var body: some View {
        Menu {
            LinkViewMenuItems(ref: ref, fact: fact, entityId: entityId, status: $status)
        } label: {
            if compact {
                Image(systemName: "ellipsis")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(Self.side), height: CicadaTheme.scaled(Self.side))
            } else {
                Text(Eyebrow.text(Copy.Links.showAs, Copy.Links.menuName(LinkCardModel.current(ref), url: ref.url)))
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(compact ? .hidden : .visible)
        .fixedSize()
        .background {
            if compact { CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus) }
        }
        .help(Copy.Links.menuHelp)
        .accessibilityLabel(Copy.Links.showAs)
        .accessibilityValue(Copy.Links.menuName(LinkCardModel.current(ref), url: ref.url))
    }
}

/// The 🔗 popover's switcher under a link's card: the view menu, then ↗ and Copy link (DR-53), and the line it says.
struct LinkSwitcher: View {
    let ref: LinkRef
    let fact: LinkFact
    let entityId: String

    @State private var status: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                LinkViewMenu(ref: ref, fact: fact, entityId: entityId, status: $status)
                Spacer(minLength: 0)
                IconButton(systemName: "arrow.up.right", help: Copy.Links.openInBrowser) { LinkOpen.browserOpen(ref.url) }
                IconButton(systemName: "doc.on.doc", help: Copy.Links.copyLink) { AppPasteboard.copy(ref.url) }
            }
            if let status {
                Text(status)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }
}

/// The 🔗 gutter button's popover: each link on the line as a bookmark preview, with its view menu under it when the
/// person can change it, and the hint line (P-h: hover is never the only explanation). VoiceOver's path too
/// (`LineLinksAction`); a right-click on the line opens the same choices directly.
struct LinkLinePopover: View {
    let refs: [LinkRef]
    let entityId: String?

    var body: some View {
        ScrollView {
            LinkLineList(refs: refs, entityId: entityId)
        }
        .frame(width: 400)
        .frame(maxHeight: 520)
        .fixedSize(horizontal: false, vertical: true)
        .task { if let entityId { await LinkFactsCache.shared.refresh(entityId) } }
    }
}

/// The popover's content: each link's card, its switcher, then the hint.
struct LinkLineList: View {
    let refs: [LinkRef]
    let entityId: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(Array(refs.enumerated()), id: \.offset) { _, ref in
                let fact = LinkFactsCache.shared.fact(ref.url, on: entityId)
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    BookmarkCard(fact: fact, ref: ref, entityId: entityId)
                    if let entityId, !LinkCardModel.offered(ref, fact: fact).isEmpty {
                        LinkSwitcher(ref: ref, fact: fact, entityId: entityId)
                    }
                }
            }
            Text(Copy.Links.openHint)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingMD)
    }
}

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

/// research-hub's bookmark, on a ring: title (one line), description (two), then mark · site · the date line. The
/// picture is on the left when the card is at least 440 pt wide, on top when narrower (`ViewThatFits`).
struct BookmarkCard: View {
    static let wideMinWidth: CGFloat = 440

    let fact: LinkFact
    var ref: LinkRef? = nil
    var entityId: String? = nil
    /// A degraded view says why in words, under the date line ("No capture of this page yet").
    var status: String? = nil

    @Environment(\.openURL) private var openURL
    @State private var hovering = false

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.cornerRadiusSmall) }
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
                picture.frame(width: 180).frame(maxHeight: .infinity).clipped()
            }
            words
        }
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
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
            Text(LinkCardModel.title(ref, fact: fact))
                .font(CicadaTheme.bodyFont.weight(.semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
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
            }
            .padding(.top, CicadaTheme.scaled(2))
            if let status {
                Text(status)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
    }

    private var footer: String {
        let site = fact.site ?? LinkGrammar.display(fact.url)
        return "\(site) · \(LinkCardModel.dateLine(fact) ?? Copy.Links.notRead)"
    }
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

/// A link alone on its line that asks for a block view: the card for that view, degraded one step and said in words
/// when Cicada has nothing for it yet, then the line's note.
struct LinkBlockView: View {
    let ref: LinkRef
    let note: String?
    let entityId: String?

    var body: some View {
        let fact = LinkFactsCache.shared.fact(ref.url, on: entityId)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            switch ref.asked {
            case .screenshot, .embed:
                if let shot = LinkCardModel.shot(fact, day: ref.day) {
                    CaptureCard(fact: fact, shot: shot, ref: ref, entityId: entityId)
                } else {
                    BookmarkCard(fact: fact, ref: ref, entityId: entityId, status: Copy.Links.noCapture)
                }
            case .captures:
                if fact.captures.isEmpty {
                    BookmarkCard(fact: fact, ref: ref, entityId: entityId, status: Copy.Links.noCaptures)
                } else {
                    CaptureStrip(fact: fact, entityId: entityId)
                }
            case .look:
                if let look = LinkCardModel.look(fact, day: ref.day) {
                    LookSwatch(fact: fact, look: look, entityId: entityId)
                } else {
                    BookmarkCard(fact: fact, ref: ref, entityId: entityId, status: Copy.Links.noLook)
                }
            default:
                BookmarkCard(fact: fact, ref: ref, entityId: entityId)
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

// MARK: - The person's view switcher

/// Text tabs (DR-45) of the views Cicada has something for, then ↗ and Copy link (DR-53). Choosing one is an ordinary
/// page edit under the person's name, pinned so Sleep's next rewrite keeps it (owner ruling 4); undo is the page's
/// history, like any edit.
struct LinkSwitcher: View {
    let ref: LinkRef
    let fact: LinkFact
    let entityId: String
    let inLinks: Bool

    @State private var saving = false
    @State private var message: String?

    private var current: LinkViewKind { LinkCardModel.current(ref, inLinks: inLinks) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingXS) {
                TextTabs(tabs: LinkCardModel.offered(ref, fact: fact).map { TextTab(id: $0, label: Copy.Links.viewName($0)) },
                         selection: Binding(get: { current }, set: { chosen in
                             guard let chosen, chosen != current, !saving else { return }
                             Task { await apply(chosen) }
                         }), showsCounts: false)
                    .disabled(saving)
                    .accessibilityLabel(Copy.Links.showAs)
                Spacer(minLength: 0)
                IconButton(systemName: "arrow.up.right", help: Copy.Links.openInBrowser) { LinkOpen.browserOpen(ref.url) }
                IconButton(systemName: "doc.on.doc", help: Copy.Links.copyLink) { AppPasteboard.copy(ref.url) }
            }
            if let message {
                Text(message)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else if saving {
                Text(Copy.Links.saving)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func apply(_ view: LinkViewKind) async {
        let new = LinkGrammar.markdown(label: ref.label, url: ref.url, view: view,
                                       day: view == ref.asked ? ref.day : nil)
        guard new != ref.markdown else { return }
        saving = true
        defer { saving = false }
        do {
            _ = try await APIClient.shared.editPage(entityId: entityId, reason: Copy.Links.reason(view),
                                                    old: ref.markdown, new: new)
            message = Copy.Links.savedAs(view)
            await LinkFactsCache.shared.refresh(entityId)
        } catch let error where SleepRefusal.matches(error) {
            message = Copy.Links.busy
        } catch {
            message = Copy.Links.couldNotSave
        }
    }
}

/// The 🔗 gutter button's popover: each link on the line as a bookmark preview, with the switcher under it when the
/// person can change it, and the hint line (P-h: hover is never the only explanation). The one path to an inline
/// link's card — SwiftUI `Text` cannot hover per run — and VoiceOver's (`LineLinksAction`).
struct LinkLinePopover: View {
    let refs: [LinkRef]
    let entityId: String?
    let inLinks: Bool

    var body: some View {
        ScrollView {
            LinkLineList(refs: refs, entityId: entityId, inLinks: inLinks)
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
    let inLinks: Bool

    var body: some View {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(Array(refs.enumerated()), id: \.offset) { _, ref in
                    let fact = LinkFactsCache.shared.fact(ref.url, on: entityId)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        BookmarkCard(fact: fact, ref: ref, entityId: entityId)
                        if let entityId, !LinkCardModel.offered(ref, fact: fact).isEmpty {
                            LinkSwitcher(ref: ref, fact: fact, entityId: entityId, inLinks: inLinks)
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

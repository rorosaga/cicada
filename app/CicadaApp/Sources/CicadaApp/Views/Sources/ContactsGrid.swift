import SwiftUI

/// G154 (owner 2026-11-04: "only 6 contacts synced") — every card on this Mac as a grid of faces, read from the backend's
/// book (`contacts_book`) into `ChannelItemsCache`. Nearly every card has no photo, so the grid is drawn to look right
/// as monograms: the people in memory come first and wear their page's picture (`EntityPicture`, its hue ring when it has
/// none) and open that page; a card with no page is a quiet neutral disc that is not a control, with no hover and no press.
struct ContactsGrid: View {
    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(Store.self) private var store: Store?
    @State private var query = ""

    private var refreshKey: Double { store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0 }

    var body: some View {
        Group {
            if let book = cache?.contactsBook {
                if book.total > 0 { content(book) }
            } else if let why = cache?.contactsBookFailure {
                InPlaceNote(text: why)
            } else {
                ListSkeleton(message: Copy.SourceBrowser.loading, rows: 2)
            }
        }
        .task(id: refreshKey) {
            await cache?.refreshContactsBook()
            // The page's status line reads the channel's newest item.
            await cache?.refresh(ContactsReader.channel)
        }
    }

    private func content(_ book: ContactsBook) -> some View {
        let shown = ContactsBookSearch.filter(book.cards, query: query)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                SourceSearchHeader(query: $query, prompt: Copy.SourceBrowser.contactsSearch)
                Text(Copy.SourceBrowser.contactsLine(total: book.total, inMemory: book.inMemory))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .fixedSize()
            }
            if shown.isEmpty {
                InPlaceNote(text: Copy.SourcePage.noMatch(query))
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(ContactsGridMetrics.cell),
                                                       maximum: CicadaTheme.scaled(ContactsGridMetrics.cell + 24)),
                                             spacing: CicadaTheme.spacingSM)],
                          alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(shown) { card in
                        if let page = card.entityId {
                            ContactPageCell(card: card, page: page) {
                                SourcePageRouting.go(.entity(page), router: router, provenance: provenance)
                            }
                        } else {
                            ContactCardCell(card: card, bank: store?.bank ?? "")
                        }
                    }
                }
            }
        }
    }
}

enum ContactsGridMetrics {
    /// A cell's side: the face (48) and the name under it.
    static let cell: CGFloat = 96
    static let face: CGFloat = 48
}

/// A face with its name under it, in one line, the same box for both kinds of cell.
private struct ContactCellLayout<Face: View>: View {
    let name: String
    let ink: Color
    @ViewBuilder let face: Face

    var body: some View {
        VStack(spacing: CicadaTheme.spacingXS) {
            face
            Text(name)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(ink)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingXS)
    }
}

/// A card with a page: the page's picture and its hue, hover a fill (DR-48), a click opens the page.
struct ContactPageCell: View {
    let card: ContactsBookCard
    let page: String
    let open: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var title: String { ContactsBookText.title(card) }

    var body: some View {
        Button(action: open) {
            ContactCellLayout(name: title, ink: CicadaTheme.textPrimary) {
                EntityPicture(id: page, name: title, type: .person, size: ContactsGridMetrics.face)
            }
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.SourceBrowser.contactHelp(title))
        .accessibilityLabel(title)
        .accessibilityHint(Copy.SourceBrowser.contactHelp(title))
    }
}

/// A card with no page: its photo, else a neutral monogram, in secondary ink. Nothing to do here, so nothing invites it.
struct ContactCardCell: View {
    let card: ContactsBookCard
    let bank: String

    @State private var image: NSImage?

    private var title: String { ContactsBookText.title(card) }

    var body: some View {
        ContactCellLayout(name: title, ink: card.name.isEmpty ? CicadaTheme.textTertiary : CicadaTheme.textSecondary) {
            face
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityAddTraits(.isStaticText)
    }

    private var face: some View {
        let side = CicadaTheme.scaled(ContactsGridMetrics.face)
        return ZStack {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: .fill)
                    .frame(width: side, height: side)
            } else {
                Circle().fill(CicadaTheme.bgFocus)
                let type = EntityPictureLayout.initialsType(units: ContactsGridMetrics.face, compact: false)
                Text(LogoImage.monogram(for: card.name))
                    .font(CicadaTheme.font(size: type.size, weight: type.weight))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }
        }
        .frame(width: side, height: side)
        .clipShape(Circle())
        .overlay { if image != nil { Circle().stroke(CicadaTheme.ring(.resting), lineWidth: 1) } }
        .task(id: card.photo) {
            guard let path = SourcePictures.contactPhotoPath(key: card.key, photo: card.photo) else { image = nil; return }
            image = await SourcePictureStore.shared.image(path: path, bank: bank)
        }
    }
}

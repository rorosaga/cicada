import SwiftUI

/// ROR-118 (owner, Sources round 1: "adding a source is an overlay with a Yours strip on top and everything else below")
/// — one overlay for every way in. *Yours* first (what is already connected, one tap to its page), then a search, the
/// every source that could still be added, grouped by kind, each with a "+" (round 3: no tabs, two columns of rows). A tap closes the overlay and opens
/// that source's page, where its own connect card lives; nothing here connects anything by itself. The scrim is the
/// shared scrim (DR-37); Esc and a tap outside close it (DR-28); the panel eases in on the panel curve and a key
/// never animates (DR-60).
struct SourceAddOverlay: View {
    let rows: [SourceCatalogRow]
    let open: (SourceCatalogRow) -> Void
    let close: () -> Void

    /// The kind the overlay opened on (nil: every kind). Round 3: no tabs, so a "+" beside a kind shows just that kind and
    /// the page's own "Add source" shows all of them, grouped.
    private let shelf: SourceShelf?
    @State private var query = ""

    init(rows: [SourceCatalogRow], shelf: SourceShelf?, open: @escaping (SourceCatalogRow) -> Void,
         close: @escaping () -> Void) {
        self.rows = rows
        self.open = open
        self.close = close
        self.shelf = shelf
    }

    /// *Yours* leads the full overlay only; opened on one kind it is that kind's additions and nothing else.
    private var yours: [SourceCatalogRow] { shelf == nil ? SourceShelves.yours(rows) : [] }
    private var groups: [SourceShelves.Shelf] { SourceShelves.addGroups(rows, shelf: shelf, query: query) }

    var body: some View {
        ZStack {
            CicadaTheme.scrim
                .ignoresSafeArea()
                .onTapGesture { close() }
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                header
                if !yours.isEmpty && !SourceGrid.isSearching(query) { yoursStrip }
                CicadaSearchField(text: $query, prompt: Copy.Catalog.searchPrompt, findEnabled: false,
                                  autofocus: true, onEscape: close)
                    .frame(width: CicadaTheme.scaled(260))
                ScrollView { list.padding(.bottom, CicadaTheme.spacingMD) }
                    .scrollBounceBehavior(.basedOnSize)
            }
            .padding(CicadaTheme.spacingXL)
            .frame(maxWidth: CicadaTheme.scaled(760), maxHeight: CicadaTheme.scaled(680), alignment: .topLeading)
            .background(CicadaTheme.surface, in: CicadaTheme.shape(CicadaTheme.radiusLarge))
            .overlay(CicadaTheme.shape(CicadaTheme.radiusLarge).stroke(CicadaTheme.border, lineWidth: 1))
            .padding(CicadaTheme.spacingXL)
        }
        .onKeyPress(.escape) { close(); return .handled }
        .accessibilityAddTraits(.isModal)
    }

    private var header: some View {
        HStack {
            Text(Copy.Shelf.addTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Spacer()
            Button(action: close) {
                Image(systemName: "xmark").font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .keyboardShortcut(.cancelAction)
            .help(Copy.Shelf.close)
            .accessibilityLabel(Copy.Shelf.close)
        }
    }

    /// What is connected, as marks with a green dot: the same tile the page's rows wear, in one scrolling line.
    private var yoursStrip: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Shelf.yours)
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    ForEach(yours) { row in YoursTile(row: row) { open(row) } }
                }
                .padding(.trailing, CicadaTheme.spacingSM)
            }
            .scrollIndicators(.hidden)
            Divider().overlay(CicadaTheme.border).padding(.top, CicadaTheme.spacingXS)
        }
    }

    @ViewBuilder
    private var list: some View {
        if groups.isEmpty {
            Text(SourceGrid.isSearching(query) ? Copy.Catalog.noMatch(query.trimmingCharacters(in: .whitespacesAndNewlines))
                                               : Copy.Shelf.nothingToAdd)
                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                ForEach(groups, id: \.shelf) { group in
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        SectionLabel(group.shelf.title)
                        LazyVGrid(columns: [GridItem(.flexible(), spacing: CicadaTheme.spacingLG, alignment: .topLeading),
                                            GridItem(.flexible(), alignment: .topLeading)],
                                  alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            ForEach(group.addable) { row in AddRow(row: row) { open(row) } }
                        }
                    }
                }
            }
        }
    }
}

/// A source that could be added: the tile, the name, and a "+" at the end. Never drawn for a connected one, so a "+" is
/// what "not connected" looks like here. Calendar carries its one honest note.
private struct AddRow: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                SourceLogoTile(origin: row.entry.origin)
                VStack(alignment: .leading, spacing: 1) {
                    Text(row.entry.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if row.entry.id == "calendar-local" {
                        Text(Copy.Shelf.calendarNote).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                Image(systemName: "plus").font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(52), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .accessibilityLabel(row.entry.title)
    }
}

/// A connected source in *Yours*: its logo tile with a green dot, and its name under it, the whole thing one tap.
private struct YoursTile: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            VStack(spacing: CicadaTheme.scaled(6)) {
                SourceLogoTile(origin: row.entry.origin)
                    .overlay(alignment: .bottomTrailing) {
                        Circle().fill(CicadaTheme.success).frame(width: CicadaTheme.scaled(9), height: CicadaTheme.scaled(9))
                            .overlay(Circle().stroke(CicadaTheme.surface, lineWidth: 2))
                            .offset(x: 3, y: 3)
                    }
                Text(row.entry.title).font(CicadaTheme.captionFont)
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1).frame(width: CicadaTheme.scaled(96))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(row.entry.title)
    }
}

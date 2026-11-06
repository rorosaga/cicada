import SwiftUI

/// ROR-118 (owner, Sources round 1: "adding a source is an overlay with a Yours strip on top and everything else below")
/// — one overlay for every way in. *Yours* first (what is already connected, one tap to its page), then a search, the
/// every source that could still be added, grouped by kind, as the same plain tiles the page draws (round 5: no "+", no rows). A tap closes the overlay and opens
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
                    // The list runs on under the panel's edge: it fades there instead of being cut mid-row.
                    .mask(VStack(spacing: 0) {
                        Rectangle()
                        LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom)
                            .frame(height: CicadaTheme.scaled(28))
                    })
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

    /// Columns for the *Yours* strip: one row up to six marks, else the fewest rows at six, spread evenly.
    static func yoursColumns(_ count: Int, perRow: Int = 6) -> Int {
        guard count > perRow else { return max(1, count) }
        let rows = (count + perRow - 1) / perRow
        return (count + rows - 1) / rows
    }

    /// What is connected, as marks: the same tile the page's rows wear, wrapped in a grid so no name is ever cut off.
    private var yoursStrip: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Shelf.yours)
            // Balanced rows: 7 marks are 4 + 3, never 6 + one name alone on a second line.
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(minimum: CicadaTheme.scaled(104)),
                                                         spacing: CicadaTheme.spacingSM, alignment: .top),
                                     count: Self.yoursColumns(yours.count)),
                      alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(yours) { row in YoursTile(row: row) { open(row) } }
            }
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
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.scaled(SourceShelfLayout.gap),
                                                                     alignment: .topLeading), count: 3),
                                  alignment: .leading, spacing: CicadaTheme.scaled(SourceShelfLayout.gap)) {
                            ForEach(group.addable) { row in SourceAddTile(row: row) { open(row) } }
                        }
                    }
                }
            }
        }
    }
}

/// A connected source in *Yours*: its logo tile and its name under it (every one here is connected, so no dot), the whole thing one tap.
private struct YoursTile: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            VStack(spacing: CicadaTheme.scaled(6)) {
                SourceLogoTile(origin: row.entry.origin)
                Text(row.entry.title).font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1).frame(maxWidth: .infinity)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(row.entry.title)
    }
}

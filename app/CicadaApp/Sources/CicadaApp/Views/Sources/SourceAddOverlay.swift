import SwiftUI

/// ROR-118 (owner, Sources round 1: "adding a source is an overlay with a Yours strip on top and everything else below")
/// — one overlay for every way in. *Yours* first (what is already connected, one tap to its page), then a search, the
/// six kinds as tabs, and every source that could still be added, grouped by kind. A tap closes the overlay and opens
/// that source's page, where its own connect card lives; nothing here connects anything by itself. The scrim is the
/// shared scrim (DR-37); Esc and a tap outside close it (DR-28); the panel eases in on the panel curve and a key
/// never animates (DR-60).
struct SourceAddOverlay: View {
    let rows: [SourceCatalogRow]
    let open: (SourceCatalogRow) -> Void
    let close: () -> Void

    @State private var shelf: SourceShelf?
    @State private var query = ""

    init(rows: [SourceCatalogRow], shelf: SourceShelf?, open: @escaping (SourceCatalogRow) -> Void,
         close: @escaping () -> Void) {
        self.rows = rows
        self.open = open
        self.close = close
        _shelf = State(initialValue: shelf)
    }

    private var yours: [SourceCatalogRow] { SourceShelves.yours(rows) }
    private var groups: [SourceShelves.Shelf] { SourceShelves.addGroups(rows, shelf: shelf, query: query) }

    private var tabs: [TextTab<SourceShelf>] {
        let all = SourceShelves.shelves(rows)
        return [TextTab(id: nil, label: Copy.Shelf.all, count: all.reduce(0) { $0 + $1.addable.count })]
            + all.filter { !$0.addable.isEmpty }.map { TextTab(id: $0.shelf, label: $0.shelf.title, count: $0.addable.count) }
    }

    private let columns = [GridItem(.adaptive(minimum: CicadaTheme.scaled(230)), spacing: CicadaTheme.spacingSM,
                                    alignment: .leading)]

    var body: some View {
        ZStack {
            CicadaTheme.scrim
                .ignoresSafeArea()
                .onTapGesture { close() }
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                header
                if !yours.isEmpty { yoursStrip }
                HStack(spacing: CicadaTheme.spacingMD) {
                    CicadaSearchField(text: $query, prompt: Copy.Catalog.searchPrompt, findEnabled: false,
                                      autofocus: true, onEscape: close)
                        .frame(width: CicadaTheme.scaled(220))
                    TextTabs(tabs: tabs, selection: $shelf)
                    Spacer(minLength: 0)
                }
                ScrollView { list.padding(.bottom, CicadaTheme.spacingMD) }
                    .scrollBounceBehavior(.basedOnSize)
            }
            .padding(CicadaTheme.spacingXL)
            .frame(maxWidth: CicadaTheme.scaled(880), maxHeight: CicadaTheme.scaled(680), alignment: .topLeading)
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

    private var yoursStrip: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Shelf.yours, count: yours.count)
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                    ForEach(yours) { row in YoursTile(row: row) { open(row) } }
                }
            }
            .scrollIndicators(.hidden)
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
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                ForEach(groups, id: \.shelf) { group in
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        if shelf == nil { SectionLabel(group.shelf.title) }
                        LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingXS) {
                            ForEach(group.addable) { row in AddRow(row: row) { open(row) } }
                        }
                    }
                }
            }
        }
    }
}

/// A connected source in *Yours*: its logo tile and its name under it, the whole thing one tap.
private struct YoursTile: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            VStack(spacing: CicadaTheme.scaled(6)) {
                SourceLogoTile(origin: row.entry.origin)
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

/// A source that could be added: the logo tile and the name, "On this Mac" when its app is here.
private struct AddRow: View {
    let row: SourceCatalogRow
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                SourceLogoTile(origin: row.entry.origin)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(row.entry.title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if row.suggested {
                        Text(Copy.Shelf.onThisMac).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: false, cornerRadius: CicadaTheme.cornerRadius)
        .accessibilityLabel(row.entry.title)
    }
}

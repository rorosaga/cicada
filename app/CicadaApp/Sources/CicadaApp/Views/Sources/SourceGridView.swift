import SwiftUI

/// ROR-7 (G217, G161) — what the Sources root's field holds. The page keeps it, so the words outlive an opened source:
/// Esc from a source's page returns to the same results.
struct SourceGridSearch: Equatable {
    var text = ""
    /// The tile ↑/↓ moved to; nil is the best result (`SourceGrid.highlighted`).
    var cursor: String?
}

/// One source as its app (owner: "each source as its app, with its icon, rather than a list"): the one logo tile (DR-52),
/// the name, one line only when it says something. On `bgFocus` with the resting ring and no shadow (DR-9); hover is a
/// fill (DR-48, DR-63), and a key's highlight never eases (DR-60).
struct SourceAppTile: View {
    let row: SourceCatalogRow
    var highlighted = false
    let now: Date
    let open: () -> Void

    @State private var hovering = false

    private var shape: some InsettableShape { CicadaTheme.shape(CicadaTheme.cornerRadius) }

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.scaled(12)) {
                SourceLogoTile(origin: row.entry.origin)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(row.entry.title)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let line = SourceGrid.line(row, now: now) {
                        StatusWord(word: line.word, tone: line.tone).monospacedDigit()
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.scaled(12))
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: CicadaTheme.scaled(RowMetrics.sourceTile))
            .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, selected: highlighted, cornerRadius: CicadaTheme.cornerRadius)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: shape)
        .help(row.help)
        .accessibilityLabel(row.status == .off && row.waitingOn == nil && !row.notInstalled
                                ? row.entry.title : "\(row.entry.title), \(row.word)")
        .accessibilityAddTraits(highlighted ? .isSelected : [])
    }
}

/// The root: *Needs you*, *Connected*, *Suggested*, then what could be added by what it is; or, with words in the field,
/// what they find, best first, with no headings. A window of any width takes as many columns as fit (DR-70: scaled).
struct SourceGridView: View {
    let rows: [SourceCatalogRow]
    let search: SourceGridSearch
    let open: (SourcesSelection) -> Void
    /// The empty search's one way on: what the person looks for may arrive as a file.
    let importFiles: () -> Void

    private var columns: [GridItem] {
        [GridItem(.adaptive(minimum: CicadaTheme.scaled(SourceGrid.tileMinWidth)), spacing: CicadaTheme.spacingSM,
                  alignment: .leading)]
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            if SourceGrid.isSearching(search.text) {
                results(now: context.date)
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                    ForEach(SourceGrid.sections(rows), id: \.section) { group in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            SectionLabel(group.section.title)
                            grid(group.rows, highlighted: nil, now: context.date)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func results(now: Date) -> some View {
        let found = SourceGrid.results(rows, query: search.text)
        if found.isEmpty {
            EmptyStateView(title: Copy.Catalog.noMatch(search.text.trimmingCharacters(in: .whitespacesAndNewlines)),
                           message: "", actionLabel: Copy.Catalog.importChatsOrFiles, action: importFiles)
        } else {
            grid(found, highlighted: SourceGrid.highlighted(found, cursor: search.cursor), now: now)
        }
    }

    private func grid(_ rows: [SourceCatalogRow], highlighted: String?, now: Date) -> some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(rows) { row in
                SourceAppTile(row: row, highlighted: row.id == highlighted, now: now) { open(.entry(row.id)) }
                    .id(SourcesSelection.entry(row.id))
            }
        }
    }
}

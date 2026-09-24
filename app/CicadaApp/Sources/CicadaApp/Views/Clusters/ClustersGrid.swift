import SwiftUI

/// F-11 (G146 plan R-PE12) — All with nothing open, as mock A's icon-led cards, pure: which cards share a row, how
/// many tiles each shows, and the order the keys walk.
enum ClustersGrid {
    /// The six that get a full card, two to a row.
    static let primary: [EntityType] = [.person, .project, .company, .tool, .concept, .media]
    static let firstRowTiles = 6
    static let laterRowTiles = 4
    static let shortLines = 2

    enum Row: Equatable, Identifiable {
        case pair([EntityType])
        case short([EntityType])

        var types: [EntityType] {
            switch self {
            case .pair(let types), .short(let types): types
            }
        }

        var id: String {
            switch self {
            case .pair(let types): "pair:" + types.map(\.rawValue).joined(separator: ",")
            case .short(let types): "short:" + types.map(\.rawValue).joined(separator: ",")
            }
        }
    }

    /// Full cards two to a row, the rest three to a short row; *Expand all* puts each card on its own row.
    static func rows(_ groups: [ClustersModel.Group], expandAll: Bool) -> [Row] {
        let present = groups.map(\.type)
        if expandAll { return present.map { .pair([$0]) } }
        let full = present.filter { primary.contains($0) }
        let rest = present.filter { !primary.contains($0) }
        let pairs = stride(from: 0, to: full.count, by: 2).map { Row.pair(Array(full[$0..<min($0 + 2, full.count)])) }
        let shorts = stride(from: 0, to: rest.count, by: 3).map { Row.short(Array(rest[$0..<min($0 + 3, rest.count)])) }
        return pairs + shorts
    }

    /// F-11's counts: 6 tiles in the first row of full cards, 4 after, 2 lines in a short card; nil = every tile.
    static func budget(_ row: Row, index: Int, expandAll: Bool) -> Int? {
        if expandAll { return nil }
        switch row {
        case .pair: return index == 0 ? firstRowTiles : laterRowTiles
        case .short: return shortLines
        }
    }

    /// DR-68 — what ↑/↓ walk: every drawn tile in reading order, row by row, card by card.
    static func visible(_ groups: [ClustersModel.Group], tab: EntityType?, expandAll: Bool) -> [Entity] {
        if let tab { return groups.first { $0.type == tab }?.entities ?? [] }
        let byType = Dictionary(groups.map { ($0.type, $0.entities) }, uniquingKeysWith: { first, _ in first })
        return rows(groups, expandAll: expandAll).enumerated().flatMap { index, row in
            row.types.flatMap { type -> [Entity] in
                let all = byType[type] ?? []
                return budget(row, index: index, expandAll: expandAll).map { Array(all.prefix($0)) } ?? all
            }
        }
    }

    /// One full-width card's columns: 2 under 900 units, 3 under 1300, 4 beyond — so ⌘+ narrows it (DR-70).
    static func tabColumns(width: CGFloat, scale: CGFloat) -> Int {
        let units = width / max(scale, 0.1)
        return units < 900 ? 2 : (units < 1300 ? 3 : 4)
    }
}

/// STATE 0 of Clusters (F-11): the cards, or a type tab's one card. The eyebrow, the View menu and the columns are the
/// page's, unchanged (R-PE12). Find is NOT drawn here: ⌘F hands the page to the list column (its ranked rows, and its
/// one `PageFindRow`), because a find row that lived in both views would be rebuilt on the first keystroke — the
/// `found == nil → non-nil` flip swaps the views — and `CicadaSearchField(autofocus:)` re-focusing a new field selects
/// its text, so the second keystroke would replace the first.
struct ClustersGridView: View {
    let groups: [ClustersModel.Group]
    let tab: EntityType?
    let expandAll: Bool
    let gutter: CGFloat
    let open: (Entity) -> Void
    let showTab: (EntityType) -> Void
    let move: (Int) -> Void
    let escape: () -> Void

    var body: some View {
        GeometryReader { geo in
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    let columns = ClustersGrid.tabColumns(width: geo.size.width - gutter * 2,
                                                          scale: CGFloat(CicadaTheme.uiScale))
                    if let tab, let group = groups.first(where: { $0.type == tab }) {
                        ClusterCard(group: group, shown: group.entities, columns: columns, open: open, showAll: nil)
                    } else {
                        let rows = ClustersGrid.rows(groups, expandAll: expandAll)
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                            rowView(row, index: index, wideColumns: columns)
                        }
                    }
                }
                .padding(.horizontal, gutter)
                .padding(.bottom, CicadaTheme.scaled(72))
            }
        }
        .listKeys(move: move, enter: { false }, escape: escape)
    }

    @ViewBuilder
    private func rowView(_ row: ClustersGrid.Row, index: Int, wideColumns: Int) -> some View {
        let budget = ClustersGrid.budget(row, index: index, expandAll: expandAll)
        HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
            ForEach(row.types, id: \.self) { type in
                if let group = groups.first(where: { $0.type == type }) {
                    let shown = budget.map { Array(group.entities.prefix($0)) } ?? group.entities
                    switch row {
                    case .pair:
                        ClusterCard(group: group, shown: shown, columns: expandAll ? wideColumns : 2, open: open,
                                    showAll: { showTab(type) })
                    case .short:
                        ClusterShortCard(group: group, shown: shown, open: open, showAll: { showTab(type) })
                    }
                }
            }
            // A lone card keeps its share of the row, so a row of one never stretches (F-11's columns).
            let slots: Int = {
                switch row {
                case .pair: return expandAll ? 1 : 2
                case .short: return 3
                }
            }()
            ForEach(0..<max(slots - row.types.count, 0), id: \.self) { _ in
                Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
            }
        }
    }
}

/// A type's card header (F-11): its outline glyph in its hue, its plural name, its count, "Show all ›" when some are
/// hidden. The hue appears once, on the glyph (DR-8).
struct ClusterCardHeader: View {
    let type: EntityType
    let count: Int
    let showAll: (() -> Void)?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: EntityPictureLayout.glyph(type))
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.entityColor(for: type))
                .accessibilityHidden(true)
            Text(type.groupLabel)
                .font(CicadaTheme.font(size: 14, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(UsageFormat.count(count))
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: 0)
            if let showAll {
                TextButton(title: Copy.People.showAll, help: Copy.People.showAllHelp(type.groupLabel), action: showAll)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(28))
        .accessibilityElement(children: .contain)
    }
}

/// A full card (F-11): the header over 56 pt tiles, two to a row — or `columns` in a tab or under *Expand all*.
struct ClusterCard: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    var columns = 2
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ClusterCardHeader(type: group.type, count: group.entities.count,
                              showAll: shown.count < group.entities.count ? showAll : nil)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingSM, alignment: .leading),
                                     count: max(columns, 1)),
                      alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                ForEach(shown) { entity in
                    ClusterTile(entity: entity) { open(entity) }.id(entity.id)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }
}

/// A short card (F-11's Skills · Places · Folders): one-line rows, a 20 pt picture, the name and its line.
struct ClusterShortCard: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let open: (Entity) -> Void
    let showAll: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            ClusterCardHeader(type: group.type, count: group.entities.count,
                              showAll: shown.count < group.entities.count ? showAll : nil)
            ForEach(shown) { entity in
                Button { open(entity) } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 20)
                        Text(entity.name)
                            .font(CicadaTheme.font(size: 13))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        if let line = ClustersModel.line(entity) {
                            Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                    .frame(height: CicadaTheme.scaled(RowMetrics.titleOnly))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.name, open: false))
                .id(entity.id)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }
}

/// A tile (F-11): the picture, the name, one line in words. The words open the card; the picture and, on hover, a
/// "Change picture…" beside the words (never inside the link) open the image picker (R-PE15). Hover is a fill (DR-63).
struct ClusterTile: View {
    let entity: Entity
    let open: () -> Void

    @Environment(Store.self) private var store
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 32, heldInputs: entity.pictureInputs,
                          editing: .tile)
            Button(action: open) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(entity.name)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if let line = ClustersModel.line(entity) {
                        Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.name, open: false))
            if hovering, PictureActions.canEdit(entity.type) {
                NeutralButton(title: Copy.People.changePicture, systemImage: "square.and.arrow.up", size: .compact) {
                    PictureActions.change(id: entity.id, name: entity.name, type: entity.type, store: store,
                                          inputs: store.pictureInputs(for: entity.id, held: entity.pictureInputs))
                }
                .fixedSize()
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine),
               maxHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
    }
}

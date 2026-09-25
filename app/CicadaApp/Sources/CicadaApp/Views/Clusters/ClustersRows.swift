import SwiftUI

/// §5.3 / §10 — the Clusters list in its three styles: one line while find is open (STATE 0 is the grid, F-11), two
/// lines beside a card, titles beside a card and the Reader. Each row its picture and, beside a card, its age
/// (R-PE12, reversing R-DL11) — a picture or a glyph, never a dot beside it (DR-48). Selection is `bgSelected`, never
/// the accent.
struct ClustersListColumn: View {
    let lines: [ClustersModel.ClusterLine]
    let style: ColumnPlan.ListStyle
    let query: String
    @Binding var findOpen: Bool
    @Binding var findText: String
    let state: ClustersListState
    let openId: String?
    let landingToken: Int
    let open: (Entity) -> Void
    let showTab: (EntityType) -> Void
    let move: (Int) -> Void
    let focusDetail: () -> Void
    let escape: () -> Void
    let showEverything: () -> Void

    var body: some View {
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // DR-46 — the find row sits above the scroll, never in the lazy stack: a lazy row scrolled far away is
                // released, and the field would take its focus and its ⌘F publisher with it.
                if findOpen {
                    PageFindRow(text: $findText, isOpen: $findOpen, prompt: Copy.Lists.findClusters)
                        .padding(EdgeInsets(top: 0, leading: ListInsets.of(style).leading, bottom: CicadaTheme.spacingSM,
                                            trailing: ListInsets.of(style).trailing))
                }
                ScrollView {
                    LazyVStack(alignment: .leading,
                               spacing: style == .triage ? CicadaTheme.scaled(RowMetrics.twoLineGap) : 0) {
                        switch state {
                        case .loading:
                            ListSkeleton(message: Copy.Lists.readingMemory)
                        case .empty:
                            EmptyStateView(title: "Nothing here yet", message: Copy.emptyGraphMessage,
                                           actionLabel: "Open Integrations", settingsSection: .integrations)
                        case .nothingInView:
                            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                                Text(Copy.Lists.nothingInView)
                                    .font(CicadaTheme.detailBodyFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                TextButton(title: Copy.Lists.showEverything, action: showEverything)
                                    .padding(.leading, -CicadaTheme.scaled(10))
                            }
                            .padding(.horizontal, CicadaTheme.scaled(10))
                        case .noMatch:
                            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                                Text(Copy.Lists.noEntityMatch(SearchAllMemoryRow.trimmed(query)))
                                    .font(CicadaTheme.detailBodyFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                SearchAllMemoryRow(query: query)
                            }
                            .padding(.horizontal, CicadaTheme.scaled(10))
                        case .list:
                            ForEach(lines) { line in lineView(line).id(line.id) }
                        }
                    }
                    .padding(ListInsets.of(style))
                }
                .onChange(of: landingToken) { _, _ in
                    guard let openId else { return }
                    Instant.run { proxy.scrollTo(openId, anchor: .center) }
                }
                .onChange(of: openId) { _, id in
                    guard let id else { return }
                    Instant.run { proxy.scrollTo(id) }
                }
            }
        }
        .listKeys(move: move, enter: {
            guard openId != nil else { return false }
            focusDetail()
            return true
        }, escape: escape)
    }

    @ViewBuilder
    private func lineView(_ line: ClustersModel.ClusterLine) -> some View {
        switch line {
        case .header(let type, let count, let first, let recency):
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: EntityPictureLayout.glyph(type))
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.entityColor(for: type))
                    .accessibilityHidden(true)
                Text(type.groupLabel)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(UsageFormat.count(count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                if recency {
                    Text(Copy.People.recencySuffix).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.top, first ? 0 : CicadaTheme.scaled(14))
            .padding(.bottom, CicadaTheme.scaled(6))
            .accessibilityElement(children: .combine)
        case .row(let entity, let showsType):
            ClusterRow(entity: entity, showsType: showsType,
                       highlight: findOpen ? ClusterSearchIndex.titleRanges(entity.name, query: query) : [],
                       style: style, selected: entity.id == openId) { open(entity) }
        case .more(let type, let count):
            TextButton(title: Copy.Lists.showAll(count)) { showTab(type) }
                .padding(.leading, CicadaTheme.scaled(2))
        }
    }
}

/// What the list column says before it has rows to draw, in precedence order.
enum ClustersListState: Equatable {
    case loading, empty, nothingInView, noMatch, list

    static func of(hasEntities: Bool, isLoading: Bool, groupsEmpty: Bool, matches: [Entity]?) -> ClustersListState {
        if !hasEntities { return isLoading ? .loading : .empty }
        if let matches { return matches.isEmpty ? .noMatch : .list }
        return groupsEmpty ? .nothingInView : .list
    }
}

/// DR-8 — a type's hue once per item, as one 8 pt dot; never a tile or a pill fill.
struct TypeDot: View {
    let type: EntityType
    var body: some View {
        Circle().fill(CicadaTheme.entityColor(for: type))
            .frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
            .accessibilityHidden(true)
    }
}

/// One entity in the list. The whole row opens it; the chevron is its visible twin (outside the row's button — a
/// button nested in a button is two targets for one click).
struct ClusterRow: View {
    let entity: Entity
    let showsType: Bool
    var highlight: [[Int]] = []
    let style: ColumnPlan.ListStyle
    let selected: Bool
    let open: () -> Void

    private var nameColor: Color { selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary }
    private var metaColor: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(action: open) {
                content
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.name, open: selected))
            .accessibilityAddTraits(selected ? .isSelected : [])
            if style == .wide {
                IconButton(systemName: "chevron.right", help: Copy.Lists.openCard, action: open)
                    .accessibilityHidden(true)
            }
        }
        .listRowSurface(height: ListRowSurface.height(style), selected: selected)
    }

    private var name: some View {
        Text(ExcerptText.attributed(entity.name, bold: highlight))
            .font(CicadaTheme.font(size: 13, weight: selected ? .medium : .regular))
            .foregroundStyle(nameColor)
            .lineLimit(1)
    }

    @ViewBuilder
    private var content: some View {
        switch style {
        case .wide:   // only while find is open (All's groups, then its ranked matches); STATE 0 is the grid
            HStack(spacing: CicadaTheme.spacingMD) {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 24)
                name.frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
                if let detail = ClustersModel.detail(entity, showsType: showsType) {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(metaColor).lineLimit(1)
                }
                Spacer(minLength: 0)
            }
        case .triage:   // F-12's list: picture, name, age; the line under them
            HStack(spacing: CicadaTheme.spacingMD) {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 32)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        name
                        Spacer(minLength: 0)
                        Text(ClustersModel.age(entity, today: ISODay.today()))
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(metaColor)
                    }
                    if let detail = ClustersModel.detail(entity, showsType: showsType) {
                        Text(detail).font(CicadaTheme.metaFont).foregroundStyle(metaColor).lineLimit(1)
                    }
                }
            }
        case .titles, .hidden:
            HStack(spacing: CicadaTheme.spacingSM) {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 20)
                name.help(entity.name)
            }
        }
    }
}

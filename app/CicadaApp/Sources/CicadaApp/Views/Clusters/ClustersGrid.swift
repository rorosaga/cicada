import SwiftUI

/// F-11 (G146 plan R-PE12) — All with nothing open, pure: which sections share a row, how many tiles each shows, and
/// the order the keys walk. ROR-118 round 1: the page leads with faces (people as a strip of portraits), then project
/// cards, then flat name lists for companies, tools and concepts, then media; six identical cards are gone.
enum ClustersGrid {
    /// The six that get a full section.
    static let primary: [EntityType] = [.person, .project, .company, .tool, .concept, .media]
    /// The trio that share one row of flat name lists.
    static let lists: [EntityType] = [.company, .tool, .concept]
    static let faces = 8
    static let leadCards = 3
    static let listNames = 5
    static let galleryNames = 6
    static let shortLines = 2

    enum Row: Equatable, Identifiable {
        /// People as a strip of portraits.
        case faces([EntityType])
        /// Projects as a row of cards, each with its one line.
        case lead([EntityType])
        /// Companies, tools, concepts: flat lists of names side by side.
        case trio([EntityType])
        /// Media: whole titles on up to two lines, a thumbnail only where one exists.
        case gallery([EntityType])
        /// One full card — Expand all's row, one per type.
        case pair([EntityType])
        case short([EntityType])

        var types: [EntityType] {
            switch self {
            case .faces(let t), .lead(let t), .trio(let t), .gallery(let t), .pair(let t), .short(let t): t
            }
        }

        var id: String {
            let kind: String
            switch self {
            case .faces: kind = "faces"
            case .lead: kind = "lead"
            case .trio: kind = "trio"
            case .gallery: kind = "gallery"
            case .pair: kind = "pair"
            case .short: kind = "short"
            }
            return kind + ":" + types.map(\.rawValue).joined(separator: ",")
        }
    }

    /// Faces, project cards, the name lists and media in that order; the rest three to a short row; *Expand all* puts
    /// each card on its own row.
    static func rows(_ groups: [ClustersModel.Group], expandAll: Bool) -> [Row] {
        let present = groups.map(\.type)
        if expandAll { return present.map { .pair([$0]) } }
        var out: [Row] = []
        if present.contains(.person) { out.append(.faces([.person])) }
        if present.contains(.project) { out.append(.lead([.project])) }
        let trio = lists.filter(present.contains)
        if !trio.isEmpty { out.append(.trio(trio)) }
        if present.contains(.media) { out.append(.gallery([.media])) }
        let rest = present.filter { !primary.contains($0) }
        out += stride(from: 0, to: rest.count, by: 3).map { Row.short(Array(rest[$0..<min($0 + 3, rest.count)])) }
        return out
    }

    /// How many each section shows; nil = every one.
    static func budget(_ row: Row, index: Int, expandAll: Bool) -> Int? {
        if expandAll { return nil }
        switch row {
        case .faces: return faces
        case .lead: return leadCards
        case .trio: return listNames
        case .gallery: return galleryNames
        case .short: return shortLines
        case .pair: return nil
        }
    }

    /// The project cards' columns: one under 900 units, else three.
    static func leadColumns(width: CGFloat, scale: CGFloat) -> Int {
        width / max(scale, 0.1) < 900 ? 1 : leadCards
    }

    /// The portraits' columns: 4 (two rows) under 900 units, else one row of 8.
    static func faceColumns(width: CGFloat, scale: CGFloat) -> Int {
        width / max(scale, 0.1) < 900 ? 4 : faces
    }

    /// A page with a picture to draw: not "use initials", which is the person's choice of no picture.
    @MainActor
    static func isPictured(_ entity: Entity, store: Store) -> Bool {
        guard let picture = store.picture(for: entity.id, held: entity.pictureRef) else { return false }
        return picture.source != .initials
    }

    /// ROR-118 round 3 — what a section shows, in the order it draws. People: of the most recent few, the ones with a
    /// photo first, so the strip reads photos then initials, never one then the other at random. The name lists and
    /// Media: the dimmed ones ("not mentioned yet") last, so the dimming is one block and never a flicker between
    /// neighbours; they arrange the whole group first and take what fits. A stable partition: each part keeps the
    /// model's order. Projects and the rest are untouched.
    static func shown(_ all: [Entity], type: EntityType, row: Row, budget: Int?, pictured: (Entity) -> Bool) -> [Entity] {
        switch row {
        case .faces:
            let recent = budget.map { Array(all.prefix($0)) } ?? all
            return recent.enumerated().sorted { a, b in
                let (pa, pb) = (pictured(a.element), pictured(b.element))
                return pa != pb ? pa : a.offset < b.offset
            }.map(\.element)
        case .trio, .gallery:
            let ordered = all.enumerated().sorted { a, b in
                a.element.quiet != b.element.quiet ? !a.element.quiet : a.offset < b.offset
            }.map(\.element)
            return budget.map { Array(ordered.prefix($0)) } ?? ordered
        default:
            return budget.map { Array(all.prefix($0)) } ?? all
        }
    }

    /// Round 5 — Media's columns, filled down: the first `ceil(n / columns)` titles are the first column, and so on. The
    /// layout draws these columns and the keys walk their concatenation (`visible`), so ↓ goes to the title under the
    /// one it left and, at a column's foot, to the top of the next column — what the eye sees, one function for both.
    static func columnMajor<T>(_ items: [T], columns: Int) -> [[T]] {
        let count = max(columns, 1)
        let rows = Int((Double(items.count) / Double(count)).rounded(.up))
        return (0..<count).map { Array(items.dropFirst($0 * rows).prefix(rows)) }
    }

    /// DR-68 — what ↑/↓ walk: every drawn tile in reading order, row by row, card by card.
    static func visible(_ groups: [ClustersModel.Group], tab: EntityType?, expandAll: Bool,
                        pictured: (Entity) -> Bool = { _ in false }) -> [Entity] {
        if let tab { return groups.first { $0.type == tab }?.entities ?? [] }
        let byType = Dictionary(groups.map { ($0.type, $0.entities) }, uniquingKeysWith: { first, _ in first })
        return rows(groups, expandAll: expandAll).enumerated().flatMap { index, row in
            row.types.flatMap { type -> [Entity] in
                shown(byType[type] ?? [], type: type, row: row,
                      budget: budget(row, index: index, expandAll: expandAll), pictured: pictured)
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

    @Environment(Store.self) private var store

    var body: some View {
        GeometryReader { geo in
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(24)) {
                    let columns = ClustersGrid.tabColumns(width: geo.size.width - gutter * 2,
                                                          scale: CGFloat(CicadaTheme.uiScale))
                    if let tab, let group = groups.first(where: { $0.type == tab }) {
                        ClusterCard(group: group, shown: group.entities, columns: columns, open: open, showAll: nil)
                    } else {
                        let rows = ClustersGrid.rows(groups, expandAll: expandAll)
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                            rowView(row, index: index, wideColumns: columns, width: geo.size.width - gutter * 2)
                        }
                    }
                }
                .padding(.horizontal, gutter)
                .padding(.bottom, CicadaTheme.scaled(72))
            }
        }
        .listKeys(move: move, enter: { false }, escape: escape)
    }

    private func section(_ type: EntityType, row: ClustersGrid.Row, index: Int) -> (ClustersModel.Group, [Entity])? {
        guard let group = groups.first(where: { $0.type == type }) else { return nil }
        let budget = ClustersGrid.budget(row, index: index, expandAll: expandAll)
        return (group, ClustersGrid.shown(group.entities, type: type, row: row, budget: budget,
                                          pictured: { ClustersGrid.isPictured($0, store: store) }))
    }

    @ViewBuilder
    private func rowView(_ row: ClustersGrid.Row, index: Int, wideColumns: Int, width: CGFloat) -> some View {
        let scale = CGFloat(CicadaTheme.uiScale)
        let shown = { (type: EntityType) in section(type, row: row, index: index) }
        switch row {
        case .faces(let types), .lead(let types), .gallery(let types):
            if let type = types.first, let (group, items) = shown(type) {
                let more: (() -> Void)? = items.count < group.entities.count ? { showTab(type) } : nil
                switch row {
                case .faces:
                    ClusterFaces(group: group, shown: items, columns: ClustersGrid.faceColumns(width: width, scale: scale),
                                 open: open, showAll: more)
                case .lead:
                    ClusterLeads(group: group, shown: items, columns: ClustersGrid.leadColumns(width: width, scale: scale),
                                 open: open, showAll: more)
                default:
                    ClusterNames(group: group, shown: items, columns: ClustersGrid.leadColumns(width: width, scale: scale),
                                 lines: 2, open: open, showAll: more)
                }
            }
        case .trio(let types):
            HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                ForEach(types, id: \.self) { type in
                    if let (group, items) = shown(type) {
                        ClusterNames(group: group, shown: items, columns: 1, open: open,
                                     showAll: items.count < group.entities.count ? { showTab(type) } : nil)
                    }
                }
                ForEach(0..<max(ClustersGrid.lists.count - types.count, 0), id: \.self) { _ in
                    Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
                }
            }
        case .pair(let types), .short(let types):
            HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
                ForEach(types, id: \.self) { type in
                    if let (group, items) = shown(type) {
                        if case .pair = row {
                            ClusterCard(group: group, shown: items, columns: wideColumns, open: open,
                                        showAll: { showTab(type) })
                        } else {
                            ClusterShortCard(group: group, shown: items, open: open, showAll: { showTab(type) })
                        }
                    }
                }
                // A lone card keeps its share of the row, so a row of one never stretches (F-11's columns).
                if case .short = row {
                    ForEach(0..<max(3 - types.count, 0), id: \.self) { _ in
                        Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
                    }
                }
            }
        }
    }
}

/// A type's card header (F-11): its plural name as a plain label, "Show all ›" when some are hidden — no type glyph
/// (owner 2026-10-28, DESIGN_RULES §9). Say it once (owner 2026-10-19): the count is the type's tab's ("People 17"),
/// so the card no longer prints it beside the name.
struct ClusterCardHeader: View {
    let type: EntityType
    let count: Int
    let showAll: (() -> Void)?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(type.groupLabel)
                .font(CicadaTheme.font(size: 14, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
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

    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ClusterCardHeader(type: group.type, count: group.entities.count,
                              showAll: shown.count < group.entities.count ? showAll : nil)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingSM, alignment: .leading),
                                     count: max(columns, 1)),
                      alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                let reserves = EntityPictureLayout.anyDrawn(shown, store: store)
                ForEach(shown) { entity in
                    ClusterTile(entity: entity, reservesPicture: reserves) { open(entity) }.id(entity.id)
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

    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            ClusterCardHeader(type: group.type, count: group.entities.count,
                              showAll: shown.count < group.entities.count ? showAll : nil)
            let reserves = EntityPictureLayout.anyDrawn(shown, store: store)
            ForEach(shown) { entity in
                Button { open(entity) } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 20,
                                      collapsesWhenEmpty: !reserves)
                        Text(entity.name)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        QualifierTag(qualifier: entity.qualifier)   // G227
                        if let line = ClustersModel.line(entity) {
                            Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                    .frame(height: CicadaTheme.scaled(RowMetrics.titleOnly))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
                .id(entity.id)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
    }
}

/// A tile (F-11): the picture, the name, one line in words. The whole cell opens the card — the picture included, with no
/// camera and no change offered (owner 2026-11-06; a picture is changed only inside the entity page). Hover is a fill (DR-63).
struct ClusterTile: View {
    let entity: Entity
    /// Some tile in this card has a picture: keep the slot so every name starts at one edge (owner 2026-10-28).
    var reservesPicture = true
    let open: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.spacingMD) {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 32, heldInputs: entity.pictureInputs,
                              collapsesWhenEmpty: !reservesPicture)
                    .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Text(entity.name)
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                            .lineLimit(1)
                        QualifierTag(qualifier: entity.qualifier)   // G227
                    }
                    if let line = ClustersModel.line(entity) {
                        Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
        .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine),
               maxHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
        .rowHover($hovering)
        .contentShape(Rectangle())
    }
}

/// A section's heading over the page itself, no card. When some are hidden the heading is itself the way to the rest: its
/// name, then a chevron (ROR-118 round 3), so six "Show all" links are not repeated down the page. The chevron says there
/// is more; the hover fill and the help say where it goes.
private struct ClusterSection<Content: View>: View {
    let group: ClustersModel.Group
    let showAll: (() -> Void)?
    var ruled = true
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if ruled { Rectangle().fill(CicadaTheme.borderLight).frame(height: 1) }
            ClusterSectionHeading(type: group.type, showAll: showAll)
            content
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

struct ClusterSectionHeading: View {
    let type: EntityType
    let showAll: (() -> Void)?
    @State private var hovering = false

    private var label: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(type.groupLabel)
                .font(CicadaTheme.font(size: 15, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            if showAll != nil {
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.font(size: 12, weight: .bold))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            }
        }
    }

    var body: some View {
        Group {
            if let showAll {
                Button(action: showAll) { label.contentShape(Rectangle()) }
                    .buttonStyle(.cicadaPlain)
                    .onHover { hovering = $0 }
                    .help(Copy.People.showAllHelp(type.groupLabel))
                    .accessibilityLabel(Copy.People.showAllHelp(type.groupLabel))
            } else {
                label
            }
        }
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(28), alignment: .leading)
        .accessibilityElement(children: .contain)
    }
}

/// ROR-118 — people lead the page: one strip of large portraits on the page's own ground, the name under each. A
/// person with no photo draws the monogram (the one fallback a picture has); the line a tile used to print is a hover
/// help, so the strip carries names alone.
struct ClusterFaces: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let columns: Int
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    var body: some View {
        ClusterSection(group: group, showAll: showAll, ruled: false) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingSM, alignment: .top),
                                     count: max(columns, 1)),
                      alignment: .center, spacing: CicadaTheme.spacingMD) {
                ForEach(shown) { entity in ClusterFace(entity: entity) { open(entity) }.id(entity.id) }
            }
        }
    }
}

struct ClusterFace: View {
    let entity: Entity
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            VStack(spacing: CicadaTheme.spacingSM) {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 76, heldInputs: entity.pictureInputs)
                    .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(entity.name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                        .lineLimit(1)
                    QualifierTag(qualifier: entity.qualifier)   // G227
                }
                .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(ClustersModel.line(entity) ?? "")
        .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
        .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.scaled(4))
        .frame(maxWidth: .infinity)
        .rowHover($hovering)
    }
}

/// ROR-118 — projects are the page's second beat: a row of cards, the name large over its whole one-line reason (two
/// lines of room, so a sentence is never cut mid-phrase), the picture at the corner only when the project has one.
struct ClusterLeads: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let columns: Int
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    var body: some View {
        ClusterSection(group: group, showAll: showAll, ruled: false) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingMD, alignment: .top),
                                     count: max(columns, 1)),
                      alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(shown) { entity in ClusterLead(entity: entity) { open(entity) }.id(entity.id) }
            }
        }
    }
}

struct ClusterLead: View {
    let entity: Entity
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Button(action: open) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Text(entity.name)
                            .font(CicadaTheme.font(size: 17, weight: .semibold))
                            .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                            .lineLimit(1)
                        QualifierTag(qualifier: entity.qualifier)   // G227
                    }
                    if let line = ClustersModel.line(entity) {
                        Text(line)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                    }
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
            .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
            EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 36, heldInputs: entity.pictureInputs,
                          collapsesWhenEmpty: true)
                .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
                .contentShape(Rectangle())
                .onTapGesture(perform: open)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(104), maxHeight: CicadaTheme.scaled(104),
               alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .rowHover($hovering, cornerRadius: CicadaTheme.cornerRadius)
    }
}

/// ROR-118 — companies, tools, concepts and media: a ruled list of names alone. A picture rides the trailing edge only
/// where one exists, so the names share one left edge. Media titles are long: they take up to two lines (round 3), so a
/// title is never cut mid-word, and every row there is two lines tall.
struct ClusterNames: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let columns: Int
    var lines = 1
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    var body: some View {
        ClusterSection(group: group, showAll: showAll) {
            // Round 4: Media fills down its columns, not across its rows, so the dimmed titles (ordered last) are
            // whole columns and the dimming reads as a block, never a flicker between neighbours.
            if lines > 1, columns > 1 {
                // Round 5: a hairline between the columns makes each one a unit, so a dimmed column beside a bright one
                // reads as a choice, not a fault; the same columns the keys walk (`ClustersGrid.columnMajor`).
                let parts = ClustersGrid.columnMajor(shown, columns: columns)
                HStack(alignment: .top, spacing: 0) {
                    ForEach(Array(parts.enumerated()), id: \.offset) { column, part in
                        if column > 0 {
                            Rectangle().fill(CicadaTheme.borderLight).frame(width: 1)
                                .padding(.horizontal, CicadaTheme.spacingXL / 2)
                        }
                        VStack(spacing: 0) {
                            ForEach(part) { entity in
                                ClusterNameRow(entity: entity, lines: lines) { open(entity) }.id(entity.id)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .top)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
            } else {
                grid(shown)
            }
        }
    }

    private func grid(_ items: [Entity]) -> some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingXL, alignment: .topLeading),
                                 count: max(columns, 1)),
                  alignment: .leading, spacing: 0) {
            ForEach(items) { entity in ClusterNameRow(entity: entity, lines: lines) { open(entity) }.id(entity.id) }
        }
    }
}

struct ClusterNameRow: View {
    let entity: Entity
    var lines = 1
    let open: () -> Void
    @State private var hovering = false
    @Environment(Store.self) private var store

    var body: some View {
        // Round 5: a name with no picture has nothing after it, so no empty slot spends the row's width on spacing
        // (it was wrapping titles a word early) and the title and mark align on the top line.
        let drawn = EntityPictureLayout.anyDrawn([entity], store: store)
        Button(action: open) {
            // Round 4: a logo sits right after its name, one mark with it, never alone at the far edge; the weight is
            // regular so a name reads a step under its heading and the cards' titles.
            HStack(alignment: lines > 1 ? .top : .center, spacing: CicadaTheme.spacingSM) {
                Text(entity.name)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                    .lineLimit(lines)
                    .multilineTextAlignment(.leading)
                QualifierTag(qualifier: entity.qualifier)   // G227
                if drawn {
                    EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 18, heldInputs: entity.pictureInputs,
                                  collapsesWhenEmpty: true)
                        .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(ClustersModel.line(entity) ?? "")
        .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
        .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
        .padding(.horizontal, CicadaTheme.scaled(8))
        // Media: every row the same two-line height with its title on the top line, so the first lines of neighbours
        // share one baseline whether a title wraps or not.
        .padding(.top, CicadaTheme.scaled(lines > 1 ? 7 : 0))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(lines > 1 ? 50 : RowMetrics.titleOnly),
               maxHeight: CicadaTheme.scaled(lines > 1 ? 50 : RowMetrics.titleOnly),
               alignment: lines > 1 ? .topLeading : .leading)
        .rowHover($hovering)
    }
}

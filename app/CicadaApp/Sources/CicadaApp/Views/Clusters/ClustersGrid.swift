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
    static let listNames = 4
    static let galleryNames = 5
    static let shortLines = 2
    /// Media covers drawn above the title list.
    static let coverCount = 4

    enum Row: Equatable, Identifiable {
        /// People as a strip of portraits.
        case faces([EntityType])
        /// Projects as a row of cards, each with its one line.
        case lead([EntityType])
        /// Companies, tools, concepts: flat lists of names side by side.
        case trio([EntityType])
        /// Media: names, a thumbnail only where one exists.
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

    /// A page with a picture to draw: not "use initials", which is the person's choice of no picture.
    @MainActor
    static func isPictured(_ entity: Entity, store: Store) -> Bool {
        guard let picture = store.picture(for: entity.id, held: entity.pictureRef) else { return false }
        return picture.source != .initials
    }

    /// ROR-118 round 2 — what a section shows, in the order it draws: of the entries it has room for, the ones with a
    /// picture first (a face, a logo, a cover — pictures carry the weight where they exist) and, in the name lists,
    /// the dimmed ones last, so the dimming reads as one block ("not mentioned yet") and never as a flicker between
    /// rows. A stable partition: each group keeps the model's order inside it. Projects and the rest are untouched.
    static func arranged(_ entities: [Entity], type: EntityType, pictured: (Entity) -> Bool) -> [Entity] {
        let picturesLead: Set<EntityType> = [.person, .company, .tool, .media]
        let quietLast: Set<EntityType> = [.company, .tool, .concept, .media]
        guard picturesLead.contains(type) || quietLast.contains(type) else { return entities }
        func rank(_ e: Entity) -> Int {
            (picturesLead.contains(type) && !pictured(e) ? 2 : 0) + (quietLast.contains(type) && e.quiet ? 1 : 0)
        }
        return entities.enumerated().sorted { a, b in
            let (ra, rb) = (rank(a.element), rank(b.element))
            return ra != rb ? ra < rb : a.offset < b.offset
        }.map(\.element)
    }

    /// What a section draws: People take the most recent few and put the photos first; the name lists and Media
    /// arrange the whole group first (pictures, then bright, then dimmed) and take what fits, so the room goes to the
    /// entries that have a picture to show. Cards and short rows keep the model's order.
    static func shown(_ all: [Entity], type: EntityType, row: Row, budget: Int?, pictured: (Entity) -> Bool) -> [Entity] {
        switch row {
        case .faces:
            let recent = budget.map { Array(all.prefix($0)) } ?? all
            return arranged(recent, type: type, pictured: pictured)
        case .trio, .gallery:
            let ordered = arranged(all, type: type, pictured: pictured)
            return budget.map { Array(ordered.prefix($0)) } ?? ordered
        default:
            return budget.map { Array(all.prefix($0)) } ?? all
        }
    }

    /// DR-68 — what ↑/↓ walk: every drawn tile in reading order, row by row, card by card.
    static func visible(_ groups: [ClustersModel.Group], tab: EntityType?, expandAll: Bool,
                        pictured: (Entity) -> Bool = { _ in false }) -> [Entity] {
        if let tab { return groups.first { $0.type == tab }?.entities ?? [] }
        let byType = Dictionary(groups.map { ($0.type, $0.entities) }, uniquingKeysWith: { first, _ in first })
        return rows(groups, expandAll: expandAll).enumerated().flatMap { index, row in
            row.types.flatMap { type -> [Entity] in
                return shown(byType[type] ?? [], type: type, row: row,
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

    private func pictured(_ entity: Entity) -> Bool { ClustersGrid.isPictured(entity, store: store) }

    var body: some View {
        GeometryReader { geo in
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(22)) {
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
        return (group, ClustersGrid.shown(group.entities, type: type, row: row, budget: budget, pictured: pictured))
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
                    ClusterFaces(group: group, shown: items, pictured: pictured, open: open, showAll: more)
                case .lead:
                    ClusterLeads(group: group, shown: items, columns: ClustersGrid.leadColumns(width: width, scale: scale),
                                 open: open, showAll: more)
                default:
                    ClusterMedia(group: group, shown: items, columns: ClustersGrid.leadColumns(width: width, scale: scale),
                                 pictured: pictured, open: open, showAll: more)
                }
            }
        case .trio(let types):
            HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
                ForEach(types, id: \.self) { type in
                    if let (group, items) = shown(type) {
                        ClusterNames(group: group, shown: items, columns: 1, leadingPicture: true, open: open,
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
/// so the card no longer prints it beside the name. ROR-118 round 2: the name is the section's one strong word (16 pt
/// semibold) and "Show all" a quiet 12 pt tertiary link — six of them at one weight were the loudest thing on the page.
struct ClusterCardHeader: View {
    let type: EntityType
    let count: Int
    let showAll: (() -> Void)?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(type.groupLabel)
                .font(CicadaTheme.font(size: 16, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Spacer(minLength: 0)
            if let showAll { ClusterShowAll(type: type, action: showAll) }
        }
        .frame(minHeight: CicadaTheme.scaled(28))
        .accessibilityElement(children: .contain)
    }
}

/// "Show all ›": tertiary until the pointer is on it (DR-63's fill-free hover is a step up in ink).
private struct ClusterShowAll: View {
    let type: EntityType
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Text(Copy.People.showAll)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.scaled(6))
                .frame(minHeight: CicadaTheme.scaled(28))
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.People.showAllHelp(type.groupLabel))
        .accessibilityLabel(Copy.People.showAllHelp(type.groupLabel))
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

/// A tile (F-11): the picture, the name, one line in words. The words open the card; a click on the picture offers its
/// choices (`PictureChoices`; R-PE15, owner 2026-09-30 and 2026-10-29). Hover is a fill (DR-63).
struct ClusterTile: View {
    let entity: Entity
    /// Some tile in this card has a picture: keep the slot so every name starts at one edge (owner 2026-10-28).
    var reservesPicture = true
    let open: () -> Void

    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 32, heldInputs: entity.pictureInputs,
                          editing: .tile, collapsesWhenEmpty: !reservesPicture)
                .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
            Button(action: open) {
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
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
            .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine),
               maxHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
        .rowHover($hovering)
        .contentShape(Rectangle())
    }
}

/// A section's heading over the page itself, no card: the plural name and "Show all ›" when some are hidden.
private struct ClusterSection<Content: View>: View {
    let group: ClustersModel.Group
    let showAll: (() -> Void)?
    var ruled = true
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if ruled { Rectangle().fill(CicadaTheme.border).frame(height: 1) }
            ClusterCardHeader(type: group.type, count: group.entities.count, showAll: showAll)
            content
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

/// ROR-118 — people lead the page. Those with a photo are the page's one focal point: large portraits on the page's own
/// ground, the name under each. Those without one (the monogram, the one fallback a picture has) follow as a quiet
/// line of small initials beside the name, so a grey disc never sits at portrait size beside a photo and reads as
/// missing data. The line a tile used to print is a hover help.
struct ClusterFaces: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let pictured: (Entity) -> Bool
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    var body: some View {
        ClusterSection(group: group, showAll: showAll, ruled: false) {
            let faces = shown.filter(pictured)
            let others = shown.filter { !pictured($0) }
            let portraits = LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(112), maximum: CicadaTheme.scaled(136)),
                                                         spacing: CicadaTheme.spacingMD, alignment: .top)],
                                      alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(faces) { entity in ClusterFace(entity: entity) { open(entity) }.id(entity.id) }
            }
            let initials = LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingSM, alignment: .leading),
                                                    count: 2),
                                     alignment: .leading, spacing: 0) {
                ForEach(others) { entity in ClusterPerson(entity: entity) { open(entity) }.id(entity.id) }
            }
            if faces.isEmpty {
                initials
            } else if others.isEmpty {
                portraits
            } else {
                // The initials sit beside the portraits where the row has room, under them where it does not.
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .center, spacing: CicadaTheme.spacingXL) {
                        portraits
                        initials.frame(width: CicadaTheme.scaled(440))
                    }
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) { portraits; initials }
                }
            }
        }
    }
}

struct ClusterFace: View {
    let entity: Entity
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 72, heldInputs: entity.pictureInputs,
                          editing: .tile)
                .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
            Button(action: open) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(entity.name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                        .lineLimit(1)
                    QualifierTag(qualifier: entity.qualifier)   // G227
                }
                .frame(maxWidth: .infinity)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(ClustersModel.line(entity) ?? "")
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
            .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.scaled(4))
        .frame(maxWidth: .infinity)
        .rowHover($hovering)
    }
}

/// A person with no photo: their initials small, the name beside them — one row, the picture slot kept.
struct ClusterPerson: View {
    let entity: Entity
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 24, heldInputs: entity.pictureInputs,
                          editing: .tile)
                .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
            Button(action: open) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(entity.name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                        .lineLimit(1)
                    QualifierTag(qualifier: entity.qualifier)   // G227
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(ClustersModel.line(entity) ?? "")
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
            .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.titleOnly), alignment: .leading)
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
                            .font(CicadaTheme.font(size: 18, weight: .semibold))
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
            EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 44, heldInputs: entity.pictureInputs,
                          editing: .tile, collapsesWhenEmpty: true)
                .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(104), maxHeight: CicadaTheme.scaled(104),
               alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(.strong, in: CicadaTheme.shape(CicadaTheme.cornerRadius))   // the card's edge reads at a glance
        .rowHover($hovering, cornerRadius: CicadaTheme.cornerRadius)
    }
}

/// ROR-118 — companies, tools and concepts: a ruled list of names. Where some entry has a logo the picture column is
/// kept at the leading edge (28 pt) so every name starts at one line — an entry without one leaves its slot empty, never
/// a glyph; with none at all the names start at the edge. A concept has no logo to draw, so its list stays words.
struct ClusterNames: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let columns: Int
    var leadingPicture = false
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    @Environment(Store.self) private var store

    var body: some View {
        ClusterSection(group: group, showAll: showAll) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingXL, alignment: .leading),
                                     count: max(columns, 1)),
                      alignment: .leading, spacing: 0) {
                let reserves = leadingPicture && EntityPictureLayout.anyDrawn(shown, store: store)
                ForEach(shown) { entity in
                    ClusterNameRow(entity: entity, leadingPicture: leadingPicture, reservesPicture: reserves) { open(entity) }
                        .id(entity.id)
                }
            }
        }
    }
}

struct ClusterNameRow: View {
    let entity: Entity
    var leadingPicture = false
    var reservesPicture = false
    /// A long title wraps to a second line instead of ending mid-word (media).
    var wraps = false
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if leadingPicture {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 26, heldInputs: entity.pictureInputs,
                              editing: .tile, collapsesWhenEmpty: !reservesPicture)
                    .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
            }
            Button(action: open) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(entity.name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                        .lineLimit(wraps ? 2 : 1)
                        .multilineTextAlignment(.leading)
                    QualifierTag(qualifier: entity.qualifier)   // G227
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(ClustersModel.line(entity) ?? "")
            .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
            .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
            if !leadingPicture {
                EntityPicture(id: entity.id, name: entity.name, type: entity.type, size: 22, heldInputs: entity.pictureInputs,
                              editing: .tile, collapsesWhenEmpty: true)
                    .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(leadingPicture ? 34 : RowMetrics.titleOnly),
               maxHeight: wraps ? nil : CicadaTheme.scaled(leadingPicture ? 34 : RowMetrics.titleOnly), alignment: .leading)
        .rowHover($hovering)
    }
}

/// ROR-118 round 2 — media: the saved pages that have an image lead as covers (3:2, the title under, wrapping to two
/// lines, never cut mid-word); the rest follow as a ruled list of titles. A cover is the saved page's own image
/// (`EntityPicture`'s thumbnail or an upload), drawn whole when it is tall (a book), never invented for a page with
/// none. Right-click still offers the picture's choices.
struct ClusterMedia: View {
    let group: ClustersModel.Group
    let shown: [Entity]
    let columns: Int
    let pictured: (Entity) -> Bool
    let open: (Entity) -> Void
    let showAll: (() -> Void)?

    /// A cover whose image never arrived (a page whose image could not be fetched) drops to the list, never a blank.
    @State private var failed: Set<String> = []

    var body: some View {
        let covers = Array(shown.filter { pictured($0) && !failed.contains($0.id) }.prefix(ClustersGrid.coverCount))
        let coverIds = Set(covers.map(\.id))
        let rest = shown.filter { !coverIds.contains($0.id) }
        ClusterSection(group: group, showAll: showAll) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                if !covers.isEmpty {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(140), maximum: CicadaTheme.scaled(170)),
                                                 spacing: CicadaTheme.spacingMD, alignment: .top)],
                              alignment: .leading, spacing: CicadaTheme.spacingMD) {
                        ForEach(covers) { entity in
                            ClusterCover(entity: entity, failed: { _ = failed.insert(entity.id) }) { open(entity) }.id(entity.id)
                        }
                    }
                }
                if !rest.isEmpty {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingXL, alignment: .top),
                                             count: max(columns, 1)),
                              alignment: .leading, spacing: 0) {
                        ForEach(rest) { entity in ClusterNameRow(entity: entity, wraps: true) { open(entity) }.id(entity.id) }
                    }
                }
            }
        }
    }
}

struct ClusterCover: View {
    let entity: Entity
    var failed: () -> Void = {}
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ClusterCoverImage(entity: entity, failed: failed)
                    .aspectRatio(3.0 / 2.0, contentMode: .fit)
                    .opacity(entity.quiet ? CicadaTheme.quietPictureOpacity : 1)
                Text(entity.name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(entity.quiet ? CicadaTheme.quietName : CicadaTheme.textPrimary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(CicadaTheme.scaled(6))
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering, cornerRadius: CicadaTheme.cornerRadius)
        .help(ClustersModel.line(entity) ?? "")
        .contextMenu { PictureMenuItems(id: entity.id, name: entity.name, type: entity.type, held: entity.pictureRef,
                                        heldInputs: entity.pictureInputs) }
        .accessibilityLabel(Copy.Lists.entityRow(type: entity.type.label, name: entity.shownName, open: false))
        .accessibilityValue(entity.quiet ? Copy.Lists.quiet : "")
    }
}

/// The cover's image: the first frame from the run's memory when it was seen already, the rest loaded as
/// `EntityPicture` loads it; a tall one is drawn whole on the picture fill, a wide one fills the frame.
private struct ClusterCoverImage: View {
    let entity: Entity
    let failed: () -> Void
    @Environment(Store.self) private var store
    @State private var image: NSImage?

    private var picture: EntityPictureRef? { store.picture(for: entity.id, held: entity.pictureRef) }
    private var shown: NSImage? {
        if let image { return image }
        guard let picture, let raw = picture.url, picture.source != .logo, picture.source != .initials else { return nil }
        return PictureURL.parse(raw).flatMap { PictureStore.cachedImage($0, bank: store.bank) }
    }
    private var loadKey: String { "\(store.bank)|\(entity.id)|\(picture?.url ?? "-")" }

    var body: some View {
        let tall = (shown.map { $0.size.height > $0.size.width }) ?? false
        ZStack {
            CicadaTheme.pictureFill
            if let shown {
                Image(nsImage: shown).resizable().interpolation(.high)
                    .aspectRatio(contentMode: tall ? .fit : .fill)
            }
        }
        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
        .overlay { CicadaTheme.shape(CicadaTheme.cornerRadius).stroke(CicadaTheme.ring(.resting), lineWidth: 1) }
        .task(id: loadKey) {
            guard let picture, let raw = picture.url, picture.source != .logo, picture.source != .initials,
                  let url = PictureURL.parse(raw) else { return }
            image = await PictureStore.shared.image(url, bank: store.bank)
            if image == nil { failed() }
        }
    }
}

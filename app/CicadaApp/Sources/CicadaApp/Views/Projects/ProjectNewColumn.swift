import SwiftUI

// MARK: - What can be attached (pure)

/// The kinds a page is picked by (owner 2026-11-04: "selecting entity pages from different sources, like youtube
/// videos, blogs, or whatever"): what the person recognises, not Cicada's ten entity types.
enum ProjectAttachKind: String, CaseIterable, Hashable, Sendable {
    case video, article, paper, repository, person, other

    var label: String {
        switch self {
        case .video: "Videos"
        case .article: "Articles"
        case .paper: "Papers"
        case .repository: "Repositories"
        case .person: "People"
        case .other: "Other"
        }
    }
}

/// One page in memory the person can attach: the page itself (its picture comes from `EntityPicture`), the kind it is
/// picked by, and where it came from in words with that source's own mark.
struct ProjectAttachCandidate: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let type: EntityType
    let kind: ProjectAttachKind
    /// "youtube.com", a channel, "Repository", "Person", "Tool" — one short line.
    let source: String
    /// The site's own mark (a saved link's site, GitHub for a repository); nil draws none.
    let mark: SavedLinkMarkModel.Mark?
    let aliases: [String]
    let lastReferenced: String?
}

/// Owner 2026-11-04 — New project's picker, and the project page's Add, over the pages already in memory: the graph's
/// nodes, with what Sleep › Saved knows about each saved link (its site, its kind). Nothing new is made here.
enum ProjectAttachModel {
    /// Rows shown with nothing typed: the most recently mentioned pages.
    static let recentLimit = 8
    static let matchLimit = 30

    static func candidates(nodes: [GraphNode], media: [MediaFeedItem], excluding: Set<String> = []) -> [ProjectAttachCandidate] {
        var items: [String: MediaFeedItem] = [:]
        for item in media where items[item.mediaEntityId] == nil { items[item.mediaEntityId] = item }
        return nodes.compactMap { node in
            guard !node.isFacet, !node.isHub, node.type != .hub, !node.isOwner, node.status != .dropped,
                  !excluding.contains(node.id) else { return nil }
            let (kind, source, mark) = describe(node, item: items[node.id])
            return ProjectAttachCandidate(id: node.id, name: node.shownName, type: node.type, kind: kind,
                                          source: source, mark: mark, aliases: node.aliases,
                                          lastReferenced: node.lastReferenced)
        }
    }

    static func describe(_ node: GraphNode, item: MediaFeedItem?) -> (ProjectAttachKind, String, SavedLinkMarkModel.Mark?) {
        switch node.type {
        case .person: return (.person, EntityType.person.label, nil)
        case .media:
            guard let item else { return (.other, EntityType.media.label, nil) }
            if item.mediaType == "repository" {
                return (.repository, Copy.ProjectsMine.repository,
                        .site(key: "github", label: "GitHub", door: .media(item.mediaEntityId)))
            }
            let kind: ProjectAttachKind
            switch FeedKind.of(item) {
            case .video: kind = .video
            case .paper: kind = .paper
            case .link, .bookmark: kind = .article
            }
            let from = [item.channel, item.site].compactMap { $0?.trimmingCharacters(in: .whitespaces) }
                .first { !$0.isEmpty } ?? FeedKind.of(item).singular
            return (kind, from, SavedLinkMarkModel.mark(item))
        default:
            return (.other, node.type.label, nil)
        }
    }

    /// The rows for a query and a kind: with nothing typed, the most recently mentioned; else the one ranker
    /// (`QuickMatch`) over the name, its other names and where it came from.
    static func shown(_ pool: [ProjectAttachCandidate], query: String, kind: ProjectAttachKind?) -> [ProjectAttachCandidate] {
        let pool = kind.map { k in pool.filter { $0.kind == k } } ?? pool
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            return Array(pool.sorted { ($0.lastReferenced ?? "", $1.name) > ($1.lastReferenced ?? "", $0.name) }
                .prefix(recentLimit))
        }
        return QuickMatch.rank(pool, query: q, limit: matchLimit, fields: fields,
                               tieBreak: { _ in 0 }, name: \.name).map(\.item)
    }

    /// How many of each kind the query finds: a kind with none draws no tab.
    static func counts(_ pool: [ProjectAttachCandidate], query: String) -> [ProjectAttachKind: Int] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let found = q.isEmpty ? pool : pool.filter { QuickMatch.matches(q, fields: fields($0)) }
        return Dictionary(grouping: found, by: \.kind).mapValues(\.count)
    }

    static func tabs(_ counts: [ProjectAttachKind: Int]) -> [TextTab<ProjectAttachKind>] {
        let kinds = ProjectAttachKind.allCases.filter { (counts[$0] ?? 0) > 0 }
        guard kinds.count > 1 else { return [] }
        return [TextTab(id: nil, label: Copy.Lists.all, count: counts.values.reduce(0, +))]
            + kinds.map { TextTab(id: $0, label: $0.label, count: counts[$0]) }
    }

    private static func fields(_ c: ProjectAttachCandidate) -> [QuickMatch.Field] {
        [QuickMatch.Field(c.name, weight: QuickMatch.Weight.name)]
            + c.aliases.map { QuickMatch.Field($0, weight: QuickMatch.Weight.alias) }
            + [QuickMatch.Field(c.source, weight: QuickMatch.Weight.keyword)]
    }
}

/// The picker's last answer, kept until one of its inputs moves (review of #595: never re-ranked per keystroke
/// elsewhere on the page). A plain class, so reading it never invalidates the view.
@MainActor
final class ProjectPickerMemo {
    private struct Key: Equatable {
        let candidates: [ProjectAttachCandidate]
        let picked: Set<String>
        let query: String
        let kind: ProjectAttachKind?
    }

    private var key: Key?
    private var value: ([TextTab<ProjectAttachKind>], [ProjectAttachCandidate]) = ([], [])
    private(set) var computed = 0

    func result(candidates: [ProjectAttachCandidate], picked: Set<String>, query: String,
                kind: ProjectAttachKind?) -> ([TextTab<ProjectAttachKind>], [ProjectAttachCandidate]) {
        let next = Key(candidates: candidates, picked: picked, query: query, kind: kind)
        if next == key { return value }
        let pool = candidates.filter { !picked.contains($0.id) }
        let tabs = ProjectAttachModel.tabs(ProjectAttachModel.counts(pool, query: query))
        value = (tabs, ProjectAttachModel.shown(pool, query: query, kind: tabs.isEmpty ? nil : kind))
        key = next
        computed += 1
        return value
    }
}

/// The candidates, built once per graph and saved-items load (keyed on their `loadedAt` and the bank), not per render.
@MainActor
final class ProjectAttachCache {
    private var key: String?
    private var value: [ProjectAttachCandidate] = []

    func candidates(key: String, build: () -> [ProjectAttachCandidate]) -> [ProjectAttachCandidate] {
        if key != self.key {
            value = build()
            self.key = key
        }
        return value
    }
}

/// The new project's draft, held by the page so closing the column (Esc, the rail) never loses the words; Cancel
/// forgets it.
struct ProjectDraft: Equatable {
    var name = ""
    var description = ""
    var pages: [ProjectAttachCandidate] = []

    var ready: Bool { !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    var isEmpty: Bool { self == ProjectDraft() }

    /// What Create sends: the trimmed words and the attached pages' ids, in the order they were attached.
    var change: ProjectChange {
        .create(name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                description: description.trimmingCharacters(in: .whitespacesAndNewlines),
                pages: pages.map(\.id))
    }

    mutating func toggle(_ c: ProjectAttachCandidate) {
        if pages.contains(where: { $0.id == c.id }) { pages.removeAll { $0.id == c.id } } else { pages.append(c) }
    }
}

// MARK: - The rows and the picker

/// One page as the picker and the attached list draw it (DR-34's two-line row): its picture, its name, and where it
/// came from with that source's mark. One slot leads every row, as wide as a media page's 3:2 well, so names line up:
/// the page's picture when it has one, else its source's mark (a saved link's site, GitHub), else nothing — the mark
/// is never drawn twice. Hover fills it (DR-48).
struct ProjectAttachRow<Trailing: View>: View {
    let candidate: ProjectAttachCandidate
    let action: () -> Void
    @ViewBuilder var trailing: (_ hovering: Bool) -> Trailing
    @Environment(Store.self) private var store
    @State private var hovering = false

    static var pictureUnits: CGFloat { 28 }

    var body: some View {
        let pictured = !EntityPictureLayout.isEmpty(candidate.type, picture: store.picture(for: candidate.id, held: nil))
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Group {
                    if pictured {
                        EntityPicture(id: candidate.id, name: candidate.name, type: candidate.type,
                                      size: Self.pictureUnits)
                    } else if let mark = candidate.mark {
                        SavedLinkMark(mark: mark, size: .row)
                    } else {
                        Color.clear.frame(height: 1)   // an empty Group takes no room; the slot keeps its width
                    }
                }
                .frame(width: EntityPictureLayout.frame(.media, size: CicadaTheme.scaled(Self.pictureUnits)).width)
                VStack(alignment: .leading, spacing: 1) {
                    Text(candidate.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    HStack(spacing: CicadaTheme.spacingXS) {
                        if pictured, let mark = candidate.mark { SavedLinkMark(mark: mark, size: .inline) }
                        Text(candidate.source).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingXS)
                trailing(hovering)
            }
            .padding(.horizontal, CicadaTheme.scaled(6))
            .padding(.vertical, CicadaTheme.scaled(5))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering)
        .accessibilityLabel(Eyebrow.text(candidate.name, candidate.source))
    }
}

/// Find a page to add: one search field, kind tabs with counts when the matches span more than one kind (DR-45), and
/// the rows — the most recently mentioned while nothing is typed. A pick adds at once (DR-42); nothing is made here.
struct ProjectPagePicker: View {
    let candidates: [ProjectAttachCandidate]
    let picked: Set<String>
    let pick: (ProjectAttachCandidate) -> Void
    var autofocus = false
    @State private var query = ""
    @State private var kind: ProjectAttachKind?
    /// Review of #595: the page re-renders on every keystroke in the description; the filter runs only when the query,
    /// the kind, the attached set or the candidates move.
    @State private var memo = ProjectPickerMemo()

    var body: some View {
        let (tabs, rows) = memo.result(candidates: candidates, picked: picked, query: query, kind: kind)
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            CicadaSearchField(text: $query, prompt: Copy.ProjectsMine.findPage, autofocus: autofocus,
                              onSubmit: { if let first = rows.first { pick(first) } })
            if !tabs.isEmpty {
                AdaptiveTextTabs(tabs: tabs, selection: $kind, menuTitle: Copy.ProjectsMine.kindMenu)
            }
            if query.trimmingCharacters(in: .whitespaces).isEmpty && !rows.isEmpty {
                SectionLabel(Copy.ProjectsMine.recent).padding(.top, CicadaTheme.scaled(4))
            }
            ForEach(rows) { c in
                ProjectAttachRow(candidate: c, action: { pick(c) }) { hovering in
                    Image(systemName: "plus")
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                        .accessibilityHidden(true)
                }
                .help(Copy.ProjectsOpen.addPageHelp)
            }
            if rows.isEmpty && !query.trimmingCharacters(in: .whitespaces).isEmpty {
                Text(Copy.ProjectsMine.nothingFound).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .onChange(of: query) { _, _ in
            // A tab the new matches no longer hold falls back to All (a tab switch is instant, DR-61).
            if let k = kind, !tabs.contains(where: { $0.id == k }) { Instant.run { kind = nil } }
        }
    }
}

// MARK: - New project, as a page

/// Owner 2026-11-04 — New project is a page, not a two-field sheet (in the spirit of Claude desktop's project
/// creation, adapted to D): the project page it will become, before it exists. The card is the name as the page's
/// H1 (DR-16, 22 pt, a field with no chrome) over a large editor for what it is about in the person's own words — the
/// project page's lead once made; the knowledge panel beside it (2026-10-27's 312 pt column) holds the pages
/// attached from memory, then the picker. One primary, Create (⌘⏎, DR-5); Cancel forgets the draft; × and Esc close
/// and keep it. Create sends one request: the server makes the page and attaches everything in one person commit.
struct ProjectNewColumn: View {
    @Binding var draft: ProjectDraft
    let candidates: [ProjectAttachCandidate]
    let blocked: Bool
    let gutter: CGFloat
    var available: CGFloat = 0
    let hiddenListCount: Int?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onCancel: () -> Void
    let onEscape: () -> Void
    let create: () -> Void

    enum Field: Hashable { case name, description }
    @FocusState private var focus: Field?

    private var contentWidth: CGFloat { available > 0 ? max(available - 2 * gutter, 0) : 0 }
    private var wide: Bool { ProjectKnowledgeLayout.sideBySide(available: contentWidth) }
    private var cap: CGFloat {
        CicadaTheme.scaled(wide ? ProjectLayout.detailMaxWidth + ProjectKnowledgeLayout.panelWidth
                                    + ProjectKnowledgeLayout.gap : ProjectLayout.detailMaxWidth)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            head
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    HStack(alignment: .top, spacing: CicadaTheme.scaled(ProjectKnowledgeLayout.gap)) {
                        card
                            .frame(maxWidth: CicadaTheme.scaled(wide ? ProjectKnowledgeLayout.cardWidth
                                                                     : ProjectLayout.textMaxWidth),
                                   alignment: .leading)
                        if wide {
                            panel.frame(width: CicadaTheme.scaled(ProjectKnowledgeLayout.panelWidth))
                        }
                    }
                    if !wide {
                        panel.frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                    }
                }
                .padding(.bottom, CicadaTheme.scaled(72))
                .frame(width: contentWidth > 0 ? min(contentWidth, cap) : nil, alignment: .leading)
            }
        }
        .frame(maxWidth: cap, maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        .onAppear { DispatchQueue.main.async { focus = draft.name.isEmpty ? .name : .description } }
        .onExitCommand { onEscape() }   // DR-28 / DR-60: Esc closes at once and keeps the draft
    }

    /// The focus card's head line (§5.3): back to the list when it is hidden, then Close × — no title over the name,
    /// which is the title (owner 2026-11-03: no title that repeats its body).
    private var head: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let n = hiddenListCount {
                TextButton(title: Copy.Projects.projectsBack(n), help: Copy.Lists.showList, action: onShowList)
                    .padding(.leading, -CicadaTheme.scaled(10))
            }
            Spacer(minLength: 0)
            IconButton(systemName: "xmark", help: Copy.Projects.closeHelp, action: onClose)
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            TextField("", text: $draft.name)
                .textFieldStyle(.plain)
                .font(CicadaTheme.displayFont(size: 22))
                .tracking(CicadaTheme.displayTracking(size: 22))
                .foregroundStyle(CicadaTheme.textPrimary)
                .focused($focus, equals: .name)
                .background(alignment: .leading) {
                    if draft.name.isEmpty {
                        Text(Copy.ProjectsMine.newName)
                            .font(CicadaTheme.displayFont(size: 22))
                            .tracking(CicadaTheme.displayTracking(size: 22))
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }
                }
                .accessibilityLabel(Copy.ProjectsMine.newName)
                .accessibilityAddTraits(.isHeader)
                .onSubmit { focus = .description }
            TextEditor(text: $draft.description)
                .focused($focus, equals: .description)
                .cicadaEditor(isFocused: focus == .description, prompt: Copy.ProjectsMine.newDescription,
                              isEmpty: draft.description.isEmpty, minHeight: 280)
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer()
                NeutralButton(title: Copy.ProjectsMine.cancel, help: Copy.ProjectsMine.discardHelp, action: onCancel)
                PrimaryActionButton(title: Copy.ProjectsMine.create, action: create)
                    .disabled(!draft.ready || blocked)
                    .keyboardShortcut(.return, modifiers: .command)
                    .help(blocked ? Copy.Projects.sleepBusy : Copy.ProjectsMine.createHelp)
            }
        }
        .padding(.top, CicadaTheme.spacingXS)
    }

    /// The knowledge panel, before the project exists: what is attached, then the picker.
    private var panel: some View {
        ProjectKnowledgePanel.block {
            Text(Copy.ProjectsMine.attached(draft.pages.count))
                .font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
            ForEach(draft.pages) { c in
                ProjectAttachRow(candidate: c, action: {}) { hovering in
                    TextButton(title: Copy.ProjectsMine.takeOff, help: Copy.ProjectsMine.takeOffHelp, inline: true) {
                        Instant.run { draft.toggle(c) }
                    }
                    .opacity(hovering ? 1 : 0)
                }
                .contextMenu { Button(Copy.ProjectsMine.takeOff) { draft.toggle(c) } }
            }
            ProjectPagePicker(candidates: candidates, picked: Set(draft.pages.map(\.id))) { c in
                Instant.run { draft.toggle(c) }
            }
            .padding(.top, draft.pages.isEmpty ? 0 : CicadaTheme.scaled(6))
        }
    }
}

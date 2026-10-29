import SwiftUI

// DR-77 / ruling 48 part 14 (part B, 2026-10-29): the History tab. The owner, 2026-10-28: "take a little inspiration
// from GitKraken-like graphs: a line traced through time showing how the page changed; hover gives the details (who,
// what changed, when)".
//
// A thin history line runs down the rows' leading edge, one node per change in its writer's picture — a face for a
// person, the model's mark for Sleep's model, the agent's own mark — and Sleep is a `Tag` beside the sentence, never an
// avatar. Filters are DR-45 text tabs (All · You · Agents · Sleep · Upkeep), All without upkeep; no folds (DR-81): a
// Sleep row always shows up to four of its changed lines. Hovering a row (or focusing it) shows who, what changed and
// when; a click pins that card with the change itself.
//
// Speed: nothing here runs when the card opens. The tab reads `GET /entities/{id}/history?summary=true&limit=30` when it
// is first shown (one `git log -p`, `page_history`), and "Older changes" the next 30.

struct EntityHistoryView: View {
    let entityId: String
    /// The page's conversations by session id (`ProvenanceSummary.episodeByConversation`), for each row's
    /// "Show in conversation".
    var openEpisode: [String: String] = [:]
    var load: (String, Int) async throws -> (rows: [EntityHistoryEntry], more: Bool) = {
        try await APIClient.shared.fetchEntityHistoryPage(id: $0, skip: $1)
    }
    var loadDiff: (String, String) async throws -> EntityDiff = {
        try await APIClient.shared.fetchEntityCommitDiff(id: $0, commitHash: $1)
    }
    /// Tests and screenshots hand the rows in; the live tab reads them.
    var initial: HistoryPager? = nil

    @State private var pager = HistoryPager()
    @State private var loading = false
    @State private var failed = false
    @State private var tab: HistoryBucket?
    @State private var hovered: String?
    @State private var pinned: String?

    private var shown: [EntityHistoryEntry] { HistoryBucket.filter(pager.rows, tab) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if pager.loaded, !pager.rows.isEmpty {
                TextTabs(tabs: tabs, selection: $tab)
            }
            content
        }
        .frame(maxWidth: CicadaTheme.scaled(760), alignment: .leading)
        .task(id: entityId) { await loadFirst() }
    }

    private var tabs: [TextTab<HistoryBucket>] {
        // Counts only once every change is read: a count over the newest 30 would say less than is there (DR-38).
        // A tab with nothing under it is not drawn once everything is read (DR-38: no "You 0"), unless it is selected.
        let counts: [HistoryBucket?: Int] = pager.hasMore ? [:] : HistoryBucket.counts(pager.rows)
        return [TextTab(id: nil, label: Copy.Graph.all, count: counts[nil])]
            + HistoryBucket.allCases
            .filter { b in pager.hasMore || tab == b || (counts[Optional(b)] ?? 0) > 0 }
            .map { b in TextTab(id: b, label: b.label, count: counts[Optional(b)]) }
    }

    @ViewBuilder
    private var content: some View {
        if !pager.loaded && failed {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.Graph.historyFailed).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                NeutralButton(title: Copy.Graph.retry, size: .compact) { Task { await loadFirst(force: true) } }
            }
        } else if !pager.loaded {
            SectionLoading(text: Copy.Graph.historyLoading)
        } else if pager.rows.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.Graph.noCommitsTitle).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.Graph.noCommitsDetail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                if shown.isEmpty {
                    Text(Copy.Graph.historyNoneHere).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .padding(.bottom, CicadaTheme.spacingMD)
                }
                ForEach(Array(groups.enumerated()), id: \.offset) { _, group in
                    SectionLabel(group.day)
                        .padding(.leading, HistoryLine.gutter)
                        .padding(.vertical, CicadaTheme.spacingSM)
                    ForEach(group.rows, id: \.commitHash) { entry in
                        row(entry, first: entry.commitHash == shown.first?.commitHash,
                            last: entry.commitHash == shown.last?.commitHash && !pager.hasMore)
                    }
                }
                if pager.hasMore {
                    OlderChangesRow(phase: loading ? .loading : (failed ? .failed : .idle)) {
                        Task { await loadMore() }
                    }
                    .padding(.leading, HistoryLine.gutter)
                }
            }
        }
    }

    private struct Group { let day: String; let rows: [EntityHistoryEntry] }

    private var groups: [Group] {
        var out: [Group] = []
        for entry in shown {
            let day = HistoryRowWords.day(entry)
            if out.last?.day == day {
                out[out.count - 1] = Group(day: day, rows: out[out.count - 1].rows + [entry])
            } else {
                out.append(Group(day: day, rows: [entry]))
            }
        }
        return out
    }

    private func row(_ entry: EntityHistoryEntry, first: Bool, last: Bool) -> some View {
        let id = entry.commitHash
        return HistoryRow(entry: entry, first: first, last: last, highlighted: hovered == id || pinned == id,
                          openEpisode: openEpisode)
            .contentShape(Rectangle())
            .onHover { inside in
                if inside { hovered = id } else if hovered == id { hovered = nil }
            }
            .onTapGesture { pinned = pinned == id ? nil : id }
            .focusable()
            .onKeyPress(.return) { pinned = pinned == id ? nil : id; return .handled }
            .popover(isPresented: Binding(get: { hovered == id || pinned == id },
                                          set: { if !$0 { if hovered == id { hovered = nil }; if pinned == id { pinned = nil } } }),
                     arrowEdge: .leading) {
                HistoryHoverCard(entry: entry, entityId: entityId, showsChange: pinned == id, loadDiff: loadDiff)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(HistoryRowWords.sentence(entry)), \(HistoryRowWords.when(entry, long: true))")
            .accessibilityHint(HistoryRowWords.changed(entry))
    }

    private func loadFirst(force: Bool = false) async {
        if let initial, !force {
            pager = initial
            return
        }
        guard force || !pager.loaded else { return }
        let id = entityId
        loading = true
        failed = false
        defer { loading = false }
        do {
            let page = try await load(id, 0)
            guard id == entityId else { return }
            var next = HistoryPager()
            next.received(page.rows, more: page.more)
            pager = next
        } catch {
            if id == entityId { failed = true }
        }
    }

    private func loadMore() async {
        guard !loading else { return }
        let id = entityId
        loading = true
        failed = false
        defer { loading = false }
        do {
            let page = try await load(id, pager.nextSkip)
            guard id == entityId else { return }
            pager.received(page.rows, more: page.more)
        } catch {
            if id == entityId { failed = true }
        }
    }
}

/// The history line's geometry: a gutter with the line through each node's centre.
enum HistoryLine {
    static var node: CGFloat { CicadaTheme.scaled(22) }
    static var gutter: CGFloat { CicadaTheme.scaled(36) }
    static var width: CGFloat { 1.5 }
}

/// One change: its node on the line (the writer's picture), what happened as a sentence with Sleep as a `Tag`, how it
/// got here and its counts, and — for a Sleep row — up to four changed lines (DR-77).
struct HistoryRow: View {
    let entry: EntityHistoryEntry
    let first: Bool
    let last: Bool
    var highlighted = false
    var openEpisode: [String: String] = [:]

    private var bucket: HistoryBucket { HistoryBucket.of(entry) }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            node
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(HistoryRowWords.sentence(entry))
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                    if bucket == .sleep { Tag(text: Copy.Graph.historySleep) }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    Text(HistoryRowWords.when(entry))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .monospacedDigit()
                }
                let detail = HistoryRowWords.detail(entry)
                if !detail.isEmpty || !entry.sessions.isEmpty {
                    HStack(spacing: CicadaTheme.spacingMD) {
                        if !detail.isEmpty {
                            Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        }
                        ShowInConversationLink(sessionIds: entry.sessions, openEpisode: openEpisode)
                    }
                }
                if bucket == .sleep, let lines = entry.summary?.lines, !lines.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        ForEach(Array(lines.prefix(4).enumerated()), id: \.offset) { _, line in
                            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(6)) {
                                Text(line.sign == "+" ? "+" : "−")
                                    .font(CicadaTheme.metaFont.weight(.semibold))
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                Text(line.text)
                                    .font(CicadaTheme.metaFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                    .lineLimit(1)
                                    .truncationMode(.tail)
                            }
                        }
                    }
                    .padding(.top, CicadaTheme.scaled(4))
                }
            }
            .padding(.vertical, CicadaTheme.scaled(8))
            .padding(.horizontal, CicadaTheme.scaled(8))
            .rowHoverFill(hovering: highlighted)
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    /// The node and the line through it: the line runs from the row above to the row below (none above the newest,
    /// none below the oldest read), the writer's picture sits on it.
    private var node: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                Rectangle().fill(first ? Color.clear : CicadaTheme.border)
                    .frame(width: HistoryLine.width, height: CicadaTheme.scaled(10))
                Spacer(minLength: 0).frame(height: HistoryLine.node)
                Rectangle().fill(last ? Color.clear : CicadaTheme.border)
                    .frame(width: HistoryLine.width)
                    .frame(maxHeight: .infinity)
            }
            HistoryWriterMark(entry: entry, size: HistoryLine.node)
                .padding(.top, CicadaTheme.scaled(10))
                .help(Copy.Graph.historyLineHelp)
        }
        .frame(width: HistoryLine.gutter)
        .frame(maxHeight: .infinity, alignment: .top)
        .accessibilityHidden(true)
    }
}

/// DR-77's writer picture. The person's own changes wear their face — the owner page's picture by G146's precedence
/// (`EntityPicture`: their choice, Contacts, a public profile, then their monogram), never a generic glyph; every
/// other writer keeps its mark (`ContributorAvatar`: the model's, the agent's own, Cicada's for upkeep). Before the
/// graph has named the owner page, the person's row falls back to the contributor avatar.
struct HistoryWriterMark: View {
    let entry: EntityHistoryEntry
    let size: CGFloat

    @Environment(Store.self) private var store

    private var kind: String { ContributorIdentity.kind(author: entry.author, serverKind: entry.authorKind) }

    static func ownerNode(_ nodes: [GraphNode]?) -> GraphNode? { nodes?.first { $0.isOwner } }

    var body: some View {
        if kind == "user", let owner = Self.ownerNode(store.graph.value?.nodes) {
            EntityPicture(id: owner.id, name: owner.name, type: .person, size: size)
        } else {
            ContributorAvatar(author: entry.author, kind: kind, provider: entry.authorProvider, size: size)
        }
    }
}

/// The hover card: who, what changed (short), when — and, pinned by a click, the change itself.
struct HistoryHoverCard: View {
    let entry: EntityHistoryEntry
    let entityId: String
    let showsChange: Bool
    let loadDiff: (String, String) async throws -> EntityDiff

    @State private var diff: EntityDiff?
    @State private var diffFailed = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                HistoryWriterMark(entry: entry, size: CicadaTheme.scaled(18))
                Text(HistoryRowWords.who(entry)).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                if HistoryBucket.of(entry) == .sleep { Tag(text: Copy.Graph.historySleep) }
            }
            Text(HistoryRowWords.changed(entry))
                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            if let lines = entry.summary?.lines, !lines.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                        Text("\(line.sign == "+" ? "+" : "−") \(line.text)")   // count-lint:ok — a sign and prose
                            .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
                    }
                }
            }
            Text(HistoryRowWords.when(entry, long: true))
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            if showsChange {
                Divider()
                if let diff { DiffView(diff: diff).frame(maxHeight: CicadaTheme.scaled(320)) }
                else if diffFailed { DiffView.error { Task { await fetch() } } }
                else { DiffView.loading }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(width: CicadaTheme.scaled(showsChange ? 520 : 320), alignment: .leading)
        .task(id: showsChange) { if showsChange, diff == nil { await fetch() } }
    }

    private func fetch() async {
        diffFailed = false
        do { diff = try await loadDiff(entityId, entry.commitHash) } catch { diffFailed = true }
    }
}

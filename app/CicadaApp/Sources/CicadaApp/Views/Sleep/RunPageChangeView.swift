import AppKit
import SwiftUI

// MARK: - What the read changed on a page (owner 2026-11-24)
//
// *"I would like the pages to render normally, not as raw markdown, because it's harder to read what the actual changes
// were. And I don't get why that page was modified there, what influenced this change? That is not clear in the UI
// either."* A click on a page chip opens the change as the page itself reads: why it changed first (only what the card it
// sits under does not already say), its facts as the entity card draws them with what moved in words, its text as the
// entity card's article draws it with the changed words washed or struck through in place, then the few other things that
// moved. No line numbers, no hunk headers, no JSON, no raw markdown. DR-9 (a ring, no shadow), DR-38 (said once),
// DR-81 (at most five rows, then "All N"), DR-7 (a dot never alone).

struct RunPageChange: View {
    let page: SleepConsolidated.Page
    let label: String
    let key: SleepConsolidatedKey
    var parent: RunPageChangeModel.Parent = .none
    let onOpen: () -> Void

    @State private var change: SleepPageChange?
    @State private var failed = false
    @Environment(\.runPageChangeLoader) private var loadChange

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(change.flatMap { RunPageChangeModel.sectionCount($0, parent: parent) <= 1 ? RunPageChangeModel.summary($0) : nil } ?? "")
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                InlineLink(title: Copy.RunCard.openPageAction, help: Copy.RunCard.openPage(label), action: onOpen)
            }
            window
        }
        .padding(.top, CicadaTheme.spacingXS)
        .task(id: "\(key)|\(page.id)") { if change == nil { await fetch() } }
    }

    @ViewBuilder
    private var window: some View {
        if let change {
            RunPageChangeBody(change: change, parent: parent)
        } else if failed {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.RunChange.unavailable)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextButton(title: Copy.RunChange.retry, inline: true) { Task { await fetch() } }
            }
        } else {
            Text(Copy.RunChange.loading)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func fetch() async {
        failed = false
        do {
            change = try await loadChange(key, page.id)
        } catch {
            failed = true
        }
    }
}

/// The change itself, in the ringed window the old diff sat in: why, facts, text, the rest — and, when there is nothing in
/// substance, one line saying so.
struct RunPageChangeBody: View {
    let change: SleepPageChange
    var parent: RunPageChangeModel.Parent = .none

    @Environment(Store.self) private var store: Store?
    @State private var showingAll: Set<String> = []

    private var evidenceIndex: EvidenceDocIndex {
        var byEpisode: [String: EvidenceDocMeta] = [:]
        for row in change.conversations {
            byEpisode[row.id] = EvidenceDocMeta(title: row.conversation.title, harness: nil,
                                                origin: row.conversation.origin, source: nil)
        }
        return EvidenceDocIndex(byEpisode: byEpisode)
    }

    /// Whether the page is its whole text (a made or removed page): nothing to wash, nothing to compare.
    private var wholePage: Bool { change.change == "created" || change.change == "removed" }

    private static let gap = CicadaTheme.spacingMD

    var body: some View {
        let why = RunPageChangeModel.why(change, parent: parent)
        let groups = factGroups
        let hasText = change.prose.hasChange
        let hasOther = !change.other.isEmpty || change.otherDetails > 0
        let sections = (why.isEmpty ? 0 : 1) + groups.count + (hasText ? 1 : 0) + (hasOther ? 1 : 0)
        VStack(alignment: .leading, spacing: Self.gap) {
            if !why.isEmpty { whySection(why) }
            ForEach(groups, id: \.id) { factSection($0, labelled: sections > 1) }
            if change.facts.faded > 0 && change.hasContent {
                Text(Copy.RunChange.otherFacts(fadedCount: change.facts.faded))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            if hasText { textSection(labelled: sections > 1) }
            if hasOther { otherSection(labelled: sections > 1) }
            if !change.hasContent { quiet(emptyLine) }
            if change.truncated || change.facts.truncated || change.prose.truncated { quiet(Copy.RunChange.cut) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .environment(\.evidenceDocIndex, evidenceIndex)
    }

    private var emptyLine: String {
        change.change == "faded" ? Copy.RunChange.faded : Copy.RunCard.noChange
    }

    private func quiet(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
    }

    private func caption(_ text: String, show: Bool) -> some View {
        Group { if show { SectionLabel(text) } }
    }

    // MARK: Why

    private func whySection(_ why: RunPageChangeModel.Why) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            SectionLabel(parent == .none ? Copy.RunChange.changedBy : Copy.RunChange.alsoChangedBy)
            ForEach(why.conversations) { RunChangeConversationLine(conversation: $0) }
            ForEach(why.steps, id: \.self) { step in
                HStack(spacing: CicadaTheme.scaled(6)) {
                    OriginMark(origin: "cicada", size: CicadaTheme.scaled(14))
                    Text(Copy.RunChange.stepSentence(step))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
    }

    // MARK: Facts

    enum FactKind: String { case added, changed, withdrawn }

    struct FactGroup: Identifiable {
        let kind: FactKind
        let facts: [SleepPageChange.Fact]
        let total: Int
        var id: String { kind.rawValue }
    }

    private var factGroups: [FactGroup] {
        let f = change.facts
        return [FactGroup(kind: .added, facts: f.added, total: f.counts["added"] ?? f.added.count),
                FactGroup(kind: .changed, facts: f.changed, total: f.counts["changed"] ?? f.changed.count),
                FactGroup(kind: .withdrawn, facts: f.withdrawn, total: f.counts["withdrawn"] ?? f.withdrawn.count)]
            .filter { !$0.facts.isEmpty }
    }

    private func factSection(_ group: FactGroup, labelled: Bool) -> some View {
        let all = showingAll.contains("facts.\(group.id)")
        let shown = all ? group.facts : Array(group.facts.prefix(RunPageChangeModel.factsShown))
        let title: String
        switch group.kind {
        case .added: title = Copy.RunChange.factsAdded
        case .changed: title = Copy.RunChange.factsChanged
        case .withdrawn: title = Copy.RunChange.factsWithdrawn
        }
        return VStack(alignment: .leading, spacing: 0) {
            caption(title, show: labelled)
            ForEach(shown) { fact in
                RunChangeFactRow(fact: fact, kind: group.kind, words: RunPageChangeModel.factWords(fact),
                                 conversation: RunPageChangeModel.factConversation(fact, in: change, parent: parent))
            }
            if group.facts.count > RunPageChangeModel.factsShown {
                TextButton(title: all ? Copy.RunChange.showFewer : Copy.RunCard.showAll(group.total), inline: true) {
                    showingAll.formSymmetricDifference(["facts.\(group.id)"])
                }
                .padding(.leading, CicadaTheme.scaled(10))
                .padding(.top, CicadaTheme.spacingXS)
            }
        }
    }

    // MARK: Text

    private func textSection(labelled: Bool) -> some View {
        let items = RunPageChangeModel.proseItems(change.prose.blocks)
        let all = showingAll.contains("text")
        let blocks = items.filter { if case .block = $0 { true } else { false } }
        // The first `blocksShown` blocks, with the quiet "under" lines that lead them.
        var shown: [RunPageChangeModel.ProseItem] = []
        var seen = 0
        for item in items {
            if case .block = item {
                if !all && seen >= RunPageChangeModel.blocksShown { break }
                seen += 1
            }
            shown.append(item)
        }
        if case .under? = shown.last { shown.removeLast() }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            caption(Copy.RunChange.text, show: labelled)
            ForEach(shown) { item in
                switch item {
                case .under(let heading, _):
                    Text(heading)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .padding(.top, CicadaTheme.spacingXS)
                case .block(let block, _):
                    RunChangeBlock(block: block, marked: !wholePage)
                }
            }
            if blocks.count > RunPageChangeModel.blocksShown {
                TextButton(title: all ? Copy.RunChange.showFewer : Copy.RunCard.showAll(blocks.count), inline: true) {
                    showingAll.formSymmetricDifference(["text"])
                }
            }
        }
    }

    // MARK: The page's own record

    private func otherSection(labelled: Bool) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            caption(Copy.RunChange.pageRecord, show: labelled)
            ForEach(Array(change.other.flatMap(RunPageChangeModel.otherLines).enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if change.otherDetails > 0 {
                quiet(Copy.RunChange.smaller(change.otherDetails))
            }
        }
    }
}

// MARK: - A conversation, as a line

/// A conversation of the run that changed the page, as the card draws one: its source's real mark and its title, a click
/// opens it in the Reader.
struct RunChangeConversationLine: View {
    let conversation: SleepConsolidated.Conversation
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @State private var hovering = false

    var body: some View {
        let label = RunItemGroups.conversationLabel(conversation)
        Button {
            reader?.open(ReaderTarget(episode: conversation.id, knownTitle: conversation.title))
        } label: {
            HStack(spacing: CicadaTheme.scaled(6)) {
                StudyListCard.mark(conversation.origin, size: CicadaTheme.scaled(14))
                Text(label)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(conversation.id)
        .accessibilityLabel(Copy.RunCard.openConversation(label))
    }
}

// MARK: - A fact

/// One fact as the entity card draws a belief (`BeliefRow`: the sentence, who said it as evidence chips with their real
/// marks) with what moved in it in words under it and, when its own evidence names a conversation other than the card's,
/// that conversation beside it. A dot at the left says what happened to it — green new, none changed, red withdrawn —
/// and the group's words (or the line above) say it in words (DR-7).
struct RunChangeFactRow: View {
    let fact: SleepPageChange.Fact
    let kind: RunPageChangeBody.FactKind
    let words: String?
    let conversation: SleepConsolidated.Conversation?

    private var dot: Color? {
        switch kind {
        case .added: CicadaTheme.success
        case .withdrawn: CicadaTheme.danger
        case .changed: nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            BeliefRow(claim: fact.claim)
                .opacity(kind == .withdrawn ? 0.65 : 1)
            if let words {
                Text(words)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.leading, CicadaTheme.scaled(10))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let conversation {
                RunChangeConversationLine(conversation: conversation)
                    .padding(.leading, CicadaTheme.scaled(10))
                    .padding(.top, CicadaTheme.scaled(2))
            }
        }
        .overlay(alignment: .topLeading) {
            if let dot {
                Circle().fill(dot)
                    .frame(width: CicadaTheme.scaled(Tag.dotSize), height: CicadaTheme.scaled(Tag.dotSize))
                    .padding(.top, CicadaTheme.scaled(15))
                    .accessibilityHidden(true)
            }
        }
        .accessibilityElement(children: .contain)
    }
}

// MARK: - A block of the page's text

/// One block of the page's own markdown, drawn by the entity card's article (`PageRun`): headings, lists, links as the app
/// draws links. A bar at the leading edge says an added block (green) or a removed one (red); an edited paragraph shows its
/// words washed or struck through in place and a block of context is quieter. Never raw markdown.
struct RunChangeBlock: View {
    let block: SleepPageChange.Block
    var marked = true

    @Environment(Store.self) private var store: Store?

    private var bar: Color? {
        guard marked else { return nil }
        switch block.op {
        case .added: return CicadaTheme.success
        case .removed: return CicadaTheme.danger
        case .edited, .context: return nil
        }
    }

    var body: some View {
        let rows = RunPageChangeModel.rows(block, marked: marked)
        HStack(alignment: .top, spacing: CicadaTheme.scaled(8)) {
            Rectangle()
                .fill(bar ?? .clear)
                .frame(width: CicadaTheme.scaled(2))
                .accessibilityHidden(true)
            PageRun(rows: rows, entityId: nil, citations: nil, related: [:], index: store?.linkIndex ?? .empty)
                .opacity(block.op == .context && marked ? 0.62 : 1)
        }
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.RunChange.blockWord(block.op))
    }
}

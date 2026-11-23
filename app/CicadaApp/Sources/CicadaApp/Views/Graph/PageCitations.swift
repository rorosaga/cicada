import SwiftUI

// MARK: - The article carries the beliefs (ruling 48 (16), DR-80, amended 2026-11-23)
//
// A cited passage ends in **one cluster of its sources' own marks** — where each was said (the ChatGPT, Claude or Notes
// mark, a chat app's mark, the agent's mark), up to three, then "+N" — never a run of superscript numbers (owner
// 2026-11-23: *"also the number for references I dont really like"*). Which passage each source backs is the server's
// (`page_citations`): decided when the page was written, never guessed here. The cluster opens a popover — a floating
// surface (DR-10), never an inline expansion — that lists every source of the passage as a row: its mark, who and where,
// the day, the located words (DR-18) and *Show in conversation* into the Reader (DR-31). A row's details are read when
// it is shown, one `GET /entities/{id}/citations/{n}` each.
//
// Keys: the cluster is in the focus order, ⏎ opens it, Esc closes it; hovering it opens it after a rest.

/// Which source is open: a source as cited by the line ending at `at`, or by a belief sentence.
struct CiteKey: Hashable, Identifiable {
    let n: Int
    var at: Int? = nil
    var claim: String? = nil
    var inferred = false

    var id: String { "\(n)|\(at ?? -1)|\(claim ?? "")" }

    init(n: Int, at: Int? = nil, claim: String? = nil, inferred: Bool = false) {
        self.n = n
        self.at = at
        self.claim = claim
        self.inferred = inferred
    }
}

enum CitationMarks {
    /// A line's keys, in the order its sources were cited.
    static func keys(_ markers: [PageBlocks.Citations.Marker]) -> [CiteKey] {
        markers.flatMap { marker in marker.refs.map { CiteKey(n: $0, at: marker.at) } }
    }

    /// The one cluster that ends a passage citing `keys`: nil when it cites nothing.
    static func cluster(_ keys: [CiteKey], in citations: PageBlocks.Citations?) -> (SourceClusterModel, [CiteKey])? {
        guard !keys.isEmpty else { return nil }
        let model = SourceClusterModel(keys: keys.map { citations?.markKey(forRef: $0.n) })
        return model.isEmpty ? nil : (model, keys)
    }
}

/// The cluster of marks that ends a cited passage. It sits on the line's baseline, glued to the last word by the flow.
struct SourceCluster: View {
    let model: SourceClusterModel
    let keys: [CiteKey]
    let entityId: String
    /// What the marks are knocked out of: the page's ground.
    var ground: Color = CicadaTheme.bgBase

    @State private var open = false
    @State private var hovering = false
    @State private var previewHovered = false
    @State private var openedByHover = false
    @State private var hoverTask: Task<Void, Never>?
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.scaled(6)) }

    var body: some View {
        Button {
            hoverTask?.cancel()
            openedByHover = false
            open = true
        } label: {
            RunSourceMarks(origins: model.marks, style: .passage, more: model.more, ground: ground)
                .padding(.horizontal, CicadaTheme.scaled(2))
                .background(shape.fill(hovering || focused || open ? CicadaTheme.bgSelected : .clear))
                .contentShape(shape)
        }
        .buttonStyle(.cicadaPlain)
        // The marks' centre sits where lowercase letters do, so the cluster reads on the words' line.
        .alignmentGuide(.firstTextBaseline) { d in d.height / 2 + CicadaTheme.scaled(5) }
        .onHover(perform: pointer)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.return) {
            openedByHover = false
            open = true
            return .handled
        }
        .popover(isPresented: $open, arrowEdge: .bottom) {
            CitationsPopover(entityId: entityId, keys: keys)
                .onHover { inside in
                    previewHovered = inside
                    if !inside { leave() }
                }
        }
        .help(Copy.Pages.sourcesHelp(model.total))
        .accessibilityLabel(Copy.Pages.sourcesSpoken(model.total))
        .accessibilityHint(Copy.Pages.sourcesHint)
        .accessibilityAddTraits(.isButton)
    }

    /// Dwell to open, grace to close (the evidence chip's rule, `CicadaTiming`): sweeping the pointer across a page opens
    /// nothing, and a popover the pointer left closes unless it was opened by a click or a key.
    private func pointer(inside: Bool) {
        hovering = inside
        hoverTask?.cancel()
        hoverTask = Task { @MainActor in
            let wait = inside ? CicadaTiming.hoverPreviewDelay : CicadaTiming.hoverPreviewGrace
            try? await Task.sleep(for: .seconds(wait))
            guard !Task.isCancelled else { return }
            if inside {
                if hovering, !open {
                    openedByHover = true
                    open = true
                }
            } else {
                closeIfIdle()
            }
        }
    }

    private func leave() {
        hoverTask?.cancel()
        hoverTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(CicadaTiming.hoverPreviewGrace))
            guard !Task.isCancelled else { return }
            closeIfIdle()
        }
    }

    private func closeIfIdle() {
        if openedByHover, !hovering, !previewHovered { open = false }
    }
}

/// Every source of a passage, one row each: its mark, who and where and what it is called, the day, the located words
/// and the way into the conversation. A floating surface (DR-10); long lists scroll.
struct CitationsPopover: View {
    let entityId: String
    let keys: [CiteKey]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ForEach(keys) { key in CitationSourceRow(entityId: entityId, key: key) }
            }
            .padding(CicadaTheme.spacingMD)
        }
        .frame(width: CicadaTheme.scaled(380))
        .frame(maxHeight: CicadaTheme.scaled(420))
    }
}

/// One source of a passage, read when its row is first shown.
struct CitationSourceRow: View {
    let entityId: String
    let key: CiteKey
    @Environment(ProvenanceRouter.self) private var router: ProvenanceRouter?
    @Environment(\.dismiss) private var dismiss
    @State private var phase: Phase = .loading

    enum Phase: Equatable {
        case loading
        case loaded(PageCitationDetail)
        case failed
        /// The page was renumbered since this passage was drawn (409): its line no longer cites this source.
        case stale
    }

    private var markSize: CGFloat { CicadaTheme.scaled(20) }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            mark
                .frame(width: markSize, height: markSize)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                switch phase {
                case .loading:
                    Text(Copy.Pages.readingSource).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                case .failed:
                    Text(Copy.Pages.sourceUnavailable).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                case .stale:
                    Text(Copy.Pages.sourceMoved).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                case .loaded(let detail):
                    loaded(detail)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task(id: key) { await load() }
    }

    @ViewBuilder
    private var mark: some View {
        if case .loaded(let d) = phase {
            RunSourceMarks.markView(PageWords.markKey(kind: d.kind, harness: d.harness, origin: d.origin),
                                    size: markSize)
        } else {
            CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBadge.opacity(0.5))
        }
    }

    @ViewBuilder
    private func loaded(_ d: PageCitationDetail) -> some View {
        let when = PageWords.refWhen(first: d.first, last: d.last, today: ISODay.today())
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            Text(line(d)).font(CicadaTheme.metaFont).lineLimit(2)
            Spacer(minLength: 0)
            if let when {
                Text(when).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    .fixedSize()
            }
        }
        let kind = PageWords.popoverKind(d, inferred: key.inferred)
        if let span = d.span, !span.excerpt.isEmpty {
            let parts = QuoteBlock.parts(excerpt: span.excerpt, mentionOffsets: span.mentionOffsets)
            QuoteBlock(before: parts.before, span: parts.span, after: parts.after, kind: span.displayKind,
                       label: kind, caption: span.stale ? Copy.Provenance.staleCaption : nil,
                       style: span.stale ? .plain : .wash, lineLimit: 6)
        } else {
            Text(kind).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
        if d.isSourceRemoved {
            // G104 slice 3, DR-80: a quiet note, never a banner and never a change to the quote (DR-18).
            Text(Copy.Provenance.sourceRemoved).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
        if let note = d.correctionNote {
            // G244, DR-80/DR-18: the same quiet note for an agent's edit of the source; the quote is never changed.
            Text(note).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
        if router != nil, target(d) != nil {
            TextButton(title: Copy.Provenance.showIn(d.sourceKind ?? d.kind) + " ›", inline: true, flushLeading: true) {
                open(d)
            }
            .fixedSize()
        }
    }

    /// "You, in ChatGPT · <title>" — who and where in the secondary ink, the title in the primary (References' line).
    private func line(_ d: PageCitationDetail) -> AttributedString {
        var who = AttributedString(PageWords.who(kind: d.kind, harness: d.harness, origin: d.origin,
                                                 correspondent: d.correspondent))
        who.foregroundColor = CicadaTheme.textSecondary
        guard let title = d.title, !title.isEmpty else { return who }
        var rest = AttributedString(" · \(title)")
        rest.foregroundColor = CicadaTheme.textPrimary
        return who + rest
    }

    private func target(_ d: PageCitationDetail) -> ReaderTarget? {
        if let span = d.span {
            return ReaderTarget.best(span, subjectId: entityId, knownTitle: d.title, knownHarness: d.harness)
        }
        // ROR-16 — nothing located still opens the source; no quote, no apology.
        guard let episode = d.episodeId else { return nil }
        return ReaderTarget(episode: episode, focus: .none, subjectId: entityId, knownTitle: d.title,
                            knownHarness: d.harness)
    }

    private func open(_ d: PageCitationDetail) {
        guard let router, let target = target(d) else { return }
        router.open(target)
        dismiss()   // The source opens beside the article; the popover would stay over whatever moved under it.
    }

    private func load() async {
        let cacheKey = "\(entityId)|\(key.id)"
        if let held = CitationDetailCache.shared.held[cacheKey] {
            phase = .loaded(held)
            return
        }
        phase = .loading
        do {
            let detail = try await APIClient.shared.fetchCitation(entityId: entityId, n: key.n, at: key.at,
                                                                  claim: key.claim)
            guard !Task.isCancelled else { return }
            CitationDetailCache.shared.held[cacheKey] = detail
            phase = .loaded(detail)
        } catch APIError.httpError(409, _) {
            if !Task.isCancelled { phase = .stale }
        } catch {
            if !Task.isCancelled { phase = .failed }
        }
    }
}

/// Popovers already read, by page and source — in memory, a few hundred at most. A page's are dropped whenever its
/// blocks change (`track`: a re-read after a write, an agent's edit, Sleep's push) as well as on its next open, so a
/// renumbered page never shows an old source. Not a Store domain.
@MainActor
final class CitationDetailCache {
    static let shared = CitationDetailCache()
    var held: [String: PageCitationDetail] = [:]
    /// The blocks each page's held popovers were read under.
    private var under: [String: PageBlocks] = [:]

    /// The card's page now has `blocks`: anything held from other blocks is forgotten.
    func track(_ entityId: String, blocks: PageBlocks?) {
        guard let blocks else { return }
        if let previous = under[entityId], previous == blocks { return }
        if under[entityId] != nil { forget(entityId) }
        under[entityId] = blocks
        if under.count > 64 { under = [entityId: blocks] }
    }

    func forget(_ entityId: String) {
        held = held.filter { !$0.key.hasPrefix(entityId + "|") }
        if held.count > 400 { held.removeAll() }
    }
}

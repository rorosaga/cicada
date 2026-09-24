import SwiftUI

/// The Reader (G118 slice 2, design §4.4): a conversation, or a page's stored
/// text, opened beside whatever is on screen and scrolled to the sentence a
/// belief came from — the belief and its sentence side by side is the point
/// of the feature.
///
/// R-DI6 / DR-31 — a COLUMN, no longer a trailing `.inspector`. An inspector's
/// width is not the page's to give: nothing reconciled the Reader's minimum
/// with a page's rigid one (the Inbox's non-wrapping chip row, for one), so the
/// split could run past the window's right edge and clip the Reader's text.
/// Now a host decides the Reader's width first (`ShellReaderHost`, and the
/// Inbox's `ProgressiveColumns` from DS-2 Task 5) and the page gets the rest.
///
/// C's styling (DESIGN_RULES §5.4): mark, title and meta; Resume as a neutral
/// button; the pinned "1 of N cited here" navigator; the words in the quote
/// face with the cited span washed and underlined (`CitedSpan`, DR-18) and a
/// span found by name bold, never washed (DR-57, R-DI11); the "Noted from this
/// conversation" rows in the same scroll (DR-30: each column scrolls once).
///
/// Content, not chrome: no glass anywhere in here (R-M5, K12). Everything it
/// shows is fetched from the bank on demand and held in memory only — spans,
/// not copies (§4.9).
struct ReaderColumn: View {
    @Environment(ProvenanceRouter.self) private var router
    @Environment(ProvenanceCache.self) private var cache
    @Environment(Store.self) private var store
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var appRouter
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Phase {
        case loading
        case loaded(EpisodeText, ScalarText)
        case gone
        case failed
    }

    @State private var phase: Phase = .loading
    @State private var washVisible = false
    @State private var landingToken = 0
    @State private var conversations = ConversationsViewModel()
    /// P4 — what this document taught Cicada (`/citations`, G106 (ii)).
    @State private var citations: EpisodeCitations?
    /// A navigator step or a "Noted" row re-focuses the Reader IN PLACE on
    /// that citation; the router trail is for moving between documents.
    @State private var jump: EpisodeCitation?

    /// DR-61 / §5.4 — the column's horizontal inset, shared by the header's
    /// leading edge, the pinned row and the text, so all three align.
    static let inset: CGFloat = 28

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ReaderColumnHeader(
                canGoBack: router.canGoBack,
                onBack: { router.back() },
                page: loadedDoc.flatMap { $0.isPage ? $0 : nil },
                markOrigin: ReaderHeader.markOrigin(harness: loadedDoc?.harness ?? router.current?.knownHarness,
                                                    origin: loadedDoc?.origin),
                episode: loadedDoc?.episode ?? router.current?.episode ?? "",
                title: title,
                meta: meta,
                canResume: conversationId.map { conversations.canResume($0) } ?? false,
                agent: loadedDoc.flatMap { EvidenceSpeaker.agentName(harness: $0.harness, origin: $0.origin) },
                onResume: {
                    // `POST /conversations/{id}/resume` only ever checks `isfile()`.
                    guard let id = conversationId else { return }
                    Task { await act(await conversations.resume(id)) }
                },
                // A pointer path: the host's drawer animation plays (DR-61).
                onClose: { router.close() })
            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgPane)
        // DR-9 — the column's leading edge is the one rule.
        .columnEdge()
        // R-DI10 — Tab reaches the Reader after the question, and Esc reaches it while it holds focus.
        .focusable()
        .focusEffectDisabled()
        // DR-60 — Esc is a keyboard path, so it never animates.
        .onExitCommand { Instant.run { router.close() } }
        .task(id: router.current) { await load() }
    }

    // MARK: Loading

    private func load() async {
        guard let target = router.current else { return }
        phase = .loading
        washVisible = false
        jump = nil
        citations = nil
        let result = await cache.document(episode: target.episode, focus: target.query)
        // `.task(id:)` cancels a superseded load, but cancellation is
        // cooperative: a slow fetch for the previous target must never land
        // on the Reader after the person has moved on to another.
        guard !Task.isCancelled, router.current == target else { return }
        switch result {
        case let .loaded(doc):
            phase = .loaded(doc, ScalarText(doc.text))
            landingToken &+= 1
            let cited = await cache.citations(episode: target.episode).value
            guard !Task.isCancelled, router.current == target else { return }
            citations = cited
            if let id = doc.conversationId, !doc.isPage {
                await conversations.load(ids: [id])
            }
        case .gone:
            phase = .gone
        case .failed:
            phase = .failed
        }
    }

    // MARK: Header inputs

    private var loadedDoc: EpisodeText? {
        if case let .loaded(doc, _) = phase { return doc }
        return nil
    }

    private var title: String {
        let known = loadedDoc?.title ?? router.current?.knownTitle ?? ""
        return known.isEmpty ? Copy.Provenance.untitled : known
    }

    private var meta: String { loadedDoc.map { ReaderHeader.meta($0) } ?? "" }
    private var conversationId: String? { loadedDoc?.conversationId }

    private func act(_ outcome: ResumeOutcome) async {
        store.toast = outcome.toast
    }

    // MARK: Body

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            ReaderSkeleton()
        case .gone:
            stateLine(Copy.Provenance.gone)
        case .failed:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                stateLine(Copy.Provenance.failed)
                NeutralButton(title: Copy.Provenance.retry, size: .compact) { Task { await load() } }
                    .padding(.horizontal, CicadaTheme.scaled(Self.inset))
            }
        case let .loaded(doc, scalars):
            if let target = router.current {
                document(doc, scalars: scalars, target: target)
            }
        }
    }

    /// DR-37 — a state is said in words, never a filled block.
    private func stateLine(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, CicadaTheme.scaled(Self.inset))
            .padding(.top, CicadaTheme.scaled(4))
    }

    private func document(_ doc: EpisodeText, scalars: ScalarText, target: ReaderTarget) -> some View {
        let presentation = jump.map {
            ReaderPresentation.citation($0, truncated: doc.truncated, textCount: scalars.count)
        } ?? ReaderPresentation.resolve(target: target, doc: doc, textCount: scalars.count)
        let rows = citations?.citations ?? []
        let stops = ReaderNavigator.stops(rows, subjectId: target.subjectId)
        let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: presentation.focus,
                                         focusStyle: presentation.focusStyle,
                                         others: stops.filter { $0 != presentation.focus })
        let landingBlock = presentation.landing.flatMap { ReaderLayout.blockID(containing: $0, in: blocks) }
        let position = ReaderNavigator.position(of: presentation.focus, in: stops)
        let captureLine = ReaderHeader.captureLine(doc)
        // One rotor stop per cited turn, even when the words straddle two of
        // its chunks — the rotor names turns, not layout pieces.
        var citedTurns = Set<Int>()
        let citedBlocks = blocks.filter { $0.holdsFocus && citedTurns.insert($0.index).inserted }
        return ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // Pinned ABOVE the text, never inside it: landing scrolls the
                // cited turn to the centre, so a bar at the top of the scrolled
                // stack would leave the screen the moment the Reader arrives
                // (and, lazily unrealised, take ⌥↑ / ⌥↓ with it).
                if captureLine != nil || stops.count > 1 {
                    HStack(alignment: .center, spacing: CicadaTheme.spacingXS) {
                        if let captureLine {
                            // DR-53 — no `info.circle`: a glyph that adds nothing.
                            Text(captureLine)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if stops.count > 1 {
                            navigator(stops: stops, rows: rows, subjectId: target.subjectId, position: position)
                        }
                    }
                    .padding(.horizontal, CicadaTheme.scaled(Self.inset))
                    .padding(.bottom, CicadaTheme.spacingSM)
                }
                ScrollView {
                    // Spacing 0 so a long turn's chunks (`ReaderLayout.chunks`)
                    // read on as one text; the gap goes between turns instead.
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(presentation.banners, id: \.self) { banner in
                            ReaderBannerView(banner: banner)
                                .padding(.bottom, CicadaTheme.spacingMD)
                        }
                        if blocks.isEmpty {
                            Text(Copy.Provenance.empty)
                                .font(CicadaTheme.detailBodyFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        // Flattened into this lazy stack, so a 400,000-character
                        // conversation's chunks are still realised on demand.
                        ReaderTurnRows(blocks: blocks, landingTurn: landingBlock?.turn, revealed: washVisible)
                        if let citations {
                            notedList(citations, doc: doc, currentRange: presentation.focus)
                                .padding(.top, CicadaTheme.scaled(32))
                        }
                    }
                    .padding(.top, CicadaTheme.scaled(4))
                    .padding(.horizontal, CicadaTheme.scaled(Self.inset))
                    .padding(.bottom, CicadaTheme.scaled(72))
                }
                .accessibilityRotor("Cited passages") {
                    ForEach(citedBlocks) { block in
                        AccessibilityRotorEntry(Text(Copy.Provenance.rotorLabel(speaker: block.speaker, turn: block.index)),
                                                id: block.id)
                    }
                }
                .accessibilityRotor("Turns") {
                    ForEach(blocks.filter(\.startsTurn)) { block in
                        AccessibilityRotorEntry(Text(Copy.Provenance.rotorLabel(speaker: block.speaker, turn: block.index)),
                                                id: block.id)
                    }
                }
                .onChange(of: landingToken, initial: true) { _, _ in
                    land(proxy: proxy, block: landingBlock, blocks: blocks, presentation: presentation)
                }
            }
        }
    }

    // MARK: Navigator (P4)

    /// "‹ 2 of 5 cited here ›" — steps through the spans this entity's claims
    /// cite in this document (or every cited span when the Reader was not
    /// opened for an entity). ⌥↓ / ⌥↑ from anywhere in the Reader.
    private func navigator(stops: [Range<Int>], rows: [EpisodeCitation], subjectId: String?,
                           position: Int?) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            IconButton(systemName: "chevron.up", help: "\(Copy.Provenance.previousCited) (⌥↑)",
                       accessibilityLabel: Copy.Provenance.previousCited,
                       shortcut: KeyboardShortcut(.upArrow, modifiers: .option)) {
                step(-1, stops: stops, rows: rows, subjectId: subjectId, position: position)
            }
            .disabled(position == 0)
            Text(ReaderNavigator.label(position: position, count: stops.count))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .monospacedDigit()
                .lineLimit(1)
                .fixedSize()
            IconButton(systemName: "chevron.down", help: "\(Copy.Provenance.nextCited) (⌥↓)",
                       accessibilityLabel: Copy.Provenance.nextCited,
                       shortcut: KeyboardShortcut(.downArrow, modifiers: .option)) {
                step(1, stops: stops, rows: rows, subjectId: subjectId, position: position)
            }
            .disabled(position == stops.count - 1)
        }
    }

    private func step(_ delta: Int, stops: [Range<Int>], rows: [EpisodeCitation], subjectId: String?,
                      position: Int?) {
        guard let next = ReaderNavigator.step(from: position, count: stops.count, by: delta) else { return }
        let stop = stops[next]
        let candidates = rows.filter { $0.range == stop }
        jumpTo(candidates.first { $0.subjectId == subjectId } ?? candidates.first)
    }

    private func jumpTo(_ citation: EpisodeCitation?) {
        guard let citation, citation.range != nil else { return }
        washVisible = false
        jump = citation
        landingToken &+= 1
    }

    // MARK: Noted from this conversation (P4, G106 (ii))

    private func notedList(_ payload: EpisodeCitations, doc: EpisodeText, currentRange: Range<Int>?) -> some View {
        let citedIds = Set(payload.citations.map(\.subjectId))
        let alsoOn = payload.entities.filter { !citedIds.contains($0.entityId) }
            .map { $0.name.isEmpty ? $0.entityId : $0.name }
        return ReaderNotedList(
            rows: payload.citations, currentRange: currentRange, isPage: doc.isPage,
            agent: EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin),
            alsoOn: alsoOn, partial: payload.partial,
            onJump: { jumpTo($0) },
            onShowOnGraph: { row in
                appRouter.pendingTab = .graph
                graphVM.revealEntity(id: row.subjectId)
            })
    }

    /// Scroll to the cited turn after the first layout, fade the wash in over
    /// `spanReveal`, then say what was landed on (§4.4 Landing).
    private func land(proxy: ScrollViewProxy, block: ReaderBlock.Key?, blocks: [ReaderBlock],
                      presentation: ReaderPresentation) {
        Task { @MainActor in
            await Task.yield()
            if let block { proxy.scrollTo(block, anchor: .center) }
            withAnimation(CicadaMotion.spanReveal(reduceMotion: reduceMotion)) { washVisible = true }
            // The first block's piece of the words: a chunk holds at least
            // `chunkLimit / 2` scalars, so the 120 announced almost always sit
            // in one block, and never read a marker line out loud.
            guard presentation.focus != nil, let hit = blocks.first(where: { $0.holdsFocus }),
                  let wash = hit.washes.first(where: { $0.style != .other }) else { return }
            let words = ScalarText(hit.text).slice(wash.range.lowerBound, wash.range.upperBound)
            AccessibilityNotification.Announcement(Copy.Provenance.citedPassage(String(words.prefix(120))))
                .post()
        }
    }
}

// MARK: - The header

/// The mock's header (§5.4, DR-16): Back, the mark, the title in the display face at 20 over its
/// meta line, Resume as a neutral button, Close. A value view, so the loading state draws the same
/// header from the target's known fields (DR-32).
struct ReaderColumnHeader: View {
    let canGoBack: Bool
    let onBack: () -> Void
    /// The loaded document when it is a page, else nil.
    let page: EpisodeText?
    let markOrigin: String
    let episode: String
    let title: String
    let meta: String
    let canResume: Bool
    let agent: String?
    let onResume: () -> Void
    let onClose: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            if canGoBack {
                // ⌥⌘[ rather than ⌘[: the entity card beside the Reader
                // already owns ⌘[ for its own back (plan R-PU9).
                IconButton(systemName: "chevron.left", help: "\(Copy.Provenance.back) (⌥⌘[)",
                           accessibilityLabel: Copy.Provenance.back,
                           shortcut: KeyboardShortcut("[", modifiers: [.command, .option]), action: onBack)
            }
            mark
                .padding(.top, CicadaTheme.scaled(2))
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(CicadaTheme.displayFont(size: 20))
                    .tracking(CicadaTheme.displayTracking(size: 20))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                if !meta.isEmpty {
                    Text(meta)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if canResume {
                NeutralButton(title: Copy.Provenance.resume, systemImage: "arrow.uturn.right", size: .compact,
                              help: Copy.Provenance.resumeHelp(agent), action: onResume)
            }
            IconButton(systemName: "xmark", help: Copy.Provenance.closeHelp,
                       accessibilityLabel: Copy.Provenance.close, action: onClose)
        }
        .padding(.top, CicadaTheme.scaled(18))
        .padding(.trailing, CicadaTheme.scaled(16))
        .padding(.bottom, CicadaTheme.scaled(12))
        .padding(.leading, CicadaTheme.scaled(ReaderColumn.inset))
    }

    /// DR-52 — a service is named by its real mark; the episode id only ever in `.help` (DR-54).
    @ViewBuilder
    private var mark: some View {
        if let page {
            LogoImage(entityId: page.episode, name: page.title, type: .media, size: CicadaTheme.scaled(20))
        } else {
            OriginMark(origin: markOrigin, size: CicadaTheme.scaled(20))
                .markHover()
                .help(Copy.Provenance.episodeHelp(episode))
        }
    }
}

// MARK: - Turns

/// The turns in a plain stack — what a host outside a lazy stack draws, and what the layout
/// tests measure (`ReaderColumnLayoutTests`). The Reader itself flattens `ReaderTurnRows` into its
/// own `LazyVStack`, so the same rows stay lazily realised there.
struct ReaderTurnsView: View {
    let blocks: [ReaderBlock]
    let landingTurn: Int?
    let revealed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ReaderTurnRows(blocks: blocks, landingTurn: landingTurn, revealed: revealed)
        }
    }
}

/// One row per block, 16 pt between turns, each `.id(block.id)` so landing and both rotors can
/// scroll to it. A `ForEach` body, so a parent stack receives the rows themselves.
struct ReaderTurnRows: View {
    let blocks: [ReaderBlock]
    let landingTurn: Int?
    let revealed: Bool

    var body: some View {
        ForEach(blocks) { block in
            // The landing TURN reads in the primary colour, all of its
            // chunks, not just the one scrolled to.
            ReaderTurnView(block: block, isLanding: block.index == landingTurn, revealed: revealed)
                .padding(.top, block.startsTurn && block.id != blocks.first?.id ? CicadaTheme.scaled(16) : 0)
                .id(block.id)
        }
    }
}

/// One turn: the speaker line, then the words. R-DI20 — every word a person or an agent said
/// passes through the quote face (DR-18); the cited span is a `CitedSpan` (R-DI11), which replaced
/// the dandelion wash and its margin bar (DR-13). Selectable text; the landing turn reads in the
/// primary colour, the rest secondary.
struct ReaderTurnView: View {
    let block: ReaderBlock
    let isLanding: Bool
    let revealed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if block.startsTurn, !block.speaker.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
                    if let mark = block.mark {
                        OriginMark(origin: mark, size: CicadaTheme.scaled(12))
                    }
                    Text(block.speaker)
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text("· " + Copy.Provenance.turn(block.index))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    if let time = block.time {
                        Text(time)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            CitedSpan.text(ReaderText.segments(block))
                .font(CicadaTheme.quoteFont)
                .lineSpacing(CicadaTheme.quoteLineSpacing)
                .foregroundStyle(isLanding ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .citedSpans(reveal: revealed ? 1 : 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(block.speaker.isEmpty || !block.startsTurn
                            ? block.text
                            : Copy.Provenance.turnLabel(speaker: block.speaker, turn: block.index, text: block.text))
    }
}

// MARK: - Noted from this conversation

/// Every belief this document contributed (DR-48): the claim over who said it, the current one
/// selected. A row with offsets jumps the text to its words; the trailing scope lands on the
/// subject in the graph (G123). The subject's logo left the row (DR-38: the claim already names
/// it). Inside the Reader's one scroll, so it is only ever built for a loaded document.
struct ReaderNotedList: View {
    let rows: [EpisodeCitation]
    let currentRange: Range<Int>?
    let isPage: Bool
    let agent: String?
    /// Pages that name this document but cite none of its words.
    let alsoOn: [String]
    /// R-PB10: the server stopped at its page cap.
    let partial: Bool
    let onJump: (EpisodeCitation) -> Void
    let onShowOnGraph: (EpisodeCitation) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(Copy.Provenance.noted(count: rows.count, isPage: isPage))
                .padding(.bottom, CicadaTheme.spacingXS)
            ForEach(rows) { row in
                ReaderNotedRow(row: row, isCurrent: row.range != nil && row.range == currentRange, agent: agent,
                               onJump: { onJump(row) }, onShowOnGraph: { onShowOnGraph(row) })
            }
            if rows.isEmpty { metaLine(Copy.Provenance.nothingNoted) }
            if !alsoOn.isEmpty { metaLine(Copy.Provenance.alsoOn(alsoOn)) }
            if partial { metaLine(Copy.Provenance.notedPartial) }
        }
    }

    private func metaLine(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct ReaderNotedRow: View {
    let row: EpisodeCitation
    let isCurrent: Bool
    let agent: String?
    let onJump: () -> Void
    let onShowOnGraph: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let name = row.subjectName.isEmpty ? row.subjectId : row.subjectName
        let label = EvidenceLabel.speaker(kind: row.displayKind, agent: agent)
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Button(action: onJump) {
                VStack(alignment: .leading, spacing: RowMetrics.twoLineGap) {
                    Text(renderWikilinks(row.text.isEmpty ? name : row.text))
                        .font(CicadaTheme.font(size: 13))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .strikethrough(!row.current)
                        .lineLimit(2)
                    Text(row.current ? label : Copy.Provenance.notCurrent(label))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(isCurrent ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .disabled(row.range == nil)
            IconButton(systemName: "scope", help: Copy.Provenance.showOnGraph(name), action: onShowOnGraph)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(isCurrent ? CicadaTheme.bgSelected : hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

// MARK: - States

/// DR-32 — loading is a skeleton in the header's shape: four bars, no shimmer (a placeholder is
/// not an animation), under a header already built from the target's known fields.
struct ReaderSkeleton: View {
    static let bars: [(fraction: CGFloat, height: CGFloat)] = [(0.30, 12), (0.94, 14), (0.88, 14), (0.52, 12)]

    var body: some View {
        GeometryReader { geo in
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(Self.bars.indices, id: \.self) { i in
                    CicadaTheme.shape(CicadaTheme.radiusXS)
                        .fill(CicadaTheme.bgSelected)
                        .frame(width: geo.size.width * Self.bars[i].fraction,
                               height: CicadaTheme.scaled(Self.bars[i].height))
                }
            }
        }
        .frame(height: CicadaTheme.scaled(12 + 14 + 14 + 12) + 3 * CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
        .padding(.top, CicadaTheme.scaled(4))
        .accessibilityHidden(true)
    }
}

/// One honest sentence above the text (§4.4 States) — a meta line with no fill (DR-37). The
/// glyph is decoration; the words carry the meaning.
struct ReaderBannerView: View {
    let banner: ReaderBanner

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            Image(systemName: icon)
                .font(CicadaTheme.icon(.inline))
                .accessibilityHidden(true)
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textSecondary)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var text: String {
        switch banner {
        case .stale: Copy.Provenance.stale
        case .grown: Copy.Provenance.grown
        case .inferred: Copy.Provenance.inferred
        case .derived: Copy.Provenance.derived
        case .notFound: Copy.Provenance.notFound
        case .truncated: Copy.Provenance.truncated
        }
    }

    private var icon: String {
        switch banner {
        case .stale: "exclamationmark.triangle"
        case .grown: "arrow.down.to.line"
        case .inferred: "lightbulb"
        case .derived: "text.magnifyingglass"
        case .notFound: "magnifyingglass"
        case .truncated: "scissors"
        }
    }
}

// MARK: - The shell's host

/// R-DI6 / DR-31 — the shell's trailing column for every page that has not adopted
/// `ProgressiveColumns` yet. The Reader's width is decided FIRST (`ColumnLayout`) and the page gets
/// the rest in a fixed, clipped frame, so a page with a rigid minimum can never push the Reader past
/// the window's edge — which is what the retired `.inspector` did. Pointer paths animate on the
/// drawer curve; Esc arrives inside `Instant.run` and does not (DR-60, DR-61).
struct ShellReaderHost<Page: View, Reader: View>: View {
    let showsReader: Bool
    let navWidth: CGFloat
    @ViewBuilder var page: () -> Page
    @ViewBuilder var reader: () -> Reader

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let plan = ColumnLayout.plan(contentWidth: geo.size.width, navWidth: navWidth,
                                         scale: CGFloat(CicadaTheme.uiScale), hasList: false,
                                         hasDetail: true, hasTrailing: showsReader)
            HStack(spacing: 0) {
                page()
                    .frame(width: plan.detail, height: geo.size.height, alignment: .topLeading)
                    .clipped()
                if showsReader {
                    reader()
                        .frame(width: plan.trailing, height: geo.size.height)
                        .transition(CicadaMotion.readerTransition(reduceMotion: reduceMotion))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
        }
        .animation(showsReader ? CicadaMotion.readerIn(reduceMotion: reduceMotion)
                               : CicadaMotion.readerOut(reduceMotion: reduceMotion), value: showsReader)
    }
}

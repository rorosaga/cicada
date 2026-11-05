import AppKit
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
    @Environment(ProjectsCache.self) private var projectsCache
    @State private var revealed: [String: String] = [:]
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
    /// What the drawn source keeps between draws (`SourceSpansView`).
    @State private var spansState = SourceSpansState()
    @State private var conversations = ConversationsViewModel()
    /// P4 — what this document taught Cicada (`/citations`, G106 (ii)).
    @State private var citations: EpisodeCitations?
    /// A navigator step or a "Noted" row re-focuses the Reader IN PLACE on
    /// that citation; the router trail is for moving between documents.
    @State private var jump: EpisodeCitation?
    /// How the last in-place jump was asked for (owner, 2026-10-20): a pointer's jump hides the wash while the column
    /// moves, shows it once landed and gives the landed message a brief ring that fades; a keyboard's (⌥↑ / ⌥↓, ⏎ on a
    /// noted row) lands in one frame with the wash kept and no ring (DR-60).
    @State private var jumpTrigger: LooksZoom.Trigger = .pointer

    /// DR-61 / §5.4 — the column's horizontal inset, shared by the header's
    /// leading edge, the pinned row and the text, so all three align.
    static let inset: CGFloat = 28

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ReaderColumnHeader(
                canGoBack: router.canGoBack,
                onBack: { router.back() },
                page: loadedDoc.flatMap { $0.isPage ? $0 : nil },
                site: loadedDoc.flatMap(ReaderHeader.siteMark),
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
                onClose: { router.close() },
                untie: router.current?.fromProject.map { project in
                    { untieFromProject(project) }
                })
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
        // DR-68 — in a chat: ↑ / ↓ a message, the page keys five, ⌘↑ / Home to the start, ⌘↓ / End to the newest.
        .onKeyPress(keys: [.upArrow, .downArrow, .pageUp, .pageDown, .home, .end]) { press in
            spansState.key(press)
        }
        .environment(\.revealedNumbers, revealed)
        .task(id: router.current) { await load() }
        .onAppear { DeviceDirectory.shared.ensureLoaded() }
    }

    // MARK: Loading

    private func load() async {
        guard let target = router.current else { return }
        phase = .loading
        spansState.reset()
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
            revealed = [:]
            // Proposed ruling 55: the document keeps its token (every offset points into it); only the drawing shows the
            // digits, from memory, for this document.
            let tokens = NumberTokens.ids(in: doc.text)
            if !tokens.isEmpty, let answer = await APIClient.shared.revealNumbers(tokens),
               !Task.isCancelled, router.current == target {
                revealed = answer.numbers
            }
            guard !Task.isCancelled, router.current == target else { return }
            spansState.landAgain()
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
        let known = loadedDoc.map(ReaderHeader.title) ?? router.current?.knownTitle ?? ""
        return known.isEmpty ? Copy.Provenance.untitled : known
    }

    /// G181 phase 3 — the header names the device a conversation came from (`DeviceDirectory`, read on demand).
    private var meta: String {
        loadedDoc.map { ReaderHeader.meta($0, device: DeviceDirectory.shared.label(for: $0.device)) } ?? ""
    }
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
        let position = ReaderNavigator.position(of: presentation.focus, in: stops)
        let captureLine = ReaderHeader.captureLine(doc)
        return SourceSpansView(state: spansState, doc: doc, scalars: scalars, presentation: presentation, others: stops,
                               jump: jump == nil ? nil : jumpTrigger) {
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
        } below: {
            if let citations {
                notedList(citations, doc: doc, currentRange: presentation.focus)
                    .padding(.top, CicadaTheme.scaled(32))
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
                       shortcut: KeyboardShortcut(.upArrow, modifiers: .option),
                       accessibilityPress: {
                           step(-1, stops: stops, rows: rows, subjectId: subjectId, position: position, ask: .assistive)
                       }) {
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
                       shortcut: KeyboardShortcut(.downArrow, modifiers: .option),
                       accessibilityPress: {
                           step(1, stops: stops, rows: rows, subjectId: subjectId, position: position, ask: .assistive)
                       }) {
                step(1, stops: stops, rows: rows, subjectId: subjectId, position: position)
            }
            .disabled(position == stops.count - 1)
        }
    }

    private func step(_ delta: Int, stops: [Range<Int>], rows: [EpisodeCitation], subjectId: String?,
                      position: Int?, ask: ReaderJumpAsk = .event) {
        guard let next = ReaderNavigator.step(from: position, count: stops.count, by: delta) else { return }
        let stop = stops[next]
        let candidates = rows.filter { $0.range == stop }
        jumpTo(candidates.first { $0.subjectId == subjectId } ?? candidates.first, ask: ask)
    }

    /// A navigator step or a noted row: re-land in place. The trigger is read from the event running the action — a
    /// key press (the ⌥↑ / ⌥↓ shortcut, ⏎ on a row) or anything else, the pointer (`LooksZoom.trigger(for:)`) — unless
    /// an assistive technology pressed it, which lands as a key does (`ReaderJumpAsk`).
    private func jumpTo(_ citation: EpisodeCitation?, ask: ReaderJumpAsk = .event) {
        guard let citation, citation.range != nil else { return }
        let trigger = ReaderJumpAsk.trigger(ask, eventType: NSApp.currentEvent?.type)
        jumpTrigger = trigger
        spansState.prepareJump(trigger)
        jump = citation
        spansState.landAgain()
    }

    // MARK: Noted from this conversation (P4, G106 (ii))

    private func notedList(_ payload: EpisodeCitations, doc: EpisodeText, currentRange: Range<Int>?) -> some View {
        let citedIds = Set(payload.citations.map(\.subjectId))
        let alsoOn = payload.entities.filter { !citedIds.contains($0.entityId) }
            .map { $0.name.isEmpty ? $0.entityId : $0.name }
        return ReaderNotedList(
            rows: payload.citations, currentRange: currentRange, sourceKind: doc.isPage ? "page" : doc.sourceKind,
            agent: EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin), source: doc.source,
            origin: doc.origin, alsoOn: alsoOn, partial: payload.partial,
            onJump: { jumpTo($0, ask: $1) },
            onShowOnGraph: { row in
                appRouter.pendingTab = .graph
                graphVM.revealEntity(id: row.subjectId)
            })
    }
}

/// Who asked for an in-place jump (2026-10-20, DR-60). A click or a key is read from the event running the action
/// (`LooksZoom.trigger(for:)`). An assistive technology's press — VoiceOver's VO-Space on the navigator's chevrons or on
/// a "Noted" row — carries no event of its own (`NSApp.currentEvent` is whatever came last, often a click), and it is
/// not a pointer: it lands as a key does, in one frame and with no ring.
enum ReaderJumpAsk: Equatable {
    case event, assistive

    static func trigger(_ ask: ReaderJumpAsk, eventType: NSEvent.EventType?) -> LooksZoom.Trigger {
        ask == .assistive ? .keyboard : LooksZoom.trigger(for: eventType)
    }
}

/// How a landing moves (owner, 2026-10-20; DR-60, DR-61). Opening the Reader shows the wash once landed. An in-place
/// jump asked for by a key (⌥↑ / ⌥↓, ⏎ on a noted row) lands in one frame: the wash is simply there and nothing
/// rings. A jump asked for by the pointer shows the wash once landed and, in a chat, gives the landed message a brief
/// ring that fades — the eye's cue to where the column moved. The wash itself never fades (`CitedPassage`).
enum ReaderLandingMotion: Equatable {
    case instant, reveal, revealAndEmphasise

    static func choose(isJump: Bool, trigger: LooksZoom.Trigger, isChat: Bool, landed: Bool) -> ReaderLandingMotion {
        guard isJump else { return .reveal }
        if trigger == .keyboard { return .instant }
        return isChat && landed ? .revealAndEmphasise : .reveal
    }
}

// MARK: - The header

/// The mock's header (§5.4, DR-16): Back, the mark, the title in the display face at 20 over its
/// meta line, Resume as a neutral button, Close. A value view, so the loading state draws the same
/// header from the target's known fields (DR-32).
extension ReaderColumn {
    /// Ruling 45 — "Not about this project" from the Reader: the same `ProjectOwnershipWrite(.tie(remove: true))` the
    /// panel's row menu sends; the Reader closes, the panel asks again.
    fileprivate func untieFromProject(_ project: String) {
        guard let episode = router.current?.episode else { return }
        let write = ProjectOwnershipWrite(.tie(id: project, episode: episode, remove: true), cache: projectsCache)
        router.close()
        Task {
            if await store.perform(write) { projectsCache.confirmPaint(write.overlayId) }
            await projectsCache.refreshConversations(project)
            await projectsCache.refreshTimeline(project)
        }
    }
}

struct ReaderColumnHeader: View {
    let canGoBack: Bool
    let onBack: () -> Void
    /// The loaded document when it is a page, else nil.
    let page: EpisodeText?
    /// Owner 2026-10-20 — a saved link's own site mark (`ReaderHeader.siteMark`); the browser it came from is the meta
    /// line's words.
    var site: SavedLinkMarkModel.Mark? = nil
    let markOrigin: String
    let episode: String
    let title: String
    let meta: String
    let canResume: Bool
    let agent: String?
    let onResume: () -> Void
    let onClose: () -> Void
    /// Ruling 45 — set when a project's knowledge panel opened this conversation: "Not about this project".
    var untie: (() -> Void)? = nil

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
            if let untie {
                TextButton(title: Copy.ProjectsMine.notAboutThis, help: Copy.ProjectsMine.tieHelp, action: untie)
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
            LogoImage(entityId: page.episode, name: page.title, type: .media, fallbackOrigin: markOrigin,
                      size: CicadaTheme.scaled(20))
        } else if let site {
            SavedLinkMark(mark: site, size: .row)
                .help(Copy.Provenance.episodeHelp(episode))
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
    @Environment(\.revealedNumbers) private var numbers

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if block.startsTurn, !block.speaker.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
                    if let mark = block.mark {
                        OriginMark(origin: mark, size: CicadaTheme.scaled(12))
                    }
                    Text(block.speaker)
                        .font(CicadaTheme.metaMediumFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    if block.showsTurnNumber {
                        Text("· " + Copy.Provenance.turn(block.index))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    if let time = block.time {
                        Text(time)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            // Selectable, and washed: a `CitedPassage`, because a selectable `Text` never reaches the span renderer.
            CitedPassage(segments: NumberTokens.shown(ReaderText.segments(block), numbers),
                         color: isLanding ? CicadaTheme.textPrimary : CicadaTheme.textSecondary,
                         reveal: revealed ? 1 : 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(NumberTokens.shown(Self.accessibilityWords(block), numbers))
    }

    /// What VoiceOver reads for a block of the document view: the chat's cited words first when it holds a cited span
    /// (review of #383, 2026-10-20 — the tint is seen, never only seen), then the speaker line and the words.
    static func accessibilityWords(_ block: ReaderBlock) -> String {
        let words = block.speaker.isEmpty || !block.startsTurn || !block.showsTurnNumber
            ? block.text
            : Copy.Provenance.turnLabel(speaker: block.speaker, turn: block.index, text: block.text)
        switch ReaderChat.citedMark(block) {
        case .current: return Copy.Provenance.citedHere + ". " + words
        case .other: return Copy.Provenance.alsoCitedHere + ". " + words
        case nil: return words
        }
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
    /// What the document is, for the list's own title (`source_spans.kind_of`).
    let sourceKind: String?
    let agent: String?
    /// The document's episode `source`; `page-read` relabels a page quote as the agent's reading.
    var source: String? = nil
    /// The document's origin: a feed's or a calendar's rows read "From the feed" / "On your calendar" (DR-57).
    var origin: String? = nil
    /// Pages that name this document but cite none of its words.
    let alsoOn: [String]
    /// R-PB10: the server stopped at its page cap.
    let partial: Bool
    /// A row asked for its span: by the event that ran it, or by an assistive press (`ReaderJumpAsk`).
    let onJump: (EpisodeCitation, ReaderJumpAsk) -> Void
    let onShowOnGraph: (EpisodeCitation) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(Copy.Provenance.noted(count: rows.count, kind: sourceKind))
                .padding(.bottom, CicadaTheme.spacingXS)
            ForEach(rows) { row in
                ReaderNotedRow(row: row, isCurrent: row.range != nil && row.range == currentRange, agent: agent, source: source,
                               origin: origin,
                               onJump: { onJump(row, $0) }, onShowOnGraph: { onShowOnGraph(row) })
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
    var source: String? = nil
    var origin: String? = nil
    let onJump: (ReaderJumpAsk) -> Void
    let onShowOnGraph: () -> Void

    @Environment(\.revealedNumbers) private var numbers
    @State private var hovering = false

    var body: some View {
        let name = row.subjectName.isEmpty ? row.subjectId : row.subjectName
        let label = EvidenceLabel.speaker(kind: row.displayKind, agent: agent, source: source, origin: origin)
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Button { onJump(.event) } label: {
                VStack(alignment: .leading, spacing: RowMetrics.twoLineGap) {
                    Text(renderWikilinks(row.text.isEmpty ? name : NumberTokens.shown(row.text, numbers)))
                        .font(CicadaTheme.bodyFont)
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
            // VoiceOver's press lands as a key does, never the pointer's fade and ring (DR-60).
            .modifier(AssistivePress(action: { onJump(.assistive) }))
            IconButton(systemName: "scope", help: Copy.Provenance.showOnGraph(name), action: onShowOnGraph)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine))
        // DR-48 (round 3, 2026-10-20): the shared row fill — the row whose words are on screen is `isCurrent`, a
        // selection, not the cited span's wash (that is `CitedSpan`'s dandelion, DR-13/G118, drawn in the text).
        .rowHover($hovering, selected: isCurrent)
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
        case .derived: Copy.Provenance.derived
        case .truncated: Copy.Provenance.truncated
        }
    }

    private var icon: String {
        switch banner {
        case .stale: "exclamationmark.triangle"
        case .grown: "arrow.down.to.line"
        case .derived: "text.magnifyingglass"
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

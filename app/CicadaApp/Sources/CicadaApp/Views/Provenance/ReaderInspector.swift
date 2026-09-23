import SwiftUI

/// The Reader (G118 slice 2, design §4.4): a conversation, or a page's stored
/// text, opened beside whatever is on screen and scrolled to the sentence a
/// belief came from. A trailing `.inspector` on the main window's detail
/// column, so the entity card stays visible next to it — the belief and its
/// sentence side by side is the point of the feature.
///
/// Content, not chrome: no glass anywhere in here (R-M5, K12). Everything it
/// shows is fetched from the bank on demand and held in memory only — spans,
/// not copies (§4.9).
struct ReaderInspector: View {
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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.background)
        .onExitCommand { router.close() }
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

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                if router.canGoBack {
                    Button { router.back() } label: {
                        Image(systemName: "chevron.left").font(CicadaTheme.font(size: 12, weight: .semibold))
                    }
                    .buttonStyle(.cicadaPlain)
                    // ⌥⌘[ rather than ⌘[: the entity card beside the Reader
                    // already owns ⌘[ for its own back (plan R-PU9).
                    .keyboardShortcut("[", modifiers: [.command, .option])
                    .help(Copy.Provenance.back)
                    .accessibilityLabel(Copy.Provenance.back)
                }
                headerMark
                VStack(alignment: .leading, spacing: 2) {
                    // The track's one display-face moment (R-M3, ≥ 22 pt): the
                    // conversation's name, set like a page title.
                    Text(title)
                        .font(CicadaTheme.displayFont(size: 22))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                    if !meta.isEmpty {
                        Text(meta)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let id = conversationId, conversations.canResume(id) {
                    Button(Copy.Provenance.resume) {
                        Task { await act(await conversations.resume(id)) }
                    }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
                }
                Button { router.close() } label: {
                    Image(systemName: "xmark").font(CicadaTheme.font(size: 11, weight: .semibold))
                }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.textSecondary)
                .help(Copy.Provenance.close)
                .accessibilityLabel(Copy.Provenance.close)
            }
            if case let .loaded(doc, _) = phase, let line = ReaderHeader.captureLine(doc) {
                Label(line, systemImage: "info.circle")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
    }

    @ViewBuilder
    private var headerMark: some View {
        if case let .loaded(doc, _) = phase, doc.isPage {
            LogoImage(entityId: doc.episode, name: doc.title, type: .media, size: CicadaTheme.scaled(20))
        } else {
            OriginMark(origin: ReaderHeader.markOrigin(harness: loadedDoc?.harness ?? router.current?.knownHarness,
                                                        origin: loadedDoc?.origin),
                       size: CicadaTheme.scaled(20))
                .iconHover()
        }
    }

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
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)”"
        case .gone: store.toast = "That conversation's transcript is gone — nothing to resume"
        case .failed(let message): store.toast = message
        }
    }

    // MARK: Body

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            placeholder
        case .gone:
            message(Copy.Provenance.gone, icon: "tray")
        case .failed:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                message(Copy.Provenance.failed, icon: "exclamationmark.triangle")
                Button(Copy.Provenance.retry) { Task { await load() } }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
            }
        case let .loaded(doc, scalars):
            if let target = router.current {
                document(doc, scalars: scalars, target: target)
                if let citations {
                    Divider().background(CicadaTheme.border)
                    notedList(citations, doc: doc)
                }
            }
        }
    }

    /// Static lines, no shimmer (§4.2 — a placeholder is not an animation).
    private var placeholder: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(0..<4, id: \.self) { i in
                RoundedRectangle(cornerRadius: CicadaTheme.radiusXS)
                    .fill(CicadaTheme.surfaceHover)
                    .frame(width: CicadaTheme.scaled(i == 3 ? 180 : 320), height: CicadaTheme.scaled(10))
            }
        }
        .padding(CicadaTheme.spacingMD)
        .accessibilityHidden(true)
    }

    private func message(_ text: String, icon: String) -> some View {
        Label(text, systemImage: icon)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingMD)
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
        let landingBlock = presentation.landing.flatMap { ReaderLayout.blockIndex(containing: $0, in: blocks) }
        return ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // Pinned ABOVE the text, never inside it: landing scrolls the
                // cited turn to the centre, so a bar at the top of the scrolled
                // stack would leave the screen the moment the Reader arrives
                // (and, lazily unrealised, take ⌥↑ / ⌥↓ with it).
                if stops.count > 1 {
                    navigator(stops: stops, rows: rows, subjectId: target.subjectId,
                              position: ReaderNavigator.position(of: presentation.focus, in: stops))
                        .padding(.horizontal, CicadaTheme.spacingMD)
                        .padding(.vertical, CicadaTheme.spacingSM)
                    Divider().background(CicadaTheme.border)
                }
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                        ForEach(presentation.banners, id: \.self) { banner in
                            ReaderBannerView(banner: banner)
                        }
                        if blocks.isEmpty {
                            message(Copy.Provenance.empty, icon: "text.bubble")
                        }
                        ForEach(blocks) { block in
                            ReaderTurnView(block: block, isLanding: block.index == landingBlock,
                                           revealed: washVisible)
                                .id(block.index)
                        }
                    }
                    .padding(CicadaTheme.spacingMD)
                }
                .accessibilityRotor("Cited passages") {
                    ForEach(blocks.filter(\.holdsFocus)) { block in
                        AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
                                                id: block.index)
                    }
                }
                .accessibilityRotor("Turns") {
                    ForEach(blocks) { block in
                        AccessibilityRotorEntry(Text("\(block.speaker), \(Copy.Provenance.turn(block.index))"),
                                                id: block.index)
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
        HStack(spacing: CicadaTheme.spacingSM) {
            Button { step(-1, stops: stops, rows: rows, subjectId: subjectId, position: position) } label: {
                Image(systemName: "chevron.up")
            }
            .keyboardShortcut(.upArrow, modifiers: .option)
            .accessibilityLabel(Copy.Provenance.previousCited)
            .disabled(position == 0)
            Text(ReaderNavigator.label(position: position, count: stops.count))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            Button { step(1, stops: stops, rows: rows, subjectId: subjectId, position: position) } label: {
                Image(systemName: "chevron.down")
            }
            .keyboardShortcut(.downArrow, modifiers: .option)
            .accessibilityLabel(Copy.Provenance.nextCited)
            .disabled(position == stops.count - 1)
            Spacer()
        }
        .buttonStyle(.cicadaPlain)
        .font(CicadaTheme.font(size: 11, weight: .semibold))
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

    /// Every belief this document contributed, each with its subject's mark
    /// and how it was sourced. A row with offsets jumps the text to its words;
    /// the trailing pin lands on the subject in the graph (G123).
    private func notedList(_ payload: EpisodeCitations, doc: EpisodeText) -> some View {
        let noted = payload.citations
        let citedIds = Set(noted.map(\.subjectId))
        let alsoOn = payload.entities.filter { !citedIds.contains($0.entityId) }
            .map { $0.name.isEmpty ? $0.entityId : $0.name }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("\(doc.isPage ? Copy.Provenance.notedFromThisPage : Copy.Provenance.notedFromThisConversation)"
                 + " (\(UsageFormat.count(noted.count)))")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityAddTraits(.isHeader)
            if noted.isEmpty {
                Text(Copy.Provenance.nothingNoted)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(noted) { row in notedRow(row, doc: doc) }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(200))
            if !alsoOn.isEmpty {
                Text(Copy.Provenance.alsoOn(alsoOn))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
            }
            if payload.partial {
                Text(Copy.Provenance.notedPartial)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
    }

    private func notedRow(_ row: EpisodeCitation, doc: EpisodeText) -> some View {
        let name = row.subjectName.isEmpty ? row.subjectId : row.subjectName
        let label = EvidenceLabel.speaker(kind: row.displayKind,
                                          agent: EvidenceSpeaker.agentName(harness: doc.harness, origin: doc.origin))
        return HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Button { jumpTo(row) } label: {
                HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                    LogoImage(entityId: row.subjectId, name: name,
                              type: EntityType(rawValue: row.subjectType) ?? .concept, size: CicadaTheme.scaled(18))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(renderWikilinks(row.text.isEmpty ? name : row.text))
                            .font(CicadaTheme.font(size: 12))
                            .strikethrough(!row.current)
                            .lineLimit(2)
                        Text(row.current ? label : "\(label) · \(Copy.Provenance.noLongerCurrent)")
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .disabled(row.range == nil)
            .opacity(row.current ? 1 : 0.6)
            Button {
                appRouter.pendingTab = .graph
                graphVM.revealEntity(id: row.subjectId)
            } label: {
                Image(systemName: "scope").font(CicadaTheme.font(size: 11))
            }
            .buttonStyle(.cicadaPlain)
            .foregroundStyle(CicadaTheme.textTertiary)
            .help(Copy.Provenance.showOnGraph(name))
            .accessibilityLabel(Copy.Provenance.showOnGraph(name))
        }
        .padding(.vertical, 3)
    }

    /// Scroll to the cited turn after the first layout, fade the wash in over
    /// `spanReveal`, then say what was landed on (§4.4 Landing).
    private func land(proxy: ScrollViewProxy, block: Int?, blocks: [ReaderBlock],
                      presentation: ReaderPresentation) {
        Task { @MainActor in
            await Task.yield()
            if let block { proxy.scrollTo(block, anchor: .center) }
            withAnimation(CicadaMotion.spanReveal(reduceMotion: reduceMotion)) { washVisible = true }
            guard presentation.focus != nil, let hit = blocks.first(where: { $0.holdsFocus }),
                  let wash = hit.washes.first(where: { $0.style != .other }) else { return }
            let words = ScalarText(hit.text).slice(wash.range.lowerBound, wash.range.upperBound)
            AccessibilityNotification.Announcement(Copy.Provenance.citedPassage(String(words.prefix(120))))
                .post()
        }
    }
}

/// One turn: the speaker line, then the words with their washes. Selectable
/// text; the landing turn reads in the primary colour, the rest secondary.
struct ReaderTurnView: View {
    let block: ReaderBlock
    let isLanding: Bool
    let revealed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if !block.speaker.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if let mark = block.mark {
                        OriginMark(origin: mark, size: CicadaTheme.scaled(12))
                    }
                    Text(block.speaker)
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text("· \(Copy.Provenance.turn(block.index))")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    if let time = block.time {
                        Text(time)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
            Text(ReaderText.attributed(block, revealed: revealed))
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(isLanding ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.leading, CicadaTheme.spacingSM)
        .overlay(alignment: .leading) {
            if block.washes.contains(where: { $0.style == .focus }) {
                Rectangle().fill(CicadaTheme.dandelion).frame(width: 2)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(block.speaker.isEmpty
                            ? block.text
                            : "\(block.speaker), \(Copy.Provenance.turn(block.index)): \(block.text)")
    }
}

enum ReaderText {
    /// The cited span's wash (§4.2/§4.4) — emphasis, not a data encoding, so
    /// the one nature token allowed on content (K13).
    static let focusOpacity = 0.35
    /// Other spans the same entity cites: present, quieter, no margin bar.
    static let otherOpacity = 0.15

    /// The turn's text with its washes applied. Offsets are SCALAR offsets
    /// (§4.1), converted through `unicodeScalars` exactly as
    /// `ExcerptText.attributed` does; a range that does not fit is skipped,
    /// never trapped on. `revealed == false` is the frame before the wash
    /// fades in (`spanReveal`) — and the only frame under Reduce Motion is
    /// the revealed one, because the animation is nil there.
    static func attributed(_ block: ReaderBlock, revealed: Bool) -> AttributedString {
        var out = AttributedString(block.text)
        let scalars = block.text.unicodeScalars
        let count = scalars.count
        for wash in block.washes {
            guard wash.range.lowerBound >= 0, wash.range.upperBound <= count, !wash.range.isEmpty else { continue }
            let lower = scalars.index(scalars.startIndex, offsetBy: wash.range.lowerBound)
            let upper = scalars.index(scalars.startIndex, offsetBy: wash.range.upperBound)
            guard let a = AttributedString.Index(lower, within: out),
                  let b = AttributedString.Index(upper, within: out) else { continue }
            switch wash.style {
            case .focus:
                out[a..<b].backgroundColor = CicadaTheme.dandelionFill.opacity(revealed ? focusOpacity : 0)
            case .mention:
                out[a..<b].inlinePresentationIntent = .stronglyEmphasized
            case .other:
                out[a..<b].backgroundColor = CicadaTheme.dandelionFill.opacity(revealed ? otherOpacity : 0)
            }
        }
        return out
    }
}

/// One honest sentence above the text (§4.4 States). The icon is decoration;
/// the words carry the meaning.
struct ReaderBannerView: View {
    let banner: ReaderBanner

    var body: some View {
        Label(text, systemImage: icon)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surfaceHover)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
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
